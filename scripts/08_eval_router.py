"""
08_eval_router.py - run the router on the labelled messages and score it.

    python scripts/08_eval_router.py                  # the dev rows (the default; tune the prompt on these)
    python scripts/08_eval_router.py --split all      # every row: a first look, not a result
    python scripts/08_eval_router.py --final          # the test rows, once at the end

It uses the real model named in config/agent.toml (needs OPENAI_API_KEY in .env), one call per message
(none for the rows that wait for a confirmation: a pending action bypasses the router, as in the agent).
It reports accuracy overall, by category and by expected route (each as "correct of total"), a table of which
routes get confused, and every miss with the model's reason. The `split` column is added to the CSV by the rule
in scripts/eval_split.py. The --final result is written once and not overwritten without --force.

The "context" column describes an earlier turn or a pending action. It is turned into a one-line note in the
conversation the router sees, so a row with context is a rough test, not a replay of a real conversation.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_split import add_split_column                            # noqa: E402
from agent.llm import LlmError, OpenAIChat, load_agent_config       # noqa: E402
from agent.rag.embedders.base import read_secret                    # noqa: E402
from agent.router import Router                                     # noqa: E402
from agent.session import Session                                   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "evals" / "router_messages.csv"
RESULTS_DIR = ROOT / "data" / "evals" / "results"


def session_for(row: dict, keep: int) -> Session:
    """A fresh session set up from the row's context column."""
    session = Session("EVAL", "EVAL")
    context = (row.get("context") or "none").strip()
    if context.startswith("pending_action"):
        session.pending_action = {"description": context}
    elif context.startswith("previous turn"):
        note = context.split(":", 1)[1].strip()
        session.add_exchange(f"(earlier in this conversation: {note})", "(the assistant's reply is not shown)", "", keep)
    return session


def evaluate(rows: list[dict], router: Router) -> list[dict]:
    """Route every row. Returns one record per row."""
    records = []
    for row in rows:
        decision = router.decide(session_for(row, router.cfg.session.history_keep), row["message"])
        records.append({"id": row["id"], "message": row["message"], "context": row.get("context", "none"),
                        "category": row["category"], "split": row.get("split", ""), "reviewed": row.get("reviewed", ""),
                        "expected": row["expected_route"], "got": decision.route, "kind": decision.kind,
                        "reason": decision.reason, "error": decision.error, "called": decision.called,
                        "latency_ms": round(decision.latency_ms, 1)})
    return records


def _share(records, key) -> dict:
    groups = defaultdict(lambda: [0, 0])
    for r in records:
        groups[r[key]][1] += 1
        groups[r[key]][0] += r["expected"] == r["got"]
    return {name: {"correct": c, "total": t} for name, (c, t) in sorted(groups.items())}


def summarize(records: list[dict]) -> dict:
    correct = sum(r["expected"] == r["got"] for r in records)
    confusion = Counter((r["expected"], r["got"]) for r in records if r["expected"] != r["got"])
    called = [r["latency_ms"] for r in records if r["called"]]
    return {
        "rows": len(records), "correct": correct,
        "by_category": _share(records, "category"), "by_expected_route": _share(records, "expected"),
        "confusion": [{"expected": e, "got": g, "count": n} for (e, g), n in confusion.most_common()],
        "misses": [r for r in records if r["expected"] != r["got"]],
        "invalid_router_outputs": sum(1 for r in records if r["error"]),
        "model_calls": sum(1 for r in records if r["called"]),
        "mean_latency_ms": round(sum(called) / len(called), 1) if called else 0.0,
    }


def format_report(summary: dict, label: str) -> str:
    pct = lambda c, t: f"{c} of {t}" + (f" ({100 * c / t:.0f}%)" if t else "")        # noqa: E731
    lines = [f"Router evaluation: {label}", f"overall: {pct(summary['correct'], summary['rows'])}", "", "by category:"]
    lines += [f"  {name:<14} {pct(v['correct'], v['total'])}" for name, v in summary["by_category"].items()]
    lines += ["", "by expected route:"]
    lines += [f"  {name:<18} {pct(v['correct'], v['total'])}" for name, v in summary["by_expected_route"].items()]
    lines += ["", "what was confused (expected -> got):"]
    lines += [f"  {c['expected']} -> {c['got']}: {c['count']}" for c in summary["confusion"]] or ["  nothing"]
    lines += ["", f"misses ({len(summary['misses'])}):"]
    for m in summary["misses"]:
        extra = f" kind={m['kind']}" if m["kind"] else ""
        lines.append(f"  {m['id']} [{m['category']}] expected {m['expected']}, got {m['got']}{extra}")
        lines.append(f"      message: {m['message']}")
        if m["context"] != "none":
            lines.append(f"      context: {m['context']}")
        lines.append(f"      router said: {m['reason']}" + (f"  (ERROR: {m['error']})" if m["error"] else ""))
    lines += ["", f"invalid router outputs: {summary['invalid_router_outputs']}; model calls: {summary['model_calls']}; "
                  f"mean latency {summary['mean_latency_ms']} ms"]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--config", default=None, help="config file (default: config/agent.toml)")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--final", action="store_true", help="score the test rows once and write the result file")
    parser.add_argument("--force", action="store_true", help="allow --final to overwrite an earlier final result")
    parser.add_argument("--output", default=None, help="where to write the results (JSON)")
    args = parser.parse_args()

    cfg = load_agent_config(args.config)
    split = "test" if args.final else args.split
    output = Path(args.output) if args.output else RESULTS_DIR / (f"router_{split}_final.json" if args.final else f"router_{split}.json")
    if args.final and output.exists() and not args.force:
        print(f"error: {output} already exists. The test rows are scored once; use --force only if you must.", file=sys.stderr)
        return 2

    if not read_secret(cfg.model.api_key_env, cfg.root / cfg.model.env_file):      # fail early; the key itself is never shown
        print(f"error: no API key: set {cfg.model.api_key_env} in the environment or in {cfg.model.env_file}", file=sys.stderr)
        return 2

    rows = add_split_column(args.csv, cfg.eval.test_fraction)
    chosen = [r for r in rows if split == "all" or r["split"] == split]
    unreviewed = sum(1 for r in chosen if r.get("reviewed", "").lower() != "yes")
    print(f"{len(chosen)} rows ({split}); {unreviewed} of them are not marked reviewed: treat the numbers as a first look.\n")

    router = Router(cfg, OpenAIChat(cfg.root))
    try:
        records = evaluate(chosen, router)
    except LlmError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    summary = summarize(records)
    print(format_report(summary, f"{split} rows, model {cfg.model.name}, temperature {cfg.model.temperature}"))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"split": split, "model": cfg.model.name, "temperature": cfg.model.temperature,
                                  "summary": {k: v for k, v in summary.items() if k != "misses"},
                                  "records": records}, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
