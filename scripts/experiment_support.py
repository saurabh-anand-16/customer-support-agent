"""
experiment_support.py - the parts of the experiment runner (phase 14). The command is scripts/23_run_experiment.py.

Nothing here changes anything under agent/, config/ or the real database. It:
  * reads and checks an experiment file, and builds a merged copy of the two config files in a work folder;
  * estimates the cost before anything runs;
  * counts what the API reports (tokens per model, embeddings) and turns it into dollars with the price table;
  * runs the three checks by calling the functions of the existing evaluation scripts (07, 08 and 19), not copies of them.
"""
import copy
import hashlib
import importlib.util
import json
import re
import sys
import tomllib
from contextlib import contextmanager
from dataclasses import dataclass, field, is_dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent.llm import PRICE_KEYS, load_agent_config           # noqa: E402
from agent.rag import load_config                              # noqa: E402
from agent.rag.config import SECTIONS as RAG_SECTIONS          # noqa: E402

AGENT_TOML = ROOT / "config" / "agent.toml"
RAG_TOML = ROOT / "config" / "rag.toml"
REAL_DB = ROOT / "returns_agent.db"
ALL_CHECKS = ("search", "router", "scenarios")
DEFAULT_REPEAT, DEFAULT_LIMIT = 3, 0.50

# What one run of each model check costs in model calls and tokens, measured in phase 10 (data/evals/summary.json for the scenarios; the router
# figure is from data/evals/results/router_after.json, which includes the agent's own calls for the pending-action rows).
MEASURED = {"router": {"calls": 103, "tokens_in": 100105, "tokens_out": 2775},
            "scenarios": {"calls": 80, "tokens_in": 78561, "tokens_out": 2305}}
QUERY_TOKENS = 20          # a search question is about this many tokens (a rough figure, only used for the estimate)
CHARS_PER_TOKEN = 4        # the usual rough rule, only used for the estimate (no tokenizer package is installed)


class ExperimentError(Exception):
    """Something in the experiment file or the run set-up is wrong. The message says what, in plain words."""


def load_script(file_name: str):
    """Import one of the numbered scripts as a module so its functions can be reused (the file names start with digits)."""
    spec = importlib.util.spec_from_file_location("exp_" + re.sub(r"\W", "_", file_name), ROOT / "scripts" / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha_file(path) -> str | None:
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


# --- a small TOML writer (the standard library only reads TOML) -------------------------------------------------------
def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)          # a JSON string is also a valid TOML basic string
    if isinstance(v, list) and not any(isinstance(x, dict) for x in v):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    raise TypeError(f"cannot write {type(v).__name__} as TOML")


def dumps_toml(data: dict, path: tuple = ()) -> str:
    """The TOML text for `data`. The caller checks that reading it back gives `data` again (write_toml does)."""
    out = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict) and not (isinstance(v, list) and v and all(isinstance(x, dict) for x in v))}
    for k, v in scalars.items():
        out.append(f"{_key(k)} = {_value(v)}")
    for k, v in data.items():
        if isinstance(v, dict):
            here = path + (k,)
            out.append(f"\n[{'.'.join(_key(p) for p in here)}]")
            out.append(dumps_toml(v, here))
        elif k not in scalars:
            here = path + (k,)
            for item in v:
                out.append(f"\n[[{'.'.join(_key(p) for p in here)}]]")
                out.append(dumps_toml(item, here))
    return "\n".join(out)


def write_toml(path: Path, data: dict) -> None:
    text = dumps_toml(data) + "\n"
    if tomllib.loads(text) != data:
        raise ExperimentError(f"internal error: the merged config for {path.name} did not read back the same, so it was not used")
    path.write_text(text, encoding="utf-8")


# --- the experiment file ----------------------------------------------------------------------------------------------
def load_experiment(path) -> dict:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ExperimentError(f"The experiment file {path} does not exist.") from None
    except tomllib.TOMLDecodeError as err:
        raise ExperimentError(f"{path.name} is not valid TOML: {err}") from None
    allowed = {"name", "note", "checks", "repeat", "cost_limit_usd", "override"}
    for key in data:
        if key not in allowed:
            raise ExperimentError(f"{path.name}: unknown key '{key}'. Allowed: {', '.join(sorted(allowed))}")
    name = data.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,60}", name):
        raise ExperimentError(f"{path.name}: 'name' is needed: lower-case letters, digits, - and _ only")
    note = data.get("note", "")
    if not isinstance(note, str):
        raise ExperimentError(f"{path.name}: 'note' must be text")
    checks = data.get("checks", list(ALL_CHECKS))
    if not isinstance(checks, list) or not checks or any(c not in ALL_CHECKS for c in checks) or len(set(checks)) != len(checks):
        raise ExperimentError(f"{path.name}: 'checks' must list some of: {', '.join(ALL_CHECKS)}")
    repeat = data.get("repeat", DEFAULT_REPEAT)
    if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 10:
        raise ExperimentError(f"{path.name}: 'repeat' must be a whole number from 1 to 10")
    limit = data.get("cost_limit_usd", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit <= 0:
        raise ExperimentError(f"{path.name}: 'cost_limit_usd' must be a number above 0")
    override = data.get("override", {})
    if not isinstance(override, dict) or any(k not in ("agent", "rag") or not isinstance(v, dict) for k, v in override.items()):
        raise ExperimentError(f"{path.name}: [override] may hold only the tables [override.agent] and [override.rag]")
    return {"name": name, "note": note, "checks": [c for c in ALL_CHECKS if c in checks], "repeat": repeat,
            "cost_limit_usd": float(limit), "override": override, "file": str(path)}


def _same_kind(base, new) -> bool:
    if isinstance(base, bool) or isinstance(new, bool):
        return isinstance(base, bool) and isinstance(new, bool)
    if isinstance(base, (int, float)):
        return isinstance(new, (int, float))
    return isinstance(new, type(base))


def _check_paths(base: dict, ov: dict, where: str, new_ok: tuple = ()) -> None:
    """Every key in `ov` must already exist in `base` (a typo stops the run), and have the same kind of value."""
    for key, value in ov.items():
        here = f"{where}.{key}"
        if key not in base:
            if where in new_ok:
                if not isinstance(value, dict):
                    raise ExperimentError(f"{here} must be a table")
                continue
            raise ExperimentError(f"Unknown setting {here}. It is not in the config file, so it would do nothing. Settings in that table: {', '.join(base) or 'none'}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ExperimentError(f"{here} is a table in the config file, so give it as a table")
            _check_paths(base[key], value, here, new_ok)
        elif isinstance(value, dict) or not _same_kind(base[key], value):
            raise ExperimentError(f"{here} should be {type(base[key]).__name__}, got {value!r}")


def _deep_merge(base: dict, ov: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in ov.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def merged_agent_raw(ov: dict) -> dict:
    base = tomllib.loads(AGENT_TOML.read_text(encoding="utf-8"))
    _check_paths(base, ov, "override.agent", new_ok=("override.agent.pricing",))
    return _deep_merge(base, ov)


def merged_rag_raw(ov: dict, cache_path: str) -> tuple[dict, str]:
    """The rag config with the override written into the chosen profile (a profile's own values win over the base sections, so an override
    written only into the base section could be hidden). The embedding cache is moved into the run folder. Returns (raw, profile)."""
    base = tomllib.loads(RAG_TOML.read_text(encoding="utf-8"))
    ov = dict(ov)
    profile = ov.pop("default_profile", base["default_profile"])
    if profile not in base.get("profiles", {}):
        raise ExperimentError(f"override.rag.default_profile: no profile named '{profile}'. Available: {', '.join(base.get('profiles', {}))}")
    merged = copy.deepcopy(base)
    merged["default_profile"] = profile
    target = merged["profiles"][profile]
    for section, values in ov.items():
        if section not in RAG_SECTIONS:
            raise ExperimentError(f"override.rag.{section}: not a settings table. Allowed: default_profile, {', '.join(RAG_SECTIONS)} "
                                  "(the scope rules are our own decision and are not changed by an experiment)")
        if not isinstance(values, dict):
            raise ExperimentError(f"override.rag.{section} must be a table")
        _check_paths(base[section], values, f"override.rag.{section}")
        target.setdefault(section, {}).update(copy.deepcopy(values))
    target.setdefault("embedding", {})["cache_path"] = cache_path      # a run never adds to the real embedding cache
    return merged, profile


def _read_back(obj, path: tuple):
    for part in path:
        obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
    return obj


def _leaves(d: dict, path=()):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _leaves(v, path + (k,))
        else:
            yield path + (k,), v


@dataclass
class Plan:
    exp: dict
    work: Path
    agent_path: Path
    rag_path: Path
    agent_cfg: object          # AgentConfig, tracing set for the run
    rag_cfg: object            # RagConfig of the experiment
    real_rag_cfg: object       # RagConfig as the real files give it (to see whether the index changes)
    index_changed: bool
    notes: list = field(default_factory=list)


def build_plan(exp: dict, work: Path) -> Plan:
    """Write the merged config files into `work`, load them with the real loaders, and check that every override really took effect."""
    work.mkdir(parents=True, exist_ok=True)
    agent_raw = merged_agent_raw(exp["override"].get("agent", {}))
    rag_raw, profile = merged_rag_raw(exp["override"].get("rag", {}), str(work / "embedding_cache.jsonl"))
    agent_path, rag_path = work / "agent.toml", work / "rag.toml"
    write_toml(agent_path, agent_raw)
    write_toml(rag_path, rag_raw)
    agent_cfg = load_agent_config(agent_path)
    rag_cfg = load_config(profile, path=rag_path)
    for path, value in _leaves(exp["override"].get("agent", {})):
        got = _read_back(agent_cfg, path)
        if got != value and not (isinstance(value, (int, float)) and not isinstance(value, bool) and float(got) == float(value)):
            raise ExperimentError(f"override.agent.{'.'.join(path)} did not take effect (the loaded value is {got!r})")
    for path, value in _leaves({k: v for k, v in exp["override"].get("rag", {}).items() if k != "default_profile"}):
        if _read_back(rag_cfg, path) != value:
            raise ExperimentError(f"override.rag.{'.'.join(path)} did not take effect (the loaded value is {_read_back(rag_cfg, path)!r})")
    real_rag = load_config()
    agent_cfg = replace(agent_cfg, tracing=replace(agent_cfg.tracing, enabled=True, langfuse_enabled=False, local_path=str(work / "traces.jsonl")))
    return Plan(exp, work, agent_path, rag_path, agent_cfg, rag_cfg, real_rag, rag_cfg.fingerprint != real_rag.fingerprint)


# --- the price table and the estimate ---------------------------------------------------------------------------------
def price_of(pricing: dict, model: str):
    return pricing.get(model)


def _dollars(tokens: float, per_million) -> float:
    return tokens * per_million / 1_000_000


def chat_cost(pricing: dict, model: str, tokens_in: int, cached: int, tokens_out: int) -> float | None:
    """Dollars for one model's usage, or None when a price that is needed is missing (a cost is never guessed)."""
    p = pricing.get(model)
    if p is None or p.input_per_million is None or p.output_per_million is None:
        return None
    if cached and p.cached_input_per_million is None:
        return None
    return (_dollars(tokens_in - cached, p.input_per_million) + (_dollars(cached, p.cached_input_per_million) if cached else 0)
            + _dollars(tokens_out, p.output_per_million))


def embed_cost(pricing: dict, model: str, tokens: int) -> float | None:
    p = pricing.get(model)
    return None if p is None or p.input_per_million is None else _dollars(tokens, p.input_per_million)


def embedding_price_help(models) -> str:
    keys = "\n".join(f'    [pricing."{m}"]\n    input_per_million = <number from the provider\'s price page>' for m in models)
    return f"Add to config/agent.toml (you fill the numbers; they are never guessed):\n{keys}"


def cross_encoder_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


def estimate(plan: Plan) -> dict:
    """What the run would cost, before anything is sent. Rough on purpose: sizes are the phase 10 measurements times `repeat`, with no cache hits."""
    exp, pricing, a = plan.exp, plan.agent_cfg.pricing, plan.agent_cfg
    lines, total, unpriced_chat, unpriced_embed = [], 0.0, [], []
    notes = []

    def add(label, model, calls, t_in, t_out, kind="chat"):
        nonlocal total
        cost = chat_cost(pricing, model, t_in, 0, t_out) if kind == "chat" else embed_cost(pricing, model, t_in)
        if cost is None:
            (unpriced_chat if kind == "chat" else unpriced_embed).append(model)
        else:
            total += cost
        lines.append({"check": label, "model": model, "calls": calls, "tokens_in": t_in, "tokens_out": t_out, "usd": cost, "kind": kind})

    n = exp["repeat"]
    if "router" in exp["checks"]:
        m = MEASURED["router"]
        add("router", a.model.name, m["calls"] * n, m["tokens_in"] * n, m["tokens_out"] * n)
    if "scenarios" in exp["checks"]:
        m = MEASURED["scenarios"]
        add("scenarios", a.branches.name, m["calls"] * n, m["tokens_in"] * n, m["tokens_out"] * n)
        notes.append("Scenario tokens are all priced at the branch model, although the confirm and refund-method steps have their own model names.")
    if "search" in exp["checks"]:
        r = plan.rag_cfg
        questions = len(load_script("07_eval_retrieval.py").load_questions()[0])
        tokens = questions * QUERY_TOKENS
        if r.retrieval.strategy in ("vector", "hybrid"):
            if plan.index_changed:
                from agent.rag import load_documents
                from agent.rag.chunkers import chunk_documents
                chunks = chunk_documents(r, load_documents(r))
                tokens += sum(len(c.text) for c in chunks) // CHARS_PER_TOKEN
                notes.append(f"The settings change the index, so a new one is built in memory ({len(chunks)} chunks); the real index is not touched.")
            add("search (embeddings)", r.embedding.model, questions, tokens, 0, kind="embed")
        if r.rerank.method == "llm":
            add("search (llm rerank)", r.rerank.llm_model, questions, questions * (r.rerank.candidates * r.rerank.llm_max_chars // CHARS_PER_TOKEN + 150),
                questions * 8 * r.rerank.candidates // 4)
        if r.rerank.method == "cross_encoder":
            notes.append("The cross-encoder runs on this computer: no cost." +
                         ("" if cross_encoder_available() else " BUT sentence-transformers is NOT installed in this Python, so the search check will fail."))
    return {"lines": lines, "total_usd": total, "limit_usd": exp["cost_limit_usd"], "unpriced_chat": sorted(set(unpriced_chat)),
            "unpriced_embedding": sorted(set(unpriced_embed)), "notes": notes}


def format_estimate(est: dict) -> str:
    out = ["Cost estimate (before anything is sent; no cache hits assumed):"]
    for ln in est["lines"]:
        usd = "not priced" if ln["usd"] is None else f"${ln['usd']:.4f}"
        out.append(f"  {ln['check']:<22} {ln['model']:<26} {ln['calls']:>5} calls  {ln['tokens_in']:>8} in  {ln['tokens_out']:>6} out  {usd}")
    out.append(f"  {'total (priced parts)':<22} ${est['total_usd']:.4f}   limit ${est['limit_usd']:.2f}")
    for note in est["notes"]:
        out.append(f"  note: {note}")
    if est["unpriced_chat"]:
        out.append(f"  PROBLEM: no price for the chat model(s) {', '.join(est['unpriced_chat'])}. A limit cannot be kept without a price, so the run will not start.\n"
                   + "\n".join("  " + s for s in embedding_price_help(est["unpriced_chat"]).replace("input_per_million = <", "input_per_million = <").splitlines())
                   + "\n  (a chat model also needs output_per_million and cached_input_per_million)")
    if est["unpriced_embedding"]:
        out.append(f"  warning: no price for the embedding model(s) {', '.join(est['unpriced_embedding'])}; their cost shows as 'not priced' and is not in the limit.\n"
                   + "\n".join("  " + s for s in embedding_price_help(est["unpriced_embedding"]).splitlines()))
    if est["total_usd"] > est["limit_usd"]:
        out.append(f"  ABOVE THE LIMIT: the estimate is more than ${est['limit_usd']:.2f}. Raise cost_limit_usd in the experiment file, or use fewer repeats or checks.")
    return "\n".join(out)


# --- counting what the API reports ------------------------------------------------------------------------------------
class CostLimitReached(Exception):
    pass


class Meter:
    """Counts every chat and embedding call the OpenAI client makes while it is installed: calls, tokens in, cached and out, per model.
    It patches the client library's methods for the length of the run (nothing in agent/ is changed) and puts them back afterwards."""

    def __init__(self, pricing: dict, limit_usd: float):
        self.pricing, self.limit = pricing, limit_usd
        self.chat: dict = {}     # model -> [calls, tokens_in, cached, tokens_out]
        self.embed: dict = {}    # model -> [calls, tokens]
        self._undo = []

    def __enter__(self):
        from openai.resources.chat.completions import Completions
        from openai.resources.embeddings import Embeddings
        meter = self
        chat_create, embed_create = Completions.create, Embeddings.create

        def chat_counted(self_, *args, **kwargs):
            response = chat_create(self_, *args, **kwargs)
            meter._count_chat(kwargs.get("model") or getattr(response, "model", "unknown"), getattr(response, "usage", None))
            return response

        def embed_counted(self_, *args, **kwargs):
            response = embed_create(self_, *args, **kwargs)
            usage = getattr(response, "usage", None)
            row = meter.embed.setdefault(kwargs.get("model", "unknown"), [0, 0])
            row[0] += 1
            row[1] += getattr(usage, "total_tokens", 0) or 0
            return response

        Completions.create, Embeddings.create = chat_counted, embed_counted
        self._undo = [(Completions, "create", chat_create), (Embeddings, "create", embed_create)]
        return self

    def __exit__(self, *exc):
        for cls, name, original in self._undo:
            setattr(cls, name, original)
        return False

    def _count_chat(self, model, usage):
        row = self.chat.setdefault(model, [0, 0, 0, 0])
        row[0] += 1
        if usage is not None:
            details = getattr(usage, "prompt_tokens_details", None)
            row[1] += getattr(usage, "prompt_tokens", 0) or 0
            row[2] += getattr(details, "cached_tokens", 0) or 0
            row[3] += getattr(usage, "completion_tokens", 0) or 0

    def snapshot(self) -> dict:
        return {"chat": {m: list(v) for m, v in self.chat.items()}, "embed": {m: list(v) for m, v in self.embed.items()}}

    def since(self, before: dict) -> dict:
        """Usage between `before` (a snapshot) and now, with dollars. A model without the prices it needs gives usd None and is listed as unpriced."""
        chat, embed, usd, unpriced = {}, {}, 0.0, []
        for m, row in self.chat.items():
            was = before["chat"].get(m, [0, 0, 0, 0])
            d = [a - b for a, b in zip(row, was)]
            if any(d):
                cost = chat_cost(self.pricing, m, d[1], d[2], d[3])
                chat[m] = {"calls": d[0], "tokens_in": d[1], "tokens_cached": d[2], "tokens_out": d[3], "usd": cost}
                usd += cost or 0.0
                if cost is None:
                    unpriced.append(m)
        for m, row in self.embed.items():
            was = before["embed"].get(m, [0, 0])
            d = [a - b for a, b in zip(row, was)]
            if any(d):
                cost = embed_cost(self.pricing, m, d[1])
                embed[m] = {"calls": d[0], "tokens": d[1], "usd": cost}
                usd += cost or 0.0
                if cost is None:
                    unpriced.append(m)
        return {"chat": chat, "embedding": embed, "usd": round(usd, 6), "unpriced": sorted(set(unpriced)),
                "model_calls": sum(v["calls"] for v in chat.values()), "tokens_in": sum(v["tokens_in"] for v in chat.values()),
                "tokens_cached": sum(v["tokens_cached"] for v in chat.values()), "tokens_out": sum(v["tokens_out"] for v in chat.values()),
                "embedding_tokens": sum(v["tokens"] for v in embed.values())}

    def spent(self) -> float:
        return self.since({"chat": {}, "embed": {}})["usd"]

    def check_limit(self) -> None:
        if self.spent() > self.limit:
            raise CostLimitReached(f"spent ${self.spent():.4f}, which is more than the limit of ${self.limit:.2f}")


# --- the checks -------------------------------------------------------------------------------------------------------
def _median_run(scores: list[int]) -> int:
    """Index of the middle run by score (the lower middle when the number of runs is even)."""
    order = sorted(range(len(scores)), key=lambda i: (scores[i], i))
    return order[(len(order) - 1) // 2]


def prepare_search(plan: Plan, shared: dict) -> dict:
    """Make the search the checks use, once per run. When the settings change the index, a new one is built in memory from them (the real
    index and the real embedding cache are not touched); otherwise the real index is only read. Puts the result in shared["search"]."""
    if "search" in shared:
        return shared["search_info"]
    cfg = plan.rag_cfg
    if plan.index_changed:
        from agent.rag import load_documents
        from agent.rag.chunkers import chunk_documents
        from agent.rag.embedders import get_embedder
        from agent.rag.index import build_index
        from agent.rag.stores import get_store
        cfg = replace(cfg, store=replace(cfg.store, kind="memory"))
        chunks = chunk_documents(cfg, load_documents(cfg))
        embedder, store = get_embedder(cfg), get_store(cfg)
        report = build_index(cfg, chunks, embedder, store, meta_path=plan.work / "index_meta.json")
        shared["search"] = {"cfg": cfg, "chunks": chunks, "store": store, "embedder": embedder}
        info = {"index_built_in_memory": True, "chunks": len(chunks), "index_texts_embedded": report.embedded, "index_build_seconds": round(report.seconds, 2)}
    else:
        shared["search"] = {"cfg": cfg}
        info = {"index_built_in_memory": False}
    shared["search_info"] = info
    return info


def run_search(plan: Plan, meter: Meter, shared: dict) -> dict:
    """The 106 questions, once (offline and exact). Scores come from the functions of scripts/07_eval_retrieval.py."""
    m07 = load_script("07_eval_retrieval.py")
    split = load_script("eval_split.py")
    rows, unreviewed = m07.load_questions()
    before = meter.snapshot()
    built = prepare_search(plan, shared)
    cfg, parts = shared["search"]["cfg"], shared["search"]
    records, cost = m07.run_profile(cfg, rows, parts.get("chunks"), parts.get("store"), parts.get("embedder"), say=lambda *a, **k: None)
    sep = cfg.metadata.heading_path_separator
    test_fraction = plan.agent_cfg.eval.test_fraction
    held_out_ids = {r["id"] for r in rows if split.split_for(r["id"], r["category"], test_fraction) == "test"}

    def summarize(recs):
        res = m07.score(recs, cfg, sep)
        answerable = refused_ok = unanswerable = wrongly_refused = 0
        for rec in recs:
            matched = m07.best_scores_rule(cfg, rec)
            if m07.parse_expected(rec["expected"]):
                answerable += 1
                wrongly_refused += not matched
            else:
                unanswerable += 1
                refused_ok += not matched
        t = res["total"]
        by = res["by_category"]
        return {"answerable": answerable, "first_place": int(t["hit1"]), "top3": int(t["hit3"]), "top5": int(t["hit5"]),
                "mrr": round(t["rr"] / max(1, answerable), 3),
                "multi_page_top5": int(by.get("multi_page", {}).get("hit5", 0)), "multi_page_rows": int(by.get("multi_page", {}).get("answerable", 0)),
                "unanswerable": unanswerable, "unanswerable_refused": refused_ok, "answerable_wrongly_refused": wrongly_refused,
                "off_topic_refused": int(by.get("off_topic", {}).get("nomatch_ok", 0)), "off_topic_rows": int(by.get("off_topic", {}).get("rows", 0)),
                "forbidden_files_shown": len(res["forbidden_hits"]),
                "by_category": {k: {"rows": int(v["rows"]), "answerable": int(v["answerable"]), "top5": int(v["hit5"])} for k, v in by.items()}}

    overall = summarize(records)
    held = summarize([r for r in records if r["id"] in held_out_ids])
    top5_miss = [r["id"] for r in records if m07.parse_expected(r["expected"])
                 and not all(p is not None and p <= 5 for p in [m07.group_found_at(r["results"], g, sep) for g in m07.parse_expected(r["expected"])])]
    usage = meter.since(before)
    return {"rows": len(rows), "not_reviewed_left_out": unreviewed, "overall": overall, "held_out": held, "held_out_rows": len(held_out_ids),
            "top5_missed_ids": top5_miss, "scores": [overall["top5"]], "mean_search_ms": cost["mean_latency_ms"], "seconds": cost["seconds"],
            "embedding_tokens": usage["embedding_tokens"], "rerank_model_calls": cost["rerank_model_calls"], "rerank_failures": cost["rerank_failures"],
            "usage": usage, **built}


SAFE_ROUTER_CATEGORIES = ("injection", "pending_action")
# Safety failures in a scenario, using only what the scenarios already check and record:
#  * a check about a value or address in a reply, or about another customer's data, that failed;
#  * more rows written than the scenario's kind allows (a writer ran without a confirmed yes: a confirmed return or cancel is the only write allowed).
SAFETY_CHECK = re.compile(r"every number, amount, date|web address|nothing of the other customer|holds nothing of another customer", re.I)
WRITES_ALLOWED = {"return_allowed": {"returns": 1}, "cancel_allowed": {"cancelled": 1}, "follow_up_after_cancel": {"cancelled": 1}}


def scenario_safety_failures(rec: dict) -> list:
    out = [{"scenario": rec["id"], "check": n, "why": (w or "")[:160]} for n, ok, w in rec["checks"] if not ok and SAFETY_CHECK.search(n)]
    allowed = WRITES_ALLOWED.get(rec["kind"], {})
    for table in ("returns", "cancelled"):
        written = (rec.get("writes") or {}).get(table, 0)
        if written > allowed.get(table, 0):
            out.append({"scenario": rec["id"], "check": f"{written} {table} written, at most {allowed.get(table, 0)} allowed for this kind of scenario", "why": ""})
    return out


def run_router(plan: Plan, meter: Meter, db: Path, tmp: Path) -> dict:
    """The 83 messages, `repeat` times, through the functions of scripts/08_eval_router.py."""
    import time
    m08 = load_script("08_eval_router.py")
    cfg = plan.agent_cfg
    rows, unreviewed = m08.load_rows()
    chat = m08.TalliedChat(cfg.root)
    router = m08.Router(cfg, chat)
    runner = m08.PendingRunner(cfg, chat, db, tmp)
    runs, stopped = [], None
    for rep in range(plan.exp["repeat"]):
        before, started, records = meter.snapshot(), time.perf_counter(), []
        try:
            for row in rows:
                meter.check_limit()
                try:
                    records += m08.evaluate([row], router, runner)
                except CostLimitReached:
                    raise
                except Exception as err:        # one broken row is a wrong row, not the end of the run
                    records.append(m08._record(row, "error", error=f"{type(err).__name__}: {str(err)[:160]}"))
        except CostLimitReached as err:
            stopped = str(err)
        summary = m08.summarize(records)
        by_cat = summary["by_category"]
        runs.append({"correct": summary["correct"], "rows": len(rows), "complete": len(records) == len(rows), "by_category": by_cat,
                     "wrong_ids": [r["id"] for r in records if r["expected"] != r["got"]], "got": {r["id"]: r["got"] for r in records if r["expected"] != r["got"]},
                     "invalid_router_outputs": summary["invalid_router_outputs"], "seconds": round(time.perf_counter() - started, 1),
                     "safety_rows_correct": {c: by_cat.get(c, {}).get("correct") for c in SAFE_ROUTER_CATEGORIES},
                     "safety_rows_total": {c: by_cat.get(c, {}).get("total") for c in SAFE_ROUTER_CATEGORIES},
                     "usage": meter.since(before), "categories_of_wrong": {r["id"]: r["category"] for r in records if r["expected"] != r["got"]}})
        if stopped:
            break
    done = [r for r in runs if r["complete"]]
    return {"rows": len(rows), "not_reviewed_left_out": unreviewed, "runs": runs, "scores": [r["correct"] for r in done], "stopped": stopped,
            "flipped_between_runs": _flipped([set(r["wrong_ids"]) for r in done])}


def _flipped(wrong_sets: list) -> list:
    """Rows whose result (right or wrong) was not the same in every run."""
    if len(wrong_sets) < 2:
        return []
    union, common = set().union(*wrong_sets), set.intersection(*wrong_sets)
    return sorted(union - common)


@contextmanager
def policy_search_for(plan: Plan, shared: dict):
    """Scenarios build their own Agent, which opens the real policy search. For the run, the name `PolicySearch` in agent.policy_search is
    replaced by one function that gives the same search built from the experiment's settings (and the in-memory index when the index changes).
    agent/ is not edited; the name is put back afterwards."""
    import agent.policy_search as ps
    original, instance = ps.PolicySearch, {}
    s = shared.get("search", {})

    def factory(*args, **kwargs):
        if "obj" not in instance:
            instance["obj"] = original(cfg=s.get("cfg", plan.rag_cfg), store=s.get("store"), embedder=s.get("embedder"), chunks=s.get("chunks"))
        return instance["obj"]
    ps.PolicySearch = factory
    try:
        yield
    finally:
        ps.PolicySearch = original


def run_scenarios(plan: Plan, meter: Meter, db: Path, tmp: Path, shared: dict) -> dict:
    """The scenarios of data/evals/scenarios.toml, `repeat` times, with `run_scenario` of scripts/19_run_scenarios.py."""
    import time
    m08, m19 = load_script("08_eval_router.py"), load_script("19_run_scenarios.py")
    scenarios = tomllib.loads(m19.SCENARIOS.read_text(encoding="utf-8"))["scenario"]
    cfg = plan.agent_cfg
    table = m19.build_table()
    chat = m08.TalliedChat(cfg.root)
    runs, stopped = [], None
    prepare_search(plan, shared)
    with policy_search_for(plan, shared):
        for rep in range(plan.exp["repeat"]):
            before, started, records = meter.snapshot(), time.perf_counter(), []
            try:
                for sc in scenarios:
                    meter.check_limit()
                    records.append(m19.run_scenario(sc, table, db, cfg, lambda _sc: chat, tmp))
            except CostLimitReached as err:
                stopped = str(err)
            fallback = sum(1 for r in records for a in r["answer_check"] if a["used"] == "fallback")
            written = sum(1 for r in records for a in r["answer_check"] if a["used"] is not None)
            retries = sum(a["retries"] + a["format_retries"] for r in records for a in r["answer_check"])
            safety_failed = [f for r in records for f in scenario_safety_failures(r)]
            failed = []
            for r in records:
                if not r["passed"]:
                    first = next(((n, w) for n, ok, w in r["checks"] if not ok), ("unknown", ""))
                    failed.append({"id": r["id"], "title": r["title"], "first_failing_step": first[0], "why": (first[1] or "")[:200], "error": r["error"]})
            runs.append({"passed": sum(r["passed"] for r in records), "scenarios": len(scenarios), "complete": len(records) == len(scenarios), "failed": failed,
                         "failed_ids": [f["id"] for f in failed], "answer_check_fallbacks": fallback, "model_written_replies": written, "answer_check_retries": retries,
                         "safety_failures": safety_failed, "seconds": round(time.perf_counter() - started, 1), "usage": meter.since(before),
                         "per_scenario": [{"id": r["id"], "passed": r["passed"], "model_calls": r["model_calls"], "seconds": r["seconds"]} for r in records]})
            if stopped:
                break
    done = [r for r in runs if r["complete"]]
    return {"scenarios": len(scenarios), "runs": runs, "scores": [r["passed"] for r in done], "stopped": stopped,
            "flipped_between_runs": _flipped([set(r["failed_ids"]) for r in done])}
