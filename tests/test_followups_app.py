"""
Tests of the phase 8b app follow-ups, part 1: chat sides, the red dot on the Manager queue link and the receipt card.
(Part 2 tests, the notices and the note, are in test_followups_notices.py.)

The pages run with Streamlit's AppTest on a COPY of the database and a fake agent. Each name says the situation it checks.
"""
import re
from pathlib import Path

from agent.review_queue import ReviewQueue
from app import components, data
from app.demo_db import ensure_demo_db
from tests.app_helpers import make_app, make_settings, result, send, sign_in
from tests.test_app import _escalation
from tests.test_manager_page import add_cases

APP = Path(__file__).resolve().parent.parent / "app"
CSS = (APP / "styles.css").read_text(encoding="utf-8")


def html_of(at) -> str:
    return " ".join(str(h.value) for h in at.get("html"))


def sidebar_html(at) -> str:
    return " ".join(str(h.value) for h in at.sidebar.get("html"))


def page_link_labels(at) -> list[str]:
    return [str(getattr(el, "label", "")) for el in at.get("page_link")]


# ---- chat sides -------------------------------------------------------------------------------------------------
def test_the_sides_css_has_the_two_bubble_colours_and_turns_the_customer_row_round():
    for needle in ("#E8EEF9", "#1F3A6B", "#E3F1EE", "#074A3F", "flex-end"):
        assert needle in CSS


def test_the_sides_css_is_loaded_once_per_page(tmp_path):
    at, _, _ = make_app(tmp_path)
    sign_in(at)
    send(at, "hello")
    assert sum("<style>" in str(m.value) for m in at.markdown) == 1
    assert sum(str(m.value).count("#E8EEF9") for m in at.markdown) == 1


def test_a_message_and_its_reply_each_have_a_label(tmp_path):
    at, _, _ = make_app(tmp_path)
    sign_in(at)
    send(at, "hello there")
    page = html_of(at)
    assert '<div class="who">You</div>' in page and '<div class="who">Agent</div>' in page


def test_the_bubbles_are_their_own_keyed_containers_and_the_cards_are_drawn_after_them():
    """The bubble is a container with its own key; the receipt and confirm card are drawn after the `with` block of the bubble ends."""
    source = (APP / "views" / "chat.py").read_text(encoding="utf-8")
    bubble_at = source.index('key=f"bubble-agent-{index}"')
    card_at = source.index("draw_receipt(turn, index, customer_id)")
    assert bubble_at < card_at
    bubble_block = source[bubble_at:card_at]
    last_line = [l for l in bubble_block.splitlines() if l.strip()][-1]
    assert last_line.startswith("        if turn.get") or last_line.startswith("        if "), last_line     # indentation falls back out of the bubble before the card


# ---- the red dot ------------------------------------------------------------------------------------------------
def test_no_dot_when_no_case_is_open(tmp_path):
    at, _, _ = make_app(tmp_path)
    at.run()
    assert "nav-dot" not in sidebar_html(at)


def test_the_dot_shows_the_number_of_open_cases_including_claimed_ones(tmp_path):
    ids = add_cases(tmp_path)                                  # an approval, a late request and a person case: three open
    at, backend, _ = make_app(tmp_path)
    queue = ReviewQueue(backend.settings.demo_db)
    assert queue.claim(ids["late"], "t")                       # claimed: still open
    queue.close()
    at.run()
    dot = sidebar_html(at)
    assert 'class="nav-dot"' in dot and ">3<" in dot and 'aria-label="3 open cases"' in dot


def test_the_dot_counts_down_and_disappears_at_zero(tmp_path):
    ids = add_cases(tmp_path, ("approval",))
    at, backend, _ = make_app(tmp_path)
    at.run()
    assert 'aria-label="1 open case"' in sidebar_html(at)
    queue = ReviewQueue(backend.settings.demo_db)
    assert queue.claim(ids["approval"], "t") and queue.finish(ids["approval"], "declined", "n", "t")
    queue.close()
    at.run()
    assert "nav-dot" not in sidebar_html(at)


def test_the_dot_is_on_every_page(tmp_path):
    add_cases(tmp_path, ("person",))
    at, _, _ = make_app(tmp_path)
    at.run()
    for page in ("views/home.py", "views/manager.py", "views/developer.py"):
        at.switch_page(page).run()
        assert 'aria-label="1 open case"' in sidebar_html(at)


def test_the_dot_html_has_the_number_in_it_and_nothing_at_zero():
    assert components.nav_dot_html(0) == "" and components.nav_dot_html(-1) == ""
    assert ">12<" in components.nav_dot_html(12) and "12 open cases" in components.nav_dot_html(12)


def test_the_dot_count_is_a_read_only_lookup(tmp_path):
    settings = make_settings(tmp_path)
    ensure_demo_db(settings)
    assert data.open_case_count(settings.demo_db) == 0
    queue = ReviewQueue(settings.demo_db)
    queue.create_item(customer_id="C0076", kind="customer_asked_for_person", reason="x")
    queue.close()
    assert data.open_case_count(settings.demo_db) == 1
    source = Path(data.__file__).read_text(encoding="utf-8")
    body = source[source.index("def open_case_count"):source.index("def item_product_name")]
    assert "_read_only(db)" in body and not re.search(r"\b(INSERT|UPDATE|DELETE|DROP)\b", body)


def test_the_sidebar_still_has_the_six_page_names_with_the_dot_present(tmp_path):
    add_cases(tmp_path, ("person",))
    at, _, _ = make_app(tmp_path)
    at.run()
    labels = [str(getattr(el, "label", "")) for el in at.sidebar.get("page_link")]
    assert labels == ["Home", "Customer chat", "Manager queue", "Developer trace", "How it works", "Limits and assumptions"]


def test_there_is_still_exactly_one_corner_tag_with_the_dot_on_the_page(tmp_path):
    add_cases(tmp_path, ("person",))
    at, _, _ = make_app(tmp_path)
    at.run()
    assert sum("corner-tag" in str(h.value) for h in at.get("html")) == 1


# ---- the receipt card -------------------------------------------------------------------------------------------
def receipt_page(tmp_path, kind, status):
    """A chat page whose last reply made a receipt for a case of this kind and status. Returns (AppTest, reference)."""
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    at, backend, agent = make_app(tmp_path)
    queue = ReviewQueue(backend.settings.demo_db)
    ref = queue.create_item(customer_id="C0076", kind=kind, reason="x")["item"]["id"]
    if status != "open":
        assert queue.claim(ref, "t") and queue.finish(ref, status, "n", "t")
    queue.close()
    agent.script = lambda m, c: result("Sent.", route="human_help", escalation=_escalation(ref))
    sign_in(at)
    send(at, "a person please")
    return at, ref


def test_a_person_case_reads_closed_never_approved_or_declined(tmp_path):
    for status in ("approved", "declined"):
        at, _ = receipt_page(tmp_path / status, "customer_asked_for_person", status)
        page = html_of(at)
        assert "Closed" in page and "Approved" not in page and "Declined" not in page


def test_the_other_kinds_keep_approved_and_declined(tmp_path):
    for kind in ("approval_required", "late_request"):
        for status, word in (("approved", "Approved"), ("declined", "Declined")):
            at, _ = receipt_page(tmp_path / f"{kind}-{status}", kind, status)
            assert word in html_of(at)


def test_an_open_case_reads_open_for_every_kind(tmp_path):
    for kind in ("customer_asked_for_person", "late_request", "approval_required"):
        at, _ = receipt_page(tmp_path / kind, kind, "open")
        assert ">Open<" in html_of(at)


def test_the_demo_tip_shows_only_while_the_case_is_open_and_links_to_the_manager_page(tmp_path):
    at, _ = receipt_page(tmp_path / "open", "customer_asked_for_person", "open")
    assert "Demo tip: open Manager queue to decide this." in page_link_labels(at)
    for status in ("approved", "declined"):
        at, _ = receipt_page(tmp_path / status, "customer_asked_for_person", status)
        assert not any("Demo tip" in label for label in page_link_labels(at))


def test_the_tip_goes_away_and_the_word_changes_when_the_case_is_decided_before_the_next_run(tmp_path):
    at, ref = receipt_page(tmp_path, "customer_asked_for_person", "open")
    assert "Demo tip: open Manager queue to decide this." in page_link_labels(at)
    queue = ReviewQueue(make_settings(tmp_path).demo_db)
    assert queue.claim(ref, "t") and queue.finish(ref, "approved", "n", "t")
    queue.close()
    at.run()
    assert "Closed" in html_of(at) and not any("Demo tip" in label for label in page_link_labels(at))


# ---- the dot follows the queue without a click on the chat page and the Manager page --------------------------------------------
def test_the_dot_is_drawn_by_plain_code_and_not_by_a_fragment_in_the_sidebar():
    """A polling fragment in the sidebar broke the page in a real browser ('Bad delta path index'), so main.py has none."""
    source = (APP / "main.py").read_text(encoding="utf-8")
    assert "st.fragment" not in source and "run_every" not in source


def test_the_chat_and_manager_pages_watch_the_count_from_their_own_fragment():
    chat = (APP / "views" / "chat.py").read_text(encoding="utf-8")
    manager = (APP / "views" / "manager.py").read_text(encoding="utf-8")
    assert "state.open_count_changed()" in chat and "run_every=None if busy else settings.poll_seconds" in chat
    assert "state.open_count_changed()" in manager and "@st.fragment(run_every=settings.poll_seconds)" in manager


def test_the_count_check_says_changed_only_when_the_open_count_is_not_the_one_drawn(tmp_path):
    at, backend, _ = make_app(tmp_path)
    at.run()
    from app import state
    drawn = at.session_state["dot_shown"]
    assert drawn == 0
    queue = ReviewQueue(backend.settings.demo_db)
    queue.create_item(customer_id="C0076", kind="customer_asked_for_person", reason="x")
    queue.close()

    import streamlit as st
    from unittest import mock
    with mock.patch.object(st, "session_state", {"_backend": backend, "dot_shown": 0}):
        assert state.open_count_changed() is True
    with mock.patch.object(st, "session_state", {"_backend": backend, "dot_shown": 1}):
        assert state.open_count_changed() is False
    at.run()
    assert at.session_state["dot_shown"] == 1                       # the next full run draws the new number and remembers it


def test_a_case_that_appears_while_a_page_is_open_shows_the_dot_on_the_next_run(tmp_path):
    at, backend, _ = make_app(tmp_path)
    sign_in(at)
    assert "nav-dot" not in sidebar_html(at)
    queue = ReviewQueue(backend.settings.demo_db)
    queue.create_item(customer_id="C0301", kind="customer_asked_for_person", reason="x")
    queue.close()
    at.run()
    assert 'aria-label="1 open case"' in sidebar_html(at)
