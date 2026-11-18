"""
agent.py - the front of the agent: Agent.start_session(customer_id) and Agent.respond(session_id, message).

Phase 4a covers the first half of the chain: session, router, the out-of-scope and clarify replies,
and stubs for the branches. No tool is called. `respond` returns:

  {"session_id": ..., "reply": the text for the customer, "route": the branch taken,
   "kind": the out-of-scope kind (else None),
   "trace": {"steps", "router" (input summary, raw output, label, kind, reason, latency, error),
             "branch", "off_topic", "pending_action_bypass"}}

The customer id is set once, in start_session(), and is neither read from a message nor sent to the model.
The model name and temperature come from config/agent.toml. LangGraph (requirements-agent.txt) is
imported when an Agent is created, so the other agent modules work without it.
"""
from .llm import AgentConfig, ChatModel, OpenAIChat, load_agent_config
from .replies import Replies
from .router import CONFIRM_STEP, Router
from .session import SessionStore


class Agent:
    def __init__(self, config: AgentConfig | None = None, chat: ChatModel | None = None, sessions: SessionStore | None = None):
        """`config` defaults to config/agent.toml, `chat` to the OpenAI model named in it. Tests give a fixed config and a fake."""
        try:
            from .graph import build_graph
        except ImportError as err:
            raise ImportError("The 'langgraph' package is not installed: pip install -r requirements-agent.txt") from err
        self.cfg = config or load_agent_config()
        self.chat = chat or OpenAIChat(self.cfg.root)
        self.sessions = sessions or SessionStore()
        self.router = Router(self.cfg, self.chat)
        self.replies = Replies(self.cfg)
        self._graph = build_graph(self.cfg, self.router, self.replies)

    def start_session(self, customer_id: str) -> str:
        """A new conversation for this customer. The customer cannot be changed afterwards. Returns the session id."""
        return self.sessions.create(customer_id).session_id

    def respond(self, session_id: str, message: str) -> dict:
        session = self.sessions.get(session_id)        # raises UnknownSession for an id that was never issued
        text = message if isinstance(message, str) else ""
        state = self._graph.invoke({"session": session, "message": text, "steps": []})
        decision = state["decision"]
        trace = {
            "session_id": session.session_id,
            "steps": state["steps"],
            "router": decision.to_trace(),
            "branch": state.get("branch"),
            "off_topic": {"count": session.off_topic_count, "limit": self.cfg.session.off_topic_limit,
                          "person_offered": bool(state.get("person_offered", False))},
            "pending_action_bypass": decision.route == CONFIRM_STEP,
        }
        return {"session_id": session.session_id, "reply": state["reply"], "route": decision.route,
                "kind": decision.kind, "trace": trace}
