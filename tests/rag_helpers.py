"""
rag_helpers.py - a fixed test config for the policy-search tests.

The tests must not depend on the values in config/rag.toml (chunk size, table handling,
profiles and so on), because those are meant to be tuned. So a test that checks behaviour
builds its config here from FIXED_CONFIG, below, and overrides only the settings it is about:

    cfg = make_config(tmp_path, chunking={"max_chars": 600})

An override value of None removes that key (to test "missing key"). Only the few tests that
check the real config/rag.toml itself call load_config() with no path.
"""
import copy
import json
from pathlib import Path

from agent.rag.config import RagConfig, load_config

# Every key the loader requires, with values chosen for the tests. Changing config/rag.toml
# does not change this.
FIXED_CONFIG = {
    "default_profile": "plain",
    "sources": {
        "policy_dir": "policy",
        "include_glob": "*.md",
        "exclude_files": ["README.md", "CHANGES.md"],
        "readme_file": "README.md",
        "copy_date_pattern": r"copied on (\d{4}-\d{2}-\d{2})",
        "page_type_heading_level": 3,
        "out_of_scope_files": ["a-to-z-guarantee.md", "third-party-seller-returns.md",
                               "return-a-gift.md", "send-a-gift-receipt.md"],
    },
    "chunking": {
        "strategy": "heading", "max_chars": 1200, "overlap_chars": 0,
        "include_heading_in_text": True, "heading_levels": [1, 2, 3],
        "merge_empty_headings": True, "table_handling": "split_rows",
    },
    "metadata": {
        "fields": ["chunk_id", "source_file", "page_title", "heading_path", "heading_level",
                   "part_index", "text", "char_count", "copied_on", "in_scope", "page_type"],
        "heading_path_separator": " > ",
        "export_path": "data/clean/test_chunks.csv",
    },
    "text": {
        "remove_toc": True, "toc_label": "**Table of Contents**",
        "toc_item_pattern": r"^\s*[-*]\s+\[.*\]\(#[^)]*\)\s*$", "collapse_blank_lines": True,
    },
    "embedding": {"provider": "test", "model": "test-model", "dimensions": 8, "batch_size": 4,
                  "normalize": True, "query_prefix": ""},
    "store": {"kind": "test", "path": "data/test_index", "collection": "test", "distance": "cosine"},
    "retrieval": {"strategy": "bm25", "top_k": 5, "candidate_k": 20, "bm25_k1": 1.5, "bm25_b": 0.75},
    "fusion": {"method": "rrf", "rrf_k": 60, "weight_bm25": 1.0, "weight_vector": 1.0},
    "rerank": {"method": "none", "top_n": 5, "cross_encoder_model": "test-ce", "llm_model": "test-llm"},
    "no_match": {"min_score": 0.0, "min_hits": 1, "note": "not covered"},
    "citations": {"format": "{page_title}", "show_copied_on": True},
    "profiles": {
        "plain": {"retrieval": {"strategy": "bm25"}, "fusion": {"method": "none"}},
        "vector": {"retrieval": {"strategy": "vector"}},
        "hybrid": {"retrieval": {"strategy": "hybrid"}, "rerank": {"method": "cross_encoder"}},
    },
}


def _merge(base: dict, extra: dict) -> dict:
    """Copy of `base` with `extra` laid over it, table by table. A value of None deletes the key."""
    merged = copy.deepcopy(base)
    for key, value in extra.items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def to_toml(data: dict, prefix: str = "") -> str:
    """Write a dict as TOML. Enough for what the config uses: text, numbers, true/false, lists, tables."""
    lines = [f"{key} = {json.dumps(value)}" for key, value in data.items() if not isinstance(value, dict)]
    out = "\n".join(lines) + "\n" if lines else ""
    for key, value in data.items():
        if isinstance(value, dict):
            name = f"{prefix}.{key}" if prefix else key
            body = to_toml(value, name)
            out += f"\n[{name}]\n{body}" if any(not isinstance(v, dict) for v in value.values()) else body
    return out


def write_config(tmp_path: Path, **changes) -> Path:
    """Write the fixed config, with `changes` laid over it, to tmp_path/rag.toml. Returns the path."""
    path = tmp_path / "rag.toml"
    path.write_text(to_toml(_merge(FIXED_CONFIG, changes)), encoding="utf-8")
    return path


def make_config(tmp_path: Path, profile: str = "plain", **changes) -> RagConfig:
    """Load the fixed config (with `changes` laid over it). The profile is always named, so the
    RAG_PROFILE environment variable cannot change what a test gets."""
    return load_config(profile, path=write_config(tmp_path, **changes))
