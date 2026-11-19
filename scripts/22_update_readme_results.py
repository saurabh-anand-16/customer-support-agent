"""
22_update_readme_results.py - write the results block of README.md from data/evals/summary.json (phase 13).

    python scripts/22_update_readme_results.py            # rewrite the block
    python scripts/22_update_readme_results.py --check    # change nothing; exit 1 if the block is out of date

It only rewrites the text between the two marker lines in README.md:  <!-- results:start -->  and  <!-- results:end -->.
Everything else in the README is left exactly as it is, and a second run gives the same bytes. Every number is read from the summary (counts
first, then a percentage); a number the summary lacks is written as "not recorded". No model or network call is made, and no other file is written.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dev_common import NOT_RECORDED, get, pct      # noqa: E402  (plain functions, no Streamlit)

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- results:start -->", "<!-- results:end -->"


def block_text(summary) -> str:
    """The lines that go between the markers (no trailing newline)."""
    chosen = get(summary, "retrieval", "chosen_profile")
    profile = get(summary, "retrieval", "profiles", chosen) if isinstance(chosen, str) else None
    date, commit = get(summary, "date"), get(summary, "git_commit")
    scenarios = pct(get(summary, "scenarios", "passed"), get(summary, "scenarios", "scenarios"))
    search = pct(get(profile, "hit_at_5"), get(profile, "answerable_rows"))
    router = pct(get(summary, "router", "after", "correct"), get(summary, "router", "after", "rows"))
    return "\n".join([
        f"Measured on {date or NOT_RECORDED} at commit `{commit or NOT_RECORDED}`, from `data/evals/summary.json`.",
        "",
        "| What was measured | Result |",
        "| --- | --- |",
        f"| End-to-end scenarios passed | {scenarios} |",
        f"| Policy search: right page in the top 5 | {search} |",
        f"| Router: messages sent to the expected lane | {router} |",
        "",
        "The test sets are our own, reviewed by one person, on synthetic data. "
        "The full tables are in the Evaluation tab of the Developer trace page.",
    ])


def replace_block(readme: str, block: str) -> str:
    """The README with only the text between the markers replaced. Raises ValueError when the markers are missing or out of order."""
    if readme.count(START) != 1 or readme.count(END) != 1 or readme.index(START) > readme.index(END):
        raise ValueError(f"README needs exactly one {START} line followed by one {END} line")
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    newline = "\r\n" if "\r\n" in readme else "\n"
    return f"{head}{START}{newline}{block.replace(chr(10), newline)}{newline}{END}{tail}"


def read_summary(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument("--summary", type=Path, default=ROOT / "data" / "evals" / "summary.json")
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if the block is out of date")
    args = parser.parse_args(argv)
    summary = read_summary(args.summary)
    if not isinstance(summary, dict):
        print(f"Cannot read {args.summary}. Create it with: python scripts/20_write_summary.py")
        return 2
    with open(args.readme, encoding="utf-8", newline="") as f:         # newline="" keeps the file's own line endings
        old = f.read()
    try:
        new = replace_block(old, block_text(summary))
    except ValueError as error:
        print(error)
        return 2
    if new == old:
        print("README results block is up to date.")
        return 0
    if args.check:
        print("README results block is out of date. Run: python scripts/22_update_readme_results.py")
        return 1
    with open(args.readme, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print("README results block updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
