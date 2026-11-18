"""
router.py - decides which branch a message goes to. One model call per message.

The router only classifies. It never answers the customer, never calls a tool and is never given a tool
result: its input is the message, the last few exchanges (the number is [router].history_turns) and
whether a confirmation is pending, and its output is JSON:

  {"route": one of [router.labels], "reason": a short sentence,
   "kind": only for out_of_scope, one of [router.kinds],
   "question": only for clarify, one short question}

A "kind" sent with any other route, or a "question" sent with any other route, is ignored and named in the
trace as "ignored_field".

If the output is not valid (not JSON, not an object, an unknown route or kind, a missing field), or the
model call fails, the route becomes "clarify" with the generic question from config and the error is
recorded in the decision, so the Developer page can show it. The customer id is never sent to the model.

A pending action bypasses the router: the model is not called and the route is "confirm_step".
"""
import json
import time
from dataclasses import dataclass, field

from .llm import AgentConfig, ChatModel, LlmError, purpose
from .session import Session

CONFIRM_STEP = "confirm_step"     # not a label the model can pick: only a pending action leads here


@dataclass
class RouterDecision:
    route: str
    kind: str | None = None           # for out_of_scope
    question: str | None = None       # for clarify: the model's question, if it was usable
    reason: str = ""
    raw_output: str | None = None     # exactly what the model returned
    error: str | None = None          # why the output (or the call) was not usable
    latency_ms: float = 0.0
    called: bool = True               # False when the model was not asked (pending action, blank message)
    blank: bool = False
    input_summary: dict = field(default_factory=dict)
    ignored_field: list = field(default_factory=list)   # "kind" or "question" the model sent on a route that does not use it

    def to_trace(self) -> dict:
        """What the Developer page shows about the router for this message."""
        return {"called": self.called, "input_summary": self.input_summary, "raw_output": self.raw_output,
                "label": self.route, "kind": self.kind, "question": self.question, "reason": self.reason,
                "latency_ms": round(self.latency_ms, 1), "error": self.error,
                "ignored_field": list(self.ignored_field) or None}


class Router:
    def __init__(self, cfg: AgentConfig, chat: ChatModel):
        self.cfg, self.chat = cfg, chat

    # -- the prompt -------------------------------------------------------------------------
    def system_prompt(self) -> str:
        r = self.cfg.router
        listing = lambda table: "\n".join(f'- "{name}": {text}' for name, text in table.items())   # noqa: E731
        return r.system_prompt.format(scope_statement=self.cfg.scope.statement.strip(), labels=listing(r.labels),
                                      kinds=listing(r.kinds), max_question_chars=r.max_question_chars)

    def user_message(self, history: list, message: str, pending: bool) -> str:
        past = "\n".join(f"Customer: {e['user']}\nAssistant: {e['assistant']}" for e in history) or "(none)"
        return (f"Earlier conversation, oldest first:\n{past}\n\n"
                f"A confirmation question is waiting for the customer's answer: {'yes' if pending else 'no'}\n\n"
                f"Customer message to route:\n{message}")

    # -- the decision -----------------------------------------------------------------------
    def decide(self, session: Session, message: str) -> RouterDecision:
        r, m = self.cfg.router, self.cfg.model
        text = (message or "").strip()
        summary = {"message": text[:r.max_message_chars], "message_chars": len(text),
                   "truncated": len(text) > r.max_message_chars, "history_turns_sent": 0,
                   "pending_action": session.pending_action is not None, "model": m.name, "temperature": m.temperature}

        if session.pending_action is not None:
            return RouterDecision(CONFIRM_STEP, reason="a confirmation is pending, so the message goes to the confirm step",
                                  called=False, input_summary=summary)
        if not text:
            return RouterDecision("clarify", reason="the message is blank", called=False, blank=True, input_summary=summary)

        history = session.recent(r.history_turns)
        summary["history_turns_sent"] = len(history)
        prompt = self.user_message(history, text[:r.max_message_chars], pending=False)

        started = time.perf_counter()
        try:
            with purpose("router"):
                raw = self.chat.complete(self.system_prompt(), [{"role": "user", "content": prompt}], m)
        except LlmError as err:
            return self._invalid(f"model call failed: {err}", None, (time.perf_counter() - started) * 1000, summary)
        latency = (time.perf_counter() - started) * 1000

        fields, error = self._validate(raw)
        if error:
            return self._invalid(error, raw, latency, summary)
        return RouterDecision(fields["route"], fields["kind"], fields["question"], fields["reason"], raw, None, latency,
                              input_summary=summary, ignored_field=fields["ignored"])

    def _invalid(self, error: str, raw, latency_ms: float, summary: dict) -> RouterDecision:
        return RouterDecision("clarify", reason="the router output was not usable, so the generic question is asked",
                              raw_output=raw, error=error, latency_ms=latency_ms, input_summary=summary)

    def _validate(self, raw) -> tuple[dict | None, str | None]:
        r = self.cfg.router
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as err:
            return None, f"invalid JSON: {err}"
        if not isinstance(data, dict):
            return None, "the output is not a JSON object"
        for key in ("route", "reason"):
            if not isinstance(data.get(key), str):
                return None, f"missing field '{key}'"
        route = data["route"]
        if route not in r.labels:
            return None, f"unknown label {route!r}"
        kind = question = None
        if route == "out_of_scope":
            kind = data.get("kind")
            if not isinstance(kind, str) or kind not in r.kinds:
                return None, f"route out_of_scope needs a valid 'kind', got {kind!r}"
        if route == "clarify":
            q = data.get("question")
            if isinstance(q, str) and q.strip() and len(q.strip()) <= r.max_question_chars and q.strip().endswith("?"):
                question = q.strip()           # otherwise the generic question is used
        # "kind" only means something for out_of_scope and "question" only for clarify. On any other route they are
        # ignored (not an error, not a clarify) and the trace says so.
        ignored = [name for name, used_by in (("kind", "out_of_scope"), ("question", "clarify"))
                   if route != used_by and data.get(name) not in (None, "")]
        return {"route": route, "kind": kind, "question": question, "reason": data["reason"].strip()[:300],
                "ignored": ignored}, None
