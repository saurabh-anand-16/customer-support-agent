"""
16_live_langfuse_paths.py - real turns copied to a real Langfuse server (phase 6b).

    python scripts/16_live_langfuse_paths.py               # auth check, three real turns, flush, read two traces back
    python scripts/16_live_langfuse_paths.py --wrong-key   # one cheap turn with a wrong secret key (set in this process only)

Keys come from the process environment, then .env. They are never printed. The real model and the real server are used; the tools
run over a COPY of returns_agent.db in a temporary folder, and the real file's hash is checked before and after.
The report: auth_check() as true or false, each turn's trace link, the flush time, and for two traces read back through the SDK's
API client: observation types, the user id (must be the keyed hash), and whether any customer id, phone number or e-mail
appears in any input, output or metadata.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                                                      # noqa: E402
from agent.langfuse_export import CUSTOMER_ID, EMAIL, PHONE, hash_customer, make_exporter   # noqa: E402
from agent.llm import FakeChat, load_agent_config                                          # noqa: E402
from agent.rag.embedders.base import read_secret                                           # noqa: E402
from agent.tracing import Tracer                                                           # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TRACE_FILE = ROOT / "data" / "traces" / "live_langfuse.jsonl"
ENV_FILE = ROOT / ".env"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def counts(con) -> dict:
    return {"returns": con.execute("SELECT COUNT(*) FROM returns").fetchone()[0],
            "cancelled": con.execute("SELECT COUNT(*) FROM order_items WHERE item_status='cancelled'").fetchone()[0],
            "review_items": con.execute("SELECT COUNT(*) FROM review_items").fetchone()[0]}


def build_agent(tools, **kwargs):
    cfg = load_agent_config()
    cfg = replace(cfg, tracing=replace(cfg.tracing, enabled=True, local_path=str(TRACE_FILE), langfuse_enabled=True))
    exporter = make_exporter(cfg.tracing, ENV_FILE)
    tracer = Tracer(cfg.tracing, cfg.root, {"router": cfg.model.name, "branch": cfg.branches.name, "confirm": cfg.confirm.name}, exporter=exporter)
    return Agent(config=cfg, tools=tools, tracer=tracer, **kwargs), exporter


def _fetch(api, trace_id: str):
    """All observations of one trace, through the SDK's API client. In SDK 5 this is the read path (there is no trace.get)."""
    out, cursor = [], None
    while True:
        page = api.observations.get_many(trace_id=trace_id, fields="core,basic,io,metadata,model,trace_context", limit=100, cursor=cursor,
                                         expand_metadata="*")
        out += [json.loads(o.json()) if hasattr(o, "json") else dict(o) for o in page.data]
        cursor = getattr(page.meta, "cursor", None)
        if not cursor:
            return out


def read_back(exporter, trace_id: str, customer_id: str, key: str, expected: int) -> dict:
    """Fetch the trace (retrying while the server ingests it) and look for what must not be there."""
    observations, last = [], "none yet"
    for _ in range(30):
        try:
            observations = _fetch(exporter.client.api, trace_id)
            if len(observations) >= expected:
                break
            last = f"{len(observations)} of {expected} observations"
        except Exception as err:
            last = type(err).__name__
        time.sleep(2)
    if not observations:
        return {"error": f"trace not readable after 60 s ({last})"}
    blob = "\n".join(json.dumps({k: o.get(k) for k in ("name", "input", "output", "metadata", "statusMessage", "model")}, default=str) for o in observations)
    kinds: dict = {}
    for o in observations:
        kinds[o.get("type")] = kinds.get(o.get("type"), 0) + 1
    users, sessions = {o.get("userId") for o in observations}, {o.get("sessionId") for o in observations}
    hits = {"customer_id_pattern": len(CUSTOMER_ID.findall(blob)), "the_customers_own_id": blob.count(customer_id),
            "phone": len(PHONE.findall(blob)), "email": len(EMAIL.findall(blob))}
    return {"observations": len(observations), "expected": expected, "observation_types": kinds, "user_ids": sorted(map(str, users)),
            "user_id_is_the_keyed_hash": users == {hash_customer(customer_id, key)}, "user_id_equals_customer_id": customer_id in users,
            "session_ids": sorted(map(str, sessions)), "trace_names": sorted({str(o.get("traceName")) for o in observations}),
            "hits_in_inputs_outputs_metadata": hits}


def expected_observations(rec: dict) -> int:
    return 1 + len(rec["steps"])          # the root plus one observation per step (checks are events)


def run_three_turns() -> int:
    live = _load("live10", "10_live_confirm_paths.py")
    real_db = ROOT / "returns_agent.db"
    real_before = live.sha256(real_db)
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACE_FILE.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="live_langfuse_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(real_db, copy)
        probe = ReturnsTools(copy)
        try:
            chosen = live.choose_customer(probe)
        finally:
            probe.con.close()
        tools = ReturnsTools(copy)
        agent, exporter = build_agent(tools)
        print(f"auth_check(): {exporter.auth_check()}")
        ret = chosen["return"]
        ask_return = (f"The {ret['product_name']} from order {ret['order_id']} (item {ret['item_id']}) arrived damaged. "
                      "I want to return it for a refund.")
        plan = [("policy question", ["How many days do I have to return an item, and how long does a refund take?"]),
                ("eligible return with confirm", [ask_return, "Yes, please go ahead."]),
                ("request for a person", ["I want to talk to a person about my order, please."])]
        print(f"customer chosen from tool output: {chosen['customer_id']}")
        try:
            for name, messages in plan:
                before = counts(tools.con)
                sid = agent.start_session(chosen["customer_id"])
                for m in messages:
                    started = time.perf_counter()
                    result = agent.respond(sid, m)
                    print(f"\n[{name}] customer: {m}\n[{name}] agent ({time.perf_counter() - started:.1f} s, export on): {result['reply'][:300]}")
                print(f"[{name}] counts {before} -> {counts(tools.con)}")
            flush_seconds = exporter.flush()
            print(f"\nflush took {flush_seconds:.2f} s (sending already ran in the background; this waits for what is left)")
            lines = [json.loads(x) for x in TRACE_FILE.read_text(encoding="utf-8").splitlines()]
            print("\n=== trace links, one per turn (message order) ===")
            for rec in lines:
                trace_id = exporter.trace_ids.get(rec["turn_id"])
                print(f"{rec['route']['router_label']:<18} {rec['route'].get('branch')!s:<18} {exporter.trace_url(trace_id) if trace_id else 'NOT SENT'}")
            key = read_secret(exporter.settings.hash_key_env_name, ENV_FILE)
            sent = [r for r in lines if r["turn_id"] in exporter.trace_ids]
            if sent:
                print("\n=== read back through the SDK API client: the first turn ===")
                print(json.dumps(read_back(exporter, exporter.trace_ids[sent[0]["turn_id"]], chosen["customer_id"], key, expected_observations(sent[0])), indent=2))
            writes = [r for r in sent if any(s["kind"] == "write" for s in r["steps"])]
            if writes:
                print("\n=== the confirm turn (it holds the write) ===")
                print(json.dumps(read_back(exporter, exporter.trace_ids[writes[0]["turn_id"]], chosen["customer_id"], key, expected_observations(writes[0])), indent=2))
        finally:
            exporter.shutdown()
            tools.con.close()
    real_after = live.sha256(real_db)
    print(f"\nreal database hash {'unchanged' if real_before == real_after else 'CHANGED'}")
    return 0 if real_before == real_after else 1


def run_wrong_key() -> int:
    """One turn with a wrong secret key in this process's environment only. A scripted model answers, so no model cost."""
    os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-this-key-is-wrong-0000"
    TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    agent, exporter = build_agent(None, chat=FakeChat('{"route": "out_of_scope", "reason": "r", "kind": "greeting"}'))
    print(f"auth_check() with the wrong key: {exporter.auth_check()}")
    sid = agent.start_session("C0001")
    started = time.perf_counter()
    result = agent.respond(sid, "hello")
    print(f"the turn returned in {time.perf_counter() - started:.2f} s: route={result['route']!r}, reply={result['reply']!r}")
    print(f"flush took {exporter.flush():.2f} s")
    exporter.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(run_wrong_key() if "--wrong-key" in sys.argv else run_three_turns())
