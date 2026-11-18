"""
Tests for building the index (scripts/06_build_policy_index.py: build_index and index_status).

Everything runs offline: vectors come from a small fake embedder, and the store is the in-memory
one (ChromaDB is used in two tests that skip when it is not installed). Every test builds its own
config from tests/rag_helpers.py and writes only to a temporary folder; none reads config/rag.toml.
"""
import importlib.util
import json
import subprocess
import sys

import pytest

from agent.rag import load_documents
from agent.rag.chunkers import chunk_documents, get_chunker
from agent.rag.config import ROOT
from agent.rag.embedders import CachedEmbedder, EmbedderError
from agent.rag.embedders.base import Embedder
from agent.rag.stores import get_store
from agent.rag.types import Document

from .rag_helpers import make_config, write_config
from .test_rag_embedders import SENTINEL_KEY, fake_vector

try:
    import chromadb   # noqa: F401
    HAVE_CHROMA = True
except ImportError:
    HAVE_CHROMA = False

_spec = importlib.util.spec_from_file_location("build_policy_index", ROOT / "scripts" / "06_build_policy_index.py")
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


class FakeEmbedder(Embedder):
    """Gives every text a fixed vector. Optionally fails, to show nothing is written then."""

    def __init__(self, cfg, fail=False):
        super().__init__(cfg)
        self.fail = fail

    def _embed_batch(self, texts):
        if self.fail:
            raise EmbedderError("the model is not reachable")
        return [fake_vector(t, 8) for t in texts]


PAGE = ("# Title\n\nIntro text.\n\n## Refunds\n\nRefunds go to the original payment method.\n\n"
        "## Returns\n\nReturn an item within the window.\n\n## Gifts\n\nGift items follow other rules.\n")


def page_chunks(cfg, text=PAGE, in_scope=True):
    doc = Document("page.md", "Title", text, "2026-11-17", in_scope, "Core policies")
    return get_chunker(cfg).chunk(doc)


def setup(tmp_path, kind="memory", **extra):
    """A config whose cache, store folder and meta file are all inside tmp_path, and a cached fake embedder."""
    cfg = make_config(tmp_path, store={"kind": kind, "path": str(tmp_path / "store"),
                                       "meta_path": str(tmp_path / "index_meta.json")},
                      embedding={"cache_path": str(tmp_path / "cache.jsonl")}, **extra)
    embedder = CachedEmbedder(FakeEmbedder(cfg), tmp_path / "cache.jsonl")
    return cfg, embedder, get_store(cfg)


def build(cfg, embedder, store, chunks):
    return script.build_index(cfg, chunks, embedder, store)


def test_the_first_build_embeds_every_chunk_and_stores_it(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    chunks = page_chunks(cfg)
    report = build(cfg, embedder, store, chunks)
    assert (report.chunks, report.embedded, report.added, report.removed) == (len(chunks), len(chunks), len(chunks), 0)
    assert store.ids() == sorted(c.chunk_id for c in chunks) and report.dimension == 8


def test_a_second_build_embeds_nothing(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    chunks = page_chunks(cfg)
    build(cfg, embedder, store, chunks)
    again = build(cfg, embedder, store, chunks)
    assert (again.embedded, again.cache_hits, again.added, again.removed) == (0, len(chunks), 0, 0)
    assert store.count() == len(chunks)                       # no duplicates


def test_a_second_build_gives_an_identical_index(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    chunks = page_chunks(cfg)
    build(cfg, embedder, store, chunks)
    snapshot = ([(m.chunk_id, m.text, m.metadata) for c in chunks for m in store.query(embedder.embed([c.text])[0], 1)],
                store.get_meta(), (tmp_path / "index_meta.json").read_bytes())
    build(cfg, embedder, store, chunks)
    assert snapshot == ([(m.chunk_id, m.text, m.metadata) for c in chunks for m in store.query(embedder.embed([c.text])[0], 1)],
                        store.get_meta(), (tmp_path / "index_meta.json").read_bytes())


def test_only_the_chunk_that_changed_is_embedded_again(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    build(cfg, embedder, store, page_chunks(cfg))
    changed = page_chunks(cfg, PAGE.replace("original payment method", "bank account you named"))
    report = build(cfg, embedder, store, changed)
    assert (report.embedded, report.added, report.removed) == (1, 0, 0)
    hit = store.query(embedder.embed([next(c.text for c in changed if "bank account" in c.text)])[0], 1)[0]
    assert "bank account" in hit.text and store.count() == len(changed)    # replaced, not added next to the old one


def test_a_chunk_that_no_longer_exists_is_removed_from_the_store(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    build(cfg, embedder, store, page_chunks(cfg))
    shorter = page_chunks(cfg, PAGE.split("## Gifts")[0])
    report = build(cfg, embedder, store, shorter)
    assert report.removed == 1 and report.embedded == 0
    assert not any("gifts" in chunk_id for chunk_id in store.ids())
    assert store.ids() == sorted(c.chunk_id for c in shorter)


def test_the_fingerprint_is_recorded_in_the_store_and_in_the_json_file(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    chunks = page_chunks(cfg)
    build(cfg, embedder, store, chunks)
    recorded = json.loads((tmp_path / "index_meta.json").read_text(encoding="utf-8"))
    assert store.get_meta()["fingerprint"] == recorded["fingerprint"] == cfg.fingerprint
    assert recorded["chunks"] == len(chunks) and recorded["dimension"] == 8 and recorded["embedder"] == embedder.name


def test_the_json_file_holds_no_chunk_text_and_no_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", SENTINEL_KEY)
    cfg, embedder, store = setup(tmp_path)
    build(cfg, embedder, store, page_chunks(cfg))
    content = (tmp_path / "index_meta.json").read_text(encoding="utf-8") + (tmp_path / "cache.jsonl").read_text(encoding="utf-8")
    assert SENTINEL_KEY not in content and "Refunds go to" not in content


def test_the_status_is_missing_then_ok_then_out_of_date_after_a_chunking_change(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    assert script.index_status(cfg, store)[0] == "missing"
    build(cfg, embedder, store, page_chunks(cfg))
    assert script.index_status(cfg, store) == ("ok", "")
    other = make_config(tmp_path, chunking={"max_chars": 800},
                        store={"kind": "memory", "path": str(tmp_path / "store")})   # same store, different chunking
    status, message = script.index_status(other, store)
    assert status == "out_of_date" and "Rebuild" in message and cfg.fingerprint in message and other.fingerprint in message


def test_an_embedding_model_change_also_makes_the_index_out_of_date(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    build(cfg, embedder, store, page_chunks(cfg))
    other = make_config(tmp_path, embedding={"model": "a-different-model"})
    assert script.index_status(other, store)[0] == "out_of_date"


def test_a_search_only_setting_does_not_make_the_index_out_of_date(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    build(cfg, embedder, store, page_chunks(cfg))
    other = make_config(tmp_path, retrieval={"top_k": 9}, rerank={"top_n": 2})
    assert script.index_status(other, store)[0] == "ok"


def test_building_after_a_settings_change_throws_the_old_index_away(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    build(cfg, embedder, store, page_chunks(cfg))
    small = make_config(tmp_path, chunking={"max_chars": 40},
                        store={"kind": "memory", "path": str(tmp_path / "store"), "meta_path": str(tmp_path / "index_meta.json")})
    new_chunks = page_chunks(small)
    assert {c.chunk_id for c in new_chunks} != set(store.ids())
    report = script.build_index(small, new_chunks, CachedEmbedder(FakeEmbedder(small), tmp_path / "cache.jsonl"), store)
    assert report.reset and store.ids() == sorted(c.chunk_id for c in new_chunks)
    assert script.index_status(small, store) == ("ok", "")


def test_stored_metadata_has_the_page_facts_but_not_the_text_or_the_id(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    chunk = page_chunks(cfg, in_scope=False)[1]
    build(cfg, embedder, store, [chunk])
    hit = store.query(embedder.embed([chunk.text])[0], 1)[0]
    assert hit.text == chunk.text and hit.chunk_id == chunk.chunk_id
    assert hit.metadata["in_scope"] is False and hit.metadata["source_file"] == "page.md"
    assert hit.metadata["heading_path"] == chunk.heading_path and hit.metadata["copied_on"] == "2026-11-17"
    assert "text" not in hit.metadata and "chunk_id" not in hit.metadata


def test_nothing_is_written_if_embedding_fails(tmp_path):
    cfg, _, store = setup(tmp_path)
    with pytest.raises(EmbedderError):
        build(cfg, FakeEmbedder(cfg, fail=True), store, page_chunks(cfg))
    assert store.count() == 0 and store.get_meta() == {} and not (tmp_path / "index_meta.json").exists()


def test_the_real_pages_all_go_into_the_index_and_each_chunk_finds_itself(tmp_path):
    cfg, embedder, store = setup(tmp_path)
    chunks = chunk_documents(cfg, load_documents(cfg))
    report = build(cfg, embedder, store, chunks)
    assert store.count() == report.chunks == len(chunks) > 100
    for c in chunks:      # a chunk's own vector finds a chunk with its text (two pages share one identical section)
        assert store.query(embedder.embed([c.text])[0], 1)[0].text == c.text
    out_of_scope = store.query(embedder.embed([chunks[0].text])[0], 500, where={"in_scope": False})
    assert out_of_scope and {m.metadata["source_file"] for m in out_of_scope} == {
        "a-to-z-guarantee.md", "third-party-seller-returns.md", "return-a-gift.md", "send-a-gift-receipt.md"}


@pytest.mark.skipif(not HAVE_CHROMA, reason="chromadb is not installed")
def test_the_real_pages_build_into_chromadb_and_a_second_run_embeds_nothing(tmp_path):
    cfg, embedder, store = setup(tmp_path, kind="chroma")
    chunks = chunk_documents(cfg, load_documents(cfg))
    first = build(cfg, embedder, store, chunks)
    second = build(cfg, embedder, store, chunks)
    distinct = len({c.text for c in chunks})            # identical texts are embedded once
    assert (first.embedded, second.embedded, second.cache_hits) == (distinct, 0, len(chunks))
    assert store.count() == len(chunks)
    assert store.query(embedder.embed([chunks[7].text])[0], 1)[0].text == chunks[7].text


@pytest.mark.skipif(not HAVE_CHROMA, reason="chromadb is not installed")
def test_a_settings_change_is_detected_and_rebuilt_in_chromadb(tmp_path):
    cfg, embedder, store = setup(tmp_path, kind="chroma")
    build(cfg, embedder, store, page_chunks(cfg))
    small = make_config(tmp_path, chunking={"max_chars": 40}, store={"kind": "chroma", "path": str(tmp_path / "store"),
                                                                    "meta_path": str(tmp_path / "index_meta.json"),
                                                                    "collection": cfg.store.collection})
    assert script.index_status(small, store)[0] == "out_of_date"
    report = script.build_index(small, page_chunks(small), CachedEmbedder(FakeEmbedder(small), tmp_path / "cache.jsonl"), store)
    assert report.reset and script.index_status(small, store)[0] == "ok"


def test_the_script_stops_with_a_clear_message_and_writes_nothing_when_the_key_is_missing(tmp_path):
    config = write_config(tmp_path,
                          embedding={"provider": "openai", "api_key_env": "NO_SUCH_KEY_VARIABLE_XYZ",
                                     "env_file": str(tmp_path / "absent.env"), "cache_path": ""},
                          store={"kind": "memory", "meta_path": str(tmp_path / "meta.json")})
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "06_build_policy_index.py"),
                             "--config", str(config), "--profile", "plain"],
                            capture_output=True, text=True, cwd=ROOT,
                            env={k: v for k, v in __import__("os").environ.items() if k != "NO_SUCH_KEY_VARIABLE_XYZ"})
    assert result.returncode == 2
    assert "NO_SUCH_KEY_VARIABLE_XYZ" in result.stderr and "Traceback" not in result.stderr
    assert not (tmp_path / "meta.json").exists()
