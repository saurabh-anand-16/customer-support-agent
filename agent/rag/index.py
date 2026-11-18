"""
index.py - build the vector index, and say whether an existing one matches the settings.

  build_index(cfg, chunks, embedder, store)  embed the chunks and write them to the store
  index_status(cfg, store)                   "ok", "missing" or "out_of_date" (plus a message)

Moved here from scripts/06_build_policy_index.py in phase 3c, unchanged, so that search can use
index_status() to refuse a stale index. The script is now only a command-line wrapper.
"""
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .stores import Record

# Metadata columns that are stored as the document itself or as the id, not as metadata.
_NOT_METADATA = {"chunk_id", "text"}


@dataclass
class BuildReport:
    chunks: int            # chunks in the new index
    embedded: int          # texts sent to the embedding model in this run
    cache_hits: int        # texts whose vector came from the cache
    added: int             # ids that were not in the store before
    removed: int           # ids that were in the store but are no longer chunks
    reset: bool            # True if the old index was thrown away (settings changed)
    dimension: int
    seconds: float


def index_status(cfg, store) -> tuple[str, str]:
    """("ok" | "missing" | "out_of_date", message). Search uses this to refuse a stale index."""
    recorded = store.get_meta().get("fingerprint")
    if not recorded:
        return "missing", "No index has been built yet. Run: python scripts/06_build_policy_index.py"
    if recorded != cfg.fingerprint:
        return "out_of_date", (
            f"The index was built with different settings (index fingerprint {recorded}, "
            f"current settings {cfg.fingerprint}). Rebuild it: python scripts/06_build_policy_index.py")
    return "ok", ""


def build_index(cfg, chunks, embedder, store, meta_path=None) -> BuildReport:
    """Write `chunks` to `store` using `embedder`. Safe to run again: same input, same index."""
    started = time.perf_counter()
    before = set(store.ids())
    reset = False
    if before and store.get_meta().get("fingerprint") != cfg.fingerprint:
        store.reset()                          # built with other settings (or unknown): start clean
        before, reset = set(), True
    embedded_before = embedder.embedded_count
    hits_before = getattr(embedder, "cache_hits", 0)

    vectors = embedder.embed([c.text for c in chunks])    # nothing is written if this fails

    keep = [f for f in cfg.metadata.fields if f not in _NOT_METADATA]
    store.add([Record(c.chunk_id, v, c.text, c.to_row(keep)) for c, v in zip(chunks, vectors)])
    stale = before - {c.chunk_id for c in chunks}
    store.delete(sorted(stale))

    dimension = len(vectors[0]) if vectors else 0
    meta = {"fingerprint": cfg.fingerprint, "embedder": embedder.name, "dimension": dimension,
            "chunks": len(chunks)}
    store.set_meta(meta)
    path = Path(meta_path) if meta_path else cfg.root / cfg.store.meta_path
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(meta, collection=cfg.store.collection, store=cfg.store.kind)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return BuildReport(
        chunks=len(chunks),
        embedded=embedder.embedded_count - embedded_before,
        cache_hits=getattr(embedder, "cache_hits", 0) - hits_before,
        added=len({c.chunk_id for c in chunks} - before),
        removed=len(stale),
        reset=reset,
        dimension=dimension,
        seconds=time.perf_counter() - started,
    )
