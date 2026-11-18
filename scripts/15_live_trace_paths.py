"""
15_live_trace_paths.py - three real-model turns that fill the local trace file (phase 6).

    python scripts/15_live_trace_paths.py            # uses the real model named in config/agent.toml (key from .env, never printed)

The turns: a policy question, an eligible return with a confirm (the second message writes one return), and a request for a
person (writes one review-queue item). The tools run over a COPY of returns_agent.db in a temporary folder; the real file's
hash is printed before and after. The customer is chosen from tool output only (the same walk as scripts/10_live_confirm_paths.py);
no other column is read, and never the test-only one.

Traces go to data/traces/live_run.jsonl (in .gitignore), then `show_traces.py` prints them. Langfuse is not touched.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                          # noqa: E402
from agent.llm import OpenAIChat, load_agent_config            # noqa: E402
from agent.tracing import list_turns                            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TRACE_FILE = ROOT / "data" / "traces" / "live_run.jsonl"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counts(con) -> dict:
    return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0],
            "review_items": con.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]}


class TalliedChat(OpenAIChat):
    """The real model, with its own count of what the API returned. It wraps the client's `create` and adds up `response.usage` by itself,
    so the total can be compared with what the trace recorded (phase 6c). It records nothing else."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.api_input = self.api_output = self.api_calls = 0

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


def shorten(rec: dict) -> dict:
    """The parts of a trace line worth reading: no long text."""
    return {"turn_id": rec["turn_id"], "route": rec["route"], "duration_ms": rec["duration_ms"], "review_reference": rec["review_reference"],
            "index_fingerprint": rec["index_fingerprint"], "passages": len(rec["passages"]),
            "steps": [f"{s['kind']}:{s['name']}:{s['status']}" + (f":{s['latency_ms']}ms" if s["latency_ms"] is not None else "") for s in rec["steps"]],
            "timeline": [f"#{t['seq']} {t['type']}:{t['name']} +{t['start_ms']}ms {t['duration_ms']}ms {t['status']}" for t in rec.get("timeline", [])],
            "model_calls": [f"{c['kind']} {c['model']} in={c['input_tokens']} out={c['output_tokens']} cached={c['cached_tokens']} "
                            f"{c['latency_ms']}ms cost={c['cost_usd']}" for c in rec.get("model_calls", [])],
            "totals": {k: rec.get(k) for k in ("total_input_tokens", "total_output_tokens", "total_cost_usd", "cost_complete", "model_call_count",
                                              "tool_call_count", "retry_count")},
            "search": [{"profile": f["profile"], "scores": [r["score"] for r in f["results"]], "no_match_fired": f["no_match_fired"],
                        "thresholds": f["no_match_thresholds"], "rewritten": f.get("rewritten")} for f in rec.get("search", [])],
            "answer_check": rec.get("answer_check") and {k: rec["answer_check"][k] for k in ("retried", "fallback_used", "used")},
            "versions": rec.get("versions"), "errors": rec.get("errors")}


def main() -> int:
    live = _load("live10", "10_live_confirm_paths.py")
    real_db = ROOT / "returns_agent.db"
    real_before = live.sha256(real_db)
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACE_FILE.unlink(missing_ok=True)
    cfg = load_agent_config()
    cfg = replace(cfg, tracing=replace(cfg.tracing, enabled=True, local_path=str(TRACE_FILE), langfuse_enabled=False))
    with tempfile.TemporaryDirectory(prefix="live_trace_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(real_db, copy)
        probe = ReturnsTools(copy)
        try:
            chosen = live.choose_customer(probe)
        finally:
            probe.con.close()
        tools = ReturnsTools(copy)
        chat = TalliedChat(cfg.root)
        agent = Agent(config=cfg, tools=tools, chat=chat)
        ret = chosen["return"]
        ask_return = (f"The {ret['product_name']} from order {ret['order_id']} (item {ret['item_id']}) arrived damaged. "
                      "I want to return it for a refund.")
        plan = [("policy question", ["How many days do I have to return an item, and how long does a refund take?"]),
                ("eligible return with confirm", [ask_return, "Yes, please go ahead."]),
                ("request for a person", ["I want to talk to a person about my order, please."])]
        print(f"customer chosen from tool output: {chosen['customer_id']} (eligible item {ret['item_id']}, day {ret['day_number']} of {ret['window_days']})")
        try:
            for name, messages in plan:
                before, hash_before = counts(tools.con), live.sha256(copy)
                sid = agent.start_session(chosen["customer_id"])
                for m in messages:
                    result = agent.respond(sid, m)
                    print(f"\n[{name}] customer: {m}\n[{name}] agent:    {result['reply']}")
                after, hash_after = counts(tools.con), live.sha256(copy)
                print(f"[{name}] counts {before} -> {after}\n[{name}] copy hash {hash_before[:16]}... -> {hash_after[:16]}... (changed: {hash_before != hash_after})")
        finally:
            tools.con.close()
    page_now = list_turns(TRACE_FILE, limit=50)
    traced_in = sum(r["total_input_tokens"] for r in page_now.turns)
    traced_out = sum(r["total_output_tokens"] for r in page_now.turns)
    traced_calls = sum(r["model_call_count"] for r in page_now.turns)
    print(f"\ntokens the API returned (counted by the script): {chat.api_calls} call(s), in {chat.api_input}, out {chat.api_output}")
    print(f"tokens the trace recorded:                       {traced_calls} call(s), in {traced_in}, out {traced_out}   "
          f"({'equal' if (chat.api_calls, chat.api_input, chat.api_output) == (traced_calls, traced_in, traced_out) else 'DIFFERENT'})")
    real_after = live.sha256(real_db)
    print(f"\nreal database hash before {real_before}\nreal database hash after  {real_after}  ({'unchanged' if real_before == real_after else 'CHANGED'})")
    print("\n=== trace lines (shortened) ===")
    page = list_turns(TRACE_FILE, limit=50)
    for rec in reversed(page.turns):
        print(json.dumps(shorten(rec), ensure_ascii=False))
    print(f"\n{len(page.turns)} line(s) in {TRACE_FILE.name}; {page.skipped} skipped")
    return 0 if real_before == real_after else 1


if __name__ == "__main__":
    sys.exit(main())
