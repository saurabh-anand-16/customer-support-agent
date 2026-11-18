"""
Tests for the section scope rules ([[scope.rules]] in config/rag.toml; agent/rag/ingest.py and the loader in config.py).

A rule hides one section of an in-scope page: chunks that match it are marked out of scope and the
rule's reason is recorded on them. Every test builds its config from tests/rag_helpers.py and the
five rules below, which name headings on the real pages; none reads config/rag.toml except the two
tests marked LIVE FILE, which check only invariants of the real file.
"""
import csv
import json
import subprocess
import sys
from dataclasses import asdict

import pytest

from agent.policy_search import PolicySearch
from agent.rag import load_config, load_documents
from agent.rag.chunkers import chunk_documents, chunk_documents_unscoped
from agent.rag.config import ROOT, ConfigError, ScopeRule
from agent.rag.embedders import CachedEmbedder
from agent.rag.index import build_index, index_status
from agent.rag.ingest import apply_scope_rules, rule_matches
from agent.rag.stores import get_store

from .rag_helpers import make_config, write_config
from .test_rag_index import FakeEmbedder
from .test_rag_retrievers import BowEmbedder, make_world, real_chunks, tiny

GIFT = "gift orders are out of scope for this agent"
SELLER = "seller-fulfilled orders are out of scope for this agent"
FIVE = [
    {"file": "returns-and-replacements-faq.md", "heading": "5. How can I return a Gift?", "reason": GIFT},
    {"file": "received-someone-elses-order.md", "heading": "Return a Gift", "reason": GIFT},
    {"file": "damaged-or-defective-item.md",
     "heading": "4. How to return a damaged product fulfilled by a third-party seller?", "reason": SELLER},
    {"file": "returns-policy.md", "heading": "Seller Fulfilled Items", "reason": SELLER},
    {"file": "about-refunds.md", "heading": "Refund for Seller-Fulfilled Orders", "reason": SELLER},
]
HIDDEN_IDS = {
    "returns-and-replacements-faq#5-how-can-i-return-a-gift-p0",
    "received-someone-elses-order#return-a-gift-p0",
    "damaged-or-defective-item#4-how-to-return-a-damaged-product-fulfilled-by-a-third-party-seller-p0",
    "damaged-or-defective-item#4-how-to-return-a-damaged-product-fulfilled-by-a-third-party-seller-p1",
    "returns-policy#seller-fulfilled-items-p0",
    "about-refunds#refund-for-seller-fulfilled-orders-p0",
}
SEP = " > "


def cfg_with_rules(tmp_path, rules=FIVE, **more):
    return make_config(tmp_path, "bare", scope={"rules": rules}, **more)


@pytest.fixture(scope="module")
def scoped(tmp_path_factory):
    """(config with the five rules, all chunks with the rules applied)."""
    cfg = cfg_with_rules(tmp_path_factory.mktemp("scope_rules"))
    return cfg, chunk_documents(cfg, load_documents(cfg))


# === applying the rules =======================================================================
def test_the_chunks_a_rule_names_are_out_of_scope_with_the_reason_recorded(scoped):
    _, chunks = scoped
    hidden = {c.chunk_id: c for c in chunks if not c.in_scope and c.scope_reason}
    assert set(hidden) == HIDDEN_IDS
    assert {hidden[i].scope_reason for i in HIDDEN_IDS if "gift" in i} == {GIFT}
    assert {hidden[i].scope_reason for i in HIDDEN_IDS if "gift" not in i} == {SELLER}


def test_every_part_of_a_long_section_is_hidden_not_just_the_first(scoped):
    _, chunks = scoped
    parts = [c for c in chunks if c.chunk_id.startswith("damaged-or-defective-item#4-")]
    assert len(parts) == 2 and all(not c.in_scope and c.scope_reason == SELLER for c in parts)


def test_neighbouring_sections_on_the_same_page_stay_in_scope(scoped):
    _, chunks = scoped
    by_id = {c.chunk_id: c for c in chunks}
    for neighbour in ("returns-and-replacements-faq#6-how-can-i-return-a-gift-card-p0",     # next to the gift section
                      "returns-and-replacements-faq#4-how-can-i-return-a-seller-fulfilled-item-p0"
                      if "returns-and-replacements-faq#4-how-can-i-return-a-seller-fulfilled-item-p0" in by_id else
                      "returns-and-replacements-faq#1-what-can-i-return-p0",
                      "damaged-or-defective-item#3-how-to-return-a-damaged-product-fulfilled-by-amazon-p0",
                      "damaged-or-defective-item#5-how-to-replace-a-damaged-product-p0"):
        assert by_id[neighbour].in_scope is True and by_id[neighbour].scope_reason == "", neighbour


def test_only_the_scope_columns_change_and_the_text_is_exactly_as_before(scoped):
    cfg, chunks = scoped
    plain = chunk_documents_unscoped(cfg, load_documents(cfg))
    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in plain]
    for after, before in zip(chunks, plain):
        a, b = asdict(after), asdict(before)
        changed = {k for k in a if a[k] != b[k]}
        assert changed <= {"in_scope", "scope_reason"}, after.chunk_id


def test_a_page_that_is_out_of_scope_as_a_whole_keeps_an_empty_reason(scoped):
    _, chunks = scoped
    gift_page = [c for c in chunks if c.source_file == "return-a-gift.md"]
    assert gift_page and all(not c.in_scope and c.scope_reason == "" for c in gift_page)


def test_with_no_rules_the_chunks_are_exactly_what_the_chunkers_make(tmp_path):
    cfg = make_config(tmp_path, "bare")
    docs = load_documents(cfg)
    assert chunk_documents(cfg, docs) == chunk_documents_unscoped(cfg, docs)


# === what exactly a rule matches ================================================================
RULE = ScopeRule("page.md", "Return a Gift", "no gifts")


def at(heading_path, source_file="page.md"):
    return tiny("x", "text", source_file=source_file, heading_path=heading_path)


def test_a_rule_matches_a_section_with_exactly_its_heading(tmp_path):
    assert rule_matches(RULE, at("Title > Return a Gift"), SEP) and rule_matches(RULE, at("Return a Gift"), SEP)


def test_a_rule_does_not_match_a_longer_heading_that_merely_ends_the_same_way(tmp_path):
    assert not rule_matches(RULE, at("Title > How to Return a Gift"), SEP)


def test_a_rule_does_not_match_a_subsection_below_the_named_heading(tmp_path):
    assert not rule_matches(RULE, at("Title > Return a Gift > Using a receipt"), SEP)


def test_a_rule_only_matches_on_its_own_page(tmp_path):
    assert not rule_matches(RULE, at("Title > Return a Gift", source_file="other.md"), SEP)


def test_matching_is_exact_text_not_a_pattern_and_is_case_sensitive(tmp_path):
    star = ScopeRule("page.md", "Return.*", "x")
    assert not rule_matches(star, at("Title > Return a Gift"), SEP) and rule_matches(star, at("Title > Return.*"), SEP)
    question = ScopeRule("page.md", "5. How can I return a Gift?", "x")      # "." and "?" are plain characters
    assert rule_matches(question, at("T > 5. How can I return a Gift?"), SEP)
    assert not rule_matches(question, at("T > 5x How can I return a Gift"), SEP)
    assert not rule_matches(RULE, at("Title > return a gift"), SEP)


def test_the_path_separator_comes_from_the_config(tmp_path):
    assert rule_matches(RULE, at("Title / Return a Gift"), " / ") and not rule_matches(RULE, at("Title / Return a Gift"), SEP)


def test_apply_scope_rules_works_on_a_partial_list_of_chunks(tmp_path):
    cfg = make_config(tmp_path, "bare", scope={"rules": FIVE})
    only_one_page = [c for c in real_chunks() if c.source_file == "about-refunds.md"]
    out = apply_scope_rules(cfg, only_one_page)                  # the other four rules match nothing here, and that is fine
    assert [c.chunk_id for c in out if not c.in_scope] == ["about-refunds#refund-for-seller-fulfilled-orders-p0"]


# === loading and checking the rules ==================================================================
def test_a_rule_that_matches_no_chunk_is_a_config_error_naming_the_rule(tmp_path):
    rules = FIVE[:1] + [{"file": "returns-policy.md", "heading": "No Such Section", "reason": "x"}]
    with pytest.raises(ConfigError, match=r"scope rule for returns-policy.md / 'No Such Section' matches no chunk"):
        cfg_with_rules(tmp_path, rules)


def test_a_heading_that_is_almost_right_does_not_match(tmp_path):
    almost = [{"file": "returns-policy.md", "heading": "Seller Fulfilled Item", "reason": "x"}]
    with pytest.raises(ConfigError, match="matches no chunk"):
        cfg_with_rules(tmp_path, almost)


def test_a_rule_for_a_page_that_does_not_exist_says_so(tmp_path):
    with pytest.raises(ConfigError, match=r"there is no page called missing-page.md"):
        cfg_with_rules(tmp_path, [{"file": "missing-page.md", "heading": "Anything", "reason": "x"}])


def test_a_rule_that_went_stale_because_the_chunking_changed_is_caught_at_load(tmp_path):
    # The section "Seller Fulfilled Items" is a "###" or "##" heading. If sections are cut at level 1 only, it is no longer a chunk heading.
    with pytest.raises(ConfigError, match="matches no chunk"):
        cfg_with_rules(tmp_path, [FIVE[3]], chunking={"heading_levels": [1]})


def test_a_repeated_rule_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match=r"duplicate scope rule for returns-policy.md / 'Seller Fulfilled Items'"):
        cfg_with_rules(tmp_path, [FIVE[3], {**FIVE[3], "reason": "a different reason"}])


def test_the_same_heading_on_two_different_pages_is_not_a_duplicate(tmp_path):
    cfg = cfg_with_rules(tmp_path, [FIVE[1], {"file": "return-a-gift.md", "heading": "Return a Gift", "reason": GIFT}])
    assert len(cfg.scope.rules) == 2


@pytest.mark.parametrize("rule, message", [
    ({"file": "returns-policy.md", "heading": "Seller Fulfilled Items"}, "missing the key 'reason'"),
    ({"file": "returns-policy.md", "reason": "x"}, "missing the key 'heading'"),
    ({"heading": "Seller Fulfilled Items", "reason": "x"}, "missing the key 'file'"),
    ({"file": "returns-policy.md", "heading": "Seller Fulfilled Items", "reason": "x", "pattern": ".*"}, "unknown key 'pattern'"),
    ({"file": "returns-policy.md", "heading": "Seller Fulfilled Items", "reason": "  "}, "'reason' must be non-empty text"),
    ({"file": "returns-policy.md", "heading": 7, "reason": "x"}, "'heading' must be non-empty text"),
])
def test_a_badly_formed_rule_is_rejected_with_its_number(tmp_path, rule, message):
    with pytest.raises(ConfigError, match=rf"\[\[scope.rules\]\] number 1.*{message}|{message}"):
        cfg_with_rules(tmp_path, [rule])


def test_an_unknown_key_in_the_scope_table_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"unknown key 'rulez' in \[scope\]"):
        make_config(tmp_path, "bare", scope={"rulez": []})


def test_a_profile_cannot_change_the_scope_rules(tmp_path):
    with pytest.raises(ConfigError, match=r"profile 'vector' has unknown section \[scope\]"):
        make_config(tmp_path, "vector", profiles={"vector": {"scope": {"rules": []}}})


def test_a_config_with_no_scope_table_at_all_has_no_rules(tmp_path):
    assert make_config(tmp_path, "bare", scope=None).scope.rules == ()


# === the index fingerprint =====================================================================
def test_the_rules_are_part_of_the_fingerprint(tmp_path):
    none, five, four = (cfg_with_rules(tmp_path, r).fingerprint for r in ([], FIVE, FIVE[:4]))
    assert len({none, five, four}) == 3
    changed_reason = [{**FIVE[0], "reason": "another reason"}] + FIVE[1:]
    assert cfg_with_rules(tmp_path, changed_reason).fingerprint != five


def test_the_order_of_the_rules_does_not_change_the_fingerprint(tmp_path):
    assert cfg_with_rules(tmp_path, FIVE).fingerprint == cfg_with_rules(tmp_path, list(reversed(FIVE))).fingerprint


def test_no_rules_gives_the_same_fingerprint_as_a_config_without_the_scope_table(tmp_path):
    assert cfg_with_rules(tmp_path, []).fingerprint == make_config(tmp_path, "bare", scope=None).fingerprint


def test_a_search_setting_still_does_not_change_the_fingerprint_with_rules_present(tmp_path):
    assert cfg_with_rules(tmp_path).fingerprint == cfg_with_rules(tmp_path, retrieval={"top_k": 9}).fingerprint


# === search ======================================================================================
STRATEGY_PROFILE = {"bm25": "plain", "vector": "vector", "hybrid": "hybrid"}
GIFT_QUESTION = "how can I return a gift"
SELLER_QUESTION = "how to return a damaged product fulfilled by a third-party seller"


def search_for(tmp_path, kind, rules=FIVE):
    world = make_world(tmp_path, STRATEGY_PROFILE[kind], no_match={"bm25_min_score": 0.0, "vector_min_score": 0.0},
                       rerank={"method": "none"}, scope={"rules": rules})
    return PolicySearch(cfg=world.cfg, store=world.store, embedder=world.embedder, chunks=world.chunks), world


def ids(result):
    return [r["provenance"]["chunk_id"] for r in result["results"]]


@pytest.fixture(params=["bm25", "vector", "hybrid"])
def kind(request):
    return request.param


def test_a_rule_matched_section_is_hidden_from_the_default_results(tmp_path, kind):
    search, _ = search_for(tmp_path, kind)
    for question in (GIFT_QUESTION, SELLER_QUESTION, "refund for seller fulfilled orders"):
        assert not (set(ids(search.search_policy(question, top_k=30))) & HIDDEN_IDS), (kind, question)


def test_a_rule_matched_section_is_shown_and_marked_out_of_scope_when_asked_for(tmp_path, kind):
    search, _ = search_for(tmp_path, kind)
    result = search.search_policy(GIFT_QUESTION, top_k=30, include_out_of_scope=True)
    shown = [r for r in result["results"] if r["provenance"]["chunk_id"] in HIDDEN_IDS]
    assert {r["provenance"]["chunk_id"] for r in shown} >= {"returns-and-replacements-faq#5-how-can-i-return-a-gift-p0",
                                                            "received-someone-elses-order#return-a-gift-p0"}
    for r in shown:
        expected = GIFT if "gift" in r["provenance"]["chunk_id"] else SELLER
        assert r["in_scope"] is False and r["provenance"]["scope_reason"] == expected


def test_without_the_rules_the_same_sections_are_returned_as_in_scope_answers(tmp_path, kind):
    # Shows the rules are what hides them (this is the problem the phase fixes).
    search, _ = search_for(tmp_path, kind, rules=[])
    found = set(ids(search.search_policy(GIFT_QUESTION, top_k=30))) & HIDDEN_IDS
    assert "returns-and-replacements-faq#5-how-can-i-return-a-gift-p0" in found


def test_a_normal_result_has_an_empty_scope_reason(tmp_path, kind):
    search, _ = search_for(tmp_path, kind)
    results = search.search_policy("refund to a credit card", top_k=5)["results"]
    assert results and all(r["provenance"]["scope_reason"] == "" and r["in_scope"] is True for r in results)


def test_the_result_shape_is_unchanged_apart_from_the_reason_inside_provenance(tmp_path, kind):
    search, _ = search_for(tmp_path, kind)
    result = search.search_policy(GIFT_QUESTION, include_out_of_scope=True)
    assert set(result) == {"ok", "query", "profile", "index_fingerprint", "results"}
    for item in result["results"]:
        assert set(item) == {"source_file", "heading_path", "text", "score", "copied_on", "in_scope", "provenance"}
        assert set(item["provenance"]) == {"chunk_id", "scope_reason", "retrievers", "fusion", "fused_score", "rerank"}


def test_the_whole_result_can_be_written_as_json(tmp_path, kind):
    search, _ = search_for(tmp_path, kind)
    result = search.search_policy(GIFT_QUESTION, include_out_of_scope=True)
    assert json.loads(json.dumps(result)) == result


def test_the_other_sections_of_the_pages_are_still_found(tmp_path, kind):
    search, _ = search_for(tmp_path, kind)
    result = search.search_policy("what qualifies as damaged or defective products", top_k=10)
    assert any(i.startswith("damaged-or-defective-item#1-") for i in ids(result))


# === the index ====================================================================================
def build_world(tmp_path, rules):
    cfg = make_config(tmp_path, "vector", scope={"rules": rules}, store={"kind": "memory", "meta_path": str(tmp_path / "meta.json")})
    return cfg, chunk_documents(cfg, load_documents(cfg))


def test_changing_the_rules_makes_the_index_out_of_date_and_a_rebuild_embeds_nothing_new(tmp_path):
    cfg_a, chunks_a = build_world(tmp_path, FIVE[:2])
    embedder = CachedEmbedder(FakeEmbedder(cfg_a), tmp_path / "cache.jsonl")
    store = get_store(cfg_a)
    first = build_index(cfg_a, chunks_a, embedder, store)
    assert first.embedded > 0 and index_status(cfg_a, store) == ("ok", "")

    cfg_b, chunks_b = build_world(tmp_path, FIVE)
    status, message = index_status(cfg_b, store)
    assert status == "out_of_date" and "Rebuild" in message

    second = build_index(cfg_b, chunks_b, embedder, store)
    assert second.reset is True and second.embedded == 0 and second.cache_hits == len(chunks_b)
    assert index_status(cfg_b, store) == ("ok", "")
    third = build_index(cfg_b, chunks_b, embedder, store)
    assert third.reset is False and third.embedded == 0


def test_the_index_stores_the_scope_of_every_chunk_and_the_reason(tmp_path):
    cfg, chunks = build_world(tmp_path, FIVE)
    embedder, store = BowEmbedder(cfg), get_store(cfg)
    build_index(cfg, chunks, embedder, store)
    hidden = next(c for c in chunks if c.chunk_id == "returns-policy#seller-fulfilled-items-p0")
    stored = store.query(embedder.embed([hidden.text])[0], 1)[0]
    assert stored.chunk_id == hidden.chunk_id
    assert stored.metadata["in_scope"] is False and stored.metadata["scope_reason"] == SELLER
    assert all(m.metadata["in_scope"] is True for m in store.query(embedder.embed(["refund"])[0], 5, where={"in_scope": True}))
    assert not any(m.chunk_id in HIDDEN_IDS for m in store.query(embedder.embed([hidden.text])[0], 200, where={"in_scope": True}))


# === the chunk file ================================================================================
def test_the_chunk_file_has_the_scope_and_reason_columns(tmp_path):
    config = write_config(tmp_path, scope={"rules": FIVE})
    out = tmp_path / "chunks.csv"
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "05_chunk_policy.py"), "--config", str(config),
                             "--profile", "plain", "--output", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    with open(out, newline="", encoding="utf-8") as f:
        rows = {r["chunk_id"]: r for r in csv.DictReader(f)}
    assert {i for i, r in rows.items() if r["scope_reason"]} == HIDDEN_IDS
    assert all(rows[i]["in_scope"] == "False" for i in HIDDEN_IDS)
    assert rows["returns-and-replacements-faq#6-how-can-i-return-a-gift-card-p0"]["in_scope"] == "True"
    assert rows["return-a-gift#return-a-gift-p0"]["in_scope"] == "False" and rows["return-a-gift#return-a-gift-p0"]["scope_reason"] == ""


# === LIVE FILE: the real config/rag.toml ===========================================================
def test_live_file_every_rule_in_the_real_config_matches_a_real_chunk_and_has_a_reason():
    # Invariants only: whatever rules are in the file, each one names a section that exists, and has a reason.
    cfg = load_config()
    sep = cfg.metadata.heading_path_separator
    plain = chunk_documents_unscoped(cfg, load_documents(cfg))
    for rule in cfg.scope.rules:
        assert rule.reason.strip()
        assert any(rule_matches(rule, c, sep) for c in plain), (rule.file, rule.heading)
    assert len({(r.file, r.heading) for r in cfg.scope.rules}) == len(cfg.scope.rules)


def test_live_file_rule_matched_chunks_are_out_of_scope_and_nothing_else_changes():
    cfg = load_config()
    sep = cfg.metadata.heading_path_separator
    plain = {c.chunk_id: c for c in chunk_documents_unscoped(cfg, load_documents(cfg))}
    for chunk in chunk_documents(cfg, load_documents(cfg)):
        before = plain[chunk.chunk_id]
        matching = [r for r in cfg.scope.rules if rule_matches(r, chunk, sep)]
        if matching:
            assert chunk.in_scope is False and chunk.scope_reason == matching[0].reason
        else:
            assert chunk == before
