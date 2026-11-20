"""Phase 14k: session facts. Pure functions, the session, the facts block in the prompt and the config switch. No model calls."""
from types import SimpleNamespace

from agent.answer_check import facts_from, find_problems
from agent.branches.base import conversation_text
from agent.llm import DEFAULT_FACTS_LABEL, load_agent_config
from agent.session import Session
from agent.session_facts import extract_facts, facts_text, pending_item_id, with_item

from .test_router import agent_config

LABEL = "Facts:"


def order_call(order_id="O-100", items=(("I-1001", "Phone | 128 GB"), ("I-1002", "Case")), ok=True, refused=None):
    output = ({"ok": True, "order": {"order_id": order_id, "order_total_inr": 999},
               "items": [{"item_id": i, "product_name": n, "line_total_inr": 500} for i, n in items]}
              if ok else {"ok": False, "error_code": "not_found", "message": "none"})
    return {"tool": "get_order", "output": output, "refused": refused}


def elig_call(item_id="I-1002", ok=True):
    return {"tool": "check_eligibility", "refused": None,
            "output": {"ok": True, "item_id": item_id, "product_name": "x"} if ok else {"ok": False, "error_code": "not_found"}}


# === extract_facts ===========================================================================
def test_a_successful_get_order_gives_the_order_and_items_with_short_names():
    facts = extract_facts([order_call()])
    assert facts == {"order_id": "O-100", "items": [{"item_id": "I-1001", "name": "Phone"}, {"item_id": "I-1002", "name": "Case"}], "item": None}


def test_no_get_order_gives_none():
    assert extract_facts([elig_call()]) is None and extract_facts([]) is None


def test_not_found_and_refused_give_none():
    assert extract_facts([order_call(ok=False)]) is None
    assert extract_facts([order_call(refused="not allowed in this branch")]) is None


def test_the_last_successful_get_order_is_used():
    facts = extract_facts([order_call("O-1", (("I-1", "A"),)), order_call(ok=False), order_call("O-2", (("I-2", "B"),))])
    assert facts["order_id"] == "O-2" and [i["item_id"] for i in facts["items"]] == ["I-2"]


def test_the_item_being_discussed_comes_from_check_eligibility():
    assert extract_facts([order_call(), elig_call("I-1002")])["item"] == {"item_id": "I-1002", "name": "Case"}


def test_a_failed_check_eligibility_or_an_item_not_in_the_order_sets_no_item():
    assert extract_facts([order_call(), elig_call(ok=False)])["item"] is None
    assert extract_facts([order_call(), elig_call("I-9999")])["item"] is None


def test_the_pending_card_sets_the_item():
    card = {"type": "cancel", "parameters": {"item_id": "I-1001"}, "display": {"item_id": "I-1001"}}
    assert pending_item_id(card) == "I-1001" and pending_item_id(None) is None
    assert extract_facts([order_call()], card)["item"]["item_id"] == "I-1001"


def test_the_facts_never_hold_a_customer_id_or_amounts():
    call = order_call()
    call["output"]["order"]["customer_id"] = "C-SECRET"
    text = str(extract_facts([call])) + facts_text(extract_facts([call]), LABEL)
    assert "C-SECRET" not in text and "999" not in text and "500" not in text


def test_with_item_changes_only_the_item_and_ignores_unknown_ids():
    facts = extract_facts([order_call()])
    assert with_item(facts, "I-1001")["item"]["name"] == "Phone"
    assert with_item(facts, "I-0")["item"] is None and with_item(None, "I-1001") is None


# === the session =============================================================================
def test_a_new_session_has_no_facts():
    assert Session("s", "C-1").facts is None


def test_set_facts_replaces_and_none_leaves_them_alone():
    s = Session("s", "C-1")
    first, second = extract_facts([order_call("O-1", (("I-1", "A"),))]), extract_facts([order_call("O-2", (("I-2", "B"),))])
    s.set_facts(first)
    s.set_facts(None)                                  # a not_found turn: nothing changes
    assert s.facts == first
    s.set_facts(second)                                # replaced, not merged
    assert s.facts == second and all(i["item_id"] != "I-1" for i in s.facts["items"])


# === the text ================================================================================
def test_facts_text_lists_order_items_and_discussed_item():
    text = facts_text(extract_facts([order_call(), elig_call("I-1002")]), LABEL)
    assert text == "Facts: order O-100; items: I-1001 Phone, I-1002 Case; item being discussed: I-1002 Case."
    assert facts_text(None, LABEL) == ""


# === the prompt and the switch ==============================================================
def ctx_for(tmp_path, facts, **branches):
    cfg = agent_config(tmp_path, branches=branches) if branches else agent_config(tmp_path)
    session = Session("s", "C-1")
    session.facts = facts
    return SimpleNamespace(cfg=cfg, session=session, message="return it")


def test_the_real_config_ships_with_the_switch_off_and_a_label():
    cfg = load_agent_config()
    assert cfg.branches.session_facts is False and cfg.branches.facts_label.strip()


def test_a_config_without_the_new_keys_still_loads_with_defaults(tmp_path):
    cfg = agent_config(tmp_path)
    assert cfg.branches.session_facts is False and cfg.branches.facts_label == DEFAULT_FACTS_LABEL


def test_switch_off_the_prompt_is_the_same_with_or_without_facts(tmp_path):
    facts = extract_facts([order_call()])
    with_facts, without = conversation_text(ctx_for(tmp_path, facts)), conversation_text(ctx_for(tmp_path, None))
    assert with_facts == without and "O-100" not in with_facts
    assert without.endswith("\n\nCustomer message:\nreturn it") and "\n\nFacts" not in without


def test_switch_on_without_facts_adds_nothing(tmp_path):
    assert conversation_text(ctx_for(tmp_path, None, session_facts=True)) == conversation_text(ctx_for(tmp_path, None))


def test_switch_on_with_facts_puts_the_block_between_history_and_message(tmp_path):
    ctx = ctx_for(tmp_path, extract_facts([order_call()]), session_facts=True, facts_label=LABEL)
    text = conversation_text(ctx)
    assert text.index("(none)") < text.index("Facts: order O-100") < text.index("Customer message:")


# === the answer check ========================================================================
def test_an_id_from_the_facts_block_is_allowed_in_a_reply_when_the_text_is_added_as_a_source():
    facts_block = facts_text(extract_facts([order_call()]), LABEL)
    reply = "I can start with item I-1001."
    assert find_problems(reply, facts_from([])) != []                      # without the block the number 1001 is not backed
    assert find_problems(reply, facts_from([], None, [facts_block])) == []  # with it, it is


def test_amounts_are_not_made_allowed_by_the_facts_block():
    facts_block = facts_text(extract_facts([order_call()]), LABEL)
    assert find_problems("The refund is Rs. 500.", facts_from([], None, [facts_block])) != []
