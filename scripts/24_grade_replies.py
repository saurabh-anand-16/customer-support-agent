"""
24_grade_replies.py - grade the replies of a finished run with a model that did not write them (phase 17, offline).

    python scripts/24_grade_replies.py --run 2026-11-20-e9-adversarial --dry-run     # count, cut evidence, estimate; sends nothing
    python scripts/24_grade_replies.py --run 2026-11-20-e9-adversarial --limit 10    # grade the first 10 replies (real model)
    python scripts/24_grade_replies.py --run 2026-11-20-e9-adversarial               # grade all
    python scripts/24_grade_replies.py --run 2026-11-20-e9-adversarial --review-sheet          # 20 replies for you to mark (no model call)
    python scripts/24_grade_replies.py --read-review data/evals/results/reply_review_<run>.csv  # agreement between your marks and the grader

It reads <run folder>/traces.jsonl and config/grader.toml. It is not part of the agent: the agent code is not imported except for the chat-model
wrapper (agent.llm) that every script uses. The key is read from .env by that wrapper and never printed. Output files go to data/evals/results/
and are never overwritten (a number is added to the name).
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import grader_support as gs                      # noqa: E402
from agent.llm import ModelSettings, OpenAIChat  # noqa: E402


def plan(turns: list, cfg: dict, agent_raw: dict, limit: int | None) -> list:
    """[(index, template)] for the turns that have a reply to the customer, first `limit` of them."""
    patterns, prefixes = gs.fixed_texts(cfg, agent_raw)
    rows = [(i, gs.is_template(t, cfg, patterns, prefixes)) for i, t in enumerate(turns) if gs.has_reply(t)]
    return rows[:limit] if limit else rows


def estimate(turns: list, rows: list, cfg: dict, price: dict | None) -> dict:
    """Token and cost estimate for the planned calls, without caching (so it is on the high side)."""
    system_tokens = gs.estimate_tokens(cfg["prompt"]["system"], cfg)
    tokens_in = sum(system_tokens + gs.estimate_tokens(gs.build_message(turns, i, cfg, tpl, gs.cut_evidence(turns[i])), cfg) for i, tpl in rows)
    tokens_out = len(rows) * cfg["estimate"]["output_tokens_per_reply"]
    return {"replies": len(rows), "templates": sum(tpl for _, tpl in rows), "cut": sum(gs.cut_evidence(turns[i]) for i, _ in rows),
            "tokens_in": tokens_in, "tokens_out": tokens_out, "usd": gs.cost_usd(price, tokens_in, tokens_out)}


def print_estimate(est: dict, cfg: dict, run_name: str, say) -> None:
    say(f"Run: {run_name}")
    say(f"Replies to grade: {est['replies']} ({est['templates']} fixed-template replies)")
    say(f"Replies with cut evidence (grounded will be {gs.NOT_ENOUGH}): {est['cut']} of {est['replies']}")
    say(f"Grader model: {cfg['model']['name']}")
    say(f"Estimated tokens: {est['tokens_in']:,} in, {est['tokens_out']:,} out (rough: {cfg['estimate']['chars_per_token']} characters a token, no caching)")
    say("Estimated cost: " + (f"${est['usd']:.4f}" if est["usd"] is not None else "not priced (no [pricing] table for this model in config/agent.toml)")
        + f"; cap ${cfg['limits']['cost_cap_usd']:.2f}")


def run_grading(args, cfg: dict, agent_raw: dict, chat, say) -> int:
    run_dir = gs.resolve_run(args.run, Path(args.runs_dir))
    out_dir = Path(args.out_dir)
    turns = gs.read_turns(run_dir)
    rows = plan(turns, cfg, agent_raw, args.limit)
    price = gs.price_of(cfg["model"]["name"], agent_raw)
    est = estimate(turns, rows, cfg, price)
    print_estimate(est, cfg, run_dir.name, say)
    cap = cfg["limits"]["cost_cap_usd"]
    if args.dry_run:
        say("Dry run: nothing was sent.")
        return 0
    if not rows:
        say("No replies to grade.")
        return 1
    if est["usd"] is None:
        say("Stopped: the model has no price, so the cost cap cannot be checked. Add [pricing.\"<model>\"] to config/agent.toml, or use another model.")
        return 2
    if est["usd"] > cap:
        say(f"Stopped: the estimate (${est['usd']:.4f}) is above the cap (${cap:.2f}). Nothing was sent. Use --limit, or raise the cap in config/grader.toml.")
        return 2
    m = cfg["model"]
    settings = ModelSettings(name=m["name"], temperature=None, max_output_tokens=m["max_output_tokens"], timeout_seconds=m["timeout_seconds"],
                             api_key_env=m["api_key_env"], env_file=m["env_file"], token_parameter=m["token_parameter"])
    system, grades, spent = cfg["prompt"]["system"], [], 0.0
    for n, (index, template) in enumerate(rows, 1):
        grades.append(gs.grade_one(chat, settings, system, turns, index, cfg, template, price))
        spent += grades[-1].cost_usd or 0
        if n % 10 == 0 or n == len(rows):
            say(f"  graded {n} of {len(rows)} (${spent:.4f} so far)")
        if spent > cap:
            say(f"Stopped: the real cost (${spent:.4f}) went above the cap (${cap:.2f}) after {n} replies. What was graded is saved.")
            break
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = gs.free_path(out_dir / f"reply_grades_{run_dir.name}.csv")
    md_path = gs.free_path(out_dir / f"reply_grades_{run_dir.name}.md")
    gs.write_grades_csv(csv_path, grades)
    md_path.write_text(gs.summary_markdown(run_dir.name, grades, cfg, m["name"]), encoding="utf-8", newline="\n")
    say(f"Wrote {csv_path} and {md_path}")
    return 0


def run_review_sheet(args, cfg: dict, say) -> int:
    run_dir = gs.resolve_run(args.run, Path(args.runs_dir))
    out_dir = Path(args.out_dir)
    source = gs.latest_grades_file(run_dir.name, out_dir)
    if source is None:
        say(f"No reply_grades_{run_dir.name}*.csv in {out_dir}: grade the run first.")
        return 1
    path = gs.free_path(out_dir / f"reply_review_{run_dir.name}.csv")
    count = gs.write_review_sheet(path, gs.read_grades_csv(source), cfg)
    say(f"Wrote {path} with {count} replies from {source.name}. Fill the my_* columns (answers: yes/partly/no; the others yes/no; overall 1 to 5),")
    say(f"then run: python scripts/24_grade_replies.py --read-review {path}")
    return 0


def run_read_review(args, say) -> int:
    result = gs.agreement(Path(args.read_review))
    say("Agreement between your marks and the grader (only the cells you filled in):")
    for criterion, (agreed, compared) in result.items():
        label = "overall within 1 point" if criterion == "overall_within_1" else criterion
        say(f"  {label}: {agreed} of {compared}" + (f" ({100 * agreed / compared:.0f}%)" if compared else " (no marks)"))
    return 0


def main(argv=None, chat=None, say=print) -> int:
    ap = argparse.ArgumentParser(description="Grade the replies of a finished run (offline).")
    ap.add_argument("--run", help="a run folder under data/experiments/runs (a name) or a path")
    ap.add_argument("--limit", type=int, help="grade only the first N replies")
    ap.add_argument("--dry-run", action="store_true", help="print the count and an estimate; send nothing")
    ap.add_argument("--review-sheet", action="store_true", help="write a CSV of 20 replies for you to mark (from the grades file of the run)")
    ap.add_argument("--read-review", help="read a filled review sheet and print the agreement")
    ap.add_argument("--config", default=str(gs.GRADER_CONFIG))
    ap.add_argument("--runs-dir", default=str(gs.RUNS_DIR))
    ap.add_argument("--out-dir", default=str(gs.RESULTS_DIR))
    args = ap.parse_args(argv)
    cfg = gs.load_config(Path(args.config))
    if args.read_review:
        return run_read_review(args, say)
    if not args.run:
        ap.error("--run is needed (or --read-review)")
    if args.review_sheet:
        return run_review_sheet(args, cfg, say)
    return run_grading(args, cfg, gs.read_agent_toml(), chat or OpenAIChat(), say)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
