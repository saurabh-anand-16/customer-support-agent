"""
graph.py - the LangGraph wiring for one message:

    router  --(route)-->  one of:  a branch | confirm_step stub | out_of_scope | clarify   -->  finish

The "router" node asks Router.decide(), which sends a message straight to the confirm step when the
session holds a pending action (the model is not called). Since phase 4b the five branches (order status,
policy question, return or replace, cancel, human help) are real (agent/branches/); the confirm step is
still a stub (phase 4c), and so is any label added in config that has no branch. A branch returns its
reply, its evidence and, when it reached a decision that needs a yes or no, a pending action, which this
graph stores in the session. Nothing is written to the database in this phase.

Needs the `langgraph` package (requirements-agent.txt). It is imported only when an Agent is made.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .branches import BRANCHES, BranchContext, Run
from .llm import AgentConfig, ChatModel
from .replies import Replies
from .router import CONFIRM_STEP, Router, RouterDecision
from .session import Session
from .tool_adapter import ToolAdapter

NO_EVIDENCE = {"tool_calls": [], "policy_passages": []}


class State(TypedDict, total=False):
    session: Session
    message: str
    decision: RouterDecision
    reply: str
    steps: list
    branch: dict            # which branch ran and whether it is a stub
    person_offered: bool
    evidence: dict          # what the reply was based on: tool calls (input, output) and policy passages


def build_graph(cfg: AgentConfig, router: Router, replies: Replies, chat: ChatModel, adapter: ToolAdapter):
    """Compile the graph for this config. A label with a branch in agent/branches/ runs it; any other label is a stub."""
    friendly = set(cfg.session.friendly_kinds)
    already_offers = set(cfg.session.offer_in_reply)
    limit = cfg.session.off_topic_limit
    special = {"out_of_scope", "clarify"}
    branch_labels = [label for label in cfg.router.labels if label not in special]

    def route_node(state: State) -> dict:
        return {"decision": router.decide(state["session"], state["message"]), "steps": [*state.get("steps", []), "router"]}

    def choose(state: State) -> str:
        route = state["decision"].route
        if route == CONFIRM_STEP or route in special:
            return route
        return f"branch_{route}"

    def stub(name: str, label: str):
        def node(state: State) -> dict:
            return {"reply": replies.not_built(label), "branch": {"name": name, "stub": True, "note": "not built yet"},
                    "steps": [*state["steps"], name]}
        return node

    def branch_node(label: str):
        branch = BRANCHES[label]()
        name = f"branch_{label}"

        def node(state: State) -> dict:
            session = state["session"]
            ctx = BranchContext(cfg, chat, adapter, session, state["message"])
            try:
                result = branch.run(ctx)
            except Exception as err:             # a branch that breaks must not end the conversation
                info = {"name": name, "stub": False, "error": f"the branch failed: {type(err).__name__}", "model_calls": [],
                        "tool_calls": 0, "refused_tools": [], "stopped_by_limit": False, "pending_action": None, "notes": {}}
                return {"reply": cfg.branches.replies["branch_error"], "branch": info, "evidence": dict(NO_EVIDENCE),
                        "steps": [*state["steps"], name]}
            run: Run = result.run
            if result.pending_action is not None:
                session.pending_action = result.pending_action       # the next message goes to the confirm step
            info = {"name": name, "stub": False, "error": run.error, "model_calls": run.model_calls,
                    "tool_calls": len(run.tool_calls), "refused_tools": run.refused(), "stopped_by_limit": run.stopped_by_limit,
                    "pending_action": result.pending_action, "notes": run.notes}
            return {"reply": result.reply, "branch": info, "evidence": result.evidence(), "steps": [*state["steps"], name]}
        return node

    def out_of_scope_node(state: State) -> dict:
        session, kind = state["session"], state["decision"].kind
        reply, offered = replies.for_kind(kind), kind in already_offers
        if kind not in friendly:                       # an off-topic message: count it, and offer a person at the limit
            session.off_topic_count += 1
            if session.off_topic_count >= limit and kind not in already_offers:
                reply, offered = replies.with_person_offer(reply), True
        return {"reply": reply, "person_offered": offered, "branch": {"name": "out_of_scope", "stub": False, "kind": kind},
                "steps": [*state["steps"], "out_of_scope"]}

    def clarify_node(state: State) -> dict:
        decision = state["decision"]
        reply = replies.blank_message() if decision.blank else replies.clarify(decision.question)
        return {"reply": reply, "branch": {"name": "clarify", "stub": False}, "steps": [*state["steps"], "clarify"]}

    def finish_node(state: State) -> dict:
        session, decision = state["session"], state["decision"]
        if decision.route not in special:               # a message on topic ends the off-topic streak
            session.off_topic_count = 0
        session.add_exchange(state["message"] if isinstance(state["message"], str) else "", state["reply"],
                             decision.route, cfg.session.history_keep)
        return {"steps": [*state["steps"], "finish"]}

    graph = StateGraph(State)
    graph.add_node("router", route_node)
    graph.add_node("confirm_step", stub("confirm_step", "confirm step"))
    for label in branch_labels:
        graph.add_node(f"branch_{label}", branch_node(label) if label in BRANCHES else stub(f"branch_{label}", label.replace("_", " ")))
    graph.add_node("out_of_scope", out_of_scope_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "router")
    targets = {name: name for name in ["confirm_step", "out_of_scope", "clarify", *[f"branch_{l}" for l in branch_labels]]}
    graph.add_conditional_edges("router", choose, targets)
    for name in targets:
        graph.add_edge(name, "finish")
    graph.add_edge("finish", END)
    return graph.compile()
