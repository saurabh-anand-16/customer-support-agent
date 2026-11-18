"""
langfuse_export.py - the optional copy of each turn in Langfuse (phase 6b, step 3 of phase 6).

This is the only module that imports the `langfuse` package, and it imports it only when the first turn is sent, which happens only
when [tracing].langfuse_enabled is true (a test checks both). The local trace file stays the main record; this is a copy.

What it does with a turn record (the cleaned dict that agent/tracing.py already built, so capture_text has already been applied):
  * one turn = one trace: a root observation "turn" (type agent) holding the message and the reply, and one child per step:
    router and model calls = generation, tools and writers = tool, policy search = retriever, review item = tool,
    each guardrail check = an event named "check:<name>".
  * `user_id` is a keyed hash of the customer id (HMAC-SHA256, key from the variable named in [tracing].hash_key_env_name),
    never the id. Without that key nothing is sent.
  * a `mask` function removes customer ids, phone numbers and e-mail addresses from every input, output and metadata value
    (the SDK does not apply the mask to `user_id`, which is why that is hashed here).
  * the keys come from the process environment first, then the env file (the same order as the OpenAI key) and go straight to the
    client constructor. They are never copied into os.environ, printed, logged or put in an error message.
  * sending is done by one background worker thread, including the flush, so a reply never waits for Langfuse. Any error is
    caught and logged once per kind. A missing package, missing keys or a missing hash key skip the export with one log line.

Not done: the SDK's observations are made after the turn has finished (the record is built at the end), so a child observation's own
start and end are not the real ones. The real latency of a step is in its metadata (`latency_ms`) where the trace had one.
"""
import hashlib
import hmac
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .rag.embedders.base import read_secret

log = logging.getLogger("agent.langfuse_export")

# The names the Langfuse SDK itself uses. Their values are read from the environment or the env file, never from config.
PUBLIC_KEY_NAME, SECRET_KEY_NAME, BASE_URL_NAME = "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"
MASKED_ID, MASKED_PHONE, MASKED_EMAIL = "[customer]", "[phone]", "[email]"

# -- the mask ---------------------------------------------------------------------------------------------------
CUSTOMER_ID = re.compile(r"\bC\d{4,}\b", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
# An Indian mobile number (optional +91, 91 or 0 in front, one space or dash in the middle allowed), or any "+" number with 8 to 15 digits.
PHONE = re.compile(r"(?<![\w.])(?:\+91[\s\-]?|91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)|(?<![\w])\+\d(?:[\s\-]?\d){7,14}(?!\d)")


def mask_text(text: str) -> str:
    """`text` with e-mail addresses, phone numbers and customer ids replaced. E-mail first, so an id inside an address goes with it."""
    return CUSTOMER_ID.sub(MASKED_ID, PHONE.sub(MASKED_PHONE, EMAIL.sub(MASKED_EMAIL, text)))


def mask(data=None, **_ignored):
    """The SDK's mask function: called as mask(data=...), returns the same shape with every string masked. Never raises."""
    try:
        return _mask_any(data)
    except Exception:
        return "[masked: error]"


def _mask_any(value):
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {_mask_any(k) if isinstance(k, str) else k: _mask_any(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_any(v) for v in value]
    return value


def hash_customer(customer_id: str, key: str) -> str:
    """A keyed hash (HMAC-SHA256, first 32 hex characters) of the customer id. The same customer always gives the same value."""
    return hmac.new(key.encode("utf-8"), str(customer_id).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


# -- the mapping ------------------------------------------------------------------------------------------------
STEP_TYPES = {"router": "generation", "model_call": "generation", "tool_call": "tool", "write": "tool", "retrieval": "retriever",
              "review_item": "tool"}


def _level(status) -> str | None:
    return "ERROR" if status == "failed" else "WARNING" if status == "refused" else None


def send_record(client, record: dict, user_hash: str) -> str | None:
    """Make the trace for one turn record with `client`. Returns the trace id. Raises on SDK errors (the caller catches them)."""
    from langfuse import propagate_attributes          # only here, with the client
    route = record.get("route") or {}
    tags = [t for t in (route.get("router_label"), route.get("branch")) if isinstance(t, str) and t]
    root_meta = {"turn_id": record.get("turn_id"), "route": route, "duration_ms": record.get("duration_ms"),
                 "capture_text": record.get("capture_text"), "index_fingerprint": record.get("index_fingerprint"),
                 "review_reference": record.get("review_reference"), "passages": record.get("passages"),
                 "pending_action": record.get("pending_action"), "schema_version": record.get("schema_version")}
    with propagate_attributes(user_id=user_hash, session_id=str(record.get("session_id")), trace_name="turn",
                              tags=[mask_text(t)[:200] for t in tags], metadata={"turn_id": str(record.get("turn_id"))}):
        with client.start_as_current_observation(name="turn", as_type="agent", input=record.get("message"), output=record.get("reply"),
                                                 metadata=root_meta) as root:
            trace_id = getattr(root, "trace_id", None)
            for step in record.get("steps") or []:
                kind, name = step.get("kind"), str(step.get("name"))
                meta = {"kind": kind, "status": step.get("status"), "latency_ms": step.get("latency_ms")}
                if step.get("refused"):
                    meta["refused"] = step.get("refused")
                if kind == "check":
                    root.create_event(name=f"check:{name}", output=step.get("output"), metadata=meta,
                                      level="WARNING" if step.get("status") == "failed" else None)
                    continue
                extra = {"model": step["model"]} if step.get("model") and STEP_TYPES.get(kind) == "generation" else {}
                if kind == "retrieval":
                    meta["index_fingerprint"] = record.get("index_fingerprint")
                child = root.start_observation(name=name, as_type=STEP_TYPES.get(kind, "span"), input=step.get("input"),
                                               output=step.get("output"), metadata=meta, level=_level(step.get("status")), **extra)
                child.end()
    return trace_id


# -- the exporter -----------------------------------------------------------------------------------------------
class LangfuseExporter:
    """
    `submit(record)` queues one turn for the background worker and returns at once. Never raises.
    `flush()` waits for the queue and the SDK's own buffer to be sent (scripts call it before they exit; a long-running app need not).
    """

    def __init__(self, settings, env_file: str | Path | None = None, environ=None, client_args: dict | None = None):
        """`environ` replaces the process environment for the key lookup (tests); `client_args` is added to the client constructor (tests)."""
        self.settings, self.env_file, self._environ = settings, env_file, environ
        self._client_args = dict(client_args or {})
        self._client = None
        self._hash_key = None
        self._ready: bool | None = None          # None: not tried yet
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="langfuse-export")
        self._logged: set = set()
        self._lock = threading.Lock()
        self.trace_ids: dict = {}                # turn_id -> trace id, for scripts that print links
        self.last_flush_seconds: float | None = None

    # -- helpers
    def _secret(self, name: str):
        if self._environ is not None and self._environ.get(name):
            return self._environ[name]
        return read_secret(name, self.env_file)

    def _log_once(self, key: str, text: str) -> None:
        with self._lock:
            if key in self._logged:
                return
            self._logged.add(key)
        log.warning("%s", text)

    def _setup(self) -> bool:
        """Open the client once. False (with one log line) when it cannot be done. Only names are ever logged, never values."""
        if self._ready is not None:
            return self._ready
        self._ready = False
        try:
            hash_name = self.settings.hash_key_env_name
            missing = [n for n in (PUBLIC_KEY_NAME, SECRET_KEY_NAME, BASE_URL_NAME, hash_name) if not self._secret(n)]
            if missing:
                self._log_once("keys", f"Langfuse export skipped: not set in the environment or the env file: {', '.join(missing)}")
                return False
            try:
                from langfuse import Langfuse
            except ImportError:
                self._log_once("package", "Langfuse export skipped: the 'langfuse' package is not installed (pip install -r requirements-tracing.txt)")
                return False
            self._hash_key = self._secret(hash_name)
            self._client = Langfuse(public_key=self._secret(PUBLIC_KEY_NAME), secret_key=self._secret(SECRET_KEY_NAME),
                                    base_url=self._secret(BASE_URL_NAME), timeout=self.settings.langfuse_timeout,
                                    environment=self.settings.langfuse_environment, sample_rate=self.settings.langfuse_sample_rate,
                                    mask=mask, **self._client_args)
            self._ready = True
        except BaseException as err:
            if isinstance(err, (KeyboardInterrupt, SystemExit)):
                raise
            self._log_once("setup:" + type(err).__name__, f"Langfuse export skipped: the client could not be started ({type(err).__name__})")
        return self._ready

    @property
    def client(self):
        return self._client

    def auth_check(self) -> bool:
        """True when the server accepts the keys. Opens the client if needed. For setup scripts, not for every turn. Never raises."""
        try:
            return bool(self._setup() and self._client.auth_check())
        except Exception as err:
            self._log_once("auth:" + type(err).__name__, f"Langfuse auth check failed ({type(err).__name__})")
            return False

    def trace_url(self, trace_id: str):
        try:
            return self._client.get_trace_url(trace_id=trace_id) if self._client is not None else None
        except Exception:
            return None

    # -- the work, on the worker thread
    def _export(self, record: dict) -> None:
        try:
            if not self._setup():
                return
            user = hash_customer(record.get("customer_id") or "", self._hash_key)
            trace_id = send_record(self._client, record, user)
            if trace_id:
                with self._lock:
                    self.trace_ids[record.get("turn_id")] = trace_id
            self._client.flush()                       # in this background thread, never in the reply path
        except BaseException as err:
            if isinstance(err, (KeyboardInterrupt, SystemExit)):
                raise
            self._log_once("send:" + type(err).__name__, f"Langfuse export failed ({type(err).__name__}); the turn is not affected. "
                                                         "Further errors of this kind are not logged.")

    # -- the front
    def submit(self, record: dict) -> None:
        try:
            self._pool.submit(self._export, record)
        except BaseException as err:
            if isinstance(err, (KeyboardInterrupt, SystemExit)):
                raise
            self._log_once("submit:" + type(err).__name__, f"Langfuse export could not be queued ({type(err).__name__})")

    def flush(self) -> float:
        """Wait until every queued turn has been handed to the SDK and flushed. Returns the seconds it took. Never raises."""
        started = time.perf_counter()
        try:
            self._pool.submit(lambda: None).result()      # the queue is in order, so this returns after every earlier turn
            if self._client is not None:
                self._client.flush()
        except Exception as err:
            self._log_once("flush:" + type(err).__name__, f"Langfuse flush failed ({type(err).__name__})")
        self.last_flush_seconds = time.perf_counter() - started
        return self.last_flush_seconds

    def shutdown(self) -> None:
        try:
            self.flush()
            self._pool.shutdown(wait=True)
            if self._client is not None:
                self._client.shutdown()
        except Exception:
            pass


def make_exporter(settings, env_file: str | Path | None = None, environ=None, client_args: dict | None = None):
    """A LangfuseExporter when [tracing].langfuse_enabled is true, else None. Imports nothing."""
    return LangfuseExporter(settings, env_file, environ, client_args) if settings.langfuse_enabled else None
