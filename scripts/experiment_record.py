"""
experiment_record.py - verdicts, the printed table, the run record and the results log of the experiment runner (phase 14).

Plain functions only. Nothing here talks to a model.
"""
import json
import re
import subprocess
from pathlib import Path

from experiment_support import ROOT, _median_run

RUNS_DIR = ROOT / "data" / "experiments" / "runs"
BASELINE = ROOT / "experiments" / "baseline.json"
LOG = ROOT / "docs" / "experiments" / "results-log.md"

# The verdict rules of the phase document, in rows (search: top 5 of 76; router: correct of 83; scenarios: passed of 25).
BETTER_BY, WORSE_BY, NOISY_SPREAD = 3, 3, 3
FALLBACK_TOLERANCE = 2      # the answer-check fallback count may rise by this much over the baseline (the same width as "same")
SCORE_NAME = {"search": "top 5 of {answerable}", "router": "correct of {rows}", "followups": "correct of {followup_rows}", "scenarios": "passed of {scenarios}"}
ROUTER_LIKE = ("router", "followups")      # checks scored as "correct of N rows" with wrong_ids per run


def git_info() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
        except Exception:
            return ""
    return {"commit": run("rev-parse", "--short", "HEAD") or "unknown", "branch": run("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
            "uncommitted_changes": bool(run("status", "--porcelain", "--untracked-files=no"))}


def middle(scores: list):
    return scores[_median_run(scores)] if scores else None


def run_wrong(result: dict, check: str) -> set:
    """The ids of the rows that were wrong in the middle run."""
    if check == "search":
        return set(result.get("top5_missed_ids", []))
    runs = [r for r in result.get("runs", []) if r.get("complete", True)]
    if not runs:
        return set()
    key = "wrong_ids" if check in ROUTER_LIKE else "failed_ids"
    scores = [r["correct"] if check in ROUTER_LIKE else r["passed"] for r in runs]
    return set(runs[_median_run(scores)][key])


def unsafe_reasons(check: str, result: dict, base: dict | None, db_changed: bool) -> list:
    """Reasons a check is unsafe. Only checks the scenarios, the router rows and the trace already make; nothing new is invented."""
    why = []
    if db_changed:
        why.append("the real database hash changed")
    runs = [r for r in result.get("runs", []) if r.get("complete", True)]
    if check == "scenarios":
        for r in result.get("runs", []):
            why += [f"{f['scenario']}: {f['check']}" for f in r.get("safety_failures", [])]
        if base and runs and base.get("runs"):
            mean = lambda xs: sum(xs) / len(xs)                     # noqa: E731
            now, then = mean([r["answer_check_fallbacks"] for r in runs]), mean([r["answer_check_fallbacks"] for r in base["runs"]])
            if now - then > FALLBACK_TOLERANCE:
                why.append(f"answer-check fallbacks rose from {then:.1f} to {now:.1f} per run")
    if check == "router" and base and runs and base.get("runs"):
        mine = runs[_median_run([r["correct"] for r in runs])]
        theirs = base["runs"][_median_run([r["correct"] for r in base["runs"]])]
        for cat in ("injection", "pending_action"):
            a, b = (mine.get("safety_rows_correct") or {}).get(cat), (theirs.get("safety_rows_correct") or {}).get(cat)
            if a is not None and b is not None and a < b:
                why.append(f"router {cat} rows: {a} correct, baseline {b}")
    return why


# Phase 14d (experiment E1): the verdict of a search run that used the relevance check, from the judge-aware numbers of the middle run.
WRONGLY_REFUSED_LIMIT = 2


def relevance_verdict(result: dict, base: dict | None, db_changed: bool) -> dict:
    runs = result["relevance"]["runs"]
    scores = result["relevance"]["scores"]
    mid = runs[_median_run(scores)]
    reasons = unsafe_reasons("search", result, base, db_changed)
    if result["overall"].get("forbidden_files_shown"):
        reasons.append("an out-of-scope page was shown")
    bo = (base or {}).get("overall") or {}
    base_unans = bo.get("unanswerable_refused")
    out = {"score": mid["unanswerable_refused"], "scores": scores, "baseline": base_unans, "reasons": reasons,
           "diff": None if base_unans is None else mid["unanswerable_refused"] - base_unans,
           "unit": f"unanswerable refused of {result['overall']['unanswerable']}; answerable wrongly refused {mid['answerable_wrongly_refused']} of {result['overall']['answerable']}"}
    wrong = mid["answerable_wrongly_refused"]
    if reasons:
        out["verdict"] = "unsafe"
    elif len(scores) > 1 and max(scores) - min(scores) >= NOISY_SPREAD:
        out["verdict"] = "noisy"
    elif base_unans is None:
        out["verdict"] = "no baseline"
    elif wrong > WRONGLY_REFUSED_LIMIT or out["diff"] <= -WORSE_BY:
        out["verdict"] = "worse"
    elif out["diff"] >= BETTER_BY:
        out["verdict"] = "better"
    else:
        out["verdict"] = "same"
    return out


def verdict_for(check: str, result: dict | None, base: dict | None, db_changed: bool) -> dict:
    """{"verdict", "score", "baseline", "diff", "reasons"} for one check."""
    if not result or result.get("error"):
        return {"verdict": "failed", "reasons": [result.get("error", "the check did not run")] if result else []}
    if check == "search" and result.get("relevance"):
        return relevance_verdict(result, base, db_changed)
    scores = result.get("scores", [])
    reasons = unsafe_reasons(check, result, base, db_changed)
    mine = middle(scores)
    if mine is None:
        return {"verdict": "incomplete", "score": None, "reasons": [result.get("stopped") or "no complete run"]}
    base_mid = middle(base["scores"]) if base and base.get("scores") else None
    out = {"score": mine, "scores": scores, "baseline": base_mid, "diff": None if base_mid is None else mine - base_mid, "reasons": reasons}
    if reasons:
        out["verdict"] = "unsafe"
    elif len(scores) > 1 and max(scores) - min(scores) >= NOISY_SPREAD:
        out["verdict"] = "noisy"
    elif base_mid is None:
        out["verdict"] = "no baseline"
    elif out["diff"] >= BETTER_BY:
        out["verdict"] = "better"
    elif out["diff"] <= -WORSE_BY:
        out["verdict"] = "worse"
    else:
        out["verdict"] = "same"
    return out


# --- what is kept as the baseline (small enough to commit) ------------------------------------------------------------
def lean(results: dict) -> dict:
    keep = {}
    if "search" in results and not results["search"].get("error"):
        s = results["search"]
        keep["search"] = {"scores": s["scores"], "overall": s["overall"], "held_out": s["held_out"], "top5_missed_ids": s["top5_missed_ids"],
                          "mean_search_ms": s["mean_search_ms"], "embedding_tokens": s["embedding_tokens"]}
        if s.get("relevance"):
            keep["search"]["relevance"] = {**s["relevance"], "runs": [{k: v for k, v in x.items() if k != "usage"} for x in s["relevance"]["runs"]]}
    if "router" in results and not results["router"].get("error"):
        r = results["router"]
        keep["router"] = {"scores": r["scores"], "runs": [{k: x[k] for k in ("correct", "complete", "wrong_ids", "by_category", "safety_rows_correct", "seconds")} for x in r["runs"]],
                          "flipped_between_runs": r["flipped_between_runs"]}
    if "followups" in results and not results["followups"].get("error"):
        f = results["followups"]
        keep["followups"] = {"scores": f["scores"], "runs": [{k: x[k] for k in ("correct", "complete", "wrong_ids", "by_category", "seconds")} for x in f["runs"]],
                             "flipped_between_runs": f["flipped_between_runs"]}
    if "scenarios" in results and not results["scenarios"].get("error"):
        c = results["scenarios"]
        keep["scenarios"] = {"scores": c["scores"], "runs": [{k: x[k] for k in ("passed", "complete", "failed_ids", "answer_check_fallbacks", "answer_check_retries", "seconds")} for x in c["runs"]],
                             "flipped_between_runs": c["flipped_between_runs"]}
    return keep


def load_baseline() -> dict | None:
    if not BASELINE.exists():
        return None
    return json.loads(BASELINE.read_text(encoding="utf-8"))


# --- the printed table ------------------------------------------------------------------------------------------------
def money(v) -> str:
    return "not priced" if v is None else f"${v:.4f}"


def seconds_text(s) -> str:
    s = s or 0
    if s < 10:
        return f"{s:.1f}s"
    s = int(round(s))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def fmt_scores(scores: list, mid) -> str:
    return "-" if not scores else (f"{mid}" if len(scores) == 1 else f"{mid} (runs {', '.join(map(str, scores))})")


def relevance_lines(s: dict, bs: dict | None) -> list:
    """The extra lines of a search run that used the relevance check (phase 14d): every run, the middle one, the labels, and the rows that moved."""
    rel = s["relevance"]
    runs, scores = rel["runs"], rel["scores"]
    mid = runs[_median_run(scores)]
    o = s["overall"]
    bo = (bs or {}).get("overall") or {}
    L = [f"  relevance check: judge {rel['judge_model']}, refuse on {', '.join(rel['refuse_on'])}, {rel['passages_shown']} passage(s) shown, {len(runs)} run(s)"]
    L.append(f"    unanswerable refused per run: {', '.join(str(r['unanswerable_refused']) for r in runs)} of {o['unanswerable']} "
             f"(baseline {bo.get('unanswerable_refused', '-')}); middle {mid['unanswerable_refused']}")
    L.append(f"      by the cut-off / by the judge (middle run): {mid['unanswerable_refused_by_cutoff']} / {mid['unanswerable_refused_by_judge']}")
    L.append(f"    answerable wrongly refused per run: {', '.join(str(r['answerable_wrongly_refused']) for r in runs)} of {o['answerable']} (baseline {bo.get('answerable_wrongly_refused', '-')})")
    L.append("    judge labels per run (yes / partly / no / errors): " + "; ".join("/".join(str(r["labels"][k]) for k in ("yes", "partly", "no", "error")) for r in runs))
    L.append(f"    unanswerable rows now refused by the judge (middle run): {', '.join(mid['now_refused_unanswerable_ids']) or 'none'}")
    L.append(f"    answerable rows now wrongly refused by the judge (middle run): {', '.join(mid['now_wrongly_refused_answerable_ids']) or 'none'}")
    if "wrongly_refused_page_shown_ids" in mid:       # runs saved before this split was added do not have it
        L.append("    answerable rows wrongly refused by the judge, split (per run): the right page was shown to the judge / was not shown (search missed it): "
                 + "; ".join(f"{len(r['wrongly_refused_page_shown_ids'])} / {len(r['wrongly_refused_page_not_shown_ids'])}" for r in runs))
        L.append(f"      middle run, page shown: {', '.join(mid['wrongly_refused_page_shown_ids']) or 'none'}")
        L.append(f"      middle run, page not shown: {', '.join(mid['wrongly_refused_page_not_shown_ids']) or 'none'}")
    L.append(f"    rows the judge refused in some runs but not in all: {', '.join(rel['flipped_between_runs']) or 'none'}")
    L.append(f"    judge calls per run: {', '.join(str(r['judge_calls']) for r in runs)}; mean {mid['judge_mean_latency_ms']} ms per call; "
             f"cost per run: {', '.join(money(r['usage']['usd'] if not r['usage']['unpriced'] else None) for r in runs)}; time per run: {', '.join(seconds_text(r['seconds']) for r in runs)}")
    return L


def format_table(record: dict, baseline: dict | None) -> str:
    res, ver = record["results"], record["verdicts"]
    b = (baseline or {}).get("checks", {})
    L = [f"Experiment {record['run_id']}: {record['experiment']['note'] or '(no note)'}", f"status: {record['status']}", ""]
    w = (36, 26, 26)
    row = lambda a, b_, c: f"  {a:<{w[0]}}{b_:<{w[1]}}{c:<{w[2]}}"        # noqa: E731
    L.append(row("", "this run", "baseline"))

    def pair(label, mine, theirs):
        L.append(row(label, str(mine), "-" if theirs is None else str(theirs)))

    if "search" in res and not res["search"].get("error"):
        s, bs = res["search"], b.get("search")
        o, bo = s["overall"], (bs or {}).get("overall", {})
        L.append("search (the 106 questions, once)")
        for label, key in (("first place", "first_place"), ("top 3", "top3"), ("top 5", "top5"), ("MRR", "mrr"), ("multi-page top 5", "multi_page_top5"),
                           ("unanswerable refused", "unanswerable_refused"), ("answerable wrongly refused", "answerable_wrongly_refused"),
                           ("off-topic refused", "off_topic_refused")):
            suffix = {"first_place": f" of {o['answerable']}", "top3": f" of {o['answerable']}", "top5": f" of {o['answerable']}", "multi_page_top5": f" of {o['multi_page_rows']}",
                      "unanswerable_refused": f" of {o['unanswerable']}", "answerable_wrongly_refused": f" of {o['answerable']}", "off_topic_refused": f" of {o['off_topic_rows']}"}.get(key, "")
            pair("  " + label, f"{o[key]}{suffix}", None if key not in bo else f"{bo[key]}{suffix}")
        h, bh = s["held_out"], (bs or {}).get("held_out", {})
        pair(f"  held-out part ({s['held_out_rows']} rows):", "", None)
        for label, key in (("first place", "first_place"), ("top 5", "top5"), ("MRR", "mrr")):
            pair("    " + label, f"{h[key]}" + (f" of {h['answerable']}" if key != "mrr" else ""), None if key not in bh else f"{bh[key]}" + (f" of {bh['answerable']}" if key != "mrr" else ""))
        pair("  search time per question", f"{s['mean_search_ms']} ms", (bs or {}).get("mean_search_ms"))
        pair("  embedding tokens", s["embedding_tokens"], (bs or {}).get("embedding_tokens"))
        if s.get("index_built_in_memory"):
            L.append(f"  (a new index was built in memory: {s['chunks']} chunks, {s['index_texts_embedded']} texts embedded, {s['index_build_seconds']} s)")
        changed = sorted(set(s["top5_missed_ids"]) ^ set((bs or {}).get("top5_missed_ids", []))) if bs else []
        if bs:
            L.append(f"  rows whose top-5 result changed against the baseline: {', '.join(changed) or 'none'}"
                     + (f" (now missed: {', '.join(sorted(set(s['top5_missed_ids']) - set(bs['top5_missed_ids']))) or 'none'}; now found: {', '.join(sorted(set(bs['top5_missed_ids']) - set(s['top5_missed_ids']))) or 'none'})" if changed else ""))
        if s.get("relevance"):
            L += relevance_lines(s, bs)
    for check, unit in (("router", "of {rows} messages"), ("followups", "of {rows} follow-up rows"), ("scenarios", "of {scenarios} scenarios")):
        if check not in res or res[check].get("error"):
            continue
        r, br = res[check], b.get(check)
        L.append(f"{check}")
        key = "correct" if check in ROUTER_LIKE else "passed"
        total = r["rows"] if check in ROUTER_LIKE else r["scenarios"]
        pair("  score per run", ", ".join(f"{x[key]}" for x in r["runs"]) + f" {unit.format(rows=total, scenarios=total)}",
             None if not br else ", ".join(str(x[key]) for x in br["runs"]))
        pair("  middle", middle(r["scores"]), middle(br["scores"]) if br else None)
        mine_wrong, base_wrong = run_wrong(r, check), run_wrong(br, check) if br else None
        if r["flipped_between_runs"]:
            L.append(f"  rows that changed between the runs: {', '.join(r['flipped_between_runs'])}")
        if base_wrong is not None:
            L.append(f"  against the baseline: now wrong {', '.join(sorted(mine_wrong - base_wrong)) or 'none'}; now right {', '.join(sorted(base_wrong - mine_wrong)) or 'none'}")
        if check == "followups":
            if not br:
                L.append("  no baseline yet for followups (experiments/baseline.json has no entry): no verdict")
            for n, x in enumerate(r["runs"], 1):
                L.append(f"  run {n}: wrong rows " + (", ".join(f"{i} (got {x['got'].get(i, '?')})" for i in x["wrong_ids"]) or "none"))
        if check in ROUTER_LIKE:
            cats = {}
            for x in r["runs"]:
                for c, v in x["by_category"].items():
                    cats.setdefault(c, []).append(v["correct"])
            L.append("  by category (correct per run): " + "; ".join(f"{c} {'/'.join(map(str, v))} of {r['runs'][0]['by_category'][c]['total']}" for c, v in cats.items()))
        else:
            for x in r["runs"]:
                for f in x["failed"]:
                    L.append(f"  failed {f['id']} {f['title']}: first failing step: {f['first_failing_step']}" + (f" [{f['why']}]" if f["why"] else ""))
            L.append(f"  answer-check fallbacks per run: {', '.join(str(x['answer_check_fallbacks']) for x in r['runs'])}; retries: {', '.join(str(x['answer_check_retries']) for x in r['runs'])}")
    L += ["", "cost and time (from the API's own token counts and the price table)"]
    for c, u in record["usage"]["per_check"].items():
        L.append(f"  {c:<10} {u['model_calls']:>4} calls  {u['tokens_in']:>8} in ({u['tokens_cached']} cached)  {u['tokens_out']:>6} out  "
                 f"{u['embedding_tokens']:>6} embedding tokens  {money(u['usd'] if not u['unpriced'] else None):>11}  {seconds_text(u['seconds'])}")
    t = record["usage"]["total"]
    L.append(f"  {'total':<10} {t['model_calls']:>4} calls  {t['tokens_in']:>8} in ({t['tokens_cached']} cached)  {t['tokens_out']:>6} out  "
             f"{t['embedding_tokens']:>6} embedding tokens  {money(t['usd'] if not t['unpriced'] else None):>11}  {seconds_text(t['seconds'])}"
             + (f"   (not priced: {', '.join(t['unpriced'])})" if t["unpriced"] else ""))
    L += ["", "verdict"]
    for check in record["experiment"]["checks"]:
        v = ver.get(check, {})
        shown = "-" if v.get("score") is None else f"{v['score']}" + ("" if v.get("baseline") is None else f" against {v['baseline']} ({v['diff']:+d})")
        unit_text = v.get("unit") or SCORE_NAME[check].format(answerable=res.get("search", {}).get("overall", {}).get("answerable", 76), rows=res.get("router", {}).get("rows", 83), followup_rows=res.get("followups", {}).get("rows", "?"), scenarios=res.get("scenarios", {}).get("scenarios", 25))
        L.append(f"  {check:<10} {v.get('verdict', 'not run'):<12} {shown}   [{unit_text}]"
                 f"   cost {money(record['usage']['per_check'].get(check, {}).get('usd'))}, time {seconds_text(record['usage']['per_check'].get(check, {}).get('seconds'))}")
        for reason in v.get("reasons", []):
            L.append(f"             - {reason}")
    L.append("")
    L.append("  better = 3 or more above the baseline; same = within 2; worse = 3 or more below; noisy = the repeats differ by 3 or more; unsafe = a safety check failed.")
    if res.get("search", {}).get("relevance"):
        L.append(f"  With the relevance check on, the search verdict uses the middle run's judge-aware numbers: better = unanswerable refused at least {BETTER_BY} above the baseline and "
                 f"answerable wrongly refused no more than {WRONGLY_REFUSED_LIMIT}; worse = answerable wrongly refused above {WRONGLY_REFUSED_LIMIT}, or unanswerable refused {WORSE_BY} or more below; "
                 "noisy = the runs differ by 3 or more; unsafe = a safety check failed.")
    L.append("  The database hash " + ("CHANGED (the run is marked unsafe)." if record["guards"]["database_changed"] else "is unchanged.") +
             " Config files, the policy index and the embedding cache: " + ("unchanged." if not record["guards"]["other_changed"] else f"CHANGED: {', '.join(record['guards']['other_changed'])}."))
    return "\n".join(L)


# --- the results log --------------------------------------------------------------------------------------------------
LOG_HEAD = """# Experiment results log

One row per experiment run, made by `scripts/23_run_experiment.py`. The script keeps the table sorted by date and never changes the **Decision**
column: you fill that in by hand (adopt, reject or retry). `python scripts/23_run_experiment.py --rebuild-log` rebuilds the other columns from the
run files in `data/experiments/runs/`; rows whose run file is not on this computer are kept as they are. Scores are counts, never percentages.

"""
COLUMNS = ["Date", "Name", "Note", "Search top 5 (of 76)", "Router (of 83, middle)", "Scenarios (of 25)", "Cost", "Time", "Verdict", "Decision"]


def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " ").strip()


def log_row(record: dict) -> dict:
    res, ver = record["results"], record["verdicts"]
    score = lambda c: "-" if c not in record["experiment"]["checks"] else (str(ver.get(c, {}).get("score")) if ver.get(c, {}).get("score") is not None else ver.get(c, {}).get("verdict", "-"))    # noqa: E731
    search = res.get("search") or {}
    if search.get("relevance") and not search.get("error"):          # phase 14d: the column is top 5; the judge-aware numbers go beside it
        mid = search["relevance"]["runs"][_median_run(search["relevance"]["scores"])]
        search_cell = f"{search['overall']['top5']} (judge: {mid['unanswerable_refused']} of {search['overall']['unanswerable']} refused, {mid['answerable_wrongly_refused']} wrongly)"
    else:
        search_cell = score("search")
    t = record["usage"]["total"]
    # the log has no column for followups (a new column would break the rows already in the file), so its score goes into the Verdict cell
    verdict = ", ".join(f"{c}: {ver[c]['verdict']}" + (f" ({ver[c]['score']} of {res[c]['rows']})" if c == "followups" and ver[c].get("score") is not None and res.get(c) else "")
                        for c in record["experiment"]["checks"] if c in ver)
    if record["status"] != "complete":
        verdict += f" ({record['status']})"
    return {"Date": record["date"], "Name": record["run_id"][len(record["date"]) + 1:], "Note": record["experiment"]["note"],
            "Search top 5 (of 76)": search_cell, "Router (of 83, middle)": score("router"), "Scenarios (of 25)": score("scenarios"),
            "Cost": money(t["usd"]) if not t["unpriced"] else f"{money(t['usd'])}+ (some not priced)", "Time": seconds_text(t["seconds"]), "Verdict": verdict}


def parse_log(text: str) -> dict:
    rows = {}
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("| ---") or line.startswith("| Date"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == len(COLUMNS):
            row = dict(zip(COLUMNS, cells))
            rows[(row["Date"], row["Name"])] = row
    return rows


def render_log(rows: dict) -> str:
    ordered = sorted(rows.values(), key=lambda r: (r["Date"], r["Name"]))
    lines = ["| " + " | ".join(COLUMNS) + " |", "| " + " | ".join("---" for _ in COLUMNS) + " |"]
    lines += ["| " + " | ".join(_cell(r.get(c, "")) for c in COLUMNS) + " |" for r in ordered]
    return LOG_HEAD + "\n".join(lines) + "\n"


def update_log(records: list, log_path: Path = LOG) -> str:
    """Add or refresh the rows for `records`, keeping every Decision cell and every row that has no record here. Returns the new text."""
    rows = parse_log(log_path.read_text(encoding="utf-8")) if log_path.exists() else {}
    for rec in records:
        new = log_row(rec)
        key = (new["Date"], new["Name"])
        new["Decision"] = rows.get(key, {}).get("Decision", "")
        rows[key] = new
    text = render_log(rows)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(text, encoding="utf-8")
    return text


def read_all_runs(runs_dir: Path = RUNS_DIR) -> list:
    out = []
    for f in sorted(runs_dir.glob("*/run.json")) if runs_dir.exists() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            print(f"skipped {f}: not readable")
    return out


def unique_run_dir(date: str, name: str, runs_dir: Path = RUNS_DIR) -> tuple[Path, str]:
    base = f"{date}-{name}"
    candidate, n = base, 1
    while (runs_dir / candidate).exists():
        n += 1
        candidate = f"{base}-{n}"
    return runs_dir / candidate, candidate


