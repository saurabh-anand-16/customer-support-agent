"""
tracing.py - the local trace file (phase 6, step 1) and the reader (step 2).

One JSON line per turn is appended to a file (default data/traces/traces.jsonl, in .gitignore). The record is built from the
result of `Agent.respond`; the agent's own trace is only read, never changed, and nothing here is shown to a model.

The rules, each tested:
  * Tracing never changes a reply and never breaks a chat. `Tracer.record_turn` catches every error, logs each kind of error once,
    and returns.
  * One turn is one `write` call under a lock, so two turns that finish together write two whole lines.
  * The file keeps the newest `max_lines` lines. The oldest are dropped in a batch (when the file passes max_lines plus a tenth)
    and a warning is logged.
  * The record holds no API key (a key-like text is replaced), no `staff_approved`, no `confirmed`, and no
    customer id except the one top-level field `customer_id`.
  * `capture_text = false` replaces the customer's message and the reply with "[not captured]" and their lengths. The model's
    own words (raw outputs, reasons) and the search query are then left out too, because they can repeat the message.
  * A broken or half-written line is skipped and counted by the reader.

The file is made for one process. The lock is a thread lock; two processes writing the same file are not coordinated.
"""
import dataclasses
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .llm import log_capture_failure, safely, short_error

log = logging.getLogger("agent.tracing")

SCHEMA_VERSION = 2      # 2 (phase 6c) adds model calls with tokens and cost, tool timing, the timeline, search and answer-check detail, versions, errors
NOT_CAPTURED = "[not captured]"
WRITER_TOOLS = ("create_return", "cancel_order")
RETRIEVAL_TOOLS = ("search_policy",)
# The key names that are never written, at any depth, are listed in [tracing].hidden_keys (the customer id is a top-level field set by code).
# Texts that look like a key. They are replaced wherever they appear in a string.
KEY_PATTERN = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|pk-lf-[A-Za-z0-9_\-]+|sk-lf-[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]{8,})")
REDACTED = "[removed key]"


# -- cleaning ---------------------------------------------------------------------------------------------------
def clean(value, hidden=()):
    """A copy of `value` with the `hidden` key names dropped and key-like text replaced, at any depth. Never changes `value`."""
    if isinstance(value, dict):
        return {str(k): clean(v, hidden) for k, v in value.items() if k not in hidden}
    if isinstance(value, (list, tuple)):
        return [clean(v, hidden) for v in value]
    if isinstance(value, str):
        return KEY_PATTERN.sub(REDACTED, value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return clean(str(value), hidden)


def short(value, limit: int) -> str:
    """`value` as short text (JSON for structures), cut to `limit` characters."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    return text if len(text) <= limit else text[:max(limit - 3, 0)] + "..."


# -- the record -------------------------------------------------------------------------------------------------
def _step(kind, name, input=None, output=None, status="ok", latency_ms=None, **extra) -> dict:
    return {"kind": kind, "name": name, "input": input, "output": output, "status": status, "latency_ms": latency_ms, **extra}


def _tool_status(call: dict) -> str:
    if call.get("refused"):
        return "refused"
    out = call.get("output")
    return "failed" if isinstance(out, dict) and out.get("ok") is False else "ok"


def _find_escalation(trace: dict) -> dict | None:
    """The review-queue record of the turn, from the branch notes or from the confirm step."""
    for holder in ((trace.get("branch") or {}).get("notes"), trace.get("confirm")):
        sent = holder.get("escalation") if isinstance(holder, dict) else None
        if isinstance(sent, dict) and ("reference" in sent or "queued" in sent):
            return sent
    return None


def build_steps(trace: dict, evidence: dict, settings, model_names: dict) -> list:
    """
    The ordered steps of a turn, from the pieces the agent's trace already has: router, confirm label, branch model calls,
    tool calls (a writer is kind "write", a policy search is "retrieval"), the review item, and the guardrail checks.
    Only the router, the model calls and the confirm label have timing. The agent's trace keeps model calls and tool calls in
    two lists, so their true interleaving is not known: model calls come first, then tool calls.
    """
    n, text_on, hidden = settings.step_chars, settings.capture_text, frozenset(settings.hidden_keys)
    steps = []
    router = trace.get("router") or {}
    if router and router.get("called") is not False:           # a turn that went to the confirm step never called the router
        said = f"{router.get('label') or router.get('route') or '?'}" + (f"/{router['kind']}" if router.get("kind") else "")
        if text_on and router.get("reason"):
            said += f": {router['reason']}"
        steps.append(_step("router", "router", None, short(said, n), "failed" if router.get("error") else "ok", router.get("latency_ms"),
                           model=model_names.get("router")))
    confirm = trace.get("confirm") or {}
    if confirm.get("model_called"):
        said = str(confirm.get("label"))
        if text_on and confirm.get("reason"):
            said += f": {confirm['reason']}"
        steps.append(_step("model_call", "confirm_label", None, short(said, n), "failed" if confirm.get("error") else "ok",
                           confirm.get("latency_ms"), model=model_names.get("confirm")))
    for call in ((trace.get("branch") or {}).get("model_calls") or []):
        raw = call.get("raw_output")
        steps.append(_step("model_call", str(call.get("purpose", "model")), None, f"{len(raw)} characters" if isinstance(raw, str) else None,
                           "ok" if raw is not None else "failed", call.get("latency_ms"), model=model_names.get("branch")))
    for call in (evidence.get("tool_calls") or []):
        name = str(call.get("tool"))
        kind = "write" if name in WRITER_TOOLS else "retrieval" if name in RETRIEVAL_TOOLS else "tool_call"
        given = call.get("input") or {}
        if kind == "retrieval" and not text_on:
            given = {k: (NOT_CAPTURED if k == "query" else v) for k, v in given.items()}      # the query is the customer's words
        steps.append(_step(kind, name, short(clean(given, hidden), n), short(clean(call.get("output"), hidden), n), _tool_status(call),
                           refused=call.get("refused")))
    sent = _find_escalation(trace)
    if sent is not None:
        steps.append(_step("review_item", str(sent.get("reference") or "not queued"), short(clean({"kind": sent.get("reason")}, hidden), n),
                           short(clean({"created": sent.get("created")}, hidden), n), "ok" if sent.get("queued") else "failed"))
    for item in (trace.get("checks") or []):
        status = item.get("status") or ("passed" if item.get("passed") else "failed")
        steps.append(_step("check", str(item.get("name")), None, short(clean(item.get("reason", ""), hidden), n), status))
    return clean(steps, hidden)


# -- phase 6c: the richer record ----------------------------------------------------------------------------------
# Everything below is built from what the TurnRecorder in agent/llm.py saw during the turn (`capture`) and from the agent's own trace.
# It is added to the record inside its own guard: if it fails, the old fields are still written and the record says so in `errors`.
MODEL_STEP_KEYS = {"router": ("router",), "confirm_label": ("confirm_label", "refund_method_label")}


def cost_of(call: dict, price) -> tuple:
    """(input cost, output cost, why not) in US dollars for one model call. Costs are None, with the reason, when a price or the usage is
    missing: a price is never guessed, and cached tokens with no cached price are not priced at the normal rate."""
    if price is None or price.input_per_million is None or price.output_per_million is None:
        return None, None, "no_price"
    n_in, n_out, cached = call.get("input_tokens"), call.get("output_tokens"), call.get("cached_tokens")
    if n_in is None or n_out is None:
        return None, None, "no_usage"
    cached = cached or 0
    if cached > n_in:
        return None, None, "bad_usage"
    if cached and price.cached_input_per_million is None:
        return None, None, "no_cached_price"
    cost_in = (n_in - cached) * price.input_per_million / 1e6 + cached * (price.cached_input_per_million or 0) / 1e6
    cost_out = n_out * price.output_per_million / 1e6
    return round(cost_in, 8), round(cost_out, 8), None


def _model_calls(capture: dict, pricing: dict) -> list:
    out = []
    for call in capture.get("model_calls") or []:
        cost_in, cost_out, why = cost_of(call, pricing.get(call.get("model_configured")))
        item = {k: v for k, v in call.items() if k != "model_configured"}
        item.update(cost_usd=None if why else round(cost_in + cost_out, 8), cost_input_usd=cost_in, cost_output_usd=cost_out, cost_missing=why)
        out.append(item)
    return out


def _match_steps(steps: list, model_calls: list, tool_calls: list) -> None:
    """Give each step that has a real counterpart its `seq`, `start_ms` and `duration_ms`. A step takes the first unused call of the same
    kind (model calls) or name (tools), in order. A step with no counterpart (a check, the review item, a writer) gets null."""
    used_model, used_tool = set(), set()
    for step in steps:
        found, duration = None, None
        if step.get("kind") in ("router", "model_call"):
            kinds = MODEL_STEP_KEYS.get(step.get("name"), (step.get("name"),))
            found = next((c for c in model_calls if c["seq"] not in used_model and c.get("kind") in kinds), None)
            if found:
                used_model.add(found["seq"])
                duration = found.get("latency_ms")
        elif step.get("kind") in ("tool_call", "retrieval"):
            found = next((c for c in tool_calls if c["seq"] not in used_tool and c.get("name") == step.get("name")), None)
            if found:
                used_tool.add(found["seq"])
                duration = found.get("duration_ms")
        step["seq"] = found["seq"] if found else None
        step["start_ms"] = found["start_ms"] if found else None
        step["duration_ms"] = duration


def _search_detail(capture: dict, trace: dict, settings) -> list:
    rewrite = (((trace.get("branch") or {}).get("notes") or {}).get("rewrite")) or {}
    out = []
    for i, found in enumerate(capture.get("searches") or []):
        item = dict(found)
        query = item.pop("query", None)
        item["query_chars"] = len(query) if isinstance(query, str) else None
        if i == 0 and rewrite.get("called"):
            item["rewritten"] = rewrite.get("original") != rewrite.get("query")
        if settings.capture_text:
            item["query"] = query
            if i == 0 and rewrite.get("called"):
                item["original_query"] = rewrite.get("original")
        out.append(item)
    return clean(out, ())


def _answer_check_detail(capture: dict, trace: dict, settings) -> dict | None:
    attempts = capture.get("answer_checks") or []
    notes = (((trace.get("branch") or {}).get("notes") or {}).get("answer_check")) or {}
    if not attempts and not notes:
        return None
    shown = []
    for a in attempts:
        item = {"attempt": a.get("attempt"), "passed": a.get("passed"), "problem_count": a.get("problem_count")}
        for kind in ("numbers", "dates", "files"):
            values = a.get(kind) or []
            item[f"{kind}_found"] = len(values)
            item[f"{kind}_unsupported"] = sum(1 for v in values if not v.get("supported"))
            if settings.capture_text:       # the values come from the reply, which capture_text = false does not keep
                item[kind] = values
        shown.append(item)
    return clean({"attempts": shown, "retried": any(str(a.get("attempt", "")).startswith("retry") for a in attempts) or bool(notes.get("retries")),
                  "retries": notes.get("retries", 0), "fallback_used": notes.get("used") == "fallback", "used": notes.get("used")}, ())


def _errors(capture: dict, trace: dict, evidence: dict) -> list:
    """Type and a short, fixed-shape message per error. Never the text of a message, a model output, a header or a key."""
    errors = [dict(e) for e in capture.get("errors") or []]
    for where, holder in (("router", trace.get("router")), ("confirm", trace.get("confirm")), ("branch", trace.get("branch"))):
        text = holder.get("error") if isinstance(holder, dict) else None
        if text and not str(text).startswith("model call failed"):       # a failed model call is already in `errors`, with its type
            errors.append({"where": where, "type": "error", "message": short_error(text)})
    for call in evidence.get("tool_calls") or []:
        out = call.get("output")
        if isinstance(out, dict) and out.get("ok") is False and not call.get("refused"):
            errors.append({"where": f"tool:{call.get('tool')}", "type": str(out.get("error_code") or "error"), "message": "the tool call did not succeed"})
    return clean(errors, ())


def build_detail(settings, *, record: dict, capture: dict | None, trace: dict, evidence: dict, pricing: dict | None, versions: dict | None) -> dict:
    """The phase 6c fields for one turn. Also gives each step in record["steps"] its seq, start_ms and duration_ms."""
    capture = capture or {}
    model_calls = _model_calls(capture, pricing or {})
    tool_calls = [dict(c) for c in capture.get("tool_calls") or []]
    _match_steps(record["steps"], model_calls, tool_calls)
    timeline = sorted([{"seq": c["seq"], "type": "model_call", "name": c.get("kind"), "start_ms": c.get("start_ms"), "duration_ms": c.get("latency_ms"),
                        "status": c.get("status")} for c in model_calls] +
                      [{"seq": c["seq"], "type": "tool_call", "name": c.get("name"), "start_ms": c.get("start_ms"), "duration_ms": c.get("duration_ms"),
                        "status": c.get("status")} for c in tool_calls], key=lambda x: x["seq"])
    costs = [c["cost_usd"] for c in model_calls]
    complete = all(v is not None for v in costs)
    tokens_in, tokens_out = [c["input_tokens"] for c in model_calls], [c["output_tokens"] for c in model_calls]
    versions = dict(versions or {})
    versions["index_fingerprint"] = record.get("index_fingerprint")
    return {
        "model_calls": model_calls, "tool_calls": tool_calls, "timeline": timeline,
        "model_call_count": len(model_calls), "tool_call_count": len(tool_calls),
        "retry_count": sum(1 for c in model_calls if c.get("kind") == "answer_retry"),
        "total_input_tokens": sum(t for t in tokens_in if t is not None), "total_output_tokens": sum(t for t in tokens_out if t is not None),
        "usage_complete": all(t is not None for t in tokens_in + tokens_out),
        "total_cost_usd": round(sum(costs), 8) if complete else None, "cost_complete": complete,
        "unpriced_calls": sum(1 for v in costs if v is None),
        "search": _search_detail(capture, trace, settings), "answer_check": _answer_check_detail(capture, trace, settings),
        "versions": clean(versions, ()), "errors": _errors(capture, trace, evidence)}


def empty_detail(error_type: str) -> dict:
    """The phase 6c fields when building them failed: the same keys, nothing in them, and one error that says why."""
    return {"model_calls": [], "tool_calls": [], "timeline": [], "model_call_count": 0, "tool_call_count": 0, "retry_count": 0,
            "total_input_tokens": 0, "total_output_tokens": 0, "usage_complete": False, "total_cost_usd": None, "cost_complete": False,
            "unpriced_calls": 0, "search": [], "answer_check": None, "versions": {},
            "errors": [{"where": "trace_detail", "type": error_type, "message": "the extra trace detail could not be built"}]}


# -- versions -------------------------------------------------------------------------------------------------------
def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:12]


def git_commit(root: Path) -> str:
    """The short commit of the code, or "unknown" when the folder is not a git repository or git cannot be run."""
    try:
        done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=5)
        out = done.stdout.strip()
        return out if done.returncode == 0 and re.fullmatch(r"[0-9a-f]{4,40}", out) else "unknown"
    except Exception:
        return "unknown"


def compute_versions(cfg, root: Path) -> dict:
    """Short commit, a hash of the resolved config, and a hash of the prompt texts. The config holds setting names and values and no secret
    (the API key stays in .env and is never loaded into it). The [tracing] section is left out of the hash: it does not change what the agent does."""
    data = dataclasses.asdict(cfg)
    for key in ("root", "tracing"):
        data.pop(key, None)
    prompts = {"router": cfg.router.system_prompt, "router_labels": cfg.router.labels, "router_kinds": cfg.router.kinds, "scope": cfg.scope.statement,
               "branches": cfg.branches.prompts, "confirm": cfg.confirm.prompt, "refund_method": cfg.refund_method.prompt,
               "answer_retry": cfg.answer_check.retry_instruction}
    return {"git_commit": git_commit(root), "config_hash": _digest(data), "prompt_hash": _digest(prompts)}


def build_record(settings, *, result: dict, session_id: str, customer_id: str, message: str, duration_ms: float,
                 model_names: dict | None = None, turn_id: str | None = None, timestamp: str | None = None,
                 capture: dict | None = None, pricing: dict | None = None, versions: dict | None = None) -> dict:
    """The turn record for one `Agent.respond` result. Pure: reads `result`, changes nothing. `capture` is the TurnRecorder's snapshot (phase 6c)."""
    hidden = frozenset(settings.hidden_keys)
    trace = result.get("trace") or {}
    evidence = result.get("evidence") or {}
    reply = result.get("reply") if isinstance(result.get("reply"), str) else ""
    message = message if isinstance(message, str) else ""
    fingerprint = next((c["output"]["index_fingerprint"] for c in evidence.get("tool_calls") or []
                        if c.get("tool") in RETRIEVAL_TOOLS and isinstance(c.get("output"), dict) and c["output"].get("index_fingerprint")), None)
    passages = [{k: p.get(k) for k in ("number", "citation", "source_file", "heading_path", "cited")} for p in evidence.get("policy_passages") or []]
    sent = _find_escalation(trace)
    record = {
        "schema_version": SCHEMA_VERSION,
        "turn_id": turn_id or uuid.uuid4().hex,
        "session_id": session_id,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "customer_id": customer_id,
        "capture_text": settings.capture_text,
        "message": clean(message, hidden) if settings.capture_text else NOT_CAPTURED,
        "message_chars": len(message),
        "reply": clean(reply, hidden) if settings.capture_text else NOT_CAPTURED,
        "reply_chars": len(reply),
        "route": {"router_label": result.get("route"), "kind": result.get("kind"), "branch": (trace.get("branch") or {}).get("name")},
        "steps": build_steps(trace, evidence, settings, model_names or {}),
        "passages": clean(passages, hidden),
        "index_fingerprint": fingerprint,
        "checks": clean(trace.get("checks") or [], hidden),
        "pending_action": clean(result.get("pending_action"), hidden),
        "review_reference": sent.get("reference") if sent else None,
        "duration_ms": round(float(duration_ms), 1),
    }
    try:                                  # phase 6c: the extra detail has its own guard, so a failure here never costs the rest of the record
        record.update(build_detail(settings, record=record, capture=capture, trace=trace, evidence=evidence, pricing=pricing, versions=versions))
    except Exception as err:
        log_capture_failure("trace detail", err)
        record.update(empty_detail(type(err).__name__))
    return record


# -- the writer -------------------------------------------------------------------------------------------------
_LOCKS: dict = {}
_COUNTS: dict = {}
_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(str(path), threading.Lock())


def resolve_path(settings, root: Path) -> Path:
    p = Path(settings.local_path)
    return p if p.is_absolute() else Path(root) / p


def _count_lines(path: Path) -> int:
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0


def append_line(path: Path, record: dict, max_lines: int) -> None:
    """Append one record as one line (one write call, under a lock). Trims the oldest lines when the file is too long."""
    data = (json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str) + "\n").encode("utf-8")
    path = Path(path)
    with _lock_for(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        key = str(path)
        if key not in _COUNTS:
            _COUNTS[key] = _count_lines(path)
        with open(path, "ab") as f:
            f.write(data)
        _COUNTS[key] += 1
        if _COUNTS[key] > max_lines + max(1, max_lines // 10):
            _trim(path, max_lines)


def _trim(path: Path, max_lines: int) -> None:
    with open(path, "rb") as f:
        lines = f.readlines()
    dropped = max(len(lines) - max_lines, 0)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.writelines(lines[-max_lines:])
    os.replace(tmp, path)
    _COUNTS[str(path)] = min(len(lines), max_lines)
    log.warning("trace file %s passed its limit; dropped the %d oldest line(s) and kept the newest %d", path.name, dropped, max_lines)


class Tracer:
    def __init__(self, settings, root: Path, model_names: dict | None = None, exporter=None, pricing: dict | None = None, versions_fn=None):
        """`exporter` (phase 6b, agent/langfuse_export.py) gets a copy of each record; it is None unless Langfuse is switched on.
        `pricing` (phase 6c) is {model: ModelPrice}; `versions_fn` is called once, on the first turn, and gives {"git_commit", "config_hash", "prompt_hash"}."""
        self.settings, self.root, self.model_names = settings, Path(root), dict(model_names or {})
        self.exporter = exporter
        self.pricing = dict(pricing or {})
        self._versions_fn, self._versions = versions_fn, None
        self._logged: set = set()

    @property
    def wants_capture(self) -> bool:
        """True when a turn's capture will be used: the file is on, or the Langfuse copy is. Otherwise the agent skips the recorder."""
        return bool(self.settings.enabled or self.exporter is not None)

    def versions(self) -> dict:
        """The versions of this run, worked out once (git is asked once). An error gives an empty dict and is logged once."""
        if self._versions is None:
            self._versions = (safely("versions", self._versions_fn) if self._versions_fn else None) or {}
        return self._versions

    @property
    def path(self) -> Path:
        return resolve_path(self.settings, self.root)

    def _log_once(self, err: BaseException) -> None:
        key = type(err).__name__
        if key not in self._logged:
            self._logged.add(key)
            log.warning("tracing failed (%s); the turn is not affected. Further errors of this kind are not logged.", key)

    def record_turn(self, *, result: dict, session_id: str, customer_id: str, message: str, duration_ms: float, capture: dict | None = None) -> str | None:
        """Write the record of one turn. Never raises and never changes `result`. Returns the turn id when the record was written (or handed to
        the Langfuse copy), else None (phase 9: the agent puts it in its result so a page can link to the turn)."""
        if not self.settings.enabled and self.exporter is None:
            return None
        try:
            record = build_record(self.settings, result=result, session_id=session_id, customer_id=customer_id, message=message,
                                  duration_ms=duration_ms, model_names=self.model_names, capture=capture, pricing=self.pricing,
                                  versions=self.versions())
            if self.settings.enabled:
                append_line(self.path, record, self.settings.max_lines)
            if self.exporter is not None:
                self.exporter.submit(record)               # queued for a background thread; never raises
            return record["turn_id"]
        except BaseException as err:                       # tracing must never break a chat (KeyboardInterrupt excepted below)
            if isinstance(err, (KeyboardInterrupt, SystemExit)):
                raise
            self._log_once(err)
            return None


# -- the reader (step 2) ----------------------------------------------------------------------------------------
@dataclass
class TurnPage:
    turns: list = field(default_factory=list)     # newest first
    total: int = 0                                # matching turns before limit and offset
    skipped: int = 0                              # lines that were broken, half written or not a turn record


def _read_all(path: Path) -> tuple[list, int]:
    """All readable records in file order, and the number of lines that were skipped."""
    records, skipped = [], 0
    try:
        with open(path, "rb") as f:
            raw_lines = f.read().split(b"\n")
    except FileNotFoundError:
        return [], 0
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            skipped += 1
            continue
        if isinstance(rec, dict) and isinstance(rec.get("turn_id"), str) and isinstance(rec.get("route"), dict):
            records.append(rec)
        else:
            skipped += 1
    return records, skipped


def _matches(rec: dict, session_id, customer_id, route, has_failed_check) -> bool:
    if session_id is not None and rec.get("session_id") != session_id:
        return False
    if customer_id is not None and rec.get("customer_id") != customer_id:
        return False
    if route is not None and route not in ((rec.get("route") or {}).get("router_label"), (rec.get("route") or {}).get("branch")):
        return False
    if has_failed_check is not None:
        failed = any(isinstance(c, dict) and not c.get("passed") for c in rec.get("checks") or [])
        if failed != bool(has_failed_check):
            return False
    return True


def list_turns(path: str | Path, limit: int = 20, offset: int = 0, *, session_id: str | None = None, customer_id: str | None = None,
               route: str | None = None, has_failed_check: bool | None = None) -> TurnPage:
    """Turns newest first. `route` matches the router label or the branch name. `has_failed_check=True` keeps turns with a check that
    failed (a blocked-by-design check passed, so it does not count); False keeps turns with none."""
    records, skipped = _read_all(Path(path))
    wanted = [r for r in reversed(records) if _matches(r, session_id, customer_id, route, has_failed_check)]
    start = max(offset, 0)
    return TurnPage(turns=wanted[start:start + max(limit, 0)], total=len(wanted), skipped=skipped)


def get_turn(path: str | Path, turn_id: str) -> dict | None:
    """One turn record by id, or None."""
    records, _ = _read_all(Path(path))
    return next((r for r in reversed(records) if r.get("turn_id") == turn_id), None)
