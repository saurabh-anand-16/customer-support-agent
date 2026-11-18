"""
agent.py - the front of the agent: Agent.start_session(customer_id) and Agent.respond(session_id, message).

Phase 4a built the first half of the chain: session, router, the out-of-scope and clarify replies.
Phase 4b added the five branches (agent/branches/), which call tools through agent/tool_adapter.py.
A branch that reaches a decision stores a pending action in the session. The next message goes to the confirm step
(phase 4c, agent/confirm.py), and only a yes there makes code run the writer tool (agent/actions.py).
`respond` returns:

  {"session_id": ..., "reply": the text for the customer, "route": the branch taken,
   "kind": the out-of-scope kind (else None),
   "pending_action": None, or what a card may show: {"action": "return"|"cancel", "item": {"item_id", "product_name",
                     "order_id"}, "resolution", "refund_amount_inr", "return_window": {"window_days", "day_number",
                     "last_eligible_date", "days_left"}, "needs_staff_approval", "question"} (never the customer id),
   "evidence": {"tool_calls": [{"tool", "input", "dropped_arguments", "output", "refused"}],
                "policy_passages": [{"number", "citation", "source_file", "heading_path", "text", "cited"}]},
   "trace": {"steps", "checks" (guardrail checks, each {"name", "passed", "reason"}), "confirm" (what the confirm step
             did, or None), "router" (input summary, raw output, label, kind, reason, latency, error, ignored_field),
             "branch" (model calls, tool calls, refused tools, round limit, pending action, notes),
             "off_topic", "pending_action_bypass"}}

Phase 5b: when a manager has decided a case of this customer that they were not told about yet, `reply` starts with a fixed notice
for each (agent/review_notice.py), once only, and `trace["checks"]` gets one "review_notice" entry per case. The notice is added
after the turn, so a turn that fails tells nothing and loses nothing.

The customer id is set once, in start_session(), and is neither read from a message nor sent to the model.
The model name and temperature come from config/agent.toml. LangGraph (requirements-agent.txt) is
imported when an Agent is created, so the other agent modules work without it.
"""
import time
from pathlib import Path

from .checks import check
from .confirm import ConfirmStep, public_pending
from .escalation import Escalator, queue_for_tools
from .llm import ROOT, AgentConfig, ChatModel, OpenAIChat, load_agent_config
from .replies import Replies
from .review_notice import outcome_notices
from .router import Router
from .session import SessionStore
from .tool_adapter import ToolAdapter
from .tracing import Tracer

DEFAULT_DB = ROOT / "returns_agent.db"


class Agent:
    def __init__(self, config: AgentConfig | None = None, chat: ChatModel | None = None, sessions: SessionStore | None = None,
                 tools=None, policy_search=None, db_path: str | Path | None = None, review_queue=None, tracer: Tracer | None = None):
        """
        `config` defaults to config/agent.toml, `chat` to the OpenAI model named in it. Tests give a fixed config and a fake.
        `tools` (a ReturnsTools) and `policy_search` (a PolicySearch) default to the real ones, opened only when first used;
        `db_path` chooses the database for the default tools. Tests give a fake policy search.
        `review_queue` (a ReviewQueue) is where cases for a person are written; by default the queue is opened, when first
        needed, on the same database file the tools use.
        `tracer` (phase 6) writes one line per turn to the local trace file; by default it follows [tracing] in the config.
        """
        try:
            from .graph import build_graph
        except ImportError as err:
            raise ImportError("The 'langgraph' package is not installed: pip install -r requirements-agent.txt") from err
        self.cfg = config or load_agent_config()
        self.tracer = tracer or Tracer(self.cfg.tracing, self.cfg.root, {"router": self.cfg.model.name, "branch": self.cfg.branches.name,
                                                                         "confirm": self.cfg.confirm.name})
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
        self._queue = review_queue

        def queue_source():
            if self._queue is None:
                self._queue = queue_for_tools(self.adapter.tools)
            return self._queue

        self.escalator = Escalator(queue_source, self.cfg)
        self.confirm = ConfirmStep(self.cfg, self.chat, self.adapter, self.escalator)
        self._graph = build_graph(self.cfg, self.router, self.replies, self.chat, self.adapter, self.confirm, self.escalator)

    def start_session(self, customer_id: str) -> str:
        """A new conversation for this customer. The customer cannot be changed afterwards. Returns the session id."""
        return self.sessions.create(customer_id).session_id

    def _outcome_notice(self, session) -> tuple:
        """The notice text and its checks for this customer's decided cases. Never raises: a queue that fails changes nothing in the reply."""
        try:
            queue, tools = self.escalator.queue_source(), self.adapter.tools
        except Exception as err:
            return "", [check("review_notice", False, f"the review queue could not be opened ({type(err).__name__}); no notice was added")]
        return outcome_notices(queue, tools, self.cfg, session.customer_id)

    def respond(self, session_id: str, message: str) -> dict:
        started = time.perf_counter()
        session = self.sessions.get(session_id)        # raises UnknownSession for an id that was never issued
        text = message if isinstance(message, str) else ""
        session.current_message = text            # for the excerpt of a review case; it joins `history` when the turn ends
        state = self._graph.invoke({"session": session, "message": text, "steps": []})
        decision = state["decision"]
        notice, notice_checks = self._outcome_notice(session)
        reply = notice + "\n\n" + state["reply"] if notice else state["reply"]
        trace = {
            "session_id": session.session_id,
            "steps": state["steps"],
            "router": decision.to_trace(),
            "branch": state.get("branch"),
            "off_topic": {"count": session.off_topic_count, "limit": self.cfg.session.off_topic_limit,
                          "person_offered": bool(state.get("person_offered", False))},
            "pending_action_bypass": state.get("confirm") is not None,
            "confirm": state.get("confirm"),
            "checks": [*state.get("checks", []), *notice_checks],
        }
        result = {"session_id": session.session_id, "reply": reply, "route": decision.route,
                  "kind": decision.kind, "pending_action": public_pending(session.pending_action),
                  "evidence": state.get("evidence") or {"tool_calls": [], "policy_passages": []}, "trace": trace}
        # Phase 6: save the turn. The tracer reads `result` and never raises, so the reply is the same with tracing on, off or failing.
        try:
            self.tracer.record_turn(result=result, session_id=session.session_id, customer_id=session.customer_id, message=text,
                                    duration_ms=(time.perf_counter() - started) * 1000)
        except Exception:
            pass
        return result
