"""
06_build_policy_index.py - embed the policy chunks and write them to the vector store.

What it does (all settings come from config/rag.toml; pick a profile with --profile or RAG_PROFILE):
  1. reads the policy pages and splits them into chunks (phase 3a)
  2. embeds each chunk's text (vectors already in the cache are reused, so unchanged chunks cost nothing)
  3. writes the chunks to the store: same ids are replaced, chunks that no longer exist are removed
  4. records the index fingerprint in the store and in data/rag/index_meta.json

Run it twice: the second run embeds nothing. If the settings that shape the index changed
(chunking, metadata, embedding model, ...), the old index is thrown away and rebuilt.
Run from the project root:  python scripts/06_build_policy_index.py

The functions build_index() and index_status() are plain functions so tests (and phase 3c's
search) can use them; the script only wires them to the config.
"""
import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.rag import load_config, load_documents                     # noqa: E402
from agent.rag.chunkers import chunk_documents                        # noqa: E402
from agent.rag.embedders import EmbedderError, get_embedder           # noqa: E402
from agent.rag.stores import Record, get_store                        # noqa: E402

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default=None, help="profile name (default: RAG_PROFILE or the config default)")
    parser.add_argument("--config", default=None, help="config file (default: config/rag.toml)")
    args = parser.parse_args()

    cfg = load_config(args.profile, path=args.config)
    chunks = chunk_documents(cfg, load_documents(cfg))
    try:
        embedder = get_embedder(cfg)
        store = get_store(cfg)
        report = build_index(cfg, chunks, embedder, store)
    except (EmbedderError, ImportError) as err:
        print(f"error: {err}", file=sys.stderr)       # these messages never contain the API key
        return 2

    print(f"profile {cfg.profile}, embedder {embedder.name}, store {cfg.store.kind} at {store.path}")
    print(f"chunks: {report.chunks}")
    print(f"embedded in this run: {report.embedded} (vectors reused from the cache: {report.cache_hits})")
    print(f"store: {report.added} added, {report.removed} removed, {store.count()} in total"
          + ("  [old index thrown away: settings changed]" if report.reset else ""))
    print(f"vector size {report.dimension}, took {report.seconds:.1f} s, fingerprint {cfg.fingerprint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
