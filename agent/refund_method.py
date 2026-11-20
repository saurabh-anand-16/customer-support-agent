"""
refund_method.py - the question "where should the refund go?" for a Pay on Delivery refund (phase 4d).

Why: create_return needs a refund method for a refund on a Pay on Delivery order (agent/tools.py). Cards and UPI are refunded
to the same method by the tool, so they never come here.

The flow, with a pending return held in the session:

  1. The return branch builds the pending action in stage "refund_method" and the reply is the question (built from config).
  2. The next message comes here (agent/confirm.py sends it, the router is not called). One short model call labels the reply:
     one of the OFFERED methods, a NOT-OFFERED method (a method listed in [refund_method].not_offered), or "unclear". The model chooses nothing.
  3. CODE checks the label against the tool's own list (get_refund_timeline for pay_on_delivery, read again now):
       offered      -> the method is stored on the pending action, the stage becomes "confirm", the reply is the confirm card
                       with the method and its fixed note;
       not offered  -> nothing is written, the case goes to a person through the escalation seam, the reply is fixed text;
       anything else (unclear, a label that is on no list, a failed model call, bad JSON) -> asked again up to
                       [confirm].max_unclear_asks times, then the action is dropped.
  4. The writer (agent/actions.py) receives the method from the pending action, after checking it against the tool's list once more.

The options are never written in code: they are the tool's list minus [refund_method].not_offered. The agent never asks for or
stores bank account details; a method that needs them (NEFT) only gets a fixed note saying the account must already be added.
Every step adds an entry to the turn's checks ({"name", "passed", "reason"}).
"""
import dataclasses
import json
import time
from dataclasses import dataclass, field

from .branches.base import fill
from .checks import check
from .llm import AgentConfig, ChatModel, LlmError, purpose, step_settings
from .session import Session
from .tool_adapter import ToolAdapter

STAGE_METHOD = "refund_method"       # the pending return waits for the customer to name a refund method
STAGE_CONFIRM = "confirm"            # the method is chosen; the pending return waits for yes or no
SLOT = "{refund_method_line}"        # where the confirm question of a Pay on Delivery return takes its method line
ORDER_TYPE = "pay_on_delivery"
UNCLEAR = "unclear"
TOOL = "get_refund_timeline"


@dataclass
class Options:
    """What the tool says a Pay on Delivery refund can go to, split by this agent's own list of methods it does not offer."""
    offered: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    error: str | None = None


@dataclass
class MethodResult:
    """What the refund-method step did for one message (agent/confirm.py turns it into a ConfirmOutcome)."""
    label: str | None
    reply: str
    checks: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    info: dict = field(default_factory=dict)


def read_options(record: dict, cfg) -> Options:
    """The options from a get_refund_timeline record. `cfg` is the [refund_method] settings."""
    out = record.get("output") if isinstance(record, dict) else None
    if not isinstance(out, dict) or out.get("ok") is not True or record.get("refused"):
        return Options(error="the tool did not give a list of refund methods")
    methods = [t.get("refund_method") for t in out.get("timelines", []) if isinstance(t.get("refund_method"), str)]
    offered = [m for m in methods if m not in cfg.not_offered]
    if not offered:
        return Options(withheld=[m for m in methods if m in cfg.not_offered], error="the tool lists no refund method that can be offered")
    return Options(offered=offered, withheld=[m for m in methods if m in cfg.not_offered])


def option_text(cfg, method: str) -> str:
    return cfg.option_texts.get(method, method.replace("_", " "))


def join_options(cfg, methods: list) -> str:
    texts = [option_text(cfg, m) for m in methods]
    return texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + " or " + texts[-1]


def question_for(cfg, product_name, offered: list) -> str:
    """The question the customer is asked: fixed text from config, the options from the tool."""
    return fill(cfg.replies["ask"], product_name=product_name or "This item", options=join_options(cfg, offered)).strip()


def method_line(cfg, method: str) -> str:
    """The line the confirm card shows once a method is chosen: the method, and its fixed note if config has one."""
    return fill(cfg.replies["chosen_line"], method=option_text(cfg, method), note=cfg.notes.get(method, "")).strip()


def confirm_question(base: str, line: str) -> str:
    """The confirm question with the method line put where the template has its slot (at the end if it has none)."""
    return base.replace(SLOT, " " + line) if SLOT in base else f"{base} {line}"


def clean_slot(question: str) -> str:
    """A question that still holds the empty slot (the customer has not chosen yet) shows nothing in its place."""
    return question.replace(SLOT, "")


class RefundMethodStep:
    def __init__(self, cfg: AgentConfig, chat: ChatModel, adapter: ToolAdapter, escalate_fn=None):
        self.cfg, self.chat, self.adapter, self.escalate_fn = cfg, chat, adapter, escalate_fn

    def _settings(self):
        return step_settings(self.cfg.model, self.cfg.refund_method)

    # -- the model's label ------------------------------------------------------------------------------------
    def label(self, pending: dict, message: str, options: Options) -> dict:
        """Ask the model for a label. Returns {"label", "reason", "raw_output", "error", "latency_ms"}; any problem gives "unclear"."""
        m = self.cfg.refund_method
        allowed = [*options.offered, *options.withheld, UNCLEAR]
        user = (f"The question the customer was asked:\n{str(pending.get('question') or '').strip()}\n\n"
                f"Refund options (labels): {', '.join(options.offered)}\n"
                f"Not offered, but use the label if the customer asks for it: {', '.join(options.withheld) or 'none'}\n"
                f"Otherwise: {UNCLEAR}\n\n"
                f"Customer message to label:\n{(message or '').strip()[:m.max_message_chars]}")
        started = time.perf_counter()
        out = {"label": UNCLEAR, "reason": "", "raw_output": None, "error": None, "latency_ms": 0.0}
        try:
            with purpose("refund_method_label"):
                raw = self.chat.complete(m.prompt, [{"role": "user", "content": user}], self._settings())
        except LlmError as err:
            out["error"] = f"model call failed: {err}"
            out["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return out
        out["latency_ms"], out["raw_output"] = round((time.perf_counter() - started) * 1000, 1), raw
        try:
            data = json.loads(raw)
        except (TypeError, ValueError) as err:
            out["error"] = f"invalid JSON: {err}"
            return out
        value = data.get("label") if isinstance(data, dict) else None
        if not isinstance(value, str) or value not in allowed:
            out["error"] = f"the output has no allowed label: {value!r}" if isinstance(data, dict) else "the output is not a JSON object"
            return out
        out["label"] = value                              # no other field of the output is read
        out["reason"] = str(data.get("reason", ""))[:300] if isinstance(data.get("reason"), str) else ""
        return out

    # -- one message while the method is asked for ---------------------------------------------------------------
    def handle(self, session: Session, message: str, pending: dict) -> MethodResult:
        c, m = self.cfg.confirm, self.cfg.refund_method
        record = self.adapter.call(session, TOOL, {"order_type": ORDER_TYPE}, (TOOL,))       # the list, read again now
        options = read_options(record, m)
        info = {"stage": STAGE_METHOD, "offered": options.offered, "not_offered": options.withheld, "model_called": False}
        if options.error:
            session.clear_pending()
            return MethodResult(None, fill(c.replies["refused"], message="I can't read the refund options just now."),
                                checks=[check("refund_method_validated", False, f"{options.error}; nothing was done")],
                                tool_calls=[record], info=info)

        got = self.label(pending, message, options)
        label = got["label"]
        info.update(model_called=True, label=label, reason=got["reason"], raw_output=got["raw_output"], error=got["error"],
                    latency_ms=got["latency_ms"])
        checks = [check("refund_method_label", got["error"] is None,
                        f"the customer's reply was labelled {label}" if got["error"] is None else f"{got['error']}; treated as unclear")]

        if label in options.offered:                        # code's own check: the label is on the tool's list
            return self._chosen(session, pending, label, checks, record, info)
        if label in options.withheld:
            return self._not_offered(session, pending, label, checks, record, info)
        return self._ask_again(session, pending, checks, record, info)

    def _chosen(self, session, pending, method, checks, record, info) -> MethodResult:
        m = self.cfg.refund_method
        question = confirm_question(pending.get("confirm_question", ""), method_line(m, method))
        new = dict(pending)
        new.update(stage=STAGE_CONFIRM, refund_method=method, question=question,
                   parameters={**pending["parameters"], "refund_method": method},
                   display={**(pending.get("display") or {}), "refund_method": method})
        session.set_pending(new)                            # the counters start again for the yes or no
        info["chosen"] = method
        return MethodResult(method, question, [*checks, check("refund_method_validated", True, f"{method} is one of the tool's refund methods")],
                            [record], info)

    def _not_offered(self, session, pending, method, checks, record, info) -> MethodResult:
        m = self.cfg.refund_method
        session.clear_pending()                             # nothing is written, and nothing waits
        details = {"item_id": (pending.get("parameters") or {}).get("item_id"), "requested_refund_method": method}
        if self.escalate_fn is None:
            sent = {"queued": False, "reply": self.cfg.review.error_reply, "reason": m.escalation_kind, "details": details,
                    "note": "no review queue is wired; nothing was queued",
                    "check": check("review_queue_write", False, "no review queue is wired; nothing was queued")}
        else:
            sent = self.escalate_fn(session, m.escalation_kind, details, m.replies["cheque_reply"])
        info.update(not_offered=[method], escalation=sent)
        return MethodResult(method, sent["reply"],
                            [*checks, check("refund_method_validated", False, f"{method} is a method this agent does not offer; the case went to a person"),
                             sent["check"]], [record], info)

    def _ask_again(self, session, pending, checks, record, info) -> MethodResult:
        c = self.cfg.confirm
        if session.pending_unclear < c.max_unclear_asks:
            session.pending_unclear += 1
            info["asked_again"] = True
            return MethodResult(UNCLEAR, fill(c.replies["unclear_ask"], question=pending.get("question", "")),
                                [*checks, check("refund_method_validated", False, "no refund method was read from the reply; asked again")], [record], info)
        session.clear_pending()
        info["dropped"] = True
        return MethodResult(UNCLEAR, c.replies["unclear_drop"],
                            [*checks, check("refund_method_validated", False, "no refund method was read from the reply; the action was dropped")], [record], info)
