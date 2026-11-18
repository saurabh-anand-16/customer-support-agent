"""
show_traces.py - print the last turns of the local trace file in a readable form (phase 6).

    python scripts/show_traces.py                       # the last 5 turns of data/traces/traces.jsonl, newest first
    python scripts/show_traces.py --limit 20 --failed   # only turns with a failed check
    python scripts/show_traces.py --session S --customer C --route branch_return_or_replace --path other.jsonl
    python scripts/show_traces.py --turn TURN_ID        # one turn

It only reads the file. A broken line is skipped and the count is printed at the end.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import ROOT, load_agent_config            # noqa: E402
from agent.tracing import get_turn, list_turns, resolve_path   # noqa: E402


def totals_line(turn: dict) -> str:
    """One line of totals per turn. A line written before phase 6c has none of these fields and prints as 'no usage recorded'."""
    if "model_call_count" not in turn:
        return "  totals: no usage recorded (written before phase 6c)"
    cost = turn.get("total_cost_usd")
    cost_text = f"${cost:.6f}" if cost is not None else f"null ({turn.get('unpriced_calls', 0)} call(s) without a price or usage)"
    return (f"  totals: {turn['model_call_count']} model call(s), {turn.get('tool_call_count', 0)} tool call(s), {turn.get('retry_count', 0)} retr(ies); "
            f"tokens in {turn.get('total_input_tokens')} out {turn.get('total_output_tokens')}"
            + ("" if turn.get("usage_complete", True) else " (some calls reported none)") + f"; cost {cost_text}")


def format_turn(turn: dict) -> str:
    route = turn.get("route") or {}
    lines = [f"{turn.get('timestamp')}  turn {turn.get('turn_id')}  session {turn.get('session_id')}  customer {turn.get('customer_id')}",
             f"  route: {route.get('router_label')} -> {route.get('branch')}   duration: {turn.get('duration_ms')} ms"
             + (f"   review: {turn['review_reference']}" if turn.get("review_reference") else ""),
             f"  customer: {turn.get('message')}",
             f"  reply:    {turn.get('reply')}"]
    lines.append(totals_line(turn))
    for step in turn.get("steps") or []:
        timing = f" {step['latency_ms']} ms" if step.get("latency_ms") is not None else (
            f" {step['duration_ms']} ms" if step.get("duration_ms") is not None else "")
        order = f"#{step['seq']} +{step['start_ms']}ms " if step.get("seq") is not None else ""
        lines.append(f"    {order}[{step.get('kind')}] {step.get('name')} ({step.get('status')}){timing}"
                     + (f"  in: {step['input']}" if step.get("input") else "") + (f"  out: {step['output']}" if step.get("output") else ""))
    for found in turn.get("search") or []:
        top = ", ".join(f"{r.get('rank')}:{r.get('score')}" for r in found.get("results") or [])
        lines.append(f"    search: profile {found.get('profile')}, rank:score {top or 'none'}, no-match rule {'fired' if found.get('no_match_fired') else 'did not fire'}")
    detail = turn.get("answer_check")
    if detail:
        lines.append(f"    answer check: {len(detail.get('attempts') or [])} attempt(s), retried {detail.get('retried')}, fallback used {detail.get('fallback_used')}")
    for error in turn.get("errors") or []:
        lines.append(f"    error: {error.get('where')} {error.get('type')}: {error.get('message')}")
    versions = turn.get("versions") or {}
    if versions:
        lines.append(f"  versions: commit {versions.get('git_commit')}  config {versions.get('config_hash')}  prompts {versions.get('prompt_hash')}  index {versions.get('index_fingerprint')}")
    if turn.get("index_fingerprint"):
        lines.append(f"  index: {turn['index_fingerprint']}   passages: {len(turn.get('passages') or [])}")
    if turn.get("pending_action"):
        lines.append(f"  pending: {turn['pending_action'].get('action')} - {turn['pending_action'].get('question')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--path", help="trace file (default: [tracing].local_path)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--session")
    ap.add_argument("--customer")
    ap.add_argument("--route")
    ap.add_argument("--failed", action="store_true", help="only turns with a failed check")
    ap.add_argument("--turn", help="show one turn by id")
    args = ap.parse_args(argv)
    path = Path(args.path) if args.path else resolve_path(load_agent_config().tracing, ROOT)
    if args.turn:
        turn = get_turn(path, args.turn)
        print(format_turn(turn) if turn else f"No turn {args.turn} in {path}")
        return 0 if turn else 1
    page = list_turns(path, args.limit, args.offset, session_id=args.session, customer_id=args.customer, route=args.route,
                      has_failed_check=True if args.failed else None)
    for turn in page.turns:
        print(format_turn(turn) + "\n")
    print(f"{len(page.turns)} of {page.total} matching turn(s) shown; {page.skipped} broken line(s) skipped; file: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
