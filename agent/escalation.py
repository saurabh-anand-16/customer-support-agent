"""
escalation.py - the one place a branch asks for a person (the "seam").

In phase 4b the review queue does not exist, so `escalate` creates nothing. It returns the fixed reply text it was
given (which says plainly that the review queue is not built yet) and a record of the request for the trace.
Phase 5 replaces the body: it will create a queue entry and say what happens next.

The record never holds the customer id: the session fixes who the customer is, and the trace never shows it.
"""


def escalate(session, reason: str, details: dict, reply: str) -> dict:
    """
    `reason` is a short code ("late_request", "customer_asked_for_person"), `details` is plain data from tools
    (item, numbers), and `reply` is the fixed text from config to show the customer.
    Returns {"queued": False, "reply", "reason", "details", "note"}.
    """
    return {"queued": False, "reply": reply, "reason": reason, "details": dict(details),
            "note": "the review queue is not built yet; nothing was created"}
