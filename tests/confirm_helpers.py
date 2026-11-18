"""
confirm_helpers.py - setup for the phase 4c tests (confirm step, answer check, guardrails).

Behaviour tests never read config/agent.toml: they use the fixed config from test_router.py (FIXED_AGENT, with the
confirm and answer-check sections from branch_helpers.py), a scripted model and the real tools over a COPY of the database.

  RoleChat      one fake model for the router, the branches and the confirm step. Each role has its own list of replies,
                used in order (the last one repeats), so a test says what each part of the agent answers.
  WriterSpy     wraps the real tools over the copy, records every call, and lets the two writers run (the 4b SpyTools
                refuses to). `writer_calls` is what the tests look at to see who wrote.
  agent_for     builds a whole Agent over a RoleChat and a WriterSpy for one customer.
"""
import json

from agent.llm import ChatModel, LlmError

from .branch_agent import make_agent  # noqa: F401  (re-exported for the tests)
from .branch_helpers import FakePolicy
from .test_router import agent_config

WRITERS = ("create_return", "cancel_order")


class WriterSpy:
    """The real tools, with every call recorded. Unlike the 4b SpyTools, the writers run."""

    def __init__(self, tools):
        self._tools, self.calls, self.writer_calls = tools, [], []
        self.con = tools.con

    def __getattr__(self, name):
        target = getattr(self._tools, name)
        if not callable(target):
            return target

        def recorded(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name in WRITERS:
                self.writer_calls.append((name, args, kwargs))
            return target(*args, **kwargs)
        return recorded


class RoleChat(ChatModel):
    """
    A fake model that answers by role, chosen from the system prompt: "ROUTER PROMPT", "CONFIRM PROMPT", else the branch.
    A role's replies are a list used in order; the last repeats. An Exception in a list is raised. Every call is recorded
    in `.calls` with its role.
    """

    def __init__(self, router=None, branch=None, confirm=None):
        self.queues = {"router": list(router or []), "branch": list(branch or []), "confirm": list(confirm or [])}
        self.used = {"router": 0, "branch": 0, "confirm": 0}
        self.calls = []

    @staticmethod
    def role_of(system: str) -> str:
        return "router" if system.startswith("ROUTER PROMPT") else "confirm" if system.startswith("CONFIRM PROMPT") else "branch"

    def complete(self, system, messages, settings):
        role = self.role_of(system)
        self.calls.append({"role": role, "system": system, "messages": messages, "model": settings.name, "temperature": settings.temperature})
        queue = self.queues[role]
        if not queue:
            raise AssertionError(f"the {role} model was called but the test gave it no reply")
        reply = queue[min(self.used[role], len(queue) - 1)]
        self.used[role] += 1
        if isinstance(reply, Exception):
            raise reply
        return reply

    def count(self, role: str) -> int:
        return sum(1 for c in self.calls if c["role"] == role)


def label(name, **extra) -> str:
    """What the confirm step's model says."""
    return json.dumps({"label": name, "reason": "because", **extra})


def agent_for(tmp_path, spy, chat, customer, policy=None, **changes):
    """A whole Agent (needs langgraph) over the fixed config, `chat`, and the spy-wrapped tools. Returns (agent, session id)."""
    from agent import Agent
    agent = Agent(config=agent_config(tmp_path, **changes), chat=chat, tools=spy, policy_search=policy or FakePolicy())
    return agent, agent.start_session(customer)


def db_state(con) -> dict:
    """What a writer would change: the returns, and the cancelled items."""
    return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0]}


def sent_to_the_model(chat, role=None) -> str:
    return json.dumps([(c["system"], c["messages"]) for c in chat.calls if role in (None, c["role"])])


__all__ = ["LlmError", "RoleChat", "WriterSpy", "agent_for", "db_state", "label", "sent_to_the_model"]
