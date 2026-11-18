"""
manager_flow.py - the only place in app/ that calls the manager's decision (`decide` in agent/review_decision.py).

Only the Manager page uses this module. The chat page, the confirm card, the agent adapter and every shared component never import
it or `decide`; a test reads the import lines of every module and fails if one does. Everything runs on the backend's worker thread,
because SQLite connections may only be used by the thread that opened them. Each call opens its own connections and closes them.

The page passes `decided_by` from config (`[app].manager_label`). It is never read from anything typed.
"""
from agent.llm import load_agent_config
from agent.review_decision import decide
from agent.review_notice import _text_for as notice_for        # a read: builds the fixed-text notice for a decided case; it marks nothing
from agent.review_queue import ReviewQueue
from agent.tools import ReturnsTools


def decide_case(backend, item_id: str, decision: str, note: str, decided_by: str) -> dict:
    """Call decide() for one case. Returns its result unchanged: {"ok", "item_id", "status", "return_id", "error_code", "message", "checks"}."""
    def job():
        db = backend.settings.demo_db
        queue, tools = ReviewQueue(db), ReturnsTools(db)
        try:
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
            text, _why = notice_for(item, tools, load_agent_config())
            return text
        finally:
            queue.close()
            tools.con.close()
    return backend.run_on_worker(job)
