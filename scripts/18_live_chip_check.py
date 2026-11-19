"""
18_live_chip_check.py - run every suggested chip for each scenario customer with the real model (phase 10 Part C3).

    python scripts/18_live_chip_check.py

The chips are what the chat page offers: the customer's own `try` text from app/personas.toml first, then [app].suggested_messages from
config/agent.toml (the same rule as app/views/chip_texts, written here again so the script does not import the app). Each chip starts a fresh
chat. Tools run on a COPY of returns_agent.db; the real file's hash is printed before and after. Nothing is confirmed: a chip that ends in
a confirm card counts as working. The key is read from .env and never printed. Tracing is off.
"""
import hashlib
import shutil
import sys
import tempfile
import time
import tomllib
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                          # noqa: E402
from agent.llm import OpenAIChat, load_agent_config            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> int:
    cfg = load_agent_config()
    cfg = replace(cfg, tracing=replace(cfg.tracing, enabled=False, langfuse_enabled=False))
    general = tomllib.loads((ROOT / "config" / "agent.toml").read_text(encoding="utf-8"))["app"]["suggested_messages"]
    personas = [p for p in tomllib.loads((ROOT / "app" / "personas.toml").read_text(encoding="utf-8"))["persona"] if p.get("try")]
    real = ROOT / "returns_agent.db"
    before, started = sha(real), time.perf_counter()
    rows = []
    with tempfile.TemporaryDirectory(prefix="chips_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(real, copy)
        tools = ReturnsTools(copy)
        try:
            agent = Agent(config=cfg, tools=tools, chat=OpenAIChat(cfg.root))
            for p in personas:
                chips = [p["try"]] + [t for t in general if t != p["try"]]
                for chip in chips:
                    result = agent.respond(agent.start_session(p["customer_id"]), chip)
                    tool_names = [c["tool"] for c in result["evidence"]["tool_calls"]]
                    rows.append((p["customer_id"], p["label"], chip, result["route"], tool_names, bool(result["pending_action"]),
                                 len(result["evidence"]["policy_passages"]), result["reply"]))
                    print(f"\n{p['customer_id']} ({p['label']}) chip: {chip}\n  route {result['route']}, tools {tool_names}, "
                          f"confirm card {bool(result['pending_action'])}, passages {len(result['evidence']['policy_passages'])}\n  reply: {result['reply'][:260]}", flush=True)
        finally:
            tools.con.close()
    after = sha(real)
    print(f"\n{len(rows)} chips, {round(time.perf_counter() - started)} s; real database hash {'unchanged' if before == after else 'CHANGED'}")
    return 0 if before == after else 1


if __name__ == "__main__":
    sys.exit(main())
