"""
eval_split.py - the dev/test split rule shared by the evaluation scripts (router in phase 4a, retrieval in 3d).

A row goes to "test" or "dev" by a fixed rule on its id and category only, so adding or removing other rows
never moves an old one, and the answer is the same on every run. About `test_fraction` of each category goes
to test (the router evaluation reads that fraction from [eval] in config/agent.toml).

Rule: take the first 8 hex digits of sha256("<category>|<id>") as a number between 0 and 1. Below
test_fraction means test, otherwise dev. Tune on dev; look at test once, at the end.
"""
import csv
import hashlib
from pathlib import Path


def split_for(row_id: str, category: str, test_fraction: float) -> str:
    """"test" or "dev" for one row."""
    digest = hashlib.sha256(f"{category}|{row_id}".encode("utf-8")).hexdigest()
    return "test" if int(digest[:8], 16) / 16 ** 8 < test_fraction else "dev"


def read_rows(path: str | Path) -> tuple[list[str], list[dict]]:
    """(column names, rows) of an evaluation CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)


def add_split_column(path: str | Path, test_fraction: float) -> list[dict]:
    """
    Make sure the CSV has a `split` column that follows the rule, and return the rows with it.
    The file is rewritten only if the column is missing or wrong; every other value is kept as it was.
    """
    columns, rows = read_rows(path)
    wanted = [split_for(r["id"], r["category"], test_fraction) for r in rows]
    if "split" in columns and [r["split"] for r in rows] == wanted:
        return rows
    for row, split in zip(rows, wanted):
        row["split"] = split
    if "split" not in columns:
        columns.append("split")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return rows
