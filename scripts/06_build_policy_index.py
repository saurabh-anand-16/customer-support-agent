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

The work is done by build_index() in agent/rag/index.py; this script only wires it to the config
and prints the result.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.rag import load_config, load_documents                     # noqa: E402
from agent.rag.chunkers import chunk_documents                        # noqa: E402
from agent.rag.embedders import EmbedderError, get_embedder           # noqa: E402
from agent.rag.index import build_index                               # noqa: E402
from agent.rag.stores import get_store                                # noqa: E402


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
