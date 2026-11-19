"""
manager_flow.py - the only place in app/ that calls the manager's decision (`decide` in agent/review_decision.py).

Only the Manager page uses this module. The chat page, the confirm card, the agent adapter and every shared component never import
it or `decide`; a test reads the import lines of every module and fails if one does. Everything runs on the backend's worker thread,
because SQLite connections may only be used by the thread that opened them. Each call opens its own connections and closes them.

The page passes `decided_by` from config (`[app].manager_label`). It is never read from anything typed.
"""
from agent.llm import load_agent_config
from agent.review_chat import ReviewChat
from agent.review_decision import decide
from agent.review_notice import _text_for as notice_for        # a read: builds the fixed-text notice for a decided case; it marks nothing
from agent.review_queue import ReviewQueue
from agent.tools import ReturnsTools


def _chat_for(queue) -> ReviewChat:
    return ReviewChat(queue.con, dict(load_agent_config().review.chat))


def join_case(backend, item_id: str) -> dict:
    """A manager joins the chat of a case. {"ok", "first"} or a refusal with "message". The joined line is written once, however many join."""
    def job():
        queue = ReviewQueue(backend.settings.demo_db)
        try:
            return _chat_for(queue).join(item_id)
        finally:
            queue.close()
    return backend.run_on_worker(job)


def send_to_customer(backend, item_id: str, text: str) -> dict:
    """The manager writes in a case they have joined. The sender is the manager: this function has no sender argument. No model is called."""
    def job():
        queue = ReviewQueue(backend.settings.demo_db)
        try:
            return _chat_for(queue).post_manager(item_id, text)
        finally:
            queue.close()
    return backend.run_on_worker(job)


def decide_case(backend, item_id: str, decision: str, note: str, decided_by: str) -> dict:
    """
    Call decide() for one case. Returns its result unchanged: {"ok", "item_id", "status", "return_id", "error_code", "message", "checks"}.
    Phase 8d: "Send reply and close" on a request for a person (approve) is a reply from the manager, so the manager joins the chat first (once) and decide()
    then writes the reply as the last manager message and closes the thread.
    """
    def job():
        db = backend.settings.demo_db
        queue, tools = ReviewQueue(db), ReturnsTools(db)
        try:
            item = queue.get_item(item_id)
            if decision == "approve" and item and item["status"] == "open" and item["kind"] == "customer_asked_for_person":
                _chat_for(queue).join(item_id)
            return decide(item_id, decision, note, decided_by, queue=queue, tools=tools, cfg=load_agent_config())
        finally:
            queue.close()
            tools.con.close()
    return backend.run_on_worker(job)


def notice_text(backend, item_id: str) -> str | None:
    """The text the customer will get in their next chat message for a decided case, or None if it cannot be built yet."""
    def job():
        db = backend.settings.demo_db
        queue, tools = ReviewQueue(db), ReturnsTools(db)
        try:
            item = queue.get_item(item_id)
            if item is None or item["status"] == "open":
                return None
            if item["kind"] == "customer_asked_for_person" and _chat_for(queue).has_thread(item_id):
                return None          # phase 8d: the chat holds the reply and the closing line; no separate notice is sent
            text, _why = notice_for(item, tools, load_agent_config())
            return text
        finally:
            queue.close()
            tools.con.close()
    return backend.run_on_worker(job)
