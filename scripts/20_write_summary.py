"""
20_write_summary.py - write data/evals/summary.json from the result files of the evaluation scripts (phase 10).

    python scripts/20_write_summary.py

It only READS files in data/evals/results/ (written by 07_eval_retrieval.py, 08_eval_router.py, 19_run_scenarios.py and 09_mutation_check.py)
and writes one small file that is committed. The Developer page (phase 11) and the README read that file. It holds counts, ids and settings, no
message text (only question and scenario ids), and no keys. A part whose result file is missing is written as null.

The retrieval scores are worked out again here from the saved search results at the thresholds now in config/rag.toml, so the summary always
matches the config. No model or embedding call is made.
"""
import csv
import importlib.util
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.rag import load_config                      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "evals" / "results"
OUT = ROOT / "data" / "evals" / "summary.json"
PROFILES = ["baseline_bm25", "vector_only", "hybrid", "hybrid_llm_rerank"]       # hybrid_cross_encoder could not run: see the notes


def _load_script(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def counts_in(csv_path: Path) -> dict:
    with open(csv_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    reviewed = sum(1 for r in rows if r.get("reviewed", "").strip().lower() == "yes")
    return {"reviewed": reviewed, "not_reviewed": len(rows) - reviewed}


def retrieval_part() -> dict | None:
    ev = _load_script("eval_retrieval", "07_eval_retrieval.py")
    profiles, chosen = {}, load_config().profile
    for name in PROFILES:
        records = read_json(RESULTS / f"retrieval_records_{name}.json")
        if records is None:
            continue
        cfg = load_config(name)
        scored = ev.score(records, cfg, cfg.metadata.heading_path_separator)
        t = scored["total"]
        answerable = int(t["answerable"])
        profiles[name] = {
            "answerable_rows": answerable, "hit_at_1": int(t["hit1"]), "hit_at_3": int(t["hit3"]), "hit_at_5": int(t["hit5"]),
            "mrr": round(t["rr"] / max(1, answerable), 3), "no_match_ok": int(t["nomatch_ok"]), "rows": int(t["rows"]),
            "forbidden_file_shown": len(scored["forbidden_hits"]),
            "by_category": {c: {k: int(v[k]) for k in ("rows", "answerable", "hit1", "hit3", "hit5", "nomatch_ok")} for c, v in scored["by_category"].items()}}
    cfg = load_config()
    return {"chosen_profile": chosen, "thresholds": {"vector_min_score": cfg.no_match.vector_min_score, "bm25_min_score": cfg.no_match.bm25_min_score,
                                                      "hybrid_require": cfg.no_match.hybrid_require},
            "embedding_model": cfg.embedding.model, "chunk_max_chars": cfg.chunking.max_chars, "profiles": profiles,
            "skipped": {"hybrid_cross_encoder": "sentence-transformers is not installed in the project environment"}}


def router_part() -> dict | None:
    before, after = read_json(RESULTS / "router_baseline.json"), read_json(RESULTS / "router_after.json")
    if before is None or after is None:
        return None

    def side(d):
        s = d["summary"]
        return {"correct": s["correct"], "rows": s["rows"], "by_category": s["by_category"],
                "wrong_ids": sorted(r["id"] for r in d["records"] if r["expected"] != r["got"])}
    a, b = {r["id"]: r for r in before["records"]}, {r["id"]: r for r in after["records"]}
    ok = lambda r: r["expected"] == r["got"]                                    # noqa: E731
    return {"before": side(before), "after": side(after), "model": after["model"],
            "got_better": sorted(i for i in a if i in b and not ok(a[i]) and ok(b[i])), "got_worse": sorted(i for i in a if i in b and ok(a[i]) and not ok(b[i]))}


def scenarios_part() -> dict | None:
    d = read_json(RESULTS / "scenarios.json")
    if d is None:
        return None
    return {"scenarios": d["total"]["scenarios"], "passed": d["total"]["passed"], "failed_ids": [s["id"] for s in d["scenarios"] if not s["passed"]],
            "model_calls": d["total"]["model_calls"], "input_tokens": d["total"]["input_tokens"], "output_tokens": d["total"]["output_tokens"],
            "real_database_unchanged": d["real_database_unchanged"]}


def mutation_part() -> dict | None:
    path = RESULTS / "mutation_full.txt"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    done = re.search(r"^(\d+) of (\d+) mutations killed(?:; survivors: (.*))?$", text, flags=re.M)
    if not done:
        return {"finished": False}
    survivors = [s.strip() for s in (done.group(3) or "").split(",") if s.strip()]
    seconds = None
    marker = RESULTS / "mutation_full_seconds.txt"
    if marker.is_file():
        seconds = int(marker.read_text().strip())
    return {"finished": True, "mutations": int(done.group(2)), "killed": int(done.group(1)), "survived": survivors, "seconds": seconds}


def main() -> int:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or None
    summary = {
        "date": date.today().isoformat(), "git_commit": commit,
        "note": "Counts, ids and settings only: no message text, no keys. Cost is not priced (the price table is empty).",
        "reviewed_rows": {"retrieval_questions": counts_in(ROOT / "data" / "evals" / "retrieval_questions.csv"),
                          "router_messages": counts_in(ROOT / "data" / "evals" / "router_messages.csv")},
        "retrieval": retrieval_part(), "router": router_part(), "scenarios": scenarios_part(), "mutations": mutation_part(),
    }
    OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
