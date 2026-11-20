"""
confirm.py - the yes or no step. While an action is pending, the next message comes here and not to the router.

One short model call labels the customer's message, and nothing else:

  confirm   a plain yes to exactly this action      -> agent/actions.py runs it (code sets confirmed=True)
  decline   a plain no                              -> the action is dropped
  change    something different ("make it a replacement")  -> the action is dropped and the message goes to the router
  unclear   anything else                           -> asked once more ([confirm].max_unclear_asks), then dropped

The model sees the confirmation question and the customer's message. It never sees the customer id, the item's database
fields or any tool. Its output is read for one label: any other field it sends (confirmed, staff_approved, a customer id,
an item) is ignored. A model call that fails, or output that is not one of the four labels, counts as `unclear`: only a
label that was read cleanly as `confirm` can write.

A pending action also expires: [confirm].pending_max_turns messages may arrive while it waits. The next one finds it
dropped and is routed like any other message, with a fixed line saying nothing was done.

The pending action is cleared BEFORE the writer runs, so a second "yes" finds nothing pending and cannot write again.
"""
import dataclasses
import json
import time
from dataclasses import dataclass, field

from .actions import fill, run_pending
from .checks import check
from .llm import AgentConfig, ChatModel, LlmError, purpose, step_settings
from .refund_method import STAGE_METHOD, RefundMethodStep
from .session import Session
from .tool_adapter import ToolAdapter

LABELS = ("confirm", "decline", "change", "unclear")


def public_pending(pending: dict | None) -> dict | None:
    """
    What a UI card may show about a pending action: the item, the action, the refund amount and the return window.
    Built from a whitelist, so nothing else in the pending action (and never a customer id) can reach the result.
    """
    if not isinstance(pending, dict):
        return None
    d = pending.get("display") if isinstance(pending.get("display"), dict) else {}
    window = d.get("return_window") if isinstance(d.get("return_window"), dict) else None
    card = {
        "action": pending.get("type"),
        "item": {"item_id": d.get("item_id"), "product_name": d.get("product_name"), "order_id": d.get("order_id")},
        "resolution": d.get("resolution"),
        "refund_amount_inr": d.get("refund_amount_inr"),
        "return_window": ({k: window.get(k) for k in ("window_days", "day_number", "last_eligible_date", "days_left")} if window else None),
        "needs_staff_approval": bool(pending.get("needs_staff_approval", False)),
        "question": pending.get("question"),
    }
    if pending.get("needs_refund_method"):           # only a Pay on Delivery refund has these keys; other cards are unchanged
        card["refund_method"] = pending.get("refund_method") if isinstance(pending.get("refund_method"), str) else None
        card["refund_method_options"] = [m for m in pending.get("refund_method_options", []) if isinstance(m, str)]
    return card


@dataclass
class ConfirmOutcome:
    """What the confirm step did for one message."""
    label: str | None = None                  # confirm, decline, change, unclear; None when the action expired
    reply: str | None = None                  # None when the message must go on to the router
    reroute: bool = False
    reply_prefix: str = ""                    # fixed text put before a routed reply (the expiry line)
    wrote: bool = False
    checks: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    info: dict = field(default_factory=dict)  # for the trace


class ConfirmStep:
    def __init__(self, cfg: AgentConfig, chat: ChatModel, adapter: ToolAdapter, escalate_fn=None):
        self.cfg, self.chat, self.adapter, self.escalate_fn = cfg, chat, adapter, escalate_fn
        self.method_step = RefundMethodStep(cfg, chat, adapter, escalate_fn)

    # -- the model's label -------------------------------------------------------------------------------
    def _settings(self):
        return step_settings(self.cfg.model, self.cfg.confirm)

    def label(self, pending: dict, message: str) -> dict:
        """Ask the model for a label. Returns {"label", "reason", "raw_output", "error", "latency_ms"}; any problem gives "unclear"."""
        c = self.cfg.confirm
        question = str(pending.get("question") or pending.get("summary") or "").strip()
        user = (f"The confirmation question the customer was asked:\n{question}\n\n"
                f"Customer message to label:\n{(message or '').strip()[:c.max_message_chars]}")
        started = time.perf_counter()
        out = {"label": "unclear", "reason": "", "raw_output": None, "error": None, "latency_ms": 0.0}
        try:
            with purpose("confirm_label"):
                raw = self.chat.complete(c.prompt, [{"role": "user", "content": user}], self._settings())
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
        if not isinstance(data, dict) or data.get("label") not in LABELS:
            out["error"] = f"the output has no valid label: {data.get('label')!r}" if isinstance(data, dict) else "the output is not a JSON object"
            return out
        out["label"] = data["label"]                      # no other field of the output is read
        out["reason"] = str(data.get("reason", ""))[:300] if isinstance(data.get("reason"), str) else ""
        return out

    # -- one message while an action is pending ------------------------------------------------------------
    def handle(self, session: Session, message: str) -> ConfirmOutcome:
        c = self.cfg.confirm
        pending = session.pending_action
        session.pending_age += 1
        if session.pending_age > c.pending_max_turns:
            session.clear_pending()
            return ConfirmOutcome(None, None, reroute=True, reply_prefix=c.replies["expired"],
                                  checks=[check("pending_expiry", False, f"the action waited more than {c.pending_max_turns} message(s), so it was dropped")],
                                  info={"label": None, "expired": True, "model_called": False})

        if isinstance(pending, dict) and pending.get("stage") == STAGE_METHOD:       # the refund method is asked first (phase 4d)
            done = self.method_step.handle(session, message, pending)
            return ConfirmOutcome(done.label, done.reply, checks=done.checks, tool_calls=done.tool_calls, info={**done.info, "model_called": done.info.get("model_called", False)})

        got = self.label(pending, message)
        label = got["label"]
        info = {"label": label, "expired": False, "model_called": True, "reason": got["reason"], "raw_output": got["raw_output"],
                "error": got["error"], "latency_ms": got["latency_ms"], "action": pending.get("type") if isinstance(pending, dict) else None}
        checks = [check("confirm_label", got["error"] is None,
                        f"the customer's message was labelled {label}" if got["error"] is None else f"{got['error']}; treated as unclear")]

        if label == "confirm":
            session.clear_pending()                       # first: a second yes finds nothing and cannot write again
            result = run_pending(session, pending, self.adapter.tools, self.cfg, self.escalate_fn)
            info["wrote"] = result.wrote
            return ConfirmOutcome(label, result.reply, wrote=result.wrote, checks=[*checks, *result.checks],
                                  tool_calls=result.tool_calls, info={**info, "escalation": result.escalation, "error_code": result.error_code})
        if label == "decline":
            session.clear_pending()
            return ConfirmOutcome(label, c.replies["declined"], checks=checks, info=info)
        if label == "change":
            session.clear_pending()
            return ConfirmOutcome(label, None, reroute=True, checks=checks, info=info)
        # unclear: ask once more (as many times as the config allows), then drop the action
        if session.pending_unclear < c.max_unclear_asks:
            session.pending_unclear += 1
            question = pending.get("question", "") if isinstance(pending, dict) else ""
            return ConfirmOutcome(label, fill(c.replies["unclear_ask"], question=question), checks=checks, info={**info, "asked_again": True})
        session.clear_pending()
        return ConfirmOutcome(label, c.replies["unclear_drop"], checks=checks, info={**info, "dropped": True})
