"""
11_table_hashes.py - row count and content hash for every table of a database (phase 5a).

    python scripts/11_table_hashes.py [database]               # prints one line per table
    python scripts/11_table_hashes.py --json out.json [database]
    python scripts/11_table_hashes.py --compare before.json after.json

The hash of a table is the SHA-256 of all its rows, each row written as JSON, rows sorted by their text, so the order in
the file does not matter. Used to show that adding a table changed no existing table. The whole-file hash is printed
too, but it is expected to change when a table is added.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def table_hashes(db: Path) -> dict:
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        tables = {}
        for name in names:
            rows = sorted(json.dumps(list(r), default=str) for r in con.execute(f'SELECT * FROM "{name}"'))
            tables[name] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()}
    finally:
        con.close()
    return {"file_sha256": hashlib.sha256(Path(db).read_bytes()).hexdigest(), "tables": tables}


def compare(before: dict, after: dict) -> int:
    same, problems = [], []
    for name, b in before["tables"].items():
        a = after["tables"].get(name)
        (same if a == b else problems).append(name if a == b else f"{name}: before {b} after {a}")
    added = sorted(set(after["tables"]) - set(before["tables"]))
    print(f"tables identical before and after: {len(same)} of {len(before['tables'])}")
    print(f"tables added: {added or 'none'}")
    print(f"whole-file hash: {'unchanged' if before['file_sha256'] == after['file_sha256'] else 'changed'}")
    for p in problems:
        print("DIFFERENT:", p)
    return 1 if problems else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("database", nargs="*")
    p.add_argument("--json", default=None)
    p.add_argument("--compare", action="store_true")
    args = p.parse_args()
    if args.compare:
        a, b = (json.loads(Path(x).read_text(encoding="utf-8")) for x in args.database[:2])
        return compare(a, b)
    result = table_hashes(Path(args.database[0]) if args.database else ROOT / "returns_agent.db")
    print(f"file sha256 {result['file_sha256']}")
    for name, t in result["tables"].items():
        print(f"  {name:<22} {t['rows']:>6} rows  {t['sha256']}")
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
