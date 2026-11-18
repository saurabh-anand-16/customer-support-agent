"""
graph.py - the LangGraph wiring for one message:

    router  --(route)-->  one of:  a branch stub | confirm_step stub | out_of_scope | clarify   -->  finish

The "router" node asks Router.decide(), which sends a message straight to the confirm step when the
session holds a pending action (the model is not called). In this phase no tool is called anywhere:
the five branches (order status, policy question, return or replace, cancel, human help) and the
confirm step are stubs that say they are not built yet, and the trace marks them as stubs.

Needs the `langgraph` package (requirements-agent.txt). It is imported only when an Agent is made.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .llm import AgentConfig
from .replies import Replies
from .router import CONFIRM_STEP, Router, RouterDecision
from .session import Session


class State(TypedDict, total=False):
    session: Session
    message: str
    decision: RouterDecision
    reply: str
    steps: list
    branch: dict            # which branch ran and whether it is a stub
    person_offered: bool


def build_graph(cfg: AgentConfig, router: Router, replies: Replies):
    """Compile the graph for this config. The branch stubs are made from the labels in [router.labels]."""
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
        graph.add_node(f"branch_{label}", stub(f"branch_{label}", label.replace("_", " ")))
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
