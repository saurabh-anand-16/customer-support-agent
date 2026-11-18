"""
Tests for the session and the session store (agent/session.py). No model and no config file are involved.
"""
import pytest

from agent.session import Session, SessionStore, UnknownSession


def test_a_session_keeps_the_customer_it_was_created_with():
    session = SessionStore().create("C0001")
    assert session.customer_id == "C0001"


def test_the_customer_cannot_be_changed_afterwards():
    session = SessionStore().create("C0001")
    with pytest.raises(AttributeError, match="cannot be changed"):
        session.customer_id = "C0123"
    with pytest.raises(AttributeError):
        setattr(session, "customer_id", "C0123")
    assert session.customer_id == "C0001"


def test_other_fields_can_still_change():
    session = SessionStore().create("C0001")
    session.off_topic_count = 2
    session.pending_action = {"description": "cancel item 3"}
    assert (session.off_topic_count, session.pending_action) == (2, {"description": "cancel item 3"}) and session.customer_id == "C0001"


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_a_session_needs_a_real_customer_id(bad):
    with pytest.raises(ValueError, match="needs a customer id"):
        SessionStore().create(bad)


def test_a_new_session_starts_empty():
    session = SessionStore().create("C0001")
    assert (session.history, session.pending_action, session.off_topic_count) == ([], None, 0)


def test_the_store_gives_back_the_same_session_for_an_id():
    store = SessionStore()
    session = store.create("C0001")
    assert store.get(session.session_id) is session and len(store) == 1


def test_an_id_that_was_never_issued_is_an_error():
    with pytest.raises(UnknownSession, match="No session with id"):
        SessionStore().get("not-a-real-id")


def test_session_ids_are_unique_and_hard_to_guess():
    store = SessionStore()
    ids = [store.create("C0001").session_id for _ in range(50)]
    assert len(set(ids)) == 50 and all(len(i) == 32 and int(i, 16) >= 0 for i in ids)


def test_two_sessions_do_not_share_anything():
    store = SessionStore()
    a, b = store.create("C0001"), store.create("C0002")
    a.add_exchange("hello", "hi", "out_of_scope", keep=5)
    a.off_topic_count = 2
    assert b.history == [] and b.off_topic_count == 0 and (a.customer_id, b.customer_id) == ("C0001", "C0002")


def test_history_keeps_only_the_newest_exchanges_as_configured():
    session = Session("s", "C0001")
    for n in range(1, 8):
        session.add_exchange(f"message {n}", f"reply {n}", "order_status", keep=3)
    assert [e["user"] for e in session.history] == ["message 5", "message 6", "message 7"]


def test_recent_gives_the_last_few_oldest_first_and_a_copy():
    session = Session("s", "C0001")
    for n in range(1, 5):
        session.add_exchange(f"m{n}", f"r{n}", "order_status", keep=10)
    recent = session.recent(2)
    assert [e["user"] for e in recent] == ["m3", "m4"]
    recent[0]["user"] = "changed"
    assert session.history[2]["user"] == "m3"
    assert session.recent(0) == [] and len(session.recent(99)) == 4


def test_an_exchange_records_the_route_taken():
    session = Session("s", "C0001")
    session.add_exchange("where is it", "not built yet", "order_status", keep=5)
    assert session.history == [{"user": "where is it", "assistant": "not built yet", "route": "order_status"}]
