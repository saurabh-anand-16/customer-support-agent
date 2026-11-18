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
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("agent.tracing")

SCHEMA_VERSION = 1
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


def build_record(settings, *, result: dict, session_id: str, customer_id: str, message: str, duration_ms: float,
                 model_names: dict | None = None, turn_id: str | None = None, timestamp: str | None = None) -> dict:
    """The turn record for one `Agent.respond` result. Pure: reads `result`, changes nothing."""
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
    def __init__(self, settings, root: Path, model_names: dict | None = None, exporter=None):
        """`exporter` (phase 6b, agent/langfuse_export.py) gets a copy of each record; it is None unless Langfuse is switched on."""
        self.settings, self.root, self.model_names = settings, Path(root), dict(model_names or {})
        self.exporter = exporter
        self._logged: set = set()

    @property
    def path(self) -> Path:
        return resolve_path(self.settings, self.root)

    def _log_once(self, err: BaseException) -> None:
        key = type(err).__name__
        if key not in self._logged:
            self._logged.add(key)
            log.warning("tracing failed (%s); the turn is not affected. Further errors of this kind are not logged.", key)

    def record_turn(self, *, result: dict, session_id: str, customer_id: str, message: str, duration_ms: float) -> None:
        """Write the record of one turn. Never raises and never changes `result`."""
        if not self.settings.enabled and self.exporter is None:
            return
        try:
            record = build_record(self.settings, result=result, session_id=session_id, customer_id=customer_id, message=message,
                                  duration_ms=duration_ms, model_names=self.model_names)
            if self.settings.enabled:
                append_line(self.path, record, self.settings.max_lines)
            if self.exporter is not None:
                self.exporter.submit(record)               # queued for a background thread; never raises
        except BaseException as err:                       # tracing must never break a chat (KeyboardInterrupt excepted below)
            if isinstance(err, (KeyboardInterrupt, SystemExit)):
                raise
            self._log_once(err)


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
