"""
Tests of phase 8c (polish): the solid corner tag, the replacement wording of a notice, short product names, a "try" text per scenario
and the two replaced chips. Each name says the situation it checks.
"""
import re
import sqlite3
from pathlib import Path

from agent.llm import load_agent_config
from agent.names import short_product_name
from agent.review_notice import _text_for
from app import components, data
from app.config import load_app_settings, load_personas, product_name_limit
from tests.app_helpers import REAL_DB, ROOT, make_app, sign_in
from tests.test_followups_app import html_of

CSS = (ROOT / "app" / "styles.css").read_text(encoding="utf-8")
CARDS = {"C0076", "C0301", "C0399", "C0087", "C0117", "C0358"}


# ---- 1. the corner tag ----------------------------------------------------------------------------------------
def tag_rule() -> str:
    return re.search(r"\.corner-tag\s*\{([^}]*)\}", CSS).group(1)


def test_the_corner_tag_has_a_solid_background_and_a_thin_border():
    rule = tag_rule()
    assert re.search(r"background:\s*#[0-9A-Fa-f]{6}\s*;", rule) and "rgba" not in rule
    assert re.search(r"border:\s*1px solid", rule)


def test_the_corner_tag_lets_clicks_through_and_stays_top_right():
    rule = tag_rule()
    assert "pointer-events: none" in rule and "position: fixed" in rule and "right:" in rule and "top:" in rule


def test_there_is_still_exactly_one_corner_tag_on_home_and_on_the_chat(tmp_path):
    at, _, _ = make_app(tmp_path)
    at.run()
    assert html_of(at).count('class="corner-tag"') == 1
    sign_in(at)
    assert html_of(at).count('class="corner-tag"') == 1


# ---- 2. wording and short names ---------------------------------------------------------------------------------
class FakeTools:
    def __init__(self, resolution, name="Phone X | 6000mAh Battery | Upto 12GB RAM"):
        self.row = {"return_id": "R000074", "product_name": name, "resolution_requested": resolution,
                    "refund_amount_inr": None, "refund_method": None}

    def get_return_status(self, customer_id, item_id=None, return_id=None):
        return {"ok": True, "return": self.row}


ITEM = {"id": "REV-0001", "kind": "approval_required", "status": "approved", "customer_id": "C0001", "order_item_id": "OI000001"}


def test_an_approved_replacement_notice_says_replacement_request_reference():
    text, _ = _text_for(dict(ITEM), FakeTools("replacement"), load_agent_config())
    assert "Your replacement request reference is R000074." in text and "return number" not in text


def test_an_approved_return_notice_keeps_the_return_number_wording():
    text, _ = _text_for(dict(ITEM), FakeTools("refund"), load_agent_config())
    assert "Your return number is R000074." in text and "replacement request" not in text


def test_the_notice_shows_the_short_name():
    text, _ = _text_for(dict(ITEM), FakeTools("replacement"), load_agent_config())
    assert "Phone X (item" in text and "6000mAh" not in text


def test_the_short_name_is_cut_at_the_first_bar_and_at_the_limit():
    assert short_product_name("Samsung Galaxy M13 | 6000mAh Battery | 12GB") == "Samsung Galaxy M13"
    long = "A" * 30 + " " + "B" * 60
    out = short_product_name(long, 60)
    assert out.endswith("…") and len(out) <= 61
    assert short_product_name("Plain name", 60) == "Plain name"


def test_the_limit_comes_from_config_with_default_60():
    assert load_agent_config().review.product_name_max_chars == 60 == product_name_limit()


def test_the_full_name_stays_in_the_catalogue_and_the_helper_only_returns_a_copy():
    con = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    names = [r[0] for r in con.execute("SELECT product_name FROM products WHERE product_name LIKE '% | %' LIMIT 20")]
    assert names and all(short_product_name(n) != n for n in names) and all(" | " in n for n in names)


def test_the_card_line_the_header_and_the_confirm_card_use_the_short_name():
    full = "Samsung Galaxy M13 (Aqua Green) | 6000mAh Battery | Upto 12GB RAM"
    assert data.short_name(full) == "Samsung Galaxy M13 (Aqua Green)"
    assert "6000mAh" not in data.item_line({"product_name": full, "item_status": "delivered"})
    card = {"item": {"product_name": full, "item_id": "OI1"}, "action": "return"}
    assert "6000mAh" not in components.confirm_card_html(card, None)


# ---- 3. a "try" text per scenario ----------------------------------------------------------------------------
def test_every_scenario_card_has_a_try_text():
    cards = {p.customer_id: p for p in load_personas() if p.card}
    assert set(cards) == CARDS and all(p.try_text and p.try_text.strip() for p in cards.values())


def test_an_order_number_in_a_try_text_belongs_to_that_customer():
    con = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    for p in load_personas():
        for number in re.findall(r"\b\d{3}-\d{7}-\d{7}\b", p.try_text or ""):
            row = con.execute("SELECT 1 FROM orders WHERE order_id = ? AND customer_id = ?", (number, p.customer_id)).fetchone()
            assert row, f"{p.customer_id}: {number} is not their order"


def test_home_shows_the_try_text_on_the_card(tmp_path):
    at, _, _ = make_app(tmp_path)
    at.run()
    page = html_of(at)
    for p in load_personas():
        if p.card:
            assert f"Try: “{components.esc(p.try_text)}”" in page


def test_the_chat_offers_the_try_text_as_the_first_chip_and_it_is_sent_as_an_ordinary_message(tmp_path):
    at, _, agent = make_app(tmp_path)
    persona = next(p for p in load_personas() if p.customer_id == "C0076")
    sign_in(at, "C0076")
    chips = [b for b in at.button if str(b.key).startswith("chip-")]
    assert chips[0].label == persona.try_text
    chips[0].click().run()
    assert agent.calls[-1][1] == persona.try_text


# ---- 4. the chips ------------------------------------------------------------------------------------------------
def test_the_general_chips_are_the_three_agreed_ones_and_the_config_says_they_are_temporary():
    assert list(load_app_settings().suggested_messages) == ["Where is my refund?", "What happens if my item is damaged or defective?",
                                                            "How does a Pay on Delivery refund work?"]
    text = (ROOT / "config" / "agent.toml").read_text(encoding="utf-8")
    assert "TEMPORARY" in text.split("suggested_messages")[0][-600:]
