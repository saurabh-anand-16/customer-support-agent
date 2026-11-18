"""
branch_agent.py - helpers that build a branch context (no langgraph needed) or a whole Agent for the 4b tests.

Everything uses the fixed config from test_router.py (which holds FIXED_BRANCHES), a scripted FakeChat and a FakePolicy.
The read tools run against the real generated database through the `tools_ro` / `tools_rw` fixtures.
"""
import json

from agent.branches import BranchContext
from agent.llm import FakeChat
from agent.session import Session
from agent.tool_adapter import ToolAdapter

from .branch_helpers import FakePolicy
from .test_router import agent_config


class SpyTools:
    """Wraps a ReturnsTools. Records every call (with the customer id it was given) and refuses to run a writer."""

    def __init__(self, tools):
        self._tools, self.calls, self.writer_calls = tools, [], []
        self.con = tools.con                       # the database connection, for counting rows (not a recorded call)

    def __getattr__(self, name):
        target = getattr(self._tools, name)
        if name in ("create_return", "cancel_order"):
            def blocked(*args, **kwargs):
                self.writer_calls.append((name, args, kwargs))
                raise AssertionError(f"{name} was run")
            return blocked
        if not callable(target):
            return target

        def recorded(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return target(*args, **kwargs)
        return recorded


def make_ctx(tmp_path, tools, replies, customer, policy=None, message="some message", session=None, **changes):
    """A BranchContext over a fixed config, a scripted model and the given tools. Returns (ctx, chat, policy)."""
    cfg = agent_config(tmp_path, **changes)
    chat = FakeChat(replies)
    policy = policy or FakePolicy()
    adapter = ToolAdapter(tools=tools, policy_search=policy, top_k=cfg.branches.policy_top_k)
    return BranchContext(cfg, chat, adapter, session or Session("s1", customer), message), chat, policy


def make_agent(tmp_path, tools, replies, customer, policy=None, **changes):
    """A whole Agent (needs langgraph). Returns (agent, chat, session id, policy)."""
    from agent import Agent
    chat = FakeChat(replies)
    policy = policy or FakePolicy()
    agent = Agent(config=agent_config(tmp_path, **changes), chat=chat, tools=tools, policy_search=policy)
    return agent, chat, agent.start_session(customer), policy


def order_of(raw, item_id):
    return raw.execute("SELECT order_id FROM order_items WHERE item_id = ?", (item_id,)).fetchone()["order_id"]


def counts(raw_con):
    """Rows in returns and cancelled items: what a writer would change."""
    return (raw_con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            raw_con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0])


def everything_sent_to_the_model(chat) -> str:
    """All prompt text the fake model was given, as one string."""
    return json.dumps([(c["system"], c["messages"]) for c in chat.calls])
