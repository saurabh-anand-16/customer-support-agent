"""
agent.py - the front of the agent: Agent.start_session(customer_id) and Agent.respond(session_id, message).

Phase 4a built the first half of the chain: session, router, the out-of-scope and clarify replies.
Phase 4b added the five branches (agent/branches/), which call tools through agent/tool_adapter.py.
Nothing is written to the database yet: a branch that reaches a decision stores a pending action in the
session, and the confirm step (phase 4c) is still a stub. `respond` returns:

  {"session_id": ..., "reply": the text for the customer, "route": the branch taken,
   "kind": the out-of-scope kind (else None),
   "evidence": {"tool_calls": [{"tool", "input", "dropped_arguments", "output", "refused"}],
                "policy_passages": [{"number", "citation", "source_file", "heading_path", "text", "cited"}]},
   "trace": {"steps", "router" (input summary, raw output, label, kind, reason, latency, error, ignored_field),
             "branch" (model calls, tool calls, refused tools, round limit, pending action, notes),
             "off_topic", "pending_action_bypass"}}

The customer id is set once, in start_session(), and is neither read from a message nor sent to the model.
The model name and temperature come from config/agent.toml. LangGraph (requirements-agent.txt) is
imported when an Agent is created, so the other agent modules work without it.
"""
from pathlib import Path

from .llm import ROOT, AgentConfig, ChatModel, OpenAIChat, load_agent_config
from .replies import Replies
from .router import CONFIRM_STEP, Router
from .session import SessionStore
from .tool_adapter import ToolAdapter

DEFAULT_DB = ROOT / "returns_agent.db"


class Agent:
    def __init__(self, config: AgentConfig | None = None, chat: ChatModel | None = None, sessions: SessionStore | None = None,
                 tools=None, policy_search=None, db_path: str | Path | None = None):
        """
        `config` defaults to config/agent.toml, `chat` to the OpenAI model named in it. Tests give a fixed config and a fake.
        `tools` (a ReturnsTools) and `policy_search` (a PolicySearch) default to the real ones, opened only when first used;
        `db_path` chooses the database for the default tools. Tests give a fake policy search.
        """
        try:
            from .graph import build_graph
        except ImportError as err:
            raise ImportError("The 'langgraph' package is not installed: pip install -r requirements-agent.txt") from err
        self.cfg = config or load_agent_config()
        self.chat = chat or OpenAIChat(self.cfg.root)
        self.sessions = sessions or SessionStore()
        self.router = Router(self.cfg, self.chat)
        self.replies = Replies(self.cfg)
        def open_tools():
            from .tools import ReturnsTools
            return ReturnsTools(db_path or DEFAULT_DB)

        def open_policy():
            from .policy_search import PolicySearch
            return PolicySearch()

        self.adapter = ToolAdapter(tools, policy_search, open_tools, open_policy, top_k=self.cfg.branches.policy_top_k)
        self._graph = build_graph(self.cfg, self.router, self.replies, self.chat, self.adapter)

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
                "kind": decision.kind,
                "evidence": state.get("evidence") or {"tool_calls": [], "policy_passages": []}, "trace": trace}
