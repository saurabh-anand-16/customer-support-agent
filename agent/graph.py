"""
graph.py - the LangGraph wiring for one message:

    router  --(route)-->  one of:  a branch | confirm_step | out_of_scope | clarify   -->  finish
    confirm_step  --(change, or the action expired)-->  the router's new route  (the rest as above)

The "router" node asks Router.decide(), which sends a message straight to the confirm step when the
session holds a pending action (the router model is not called). The confirm step (agent/confirm.py) labels the
answer; on a yes, code runs the writer (agent/actions.py). A "change" or an expired action drops the pending action and
sends the same message through the router again. The five branches (order status, policy question, return or
replace, cancel, human help) are real (agent/branches/), and any label added in config that has no branch is
a stub. A branch returns its reply, its evidence and, when it reached a decision that needs a yes or no, a pending
action, which this graph stores in the session. A branch does the answer check on any reply its model wrote.

Every guardrail decision of the turn is added to state["checks"] as {"name", "passed", "reason"}.

Needs the `langgraph` package (requirements-agent.txt). It is imported only when an Agent is made.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .branches import BRANCHES, BranchContext, Run
from .checks import tool_argument_checks
from .confirm import ConfirmStep
from .llm import AgentConfig, ChatModel
from .replies import Replies
from .router import CONFIRM_STEP, Router, RouterDecision
from .session import Session
from .session_facts import extract_facts, facts_text, pending_item_id, with_item
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
    checks: list            # guardrail checks of this turn, each {"name", "passed", "reason"}
    confirm: dict           # what the confirm step did (only present when it ran)
    reroute: bool           # the confirm step handed the message back to the router
    reply_prefix: str       # fixed text put before a rerouted reply (the expiry line)


def build_graph(cfg: AgentConfig, router: Router, replies: Replies, chat: ChatModel, adapter: ToolAdapter,
                confirm: ConfirmStep | None = None, escalate=None):
    """Compile the graph for this config. A label with a branch in agent/branches/ runs it; any other label is a stub."""
    friendly = set(cfg.session.friendly_kinds)
    already_offers = set(cfg.session.offer_in_reply)
    limit = cfg.session.off_topic_limit
    special = {"out_of_scope", "clarify"}
    branch_labels = [label for label in cfg.router.labels if label not in special]
    confirm = confirm or ConfirmStep(cfg, chat, adapter, escalate)

    def route_node(state: State) -> dict:
        return {"decision": router.decide(state["session"], state["message"]), "steps": [*state.get("steps", []), "router"]}

    def choose(state: State) -> str:
        route = state["decision"].route
        if route == CONFIRM_STEP or route in special:
            return route
        return f"branch_{route}"

    def confirm_node(state: State) -> dict:
        session = state["session"]
        card_item = pending_item_id(session.pending_action)          # phase 14k: the item on the card, read before the step clears it
        outcome = confirm.handle(session, state["message"])
        if cfg.branches.session_facts and card_item:
            session.facts = with_item(session.facts, card_item)
        update = {"steps": [*state["steps"], "confirm_step"], "checks": [*state.get("checks", []), *outcome.checks],
                  "confirm": outcome.info,
                  "evidence": {"tool_calls": outcome.tool_calls, "policy_passages": []},
                  "branch": {"name": "confirm_step", "stub": False, "label": outcome.label, "wrote": outcome.wrote}}
        if outcome.reroute:                              # the message is routed again, with nothing pending
            update.update(decision=router.decide(session, state["message"]), reroute=True, reply_prefix=outcome.reply_prefix,
                          steps=[*update["steps"], "router"])
        else:
            update["reply"] = outcome.reply
        return update

    def after_confirm(state: State) -> str:
        return choose(state) if state.get("reroute") else "finish"

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
            ctx = BranchContext(cfg, chat, adapter, session, state["message"], escalate)
            prior = state.get("checks", [])
            try:
                result = branch.run(ctx)
            except Exception as err:             # a branch that breaks must not end the conversation
                info = {"name": name, "stub": False, "error": f"the branch failed: {type(err).__name__}", "model_calls": [],
                        "tool_calls": 0, "refused_tools": [], "stopped_by_limit": False, "pending_action": None, "notes": {}}
                return {"reply": cfg.branches.replies["branch_error"], "branch": info, "evidence": dict(NO_EVIDENCE),
                        "checks": prior, "steps": [*state["steps"], name]}
            run: Run = result.run
            if result.pending_action is not None:
                session.set_pending(result.pending_action)           # the next message goes to the confirm step
            if cfg.branches.session_facts:                           # phase 14k: keep the order and items for the next turn (off = nothing is kept or traced)
                new_facts = extract_facts(run.tool_calls, result.pending_action, cfg.review.product_name_max_chars)
                session.set_facts(new_facts)
                if new_facts is not None:
                    run.notes["session_facts"] = facts_text(new_facts, "").strip()
            info = {"name": name, "stub": False, "error": run.error, "model_calls": run.model_calls,
                    "tool_calls": len(run.tool_calls), "refused_tools": run.refused(), "stopped_by_limit": run.stopped_by_limit,
                    "pending_action": result.pending_action, "notes": run.notes}
            checks = [*prior, *tool_argument_checks(run.tool_calls), *run.checks]
            return {"reply": result.reply, "branch": info, "evidence": result.evidence(), "checks": checks, "steps": [*state["steps"], name]}
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
        reply = f"{state['reply_prefix']} {state['reply']}" if state.get("reply_prefix") else state["reply"]
        session.add_exchange(state["message"] if isinstance(state["message"], str) else "", reply,
                             decision.route, cfg.session.history_keep)
        return {"reply": reply, "steps": [*state["steps"], "finish"]}

    graph = StateGraph(State)
    graph.add_node("router", route_node)
    graph.add_node("confirm_step", confirm_node)
    for label in branch_labels:
        graph.add_node(f"branch_{label}", branch_node(label) if label in BRANCHES else stub(f"branch_{label}", label.replace("_", " ")))
    graph.add_node("out_of_scope", out_of_scope_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("finish", finish_node)

    graph.add_edge(START, "router")
    targets = {name: name for name in ["confirm_step", "out_of_scope", "clarify", *[f"branch_{l}" for l in branch_labels]]}
    graph.add_conditional_edges("router", choose, targets)
    for name in targets:
        if name != "confirm_step":
            graph.add_edge(name, "finish")
    graph.add_conditional_edges("confirm_step", after_confirm, {**targets, "finish": "finish"})
    graph.add_edge("finish", END)
    return graph.compile()
