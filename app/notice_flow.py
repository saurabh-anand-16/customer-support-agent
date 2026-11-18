"""
notice_flow.py - how the Customer chat page gets the notices of decided cases (phase 8b).

`deliver(backend, customer_id)` asks the agent's notice code for the customer's pending notices (decided cases they have not been told about),
and the notice code marks each one as told. It runs on the backend's worker thread, because SQLite connections may only be used by the thread that
opened them. No model is called and nothing is decided or written to orders or returns: the only change is the "told" mark on the customer's own case.

The agent's own next chat turn uses the same function in `agent/review_notice.py`, and marking a case as told is one atomic update, so a notice
is shown once, whether it arrives here or with the next message. The customer id is the page's own record of who is signed in (never a message).
"""
from functools import lru_cache

from agent.llm import load_agent_config
from agent.review_notice import pending_notices
from agent.review_queue import ReviewQueue
from agent.tools import ReturnsTools


@lru_cache(maxsize=1)
def _config():
    return load_agent_config()


def deliver(backend, customer_id: str) -> list[dict]:
    """The notices not yet told to this customer, now marked as told: [{"reference", "kind", "status", "text"}]. Never raises."""
    def job():
        db = backend.settings.demo_db
        queue, tools = ReviewQueue(db), ReturnsTools(db)
        try:
            notices, _checks = pending_notices(queue, tools, _config(), customer_id)
            return notices
        finally:
            queue.close()
            tools.con.close()
    try:
        return backend.run_on_worker(job)
    except Exception:
        return []
