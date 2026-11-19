"""
08_eval_router.py - run the router on every reviewed labelled message and score it (phase 4a; rebuilt in phase 10 Part B).

    python scripts/08_eval_router.py --label baseline          # every reviewed row, real model, writes data/evals/results/router_baseline.json
    python scripts/08_eval_router.py --label after
    python scripts/08_eval_router.py --compare router_baseline.json router_after.json    # rows that changed, in either direction (no model call)

It uses the real model named in config/agent.toml (needs OPENAI_API_KEY in .env). Only rows with reviewed = yes count; rows still marked
"no" are counted and left out. The CSV is only read: nothing is written to it.

How a row is run:
  * Most rows: one router call, the way the agent makes it. The row's "context" column becomes the conversation the router sees
    (a "previous turn" note becomes one earlier exchange), so a row with context is a rough test, not a replay of a real chat.
  * Rows that wait for a confirmation (context "pending_action: ..."): the router must NOT see them. They are run through the real Agent
    on a COPY of the database: the first message makes the agent propose an action (a cancel or a return, chosen from app/personas.toml),
    so a real pending action exists; then the row's message is sent. The row passes when the trace shows the message went to the confirm
    step before any router call (steps start "router", "confirm_step"; the router was not called) and the route is the expected one.
    A change of mind ("make it a replacement instead") must be handed back to the router and come out as the expected route.

It reports accuracy overall, by category and by expected route (each as "n of N"), a confusion table, every wrong row with the route chosen,
the model calls and tokens (counted from what the API returned) and the time. Cost is "not priced": the price table is empty.
"""
import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import time
import tomllib
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                              # noqa: E402
from agent.llm import LlmError, OpenAIChat, load_agent_config       # noqa: E402
from agent.rag.embedders.base import read_secret                    # noqa: E402
from agent.router import Router                                     # noqa: E402
from agent.session import Session                                   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "data" / "evals" / "router_messages.csv"
RESULTS_DIR = ROOT / "data" / "evals" / "results"
PERSONAS = ROOT / "app" / "personas.toml"


def load_rows(path=DEFAULT_CSV) -> tuple[list[dict], int]:
    """(reviewed rows, number of rows left out because they are not reviewed)."""
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if r.get("reviewed", "").strip().lower() == "yes"]
    return kept, len(rows) - len(kept)


def is_pending(row: dict) -> bool:
    return (row.get("context") or "").strip().startswith("pending_action")


class TalliedChat(OpenAIChat):
    """The real model with its own count of what the API returned (calls, input and output tokens). It records nothing else."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.api_calls = self.api_input = self.api_output = 0

    def _get_client(self, settings):
        client = super()._get_client(settings)
        if not getattr(client, "_tallied", False):
            create = client.chat.completions.create

            def counted(*args, **kwargs):
                response = create(*args, **kwargs)
                self.api_calls += 1
                self.api_input += response.usage.prompt_tokens
                self.api_output += response.usage.completion_tokens
                return response
            client.chat.completions.create = counted
            client._tallied = True
        return client


def session_for(row: dict, keep: int) -> Session:
    """A fresh session set up from the row's context column (rows that are not pending)."""
    session = Session("EVAL", "EVAL")
    context = (row.get("context") or "none").strip()
    if context.startswith("pending_action"):
        session.pending_action = {"description": context}
    elif context.startswith("previous turn"):
        note = context.split(":", 1)[1].strip()
        session.add_exchange(f"(earlier in this conversation: {note})", "(the assistant's reply is not shown)", "", keep)
    return session


def _record(row: dict, got: str, **extra) -> dict:
    base = {"id": row["id"], "message": row["message"], "context": row.get("context", "none"), "category": row["category"],
            "reviewed": row.get("reviewed", ""), "expected": row["expected_route"], "got": got, "kind": None, "reason": "", "error": None,
            "called": True, "latency_ms": 0.0, "via": "router"}
    return {**base, **extra}


def evaluate(rows: list[dict], router: Router, pending_runner=None) -> list[dict]:
    """Route every row. Pending rows go to `pending_runner(row)` (the agent) when one is given; otherwise the router itself shows the bypass."""
    records = []
    for row in rows:
        if pending_runner is not None and is_pending(row):
            records.append(pending_runner(row))
            continue
        decision = router.decide(session_for(row, router.cfg.session.history_keep), row["message"])
        records.append(_record(row, decision.route, kind=decision.kind, reason=decision.reason, error=decision.error,
                               called=decision.called, latency_ms=round(decision.latency_ms, 1)))
    return records


# --- pending rows, through the agent ------------------------------------------------------------------------------
def _persona(label: str) -> dict:
    data = tomllib.loads(PERSONAS.read_text(encoding="utf-8"))
    return next(p for p in data["persona"] if p["label"] == label)


class PendingRunner:
    """Runs a pending-action row through the real Agent on a copy of the database."""

    def __init__(self, cfg, chat, db_path: Path, tmp: Path):
        self.cfg, self.chat, self.db_path, self.tmp = cfg, chat, db_path, tmp

    def __call__(self, row: dict) -> dict:
        wanted = "Order still processing" if "cancel" in row["context"] else "Last eligible day"
        persona = _persona(wanted)
        copy = self.tmp / f"{row['id']}.db"
        shutil.copy2(self.db_path, copy)
        tools = ReturnsTools(copy)
        started = time.perf_counter()
        try:
            agent = Agent(config=self.cfg, tools=tools, chat=self.chat)
            attempts = 0
            while True:                    # the real model sometimes asks a question instead of proposing: try the setup again (new session), up to 3 times
                attempts += 1
                sid = agent.start_session(persona["customer_id"])
                first = agent.respond(sid, persona["try"])
                if agent.sessions.get(sid).pending_action is not None:
                    break
                if attempts == 3:
                    return _record(row, "setup_failed", error="the setup message did not leave a pending action in 3 tries", via="agent")
            result = agent.respond(sid, row["message"])
        finally:
            tools.con.close()
        trace = result["trace"]
        steps = trace["steps"]
        bypass = steps[:2] == ["router", "confirm_step"] and bool(trace["pending_action_bypass"])
        label = (trace.get("confirm") or {}).get("label") or (trace.get("branch") or {}).get("label")
        extra = {"via": "agent", "setup_route": first["route"], "setup_attempts": attempts, "steps": steps, "confirm_label": label, "went_to_confirm_first": bypass,
                 "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
        if row["expected_route"] == "confirm_step":
            got = "confirm_step" if bypass and result["route"] == "confirm_step" else result["route"]
        else:                                                         # a change of mind: confirm step first, then routed again
            got = result["route"] if bypass else f"not_bypassed:{result['route']}"
        return _record(row, got, called=False if row["expected_route"] == "confirm_step" else True, **extra)


# --- scoring ------------------------------------------------------------------------------------------------------
def _share(records, key) -> dict:
    groups = defaultdict(lambda: [0, 0])
    for r in records:
        groups[r[key]][1] += 1
        groups[r[key]][0] += r["expected"] == r["got"]
    return {name: {"correct": c, "total": t} for name, (c, t) in sorted(groups.items())}


def summarize(records: list[dict]) -> dict:
    correct = sum(r["expected"] == r["got"] for r in records)
    confusion = Counter((r["expected"], r["got"]) for r in records if r["expected"] != r["got"])
    called = [r["latency_ms"] for r in records if r["called"] and r.get("via", "router") == "router"]
    return {
        "rows": len(records), "correct": correct,
        "by_category": _share(records, "category"), "by_expected_route": _share(records, "expected"),
        "confusion": [{"expected": e, "got": g, "count": n} for (e, g), n in confusion.most_common()],
        "misses": [r for r in records if r["expected"] != r["got"]],
        "invalid_router_outputs": sum(1 for r in records if r["error"]),
        "model_calls": sum(1 for r in records if r["called"] and r.get("via", "router") == "router"),
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
    lines += ["", f"invalid router outputs: {summary['invalid_router_outputs']}; router calls: {summary['model_calls']}; "
                  f"mean router latency {summary['mean_latency_ms']} ms"]
    return "\n".join(lines)


def compare(before: dict, after: dict) -> str:
    """Rows whose result changed between two result files, in both directions."""
    a = {r["id"]: r for r in before["records"]}
    b = {r["id"]: r for r in after["records"]}
    better, worse, other = [], [], []
    for rid in sorted(a.keys() & b.keys()):
        ok_a, ok_b = a[rid]["expected"] == a[rid]["got"], b[rid]["expected"] == b[rid]["got"]
        if ok_a != ok_b:
            (better if ok_b else worse).append(rid)
        elif a[rid]["got"] != b[rid]["got"]:
            other.append(rid)
    pct = lambda recs: f"{sum(r['expected'] == r['got'] for r in recs)} of {len(recs)}"      # noqa: E731
    lines = [f"before: {pct(before['records'])}   after: {pct(after['records'])}",
             f"rows that got better ({len(better)}):"]
    lines += [f"  {i} [{b[i]['category']}] {a[i]['message'][:60]!r}: {a[i]['got']} -> {b[i]['got']} (expected {b[i]['expected']})" for i in better]
    lines += [f"rows that got WORSE ({len(worse)}):"]
    lines += [f"  {i} [{b[i]['category']}] {a[i]['message'][:60]!r}: {a[i]['got']} -> {b[i]['got']} (expected {b[i]['expected']})" for i in worse]
    lines += [f"rows still wrong that changed their wrong answer ({len(other)}):"]
    lines += [f"  {i} {a[i]['got']} -> {b[i]['got']} (expected {b[i]['expected']})" for i in other]
    return "\n".join(lines)


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    parser.add_argument("--config", default=None, help="config file (default: config/agent.toml)")
    parser.add_argument("--label", default="run", help="names the result file: data/evals/results/router_<label>.json")
    parser.add_argument("--output", default=None, help="where to write the results (JSON); overrides --label")
    parser.add_argument("--db", default=str(ROOT / "returns_agent.db"), help="database copied for the pending-action rows")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="compare two result files; no model call")
    args = parser.parse_args()

    if args.compare:
        load = lambda p: json.loads((Path(p) if Path(p).exists() else RESULTS_DIR / p).read_text(encoding="utf-8"))    # noqa: E731
        print(compare(load(args.compare[0]), load(args.compare[1])))
        return 0

    cfg = load_agent_config(args.config)
    output = Path(args.output) if args.output else RESULTS_DIR / f"router_{args.label}.json"
    if not read_secret(cfg.model.api_key_env, cfg.root / cfg.model.env_file):      # fail early; the key itself is never shown
        print(f"error: no API key: set {cfg.model.api_key_env} in the environment or in {cfg.model.env_file}", file=sys.stderr)
        return 2

    rows, unreviewed = load_rows(args.csv)
    print(f"{len(rows)} reviewed rows; {unreviewed} not reviewed and left out.\n")
    chat = TalliedChat(cfg.root)
    router = Router(cfg, chat)
    agent_cfg = replace(cfg, tracing=replace(cfg.tracing, enabled=False, langfuse_enabled=False))
    db = Path(args.db)
    db_before = _sha(db)
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="router_eval_", ignore_cleanup_errors=True) as tmp:
            records = evaluate(rows, router, PendingRunner(agent_cfg, chat, db, Path(tmp)))
    except LlmError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    seconds = round(time.perf_counter() - started, 1)
    db_after = _sha(db)
    summary = summarize(records)
    usage = {"api_calls": getattr(chat, "api_calls", 0), "input_tokens": getattr(chat, "api_input", 0), "output_tokens": getattr(chat, "api_output", 0), "seconds": seconds, "cost": "not priced"}
    print(format_report(summary, f"{len(rows)} reviewed rows, model {cfg.model.name}, temperature {cfg.model.temperature}"))
    print(f"\nmodel calls {usage['api_calls']} (router rows and the agent's own calls for the pending rows), tokens in {usage['input_tokens']}, "
          f"out {usage['output_tokens']}, {seconds} s, cost not priced")
    print(f"real database hash {'unchanged' if db_before == db_after else 'CHANGED'}")
    pending = [r for r in records if r.get("via") == "agent"]
    for r in pending:
        print(f"  pending row {r['id']}: steps {r.get('steps')}, confirm label {r.get('confirm_label')}, went to confirm first: "
              f"{r.get('went_to_confirm_first')}, route {r['got']}")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"label": args.label, "model": cfg.model.name, "temperature": cfg.model.temperature, "reviewed_rows": len(rows),
                                  "unreviewed_rows": unreviewed, "usage": usage, "summary": {k: v for k, v in summary.items() if k != "misses"},
                                  "records": records}, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {output}")
    return 0 if db_before == db_after else 1


if __name__ == "__main__":
    sys.exit(main())
