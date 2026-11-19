"""
17_live_search_app_check.py - the app check of phase 3d (phase 10 Part A): policy questions through the real Agent, before and after the new search default.

    python scripts/17_live_search_app_check.py before    # the old setup: keyword search (baseline_bm25) with the old placeholder thresholds 5.0 and 0.35
    python scripts/17_live_search_app_check.py after     # the setup now in config/rag.toml

Every question starts a fresh chat for one customer, on a COPY of returns_agent.db in a temporary folder (the real file's hash is printed
before and after). It uses the real model named in config/agent.toml (key from .env, never printed). Tracing is off.

Questions: the 32 of the phase 8b report (read from its table, so they are not typed twice) and the two other suggested chips from that time.
For each: the route, the search scores and whether it counted as a match, and whether the reply cited a policy passage.
"""
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import Agent, ReturnsTools                          # noqa: E402
from agent.llm import OpenAIChat, load_agent_config            # noqa: E402
from agent.policy_search import PolicySearch                    # noqa: E402
from agent.rag import load_config                               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "builds" / "phase-08b-build.md"
EXTRA_CHIPS = ["Where is my refund?", "Cancel my other order"]
CUSTOMER = "C0117"            # the "Policy questions" persona


def sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def questions_from_report() -> list[dict]:
    """The rows of the 8b table: | Question | Source | bm25 | vector |. The out-of-scope rows start with '*Out of scope:*'."""
    rows = []
    for line in REPORT.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (.+?) \| (router-eval|heading|starter|chip|chat) \| ", line)
        if not m:
            continue
        text = re.sub(r"\*\*|\*Out of scope:\* ", "", m.group(1))
        text = re.sub(r" \((policy silent)\)$", "", text).strip()
        rows.append({"question": text, "source": m.group(2)})
    return rows


class RecordingSearch(PolicySearch):
    """The real PolicySearch; remembers what each call returned so the script can print it."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls: list[dict] = []

    def search_policy(self, query, top_k=None, include_out_of_scope=False):
        out = super().search_policy(query, top_k=top_k, include_out_of_scope=include_out_of_scope)
        self.calls.append({"query": out.get("query"), "ok": out.get("ok"), "scores": [round(r["score"], 3) for r in out.get("results", [])],
                           "no_match": bool(out.get("note")), "profile": out.get("profile")})
        return out


def make_search(which: str) -> RecordingSearch:
    if which == "before":
        base = load_config("baseline_bm25")
        cfg = replace(base, no_match=replace(base.no_match, bm25_min_score=5.0, vector_min_score=0.35))   # the old placeholders
        return RecordingSearch(cfg=cfg)
    return RecordingSearch()            # the config's default profile and thresholds


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "after"
    if which not in ("before", "after"):
        print("usage: 17_live_search_app_check.py before|after", file=sys.stderr)
        return 2
    items = questions_from_report() + [{"question": q, "source": "chip"} for q in EXTRA_CHIPS]
    real_db = ROOT / "returns_agent.db"
    real_before = sha256(real_db)
    cfg = load_agent_config()
    cfg = replace(cfg, tracing=replace(cfg.tracing, enabled=False, langfuse_enabled=False))
    search = make_search(which)
    started = time.perf_counter()
    rows = []
    with tempfile.TemporaryDirectory(prefix="live_search_", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(real_db, copy)
        tools = ReturnsTools(copy)
        try:
            agent = Agent(config=cfg, tools=tools, chat=OpenAIChat(cfg.root), policy_search=search)
            for item in items:
                search.calls.clear()
                sid = agent.start_session(CUSTOMER)
                result = agent.respond(sid, item["question"])
                passages = result["evidence"]["policy_passages"]
                rows.append({**item, "route": result["route"],
                             "searches": list(search.calls), "cited_passages": sum(1 for p in passages if p.get("cited")),
                             "passages_shown": len(passages), "reply": result["reply"][:160]})
                print(f"{item['source']:<12} {item['question'][:62]:<62} route={rows[-1]['route']} searches={len(search.calls)} "
                      f"no_match={[c['no_match'] for c in search.calls]} cited={rows[-1]['cited_passages']}", flush=True)
        finally:
            tools.con.close()
    real_after = sha256(real_db)
    answered = sum(1 for r in rows if r["cited_passages"])
    searched = [r for r in rows if r["searches"]]
    print(f"\n{which}: {len(rows)} questions; {len(searched)} reached policy search; {answered} replies cited a policy passage; "
          f"{round(time.perf_counter() - started)} s")
    print(f"real database hash before {real_before}\nreal database hash after  {real_after}  ({'unchanged' if real_before == real_after else 'CHANGED'})")
    out = ROOT / "data" / "evals" / "results" / f"app_check_{which}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0 if real_before == real_after else 1


if __name__ == "__main__":
    sys.exit(main())
