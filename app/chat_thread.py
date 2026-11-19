"""
chat_thread.py - the customer's side of the live chat of a review case (phase 8d). No Streamlit calls, so it can be tested alone.

The Customer chat page uses this module, and nothing else, to talk to the thread of a case:

  * `paused_post(backend, customer_id, text)`: the check made BEFORE the agent is called. If the customer has an open case, the message is stored in the
    thread of the newest open case and the agent is not called (the page does not call it); the answer says so. With no open case it answers None and
    the page sends the message to the agent as usual.
  * `look(backend, customer_id, after_id)`: the new thread messages of this customer, and whether a case of theirs is open and whether a manager has joined.

The only write is `ReviewChat.post_customer`, which can only write a customer message: this module has no sender argument and never reads one from a message.
No model is called here, and the customer id is the page's own record of who is signed in. Everything runs on the backend's worker thread because SQLite
connections may only be used by the thread that opened them. No message text is printed or logged.
"""
from functools import lru_cache

from agent.llm import load_agent_config
from agent.review_chat import ReviewChat
from agent.review_queue import ReviewQueue


@lru_cache(maxsize=1)
def _chat_config() -> dict:
    return dict(load_agent_config().review.chat)


def _with_chat(backend, work):
    """Run `work(chat, queue)` on the worker thread with a chat on its own connection to the demo database."""
    def job():
        queue = ReviewQueue(backend.settings.demo_db)
        try:
            return work(ReviewChat(queue.con, _chat_config()), queue)
        finally:
            queue.close()
    return backend.run_on_worker(job)


def paused_post(backend, customer_id: str, text: str) -> dict | None:
    """
    None when this customer has no open case (the agent answers as usual). Otherwise the message goes to the thread and the agent is not called:
    {"ok": True, "item_id", "message_id"} or {"ok": False, "message": the refusal text} for an empty or too long message.
    """
    def work(chat: ReviewChat, queue):
        if chat.open_case_id(customer_id) is None:
            return None
        return chat.post_customer(customer_id, text)
    return _with_chat(backend, work)


def look(backend, customer_id: str, after_id: int | None) -> dict:
    """
    {"messages": new thread messages (oldest first), "seen": the newest message id looked at, "open_case": id or None, "joined": bool}.
    `after_id` None is the first look of a chat: the messages of a closed case are shown only if the customer has not been told how it ended yet (so a reply
    sent while they were away still reaches them once), and a fresh chat does not replay old, told conversations; those of an open case are all shown.
    When a closing line of a "customer asked for a person" case is shown, the customer is marked as told (the same atomic mark the notices use). Never raises.
    """
    def work(chat: ReviewChat, queue):
        rows = chat.messages_for_customer(customer_id, after_id or 0)
        open_case = chat.open_case_id(customer_id)
        joined = bool(open_case) and chat.is_joined(open_case)
        shown = [r for r in rows if not (after_id is None and r["case_status"] != "open" and r["told_at"] is not None)]
        for r in shown:
            if r["event"] == "closed" and r["case_kind"] == "customer_asked_for_person":
                queue.mark_notified(r["review_item_id"])
        return {"messages": shown, "seen": max([after_id or 0, *[r["id"] for r in rows]]), "open_case": open_case, "joined": joined}
    try:
        return _with_chat(backend, work)
    except Exception:
        return {"messages": [], "seen": after_id or 0, "open_case": None, "joined": False, "failed": True}


def texts() -> dict:
    """The fixed lines and labels of the live chat, from [review.chat] in config/agent.toml."""
    return dict(_chat_config())


def manager_label() -> str:
    return _chat_config()["manager_label"]
