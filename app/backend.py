"""
backend.py - the one object between the pages and the agent.

* All agent work (building the agent, starting a session, answering a message, resetting) runs on ONE daemon worker thread.
  The agent's database connections are opened on first use and SQLite connections may only be used by the thread that
  opened them, while Streamlit runs each page run on its own thread. One worker thread keeps that rule without any change
  to the agent. It also means two visitors are served one after the other (a limit of this demo; see the build report).
* The page never gives the agent a customer id with a message. `start_session(customer_id)` is called once when a customer
  is chosen on Home; after that only the session id and the message text go in.
* A missing API key is found before the call and answered with how to set it up. The key is read only to see that it exists
  and is never kept, printed or shown.
* Tests give `agent_factory` (a fake agent), and then no key is needed.
"""
import gc
import queue
import threading
from concurrent.futures import Future

from .config import AppSettings
from .demo_db import ensure_demo_db, reset_demo_db


class MissingApiKey(RuntimeError):
    """No OpenAI key was found. The page shows the set-up help; the message never holds a key."""


class Worker:
    """
    One DAEMON thread that runs the jobs it is given, one after the other. A daemon thread never keeps the process alive, so the app
    can stop at once when Streamlit exits, even while a job is still running. (A ThreadPoolExecutor thread is joined at exit.)
    """

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="agent-worker", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            fn, args, future = self._jobs.get()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as err:        # handed back to the caller, which decides what the page shows
                future.set_exception(err)

    def run(self, fn, *args):
        future: Future = Future()
        self._jobs.put((fn, args, future))
        return future.result()


class Backend:
    def __init__(self, settings: AppSettings, agent_factory=None):
        self.settings = settings
        self._factory = agent_factory
        self._agent = None
        self._worker = Worker()
        self._lock = threading.Lock()

    # -- on the worker thread -----------------------------------------------------------------------------------
    def _get_agent(self):
        if self._agent is None:
            ensure_demo_db(self.settings)
            if self._factory is not None:
                self._agent = self._factory()
            else:
                from agent.agent import Agent
                self._agent = Agent(db_path=self.settings.demo_db)
        return self._agent

    def _key_present(self) -> bool:
        from agent.llm import load_agent_config
        from agent.rag.embedders.base import read_secret
        model = load_agent_config().model
        return bool(read_secret(model.api_key_env, self.settings.root / model.env_file))

    def _respond(self, session_id: str, message: str) -> dict:
        if self._factory is None and not self._key_present():
            raise MissingApiKey("no API key")
        return self._get_agent().respond(session_id, message)

    def _reset(self) -> None:
        self._agent = None                      # lets go of the agent, its sessions and its database connections
        gc.collect()
        reset_demo_db(self.settings)

    # -- called from the pages ----------------------------------------------------------------------------------
    def _run(self, fn, *args):
        return self._worker.run(fn, *args)

    def run_on_worker(self, fn):
        """Run `fn()` on the worker thread and return its result (the Manager page uses this for the decision; see manager_flow.py)."""
        return self._run(fn)

    def start_session(self, customer_id: str) -> str:
        return self._run(lambda: self._get_agent().start_session(customer_id))

    def respond(self, session_id: str, message: str) -> dict:
        return self._run(self._respond, session_id, message)

    def reset(self) -> None:
        """Put the demo database back and forget every session. Visitors must sign in again."""
        with self._lock:
            self._run(self._reset)
