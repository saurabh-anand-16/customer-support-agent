"""
session.py - one conversation, and the store that holds them (in memory).

A Session is created with a customer id and that id never changes for its life. Nothing the customer
types, nothing the router returns and no branch can change it: the id is set once here, from the
caller (the app, after "log in"), and it is never read out of a message. It is also never sent to the
model.

A Session holds:
  history          the recent exchanges, oldest first: {"user", "assistant", "route"}
  pending_action   None, or a description of an action waiting for a yes or no (set from phase 4b)
  off_topic_count  off-topic messages in a row
"""
import uuid
from dataclasses import dataclass, field


class UnknownSession(KeyError):
    """No session has this id."""


@dataclass
class Session:
    session_id: str
    customer_id: str
    history: list = field(default_factory=list)
    pending_action: dict | None = None
    off_topic_count: int = 0

    def __post_init__(self):
        if not isinstance(self.customer_id, str) or not self.customer_id.strip():
            raise ValueError("A session needs a customer id (non-empty text)")

    def __setattr__(self, name, value):
        # The customer is fixed when the session is created; any later attempt to change it is refused.
        if name == "customer_id" and "customer_id" in self.__dict__:
            raise AttributeError("The customer of a session cannot be changed")
        super().__setattr__(name, value)

    def add_exchange(self, user: str, assistant: str, route: str, keep: int) -> None:
        """Remember one message and its reply, keeping only the newest `keep` exchanges."""
        self.history.append({"user": user, "assistant": assistant, "route": route})
        del self.history[:-keep]

    def recent(self, turns: int) -> list:
        """The last `turns` exchanges, oldest first (a copy)."""
        return [dict(e) for e in self.history[-turns:]] if turns > 0 else []


class SessionStore:
    """Sessions by id, in memory. A visitor's sessions live only as long as the process."""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create(self, customer_id: str) -> Session:
        session = Session(session_id=uuid.uuid4().hex, customer_id=customer_id)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise UnknownSession(f"No session with id '{session_id}'") from None

    def __len__(self) -> int:
        return len(self._sessions)
