"""
05_chunk_policy.py - read the policy pages, split them into chunks, and write the result to
a CSV so the chunks can be inspected by eye (default: data/clean/policy_chunks.csv).

Everything is controlled by config/rag.toml. Pick a profile with RAG_PROFILE or --profile.
Run from the project root:  python scripts/05_chunk_policy.py
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.rag import load_config, load_documents    # noqa: E402
from agent.rag.chunkers import chunk_documents       # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None, help="profile name (default: RAG_PROFILE or the config default)")
    parser.add_argument("--config", default=None, help="config file (default: config/rag.toml)")
    parser.add_argument("--output", default=None, help="CSV to write (default: [metadata].export_path)")
    args = parser.parse_args()

    cfg = load_config(args.profile, path=args.config)
    docs = load_documents(cfg)
    chunks = chunk_documents(cfg, docs)

    out = Path(args.output) if args.output else cfg.root / cfg.metadata.export_path
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cfg.metadata.fields, lineterminator="\n")
        writer.writeheader()
        for chunk in chunks:
            writer.writerow(chunk.to_row(cfg.metadata.fields))

    sizes = [c.char_count for c in chunks]
    print(f"profile {cfg.profile}, strategy {cfg.chunking.strategy}, fingerprint {cfg.fingerprint}")
    print(f"{len(docs)} pages -> {len(chunks)} chunks (shortest {min(sizes)}, longest {max(sizes)} characters)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
