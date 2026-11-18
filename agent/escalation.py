"""
escalation.py - the one place a branch asks for a person (the "seam"). Phase 5a: it now writes a review-queue item.

An `Escalator` is called the way the stand-in was: escalator(session, kind, details, reply_template). `kind` says why the
case goes to a person (the keys of [review.reasons] in config/agent.toml: customer_asked_for_person, late_request,
approval_required), `details` is plain data from tools, and `reply_template` is the fixed text from config. It

  * writes one item to the queue (agent/review_queue.py), or finds the open item for the same customer, order item and kind;
  * writes the item's one-sentence reason itself, from the details and the fixed texts in config; the model writes none of it;
  * keeps the last [review].excerpt_messages messages of the conversation (customer and agent text only);
  * returns the reply: the fixed template with the reference filled in, and nothing else of the queue;
  * stores the refund method of a Pay on Delivery return (details["refund_method"], set by agent/actions.py) in the item's
    refund_method column; any other case leaves it empty (phase 5b);
  * returns one guardrail entry ({name, passed, reason}) for the trace. If the write fails, the reply is the fixed error text,
    the entry is a failed check, and "queued" is False. A failed write never looks like a success.

The customer id is read from the session and stored in the item. It is not put in the reply, the record or the check entry.
This module does not call a writer tool and does not touch orders or return requests.
"""
from datetime import datetime, timezone

from .branches.base import fill
from .checks import check
from .llm import AgentConfig
from .review_queue import OPEN, ReviewQueue

CUSTOMER_KEYS = ("customer_id",)      # removed from anything stored as eligibility or put in the trace record


def queue_for_tools(tools) -> ReviewQueue:
    """Open the queue on the same database file the tools use (found from the tools' connection)."""
    row = next((r for r in tools.con.execute("PRAGMA database_list") if r[1] == "main"), None)
    if row is None or not row[2]:
        raise ValueError("the tools' database has no file, so the queue cannot be opened on it")
    return ReviewQueue(row[2])


def _scrub(value):
    """A copy of `value` without any customer id key, at any depth."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in CUSTOMER_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class Escalator:
    def __init__(self, queue_source, cfg: AgentConfig, now=None):
        """`queue_source` is a function that returns a ReviewQueue (called each time; it may cache). Tests give an in-memory one. `now` gives the time for "decided recently"."""
        self.queue_source, self.cfg = queue_source, cfg
        self._now = now or (lambda: datetime.now(timezone.utc))

    # -- what this customer already has (phase 8b) ------------------------------------------------------------
    def recent_cases(self, session, limit: int = 3) -> list:
        """
        The session's customer's own cases that are open (claimed ones too) or were decided within [review].recent_decision_days, newest first,
        at most `limit`: [{"id", "kind", "status", "decision_note", "order_item_id"}]. Only this customer's cases are returned, and only those
        fields. A queue that cannot be read gives an empty list (the caller then goes on as before).
        """
        days = self.cfg.review.recent_decision_days
        try:
            items = self.queue_source().list_items()
            now, kept = self._now(), []
            for item in items:
                if item["customer_id"] != session.customer_id:
                    continue
                if item["status"] != OPEN:
                    decided = datetime.fromisoformat(item["decided_at"]) if item.get("decided_at") else None
                    if decided is None or (now - (decided if decided.tzinfo else decided.replace(tzinfo=timezone.utc))).total_seconds() > days * 86400:
                        continue
                kept.append({k: item.get(k) for k in ("id", "kind", "status", "decision_note", "order_item_id")})
            return list(reversed(kept))[:limit]
        except Exception:
            return []

    # -- the pieces, each from fixed text and data -----------------------------------------------------------
    def _reason_sentence(self, kind: str, details: dict) -> str:
        template = self.cfg.review.reasons[kind]          # an unknown kind is a KeyError, which is a failed write
        # a case that asks for a refund method this agent does not offer (a paper cheque) keeps its kind but has its own sentence
        template = self.cfg.review.reasons_by_requested_method.get(details.get("requested_refund_method"), template)
        approval = self.cfg.branches.approval_texts
        why = ", and ".join(approval.get(code, code) for code in details.get("approval_reasons") or [])
        return fill(template, approval_reasons=why, **{k: v for k, v in details.items() if isinstance(v, (str, int, float))}).strip()

    def _excerpt(self, session) -> list:
        """The last N messages as {"role", "text"}: earlier exchanges, then the message being answered now. Text only."""
        r = self.cfg.review
        messages = []
        for exchange in session.history:
            messages += [{"role": "customer", "text": exchange["user"]}, {"role": "agent", "text": exchange["assistant"]}]
        if session.current_message:
            messages.append({"role": "customer", "text": session.current_message})
        kept = messages[-r.excerpt_messages:] if r.excerpt_messages > 0 else []
        return [{"role": m["role"], "text": str(m["text"])[:r.excerpt_message_chars]} for m in kept]

    # -- the call --------------------------------------------------------------------------------------------
    def __call__(self, session, kind: str, details: dict, reply: str | None = None) -> dict:
        r = self.cfg.review
        details = _scrub(dict(details))
        record = {"queued": False, "created": None, "reference": None, "reply": r.error_reply, "reason": kind,
                  "details": {k: v for k, v in details.items() if k != "eligibility"}, "note": ""}
        try:
            made = self.queue_source().create_item(
                customer_id=session.customer_id, kind=kind, reason=self._reason_sentence(kind, details),
                order_item_id=details.get("item_id"), excerpt=self._excerpt(session),
                eligibility=details.get("eligibility"), refund_method=details.get("refund_method"), dedupe=r.dedupe_open_items)
        except Exception as err:
            # any failure is a failed write, never a crash and never a success. Only the kind of error is recorded: its text could hold a path or an id
            record["note"] = f"the review queue write failed ({type(err).__name__}); nothing was queued"
            record["check"] = check("review_queue_write", False, record["note"])
            return record
        reference = made["item"]["id"]
        record.update(queued=True, created=made["created"], reference=reference, reply=fill(reply or r.reply_template, reference=reference))
        if made["created"]:
            record["note"] = f"queue item {reference} was created"
            record["check"] = check("review_queue_write", True, f"{reference} created ({kind})")
        else:
            record["note"] = f"an open item {reference} already exists for this case; no second item was created"
            record["check"] = check("review_queue_write", True, f"{reference} already open for this case ({kind}); no second item created")
        return record
