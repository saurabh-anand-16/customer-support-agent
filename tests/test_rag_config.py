"""
Tests for the RAG config loader (agent/rag/config.py).

Almost every test here builds its own config from the fixed values in tests/rag_helpers.py,
changes one setting, and loads that. So editing config/rag.toml (chunk size, profiles, and so
on) cannot break them.

Only the tests marked "LIVE FILE" call load_config() with no path. They check things that must
hold for any sensible rag.toml (it loads, every profile in it loads, the fingerprint behaves),
not particular values.
"""
import pytest

from agent.rag import load_config
import agent.rag.chunkers   # noqa: F401  (importing it registers the chunkers)
from agent.rag.config import ConfigError, load_config as load_config_from
from agent.rag.registry import names

from .rag_helpers import make_config, write_config


# --- LIVE FILE: config/rag.toml itself ----------------------------------------------------
def test_live_file_loads_and_its_default_profile_and_chunker_exist():
    # Invariant: whatever the values are, the file must load, name a real chunker and have sane sizes.
    cfg = load_config()
    assert cfg.profile
    assert cfg.chunking.strategy in names("chunker")
    assert 0 <= cfg.chunking.overlap_chars < cfg.chunking.max_chars
    assert cfg.sources.exclude_files and cfg.metadata.fields


def test_live_file_has_the_five_named_profiles_and_each_loads():
    # Invariant: the profile names are a contract with phase 3d; the values behind them are not tested.
    for name in ["baseline_bm25", "vector_only", "hybrid", "hybrid_cross_encoder", "hybrid_llm_rerank"]:
        assert load_config(name).profile == name


def test_live_file_fingerprint_is_stable_across_loads():
    assert load_config().fingerprint == load_config().fingerprint


def test_live_file_gives_the_same_fingerprint_for_every_profile():
    # Invariant: a profile must only change search settings, never what the index is built from.
    profiles = ["baseline_bm25", "vector_only", "hybrid", "hybrid_cross_encoder", "hybrid_llm_rerank"]
    assert len({load_config(p).fingerprint for p in profiles}) == 1


# --- loading and profiles (fixed config) ----------------------------------------------------
def test_fixed_config_loads_with_its_values(tmp_path):
    cfg = make_config(tmp_path)
    assert (cfg.profile, cfg.chunking.strategy, cfg.chunking.max_chars) == ("plain", "heading", 1200)
    assert cfg.sources.exclude_files == ["README.md", "CHANGES.md"]


def test_profile_overrides_only_the_keys_it_lists(tmp_path):
    base, hybrid = make_config(tmp_path, "plain"), make_config(tmp_path, "hybrid")
    assert (base.retrieval.strategy, base.rerank.method) == ("bm25", "none")
    assert (hybrid.retrieval.strategy, hybrid.rerank.method) == ("hybrid", "cross_encoder")
    assert hybrid.retrieval.top_k == base.retrieval.top_k      # not overridden, so shared
    assert hybrid.chunking == base.chunking


def test_environment_variable_picks_the_profile_and_an_argument_beats_it(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    monkeypatch.setenv("RAG_PROFILE", "hybrid")
    assert load_config_from(path=path).profile == "hybrid"
    assert load_config_from("vector", path=path).profile == "vector"


def test_with_no_argument_or_variable_the_default_profile_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv("RAG_PROFILE", raising=False)
    assert load_config_from(path=write_config(tmp_path, default_profile="vector")).profile == "vector"


def test_a_missing_profile_fails_and_lists_the_real_ones(tmp_path):
    with pytest.raises(ConfigError, match="no profile named 'nope'.*hybrid.*plain.*vector"):
        load_config_from("nope", path=write_config(tmp_path))


# --- bad files are rejected with a clear message ------------------------------------------
def test_unknown_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"unknown key 'max_charz' in \[chunking\]"):
        make_config(tmp_path, chunking={"max_charz": 1200})


def test_unknown_section_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"unknown section \[surprise\]"):
        make_config(tmp_path, surprise={"x": 1})


def test_wrong_type_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"\[chunking\]\.max_chars must be a whole number"):
        make_config(tmp_path, chunking={"max_chars": "big"})


def test_true_is_not_accepted_as_a_number(tmp_path):
    with pytest.raises(ConfigError, match=r"\[retrieval\]\.top_k must be a whole number"):
        make_config(tmp_path, retrieval={"top_k": True})


def test_a_missing_key_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match=r"\[chunking\] is missing the key 'overlap_chars'"):
        make_config(tmp_path, chunking={"overlap_chars": None})


def test_a_profile_cannot_set_an_unknown_key(tmp_path):
    with pytest.raises(ConfigError, match="unknown key 'strat'"):
        make_config(tmp_path, "vector", profiles={"vector": {"retrieval": {"strat": "vector"}}})


def test_a_profile_cannot_use_an_unknown_section(tmp_path):
    with pytest.raises(ConfigError, match=r"profile 'vector' has unknown section \[surprise\]"):
        make_config(tmp_path, "vector", profiles={"vector": {"surprise": {"x": 1}}})


def test_overlap_must_be_smaller_than_the_chunk_size(tmp_path):
    with pytest.raises(ConfigError, match="overlap_chars"):
        make_config(tmp_path, chunking={"max_chars": 500, "overlap_chars": 500})


def test_chunk_size_must_be_above_zero(tmp_path):
    with pytest.raises(ConfigError, match="max_chars must be above 0"):
        make_config(tmp_path, chunking={"max_chars": 0})


def test_table_handling_must_be_one_of_the_two_known_values(tmp_path):
    with pytest.raises(ConfigError, match="table_handling"):
        make_config(tmp_path, chunking={"table_handling": "shred"})


def test_metadata_field_must_exist_on_a_chunk(tmp_path):
    fields = make_config(tmp_path).metadata.fields
    with pytest.raises(ConfigError, match="unknown field 'colour'"):
        make_config(tmp_path, metadata={"fields": fields + ["colour"]})


def test_metadata_fields_must_include_chunk_id_and_text(tmp_path):
    with pytest.raises(ConfigError, match="must include 'text'"):
        make_config(tmp_path, metadata={"fields": ["chunk_id"]})


def test_a_broken_pattern_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="toc_item_pattern is not a valid pattern"):
        make_config(tmp_path, text={"toc_item_pattern": "(^"})


def test_a_missing_file_gives_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="Config file not found"):
        load_config_from(path=tmp_path / "absent.toml")


def test_a_missing_default_profile_line_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="default_profile"):
        make_config(tmp_path, default_profile=None)


# --- the index fingerprint (fixed config) -------------------------------------------------
def test_fingerprint_is_stable_across_loads(tmp_path):
    assert make_config(tmp_path).fingerprint == make_config(tmp_path).fingerprint


def test_fingerprint_changes_when_chunk_size_changes(tmp_path):
    assert make_config(tmp_path, chunking={"max_chars": 800}).fingerprint != make_config(tmp_path).fingerprint


def test_fingerprint_changes_for_each_index_shaping_setting(tmp_path):
    base = make_config(tmp_path).fingerprint
    changes = [
        {"chunking": {"strategy": "fixed"}},
        {"chunking": {"merge_empty_headings": False}},
        {"chunking": {"table_handling": "keep_whole"}},
        {"embedding": {"model": "another-model"}},
        {"embedding": {"dimensions": 16}},
        {"metadata": {"heading_path_separator": " / "}},
        {"text": {"remove_toc": False}},
        {"sources": {"out_of_scope_files": []}},
    ]
    for change in changes:
        assert make_config(tmp_path, **change).fingerprint != base, change


def test_fingerprint_ignores_search_only_settings(tmp_path):
    base = make_config(tmp_path).fingerprint
    changes = [
        {"retrieval": {"top_k": 9}}, {"fusion": {"rrf_k": 30}}, {"no_match": {"min_score": 0.5}},
        {"retrieval": {"bm25_k1": 1.2}}, {"rerank": {"top_n": 3}},
        {"embedding": {"batch_size": 99}},                       # how fast, not what is embedded
        {"metadata": {"export_path": "somewhere/else.csv"}},     # where the CSV goes
    ]
    for change in changes:
        assert make_config(tmp_path, **change).fingerprint == base, change


def test_fingerprint_is_the_same_for_every_profile(tmp_path):
    assert len({make_config(tmp_path, p).fingerprint for p in ["plain", "vector", "hybrid"]}) == 1
