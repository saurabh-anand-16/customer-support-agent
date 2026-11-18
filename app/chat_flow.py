"""
chat_flow.py - one chat turn, without any Streamlit calls (so it can be tested alone).

`run_turn` sends one message to the agent session and returns a "turn" dict for the page to keep and draw:

  {"user": the message, "reply": text to show, "status": "ok" | "error" | "no_key",
   "result": the agent's result (only when status is "ok"), "review": see review_info, "answered": None}

The turn never holds more than the result already holds. If the agent raises, the turn is the fixed friendly message from
config: no traceback and no exception text, because those could hold ids or text from the database. Nothing is printed.
"""
from .backend import MissingApiKey


def review_info(result: dict | None) -> dict | None:
    """
    The review-queue record of a turn, if the turn made one: {"reference", "kind", "item_id", "created"}.
    The agent's result has no top-level review field; the record sits in its trace (a branch's notes, or the confirm step's
    info) under "escalation". Returns None when nothing was queued.
    """
    trace = (result or {}).get("trace") or {}
    for holder in ((trace.get("branch") or {}).get("notes"), trace.get("confirm")):
        sent = holder.get("escalation") if isinstance(holder, dict) else None
        if isinstance(sent, dict) and sent.get("queued") and isinstance(sent.get("reference"), str):
            details = sent.get("details") if isinstance(sent.get("details"), dict) else {}
            return {"reference": sent["reference"], "kind": sent.get("reason"), "item_id": details.get("item_id"), "created": sent.get("created")}
    return None


def run_turn(backend, settings, session_id: str, message: str) -> dict:
    turn = {"user": message, "reply": "", "status": "ok", "result": None, "review": None, "answered": None}
    try:
        result = backend.respond(session_id, message)
    except MissingApiKey:
        turn.update(status="no_key", reply=settings.missing_key_help)
        return turn
    except Exception:           # any failure: the fixed message, nothing else. The agent has recorded what it can in its own trace.
        turn.update(status="error", reply=settings.error_reply)
        return turn
    if not isinstance(result, dict) or not isinstance(result.get("reply"), str):
        turn.update(status="error", reply=settings.error_reply)
        return turn
    turn.update(reply=result["reply"], result=result, review=review_info(result))
    return turn


def answer_label(next_turn: dict | None) -> str | None:
    """
    What to write on a confirm card after the customer answered it: "Confirmed" or "Declined", read from the label the confirm
    step gave the answer (result.trace.confirm.label). Any other outcome (unclear, a change of mind, an expired action) gives
    "Closed", because the card is no longer the one being asked about.
    """
    if next_turn is None:
        return None
    confirm = (((next_turn.get("result") or {}).get("trace") or {}).get("confirm")) or {}
    return {"confirm": "Confirmed", "decline": "Declined"}.get(confirm.get("label"), "Closed")
