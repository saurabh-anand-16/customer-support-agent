"""
23_run_experiment.py - try one idea and compare it with the baseline (phase 14).

    python scripts/23_run_experiment.py experiments/configs/<name>.toml             # run it (costs money if it calls a model)
    python scripts/23_run_experiment.py experiments/configs/<name>.toml --dry-run   # check the file and print the cost estimate; sends nothing
    python scripts/23_run_experiment.py experiments/configs/baseline.toml --baseline   # run, then ask whether to save it as the baseline
    python scripts/23_run_experiment.py --rebuild-log                                # rebuild docs/experiments/results-log.md from the run files

The experiment file names only what differs from config/agent.toml and config/rag.toml. The script never edits those files: it writes a merged copy
into the run folder (data/experiments/runs/<date>-<name>/) and uses the copy. The real database, the real policy index and the real embedding cache
are only read. How to write a file and read the table: docs/experiments/how-to-run.md.
"""
import argparse
import json
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import experiment_record as rec                                                 # noqa: E402
import experiment_support as sup                                                # noqa: E402
from agent.rag.embedders.base import read_secret                                # noqa: E402


def say_override(exp: dict) -> str:
    lines = []
    for which in ("agent", "rag"):
        for path, value in sup._leaves(exp["override"].get(which, {})):
            shown = json.dumps(value)
            lines.append(f"  {which}.{'.'.join(path)} = {shown if len(shown) < 90 else shown[:87] + '...'}")
    return "\n".join(lines) or "  (nothing: this run uses the defaults)"


def guards(plan: sup.Plan) -> dict:
    """Hashes of everything a run must not change. The index folder is only counted (opening a Chroma index may touch its files)."""
    root, real = sup.ROOT, plan.real_rag_cfg
    chroma = root / real.store.path
    files = [p for p in chroma.rglob("*") if p.is_file()] if chroma.exists() else []
    return {"database": sup.sha_file(sup.REAL_DB), "config/agent.toml": sup.sha_file(sup.AGENT_TOML), "config/rag.toml": sup.sha_file(sup.RAG_TOML),
            "index_meta": sup.sha_file(root / real.store.meta_path), "embedding_cache": sup.sha_file(root / real.embedding.cache_path) if real.embedding.cache_path else None,
            "index_files": [len(files), sum(p.stat().st_size for p in files)]}


def ask_yes(question: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        print(f"{question} (no terminal to answer on, so the answer is no)")
        return False
    return input(f"{question} Type yes to confirm: ").strip().lower() == "yes"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiment", nargs="?", help="the experiment file, e.g. experiments/configs/chunk-900.toml")
    parser.add_argument("--dry-run", action="store_true", help="check the file, print the estimate and stop")
    parser.add_argument("--baseline", action="store_true", help="after the run, ask whether to save it as experiments/baseline.json")
    parser.add_argument("--rebuild-log", action="store_true", help="rebuild docs/experiments/results-log.md from the run files and stop")
    args = parser.parse_args(argv)

    if args.rebuild_log:
        runs = rec.read_all_runs()
        rec.update_log(runs)
        print(f"rebuilt {rec.LOG.relative_to(sup.ROOT)} from {len(runs)} run file(s); Decision cells kept")
        return 0
    if not args.experiment:
        parser.error("give an experiment file, or --rebuild-log")

    try:
        exp = sup.load_experiment(args.experiment)
        with tempfile.TemporaryDirectory(prefix="exp_check_", ignore_cleanup_errors=True) as check_dir:
            plan = sup.build_plan(exp, Path(check_dir))
            est = sup.estimate(plan)
            print(f"Experiment: {exp['name']}\nNote: {exp['note'] or '(none)'}\nChecks: {', '.join(exp['checks'])}"
                  f"{'' if 'search' in exp['checks'] and len(exp['checks']) == 1 else f', repeated {exp['repeat']} times (model checks)'}")
            print(f"Changes from the defaults:\n{say_override(exp)}")
            print(f"Search settings: profile {plan.rag_cfg.profile}, index {'CHANGED (a new index is built in memory)' if plan.index_changed else 'same as the real index'}\n")
            print(sup.format_estimate(est))
    except sup.ExperimentError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    except Exception as err:          # a config the real loaders refuse: show their message
        print(f"error: {type(err).__name__}: {err}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("\nDry run: nothing was sent and nothing was written.")
        return 0
    if est["unpriced_chat"] or est["total_usd"] > est["limit_usd"]:
        print("\nNot started. Fix the point above (or raise cost_limit_usd in the experiment file) and run again.", file=sys.stderr)
        return 3
    needs_key = any(c in exp["checks"] for c in ("router", "scenarios")) or plan.rag_cfg.retrieval.strategy in ("vector", "hybrid") or plan.rag_cfg.rerank.method == "llm"
    if needs_key and not read_secret(plan.agent_cfg.model.api_key_env, sup.ROOT / plan.agent_cfg.model.env_file):
        print(f"error: no API key: set {plan.agent_cfg.model.api_key_env} in the environment or in {plan.agent_cfg.model.env_file}", file=sys.stderr)
        return 2

    today = date.today().isoformat()
    run_dir, run_id = rec.unique_run_dir(today, exp["name"])
    run_dir.mkdir(parents=True)
    plan = sup.build_plan(exp, run_dir)
    before = guards(plan)
    baseline = rec.load_baseline()
    print(f"\nRun folder: {run_dir.relative_to(sup.ROOT)}\n")

    results, shared, status, started_all = {}, {}, "complete", time.perf_counter()
    per_check_usage = {}
    with sup.Meter(plan.agent_cfg.pricing, exp["cost_limit_usd"]) as meter, tempfile.TemporaryDirectory(prefix="exp_run_", ignore_cleanup_errors=True) as tmp:
        for check in exp["checks"]:
            print(f"--- {check} ---", flush=True)
            snap, t0 = meter.snapshot(), time.perf_counter()
            try:
                if check == "search":
                    results[check] = sup.run_search(plan, meter, shared)
                elif check == "router":
                    results[check] = sup.run_router(plan, meter, sup.REAL_DB, Path(tmp))
                else:
                    results[check] = sup.run_scenarios(plan, meter, sup.REAL_DB, Path(tmp), shared)
            except sup.CostLimitReached as err:
                results[check] = {"error": f"stopped: cost limit ({err})", "scores": []}
            except Exception as err:         # the message of a failed check never holds a key: the clients scrub theirs
                results[check] = {"error": f"{type(err).__name__}: {str(err)[:300]}", "scores": []}
            used = meter.since(snap)
            used["seconds"] = round(time.perf_counter() - t0, 1)
            per_check_usage[check] = used
            r = results[check]
            if r.get("error"):
                status = "stopped: cost limit" if str(r["error"]).startswith("stopped: cost limit") else f"failed: {r['error'][:120]}"
                print(f"  {check}: {r['error']}")
            elif r.get("stopped"):
                status = "stopped: cost limit"
                print(f"  {check}: stopped, {r['stopped']}")
            else:
                print(f"  {check}: done in {used['seconds']} s, spent ${used['usd']:.4f}", flush=True)
            if status != "complete" and status.startswith("stopped"):
                break
        total_usage = meter.since({"chat": {}, "embed": {}})
        total_usage["seconds"] = round(time.perf_counter() - started_all, 1)

    after = guards(plan)
    db_changed = before["database"] != after["database"]
    other_changed = [k for k in before if k != "database" and before[k] != after[k]]
    base_checks = (baseline or {}).get("checks", {})
    verdicts = {c: rec.verdict_for(c, results.get(c), base_checks.get(c), db_changed) for c in exp["checks"] if c in results}
    record = {"schema": 1, "run_id": run_id, "date": today, "status": status, "git": rec.git_info(),
              "experiment": {k: exp[k] for k in ("name", "note", "checks", "repeat", "cost_limit_usd", "override")},
              "estimate": {k: est[k] for k in ("total_usd", "limit_usd", "lines")}, "results": results, "verdicts": verdicts,
              "usage": {"per_check": per_check_usage, "total": total_usage},
              "guards": {"before": before, "after": after, "database_changed": db_changed, "other_changed": other_changed},
              "compared_with_baseline": bool(baseline), "baseline_run": (baseline or {}).get("run_id")}
    (run_dir / "run.json").write_text(json.dumps(record, indent=1, default=str) + "\n", encoding="utf-8")

    print("\n" + rec.format_table(record, baseline))
    runs = rec.read_all_runs()
    rec.update_log(runs if any(r["run_id"] == run_id for r in runs) else [*runs, record])
    print(f"\nrecord: {(run_dir / 'run.json').relative_to(sup.ROOT)}\nlog line added to {rec.LOG.relative_to(sup.ROOT)} (fill in the Decision column by hand)")

    if args.baseline:
        if status != "complete" or any(v["verdict"] in ("failed", "incomplete") for v in verdicts.values()):
            print("The run did not finish cleanly, so it is not offered as the baseline.")
        else:
            note = "This replaces the saved baseline." if baseline else "There is no saved baseline yet."
            if ask_yes(f"Save this run as the baseline (experiments/baseline.json)? {note}"):
                rec.BASELINE.parent.mkdir(parents=True, exist_ok=True)
                rec.BASELINE.write_text(json.dumps({"run_id": run_id, "date": today, "git": record["git"], "note": exp["note"], "checks": rec.lean(results),
                                                    "usd": total_usage["usd"], "seconds": total_usage["seconds"]}, indent=1) + "\n", encoding="utf-8")
                print("baseline saved")
            else:
                print("baseline not saved")
    return 1 if db_changed or any(v["verdict"] == "unsafe" for v in verdicts.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
