"""
llm.py - the agent's settings (config/agent.toml) and one small wrapper for chat-model calls.

Two jobs, kept together because they are the only things every other agent module needs:

1. load_agent_config() reads config/agent.toml into typed objects and checks it: unknown or missing
   keys, wrong types, an out-of-scope or clarify label that is missing, a reply text that is
   missing for a kind, a prompt that cannot be filled in. Nothing is hard-coded elsewhere: the model
   name, temperature, labels, kinds, scope statement and reply texts all come from this file.

2. ChatModel is the contract for a chat call that returns text (the router asks for JSON). OpenAIChat
   is the real one; FakeChat is a scripted stand-in for tests. The API key is read exactly as in
   phase 3b (the variable named in [model].api_key_env, then the env file, by read_secret()). It is
   used only to build the client and is never printed, logged, traced or written to an error message.
"""
import contextlib
import contextvars
import dataclasses
import logging
import os
import re
import string
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .eligibility import REASONS
from .rag.embedders.base import MissingDependencyError, MissingKeyError, read_secret, scrub

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "agent.toml"


class AgentConfigError(ValueError):
    """config/agent.toml is wrong. The message says where and why."""


class LlmError(RuntimeError):
    """A model call failed. The message never contains the API key."""


# --- settings ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelSettings:
    name: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: int
    api_key_env: str
    env_file: str


@dataclass(frozen=True)
class SessionSettings:
    history_keep: int
    off_topic_limit: int
    friendly_kinds: list     # out-of-scope kinds that do not count as off-topic (greetings, thanks)
    offer_in_reply: list     # kinds whose fixed reply already offers a person, so the streak does not add a second offer


@dataclass(frozen=True)
class RouterSettings:
    history_turns: int
    max_message_chars: int
    max_question_chars: int
    generic_clarify: str
    system_prompt: str
    labels: dict      # route label -> description, in prompt order
    kinds: dict       # out-of-scope kind -> description, in prompt order


@dataclass(frozen=True)
class ScopeSettings:
    statement: str


@dataclass(frozen=True)
class BranchSettings:
    """[branches]: the five branch flows (phase 4b). `name` is the branch model; nothing else names a model."""
    name: str
    temperature: float
    max_output_tokens: int
    tool_round_limit: int
    format_retries: int         # phase 10: how many times a bare action (no "call_tool" or "final") is answered with the reminder below
    format_reminder: str        # the short reminder of the expected format, sent after such an answer
    history_turns: int
    max_message_chars: int
    max_question_chars: int
    rewrite_follow_ups: bool
    rewrite_max_chars: int
    policy_top_k: int
    max_passage_chars: int
    returns_lookup_orders: int   # phase 8b: how many of the newest orders are searched for returns by code (0 = off)
    returns_lookup_words: list   # phase 8b: a conversation with one of these words gets that search before the model answers
    prompts: dict
    reason_texts: dict
    resolution_texts: dict
    approval_texts: dict
    replies: dict


@dataclass(frozen=True)
class ConfirmSettings:
    """[confirm]: the yes or no step before a write (phase 4c). `name` is the model that labels the customer's answer."""
    name: str
    temperature: float
    max_output_tokens: int
    max_message_chars: int
    pending_max_turns: int       # messages the customer may send while an action waits; the next one finds it expired
    max_unclear_asks: int        # how many times an unclear answer is asked about again before the action is dropped
    prompt: str
    replies: dict


@dataclass(frozen=True)
class RefundMethodSettings:
    """[refund_method]: the question asked before the confirm card of a Pay on Delivery refund (phase 4d)."""
    name: str                    # the model that labels the customer's reply (it picks nothing: code checks the label)
    temperature: float
    max_output_tokens: int
    max_message_chars: int
    not_offered: list            # methods the tool lists that this agent never offers (a customer who asks for one goes to a person)
    escalation_kind: str         # the review kind used for that case; one of REVIEW_KINDS
    prompt: str
    option_texts: dict           # method name -> how the question words it (a method with no text is shown by its name)
    notes: dict                  # method name -> a fixed note shown with the confirm card when that method is chosen
    replies: dict


@dataclass(frozen=True)
class AnswerCheckSettings:
    """[answer_check]: numbers, amounts and dates in a model-written reply must come from this turn's tool results."""
    enabled: bool
    max_retries: int
    max_facts_listed: int
    max_passage_chars: int       # the template fallback for a policy answer quotes the top passage cut to this length
    allowed_text: list           # config text whose numbers and dates are also allowed in an answer
    retry_instruction: str
    replies: dict


@dataclass(frozen=True)
class ReviewSettings:
    """[review]: the review queue (phase 5a). The reply texts are fixed; the model writes none of them."""
    excerpt_messages: int        # how many of the last messages (customer and agent) are kept in a queue item
    excerpt_message_chars: int   # each kept message is cut to this length
    dedupe_open_items: bool      # the same customer, order item and kind with an open item gives that item back, not a second one
    reply_template: str          # shown to the customer; {reference} is the only field
    error_reply: str             # shown when the queue write failed; no fields
    reasons: dict                # kind -> the one-sentence reason a queue item gets, filled in by code from tool data
    reasons_by_requested_method: dict   # refund method the customer asked for that is not offered (paper_cheque) -> its own reason sentence (5b)
    show_note_to_customer: bool  # false: the manager's note is never put in the outcome notice (5b)
    product_name_max_chars: int  # phase 8c: a product name longer than this is cut (with an ellipsis) in the notices
    recent_decision_days: int    # phase 8b: a case decided this recently still counts when the customer asks about it again
    note_to_customer: dict       # phase 8b: kind -> whether a manager's reply is shown to the customer (only a person case: true)
    existing_case: dict          # phase 8b: the fixed texts for "you already have a request" (open, closed, approved, declined, ask_new)
    note_max_chars: int          # a decision note longer than this is refused; a shown note is cut to it
    default_decided_by: str      # the label scripts use when they give no decided_by
    notices: dict                # the fixed texts of the outcome notice: approved, refund_line, declined, closed, note_line
    decision_replies: dict       # the fixed texts a decision gives back to the caller (the manager side)


@dataclass(frozen=True)
class ModelPrice:
    """[pricing.<model>] (phase 6c): US dollars per million tokens. A price that is None is not known, and no cost is ever worked out from it."""
    input_per_million: float | None = None
    output_per_million: float | None = None
    cached_input_per_million: float | None = None


PRICE_KEYS = ("input_per_million", "output_per_million", "cached_input_per_million")


@dataclass(frozen=True)
class EvalSettings:
    test_fraction: float


@dataclass(frozen=True)
class TracingSettings:
    """[tracing] (phase 6): the local trace file, and the optional Langfuse copy. The three switches can be overridden by environment variables."""
    enabled: bool                # write one JSON line per turn to local_path
    local_path: str              # relative paths are under the project root
    max_lines: int               # the newest this many lines are kept; older ones are dropped (a warning is logged)
    capture_text: bool           # false: the customer's message and the reply are replaced by "[not captured]" and their lengths
    step_chars: int              # a step's short input or output is cut to this many characters
    hidden_keys: list            # key names that are dropped from every record, at any depth (the customer id is written only in its own field)
    langfuse_enabled: bool       # off by default; having Langfuse keys never turns it on
    langfuse_environment: str
    langfuse_sample_rate: float  # share of turns sent to Langfuse, 0 to 1
    langfuse_timeout: int        # seconds
    hash_key_env_name: str       # name of the variable that holds the key for hashing the customer id (the key itself stays in .env)


# Environment variable -> the [tracing] field it overrides. Only these three; an unreadable value is a config error.
TRACING_ENV = {"TRACING_ENABLED": "enabled", "TRACING_LANGFUSE_ENABLED": "langfuse_enabled", "TRACING_CAPTURE_TEXT": "capture_text"}
_TRUE, _FALSE = {"1", "true", "yes", "on"}, {"0", "false", "no", "off"}


def _env_file_for(model: ModelSettings):
    """The env file that holds the secrets and the tracing overrides: the one named in [model].env_file, under the project root.
    (Tests replace this function so that the developer's own .env never changes a test.)"""
    return ROOT / model.env_file


def apply_tracing_env(settings: TracingSettings, environ=None, env_file=None) -> TracingSettings:
    """
    `settings` with the three overrides applied. Order, the same as for the API key: the process environment first, then the
    env file (`read_secret`, which copies nothing into os.environ). A variable that is unset or empty in both changes nothing.
    `environ` replaces the process environment (tests); the env file is still read as the fallback.
    """
    changes = {}
    for name, field_name in TRACING_ENV.items():
        raw = ((environ.get(name) if environ is not None else None) or read_secret(name, env_file) or "").strip().lower()
        if not raw:
            continue
        if raw in _TRUE:
            changes[field_name] = True
        elif raw in _FALSE:
            changes[field_name] = False
        else:
            raise AgentConfigError(f"The variable {name} (environment or env file) must be true or false, got {raw!r}")
    return dataclasses.replace(settings, **changes) if changes else settings


@dataclass(frozen=True)
class AgentConfig:
    root: Path
    model: ModelSettings
    session: SessionSettings
    router: RouterSettings
    scope: ScopeSettings
    branches: BranchSettings
    confirm: ConfirmSettings
    answer_check: AnswerCheckSettings
    review: ReviewSettings
    refund_method: RefundMethodSettings
    tracing: TracingSettings
    replies: dict     # kind -> text, plus person_offer, not_built, blank_message
    eval: EvalSettings
    pricing: dict = dataclasses.field(default_factory=dict)    # model name -> ModelPrice (phase 6c); no [pricing] section means no prices


# The labels the code itself relies on: out_of_scope picks a fixed reply, clarify asks a question.
REQUIRED_LABELS = ("out_of_scope", "clarify")
EXTRA_REPLIES = ("person_offer", "not_built", "blank_message")

# [branches]: the prompts and fixed reply texts the code needs, and the fields a reply text may contain.
BRANCH_PROMPTS = ("common", "order_status", "policy_question", "rewrite", "return_or_replace", "cancel_item")
BRANCH_REPLIES = ("no_policy_match", "sources_line", "tool_limit", "branch_error", "ask_generic", "item_not_found",
                  "ask_resolution", "confirm_return", "approval_note", "confirm_cancel", "explain_window_expired",
                  "explain_non_returnable", "explain_change_of_mind_not_allowed", "explain_not_yet_delivered",
                  "explain_return_already_opened", "explain_item_cancelled", "explain_guidance_only", "explain_other",
                  "cancel_shipped", "cancel_delivered", "cancel_cancelled", "cancel_other")
BRANCH_RESOLUTIONS = ("refund", "replacement", "exchange", "brand_service")
BRANCH_APPROVALS = ("account_restricted", "high_value", "repeat_returner")
BRANCH_REPLY_FIELDS = {"product_name", "item_id", "order_id", "amount", "reason", "resolution", "options", "condition_note",
                       "approval_note", "approval_reasons", "order_part", "delivered_at", "day_number", "window_days", "refund_method_line",
                       "last_eligible_date", "days_late", "days_left", "return_id", "sources"}

CONFIRM_REPLIES = ("done_return", "done_return_refund_line", "done_cancel", "declined", "unclear_ask", "unclear_drop", "expired",
                   "refund_method_needed", "refused")
CONFIRM_REPLY_FIELDS = {"product_name", "item_id", "order_id", "return_id", "resolution", "refund_line", "next_step", "question",
                        "message", "options", "amount", "method", "timeline"}
REFUND_METHOD_REPLIES = ("ask", "chosen_line", "cheque_reply")
REFUND_METHOD_REPLY_FIELDS = {"options", "product_name", "method", "note", "reference"}
ANSWER_CHECK_REPLIES = ("fallback_intro", "fallback_order_line", "fallback_item_line", "fallback_return_line", "fallback_timeline_line",
                        "fallback_policy_line", "fallback_nothing")
ANSWER_CHECK_REPLY_FIELDS = {"order_id", "ordered_at", "product_name", "item_id", "item_status", "delivered_at", "return_id", "return_status",
                             "refund_line", "order_type", "refund_method", "time_text", "passage", "sources", "payment_type"}
RETRY_FIELDS = {"problems", "facts"}

# [review]: the reasons that callers of the escalation seam use today (the document for phase 5a names four kinds; these are the
# callers' own). A kind with no sentence in [review.reasons] could not be written, so every one must be there.
REVIEW_KINDS = ("customer_asked_for_person", "late_request", "approval_required")
REVIEW_REASON_FIELDS = {"item_id", "reason", "resolution", "approval_reasons", "day_number", "window_days", "days_late", "last_eligible_date"}
# Phase 5b: the outcome notice a customer gets, and the texts a decision gives back. Each key has the fields it may use.
REVIEW_NOTICE_FIELDS = {"approved": {"reference", "product_name", "item_id", "return_id", "refund_line"},
                        "approved_replacement": {"reference", "product_name", "item_id", "return_id", "refund_line"},
                        "refund_line": {"amount", "method"},
                        "declined": {"reference", "product_name", "item_id"},
                        "closed": {"reference"},
                        "person_reply": {"reference", "note"},
                        "note_line": {"note"}}
# Phase 8b: the texts for an existing case, and the fields each may use.
REVIEW_EXISTING_CASE_FIELDS = {"open": {"reference"}, "closed": {"reference"}, "approved": {"reference"}, "declined": {"reference"}, "ask_new": set()}
REVIEW_DECISION_REPLIES = ("approved", "declined", "closed", "bad_decision", "bad_note", "note_too_long", "not_found", "already_decided",
                           "decision_in_progress", "late_cannot_be_approved", "item_incomplete", "refund_method_missing",
                           "refund_method_not_offered", "write_refused", "write_failed", "record_failed")
REVIEW_DECISION_REPLY_FIELDS = {"reference", "message", "return_id", "limit"}

_SPEC = {
    "model": (ModelSettings, {"name": str, "temperature": float, "max_output_tokens": int, "timeout_seconds": int,
                              "api_key_env": str, "env_file": str}),
    "session": (SessionSettings, {"history_keep": int, "off_topic_limit": int, "friendly_kinds": list, "offer_in_reply": list}),
    "router": (RouterSettings, {"history_turns": int, "max_message_chars": int, "max_question_chars": int,
                                "generic_clarify": str, "system_prompt": str, "labels": dict, "kinds": dict}),
    "scope": (ScopeSettings, {"statement": str}),
    "branches": (BranchSettings, {"name": str, "temperature": float, "max_output_tokens": int, "tool_round_limit": int,
                                  "format_retries": int, "format_reminder": str, "history_turns": int, "max_message_chars": int, "max_question_chars": int,
                                  "rewrite_follow_ups": bool, "rewrite_max_chars": int, "policy_top_k": int,
                                  "max_passage_chars": int, "returns_lookup_orders": int, "returns_lookup_words": list, "prompts": dict, "reason_texts": dict,
                                  "resolution_texts": dict, "approval_texts": dict, "replies": dict}),
    "confirm": (ConfirmSettings, {"name": str, "temperature": float, "max_output_tokens": int, "max_message_chars": int,
                                  "pending_max_turns": int, "max_unclear_asks": int, "prompt": str, "replies": dict}),
    "answer_check": (AnswerCheckSettings, {"enabled": bool, "max_retries": int, "max_facts_listed": int, "max_passage_chars": int,
                                           "allowed_text": list, "retry_instruction": str, "replies": dict}),
    "review": (ReviewSettings, {"excerpt_messages": int, "excerpt_message_chars": int, "dedupe_open_items": bool,
                                "reply_template": str, "error_reply": str, "reasons": dict,
                                "reasons_by_requested_method": dict, "show_note_to_customer": bool, "note_max_chars": int,
                                "product_name_max_chars": int, "recent_decision_days": int, "note_to_customer": dict, "existing_case": dict,
                                "default_decided_by": str, "notices": dict, "decision_replies": dict}),
    "refund_method": (RefundMethodSettings, {"name": str, "temperature": float, "max_output_tokens": int, "max_message_chars": int,
                                             "not_offered": list, "escalation_kind": str, "prompt": str, "option_texts": dict,
                                             "notes": dict, "replies": dict}),
    "tracing": (TracingSettings, {"enabled": bool, "local_path": str, "max_lines": int, "capture_text": bool, "step_chars": int, "hidden_keys": list,
                                  "langfuse_enabled": bool, "langfuse_environment": str, "langfuse_sample_rate": float,
                                  "langfuse_timeout": int, "hash_key_env_name": str}),
    "eval": (EvalSettings, {"test_fraction": float}),
}


def _ok(value, tp) -> bool:
    if tp is bool:
        return isinstance(value, bool)
    if tp is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if tp is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, tp)


def _build(name: str, data, cls, spec: dict, where: str):
    if not isinstance(data, dict):
        raise AgentConfigError(f"{where}: [{name}] is missing or is not a table")
    for key in data:
        if key not in spec:
            raise AgentConfigError(f"{where}: unknown key '{key}' in [{name}]. Allowed keys: {', '.join(spec)}")
    for key, tp in spec.items():
        if key not in data:
            raise AgentConfigError(f"{where}: [{name}] is missing the key '{key}'")
        if not _ok(data[key], tp):
            raise AgentConfigError(f"{where}: [{name}].{key} must be of type {tp.__name__}, got {data[key]!r}")
    values = {k: (float(v) if spec[k] is float else v) for k, v in data.items()}
    return cls(**values)


def load_agent_config(path: str | Path | None = None) -> AgentConfig:
    """Load and check config/agent.toml (or `path`). Never reads the API key."""
    path = Path(path) if path else DEFAULT_CONFIG
    where = path.name
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as err:
        raise AgentConfigError(f"Config file not found: {path}") from err
    except tomllib.TOMLDecodeError as err:
        raise AgentConfigError(f"{where}: not valid TOML: {err}") from err

    for key in raw:
        # [app] (phase 7) belongs to the Streamlit app, which reads and checks it itself (app/config.py). The agent only lets it be there.
        if key not in _SPEC and key not in ("replies", "app", "pricing"):
            raise AgentConfigError(f"{where}: unknown section [{key}]. Allowed: {', '.join([*_SPEC, 'replies', 'app', 'pricing'])}")
    built = {name: _build(name, raw.get(name), cls, spec, where) for name, (cls, spec) in _SPEC.items()}
    replies = raw.get("replies")
    if not isinstance(replies, dict):
        raise AgentConfigError(f"{where}: [replies] is missing or is not a table")

    built["tracing"] = apply_tracing_env(built["tracing"], env_file=_env_file_for(built["model"]))   # the three overrides: environment, then env file
    cfg = AgentConfig(root=ROOT, replies=dict(replies), pricing=_read_pricing(raw.get("pricing"), where), **built)
    _check(cfg, where)
    return cfg


def _read_pricing(raw, where: str) -> dict:
    """[pricing.<model>] tables -> {model: ModelPrice}. A price must be a number of 0 or more; an unknown key or a bad value is refused."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AgentConfigError(f"{where}: [pricing] must hold one table per model, such as [pricing.\"model-name\"]")
    prices = {}
    for model, table in raw.items():
        if not isinstance(table, dict):
            raise AgentConfigError(f"{where}: [pricing].{model} must be a table with {', '.join(PRICE_KEYS)}")
        for key, value in table.items():
            if key not in PRICE_KEYS:
                raise AgentConfigError(f"{where}: [pricing.{model}] has '{key}'. Allowed keys: {', '.join(PRICE_KEYS)}")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AgentConfigError(f"{where}: [pricing.{model}].{key} must be a number, got {value!r}")
            if value != value or value < 0 or value == float("inf"):
                raise AgentConfigError(f"{where}: [pricing.{model}].{key} must be 0 or more, got {value!r}")
        prices[model] = ModelPrice(**{k: float(v) for k, v in table.items()})
    return prices


def _check_tracing(t: TracingSettings, where: str) -> None:
    if not all(isinstance(k, str) and k.strip() for k in t.hidden_keys):
        raise AgentConfigError(f"{where}: [tracing].hidden_keys must be a list of key names")
    for label, value in (("max_lines", t.max_lines), ("step_chars", t.step_chars), ("langfuse_timeout", t.langfuse_timeout)):
        if value < 1:
            raise AgentConfigError(f"{where}: [tracing].{label} must be 1 or more")
    if not 0 <= t.langfuse_sample_rate <= 1:
        raise AgentConfigError(f"{where}: [tracing].langfuse_sample_rate must be between 0 and 1")
    for label, value in (("local_path", t.local_path), ("langfuse_environment", t.langfuse_environment), ("hash_key_env_name", t.hash_key_env_name)):
        if not value.strip():
            raise AgentConfigError(f"{where}: [tracing].{label} must not be empty")


def _check(cfg: AgentConfig, where: str) -> None:
    r, m, s = cfg.router, cfg.model, cfg.session
    for table_name, table in (("labels", r.labels), ("kinds", r.kinds)):
        if not table or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in table.items()):
            raise AgentConfigError(f"{where}: [router.{table_name}] must be a table of non-empty descriptions")
    for label in REQUIRED_LABELS:
        if label not in r.labels:
            raise AgentConfigError(f"{where}: [router.labels] must include '{label}'")
    needed = [*r.kinds, *EXTRA_REPLIES]
    for key in needed:
        if not isinstance(cfg.replies.get(key), str) or not cfg.replies[key].strip():
            raise AgentConfigError(f"{where}: [replies] needs non-empty text for '{key}'")
    for key in cfg.replies:
        if key not in needed:
            raise AgentConfigError(f"{where}: [replies] has '{key}', which is neither a kind in [router.kinds] nor one of {', '.join(EXTRA_REPLIES)}")
    if "{branch}" not in cfg.replies["not_built"]:
        raise AgentConfigError(f"{where}: [replies].not_built must contain {{branch}}")
    try:
        r.system_prompt.format(scope_statement="", labels="", kinds="", max_question_chars=0)
    except (KeyError, IndexError, ValueError) as err:
        raise AgentConfigError(
            f"{where}: [router].system_prompt cannot be filled in ({err!r}); use only {{scope_statement}}, "
            "{labels}, {kinds} and {max_question_chars}, and write literal braces as {{ and }}") from err
    for key, listed in ("friendly_kinds", s.friendly_kinds), ("offer_in_reply", s.offer_in_reply):
        for kind in listed:
            if kind not in r.kinds:
                raise AgentConfigError(f"{where}: [session].{key} has '{kind}', which is not a kind in [router.kinds]")
    if not 0 <= m.temperature <= 2:
        raise AgentConfigError(f"{where}: [model].temperature must be between 0 and 2")
    for label, value in (("[model].max_output_tokens", m.max_output_tokens), ("[model].timeout_seconds", m.timeout_seconds),
                         ("[session].history_keep", s.history_keep), ("[session].off_topic_limit", s.off_topic_limit),
                         ("[router].max_message_chars", r.max_message_chars), ("[router].max_question_chars", r.max_question_chars)):
        if value < 1:
            raise AgentConfigError(f"{where}: {label} must be 1 or more")
    if r.history_turns < 0:
        raise AgentConfigError(f"{where}: [router].history_turns must be 0 or more")
    if not 0 < cfg.eval.test_fraction < 1:
        raise AgentConfigError(f"{where}: [eval].test_fraction must be between 0 and 1")
    if not r.generic_clarify.strip().endswith("?"):
        raise AgentConfigError(f"{where}: [router].generic_clarify must be a question")
    _check_branches(cfg.branches, where)
    _check_confirm(cfg.confirm, where)
    _check_answer_check(cfg.answer_check, where)
    _check_review(cfg.review, where)
    _check_refund_method(cfg.refund_method, where)
    _check_tracing(cfg.tracing, where)


def _fields_of(text: str) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _check_table(where: str, section: str, table: dict, needed, allowed_fields) -> None:
    for key in needed:
        if not isinstance(table.get(key), str) or not table[key].strip():
            raise AgentConfigError(f"{where}: [{section}] needs non-empty text for '{key}'")
    for key, text in table.items():
        if key not in needed:
            raise AgentConfigError(f"{where}: [{section}] has '{key}', which is not one of {', '.join(needed)}")
        try:
            used = _fields_of(text)
        except ValueError as err:
            raise AgentConfigError(f"{where}: [{section}].{key} cannot be filled in ({err!r})") from err
        if used - allowed_fields:
            raise AgentConfigError(f"{where}: [{section}].{key} uses {sorted(used - allowed_fields)}; allowed fields: {', '.join(sorted(allowed_fields))}")


def _check_confirm(c: ConfirmSettings, where: str) -> None:
    if not c.name.strip():
        raise AgentConfigError(f"{where}: [confirm].name (the model) must not be empty")
    if not 0 <= c.temperature <= 2:
        raise AgentConfigError(f"{where}: [confirm].temperature must be between 0 and 2")
    for key in ("max_output_tokens", "max_message_chars", "pending_max_turns"):
        if getattr(c, key) < 1:
            raise AgentConfigError(f"{where}: [confirm].{key} must be 1 or more")
    if c.max_unclear_asks < 0:
        raise AgentConfigError(f"{where}: [confirm].max_unclear_asks must be 0 or more")
    _check_table(where, "confirm.replies", c.replies, CONFIRM_REPLIES, CONFIRM_REPLY_FIELDS)
    if not c.prompt.strip():
        raise AgentConfigError(f"{where}: [confirm].prompt must not be empty")      # used as written: it is not a template


def _check_refund_method(m: RefundMethodSettings, where: str) -> None:
    if not m.name.strip():
        raise AgentConfigError(f"{where}: [refund_method].name (the model) must not be empty")
    if not 0 <= m.temperature <= 2:
        raise AgentConfigError(f"{where}: [refund_method].temperature must be between 0 and 2")
    for key in ("max_output_tokens", "max_message_chars"):
        if getattr(m, key) < 1:
            raise AgentConfigError(f"{where}: [refund_method].{key} must be 1 or more")
    if not m.prompt.strip():
        raise AgentConfigError(f"{where}: [refund_method].prompt must not be empty")      # used as written: it is not a template
    if not all(isinstance(x, str) and x.strip() for x in m.not_offered):
        raise AgentConfigError(f"{where}: [refund_method].not_offered must be a list of method names")
    if m.escalation_kind not in REVIEW_KINDS:
        raise AgentConfigError(f"{where}: [refund_method].escalation_kind must be one of {', '.join(REVIEW_KINDS)}")
    for table_name in ("option_texts", "notes"):
        table = getattr(m, table_name)
        if not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in table.items()):
            raise AgentConfigError(f"{where}: [refund_method.{table_name}] must be a table of method name -> non-empty text")
    _check_table(where, "refund_method.replies", m.replies, REFUND_METHOD_REPLIES, REFUND_METHOD_REPLY_FIELDS)
    for key, field_name in (("ask", "options"), ("chosen_line", "method"), ("cheque_reply", "reference")):
        if field_name not in _fields_of(m.replies[key]):
            raise AgentConfigError(f"{where}: [refund_method.replies].{key} must contain {{{field_name}}}")


def _check_review(r: ReviewSettings, where: str) -> None:
    if r.excerpt_messages < 0:
        raise AgentConfigError(f"{where}: [review].excerpt_messages must be 0 or more")
    if r.excerpt_message_chars < 1:
        raise AgentConfigError(f"{where}: [review].excerpt_message_chars must be 1 or more")
    for key, wanted in (("reply_template", {"reference"}), ("error_reply", set())):
        text = getattr(r, key)
        if not text.strip():
            raise AgentConfigError(f"{where}: [review].{key} must not be empty")
        try:
            found = _fields_of(text)
        except ValueError as err:
            raise AgentConfigError(f"{where}: [review].{key} cannot be filled in ({err!r})") from err
        if found != wanted:
            raise AgentConfigError(f"{where}: [review].{key} must use exactly the fields {sorted(wanted)}, got {sorted(found)}")
    _check_table(where, "review.reasons", r.reasons, REVIEW_KINDS, REVIEW_REASON_FIELDS)
    for method, text in r.reasons_by_requested_method.items():
        if not isinstance(text, str) or not text.strip():
            raise AgentConfigError(f"{where}: [review.reasons_by_requested_method].{method} must be non-empty text")
        try:
            used = _fields_of(text)
        except ValueError as err:
            raise AgentConfigError(f"{where}: [review.reasons_by_requested_method].{method} cannot be filled in ({err!r})") from err
        if used - REVIEW_REASON_FIELDS:
            raise AgentConfigError(f"{where}: [review.reasons_by_requested_method].{method} uses {sorted(used - REVIEW_REASON_FIELDS)}")
    if r.note_max_chars < 1:
        raise AgentConfigError(f"{where}: [review].note_max_chars must be 1 or more")
    if not r.default_decided_by.strip():
        raise AgentConfigError(f"{where}: [review].default_decided_by must not be empty")
    for key, allowed in REVIEW_NOTICE_FIELDS.items():
        text = r.notices.get(key)
        if not isinstance(text, str) or not text.strip():
            raise AgentConfigError(f"{where}: [review.notices] needs non-empty text for '{key}'")
        try:
            used = _fields_of(text)
        except ValueError as err:
            raise AgentConfigError(f"{where}: [review.notices].{key} cannot be filled in ({err!r})") from err
        if used - allowed:
            raise AgentConfigError(f"{where}: [review.notices].{key} uses {sorted(used - allowed)}; allowed fields: {', '.join(sorted(allowed))}")
    extra = set(r.notices) - set(REVIEW_NOTICE_FIELDS)
    if extra:
        raise AgentConfigError(f"{where}: [review.notices] has {sorted(extra)}, which are not one of {', '.join(REVIEW_NOTICE_FIELDS)}")
    _check_table(where, "review.decision_replies", r.decision_replies, REVIEW_DECISION_REPLIES, REVIEW_DECISION_REPLY_FIELDS)
    if _fields_of(r.notices["person_reply"]) != {"reference", "note"}:
        raise AgentConfigError(f"{where}: [review.notices].person_reply must use exactly {{reference}} and {{note}}")
    if r.product_name_max_chars < 10:
        raise AgentConfigError(f"{where}: [review].product_name_max_chars must be 10 or more")
    if r.recent_decision_days < 0:
        raise AgentConfigError(f"{where}: [review].recent_decision_days must be 0 or more")
    if set(r.note_to_customer) != set(REVIEW_KINDS) or not all(isinstance(v, bool) for v in r.note_to_customer.values()):
        raise AgentConfigError(f"{where}: [review.note_to_customer] needs true or false for each of {', '.join(REVIEW_KINDS)} and nothing else")
    for key, allowed in REVIEW_EXISTING_CASE_FIELDS.items():
        _check_table(where, "review.existing_case", {key: r.existing_case.get(key)}, (key,), allowed)
    extra_texts = set(r.existing_case) - set(REVIEW_EXISTING_CASE_FIELDS)
    if extra_texts:
        raise AgentConfigError(f"{where}: [review.existing_case] has {sorted(extra_texts)}, which are not one of {', '.join(REVIEW_EXISTING_CASE_FIELDS)}")


def _check_answer_check(a: AnswerCheckSettings, where: str) -> None:
    for key in ("max_facts_listed", "max_passage_chars"):
        if getattr(a, key) < 1:
            raise AgentConfigError(f"{where}: [answer_check].{key} must be 1 or more")
    if a.max_retries < 0:
        raise AgentConfigError(f"{where}: [answer_check].max_retries must be 0 or more")
    if not all(isinstance(t, str) for t in a.allowed_text):
        raise AgentConfigError(f"{where}: [answer_check].allowed_text must be a list of text")
    try:
        found = _fields_of(a.retry_instruction)
    except ValueError as err:
        raise AgentConfigError(f"{where}: [answer_check].retry_instruction cannot be filled in ({err!r})") from err
    if found != RETRY_FIELDS:
        raise AgentConfigError(f"{where}: [answer_check].retry_instruction must use exactly the fields {sorted(RETRY_FIELDS)}, got {sorted(found)}")
    _check_table(where, "answer_check.replies", a.replies, ANSWER_CHECK_REPLIES, ANSWER_CHECK_REPLY_FIELDS)


def _check_branches(b: BranchSettings, where: str) -> None:
    if not 0 <= b.temperature <= 2:
        raise AgentConfigError(f"{where}: [branches].temperature must be between 0 and 2")
    for key in ("max_output_tokens", "tool_round_limit", "max_message_chars", "max_question_chars", "rewrite_max_chars",
                "policy_top_k", "max_passage_chars"):
        if getattr(b, key) < 1:
            raise AgentConfigError(f"{where}: [branches].{key} must be 1 or more")
    if b.history_turns < 0:
        raise AgentConfigError(f"{where}: [branches].history_turns must be 0 or more")
    if b.format_retries < 0:
        raise AgentConfigError(f"{where}: [branches].format_retries must be 0 or more")
    if not b.format_reminder.strip():
        raise AgentConfigError(f"{where}: [branches].format_reminder cannot be empty")
    if b.returns_lookup_orders < 0 or b.returns_lookup_orders > 25:
        raise AgentConfigError(f"{where}: [branches].returns_lookup_orders must be between 0 and 25")
    if not all(isinstance(w, str) and w.strip() for w in b.returns_lookup_words):
        raise AgentConfigError(f"{where}: [branches].returns_lookup_words must be a list of non-empty words")
    if not b.name.strip():
        raise AgentConfigError(f"{where}: [branches].name (the model) must not be empty")
    for table_name, table, needed in (("prompts", b.prompts, BRANCH_PROMPTS), ("replies", b.replies, BRANCH_REPLIES),
                                      ("reason_texts", b.reason_texts, REASONS),
                                      ("resolution_texts", b.resolution_texts, BRANCH_RESOLUTIONS),
                                      ("approval_texts", b.approval_texts, BRANCH_APPROVALS)):
        for key in needed:
            if not isinstance(table.get(key), str) or not table[key].strip():
                raise AgentConfigError(f"{where}: [branches.{table_name}] needs non-empty text for '{key}'")
        for key in table:
            if key not in needed:
                raise AgentConfigError(f"{where}: [branches.{table_name}] has '{key}', which is not one of {', '.join(needed)}")
    for key, text in b.replies.items():
        fields = {name for _, name, _, _ in string.Formatter().parse(text) if name}
        if fields - BRANCH_REPLY_FIELDS:
            raise AgentConfigError(f"{where}: [branches.replies].{key} uses {sorted(fields - BRANCH_REPLY_FIELDS)}; "
                                   f"allowed fields: {', '.join(sorted(BRANCH_REPLY_FIELDS))}")
    for key, fields in (("common", {"tools"}), ("return_or_replace", {"reasons"})):
        found = {name for _, name, _, _ in string.Formatter().parse(b.prompts[key]) if name}
        if found != fields:
            raise AgentConfigError(f"{where}: [branches.prompts].{key} must use exactly the fields {sorted(fields)}, got {sorted(found)}")
    for key in BRANCH_PROMPTS:
        try:
            b.prompts[key].format(tools="", reasons="")
        except (KeyError, IndexError, ValueError) as err:
            raise AgentConfigError(f"{where}: [branches.prompts].{key} cannot be filled in ({err!r}); write literal braces as {{{{ and }}}}") from err


# --- the chat model -------------------------------------------------------------------------------
class ChatModel:
    """A chat call: a system prompt and messages in, text out. Raises LlmError on any failure."""

    def complete(self, system: str, messages: list[dict], settings: ModelSettings) -> str:
        raise NotImplementedError

    def take_usage(self) -> dict | None:
        """The usage of this thread's last call, once: {"model", "input_tokens", "output_tokens", "cached_tokens"} (any may be None), or None
        when the model does not report it. Phase 6c: read by RecordingChat, never by the agent's own logic."""
        return None


class OpenAIChat(ChatModel):
    """The real model. Asks for a JSON object. For tests, pass a `client` shaped like openai.OpenAI()."""

    def __init__(self, root: Path = ROOT, client=None):
        self.root, self._client, self._key = root, client, None
        self._local = threading.local()          # the usage of the last call, per thread (a worker thread and a script may share one model)

    def _get_client(self, settings: ModelSettings):
        if self._client is None:
            self._key = read_secret(settings.api_key_env, self.root / settings.env_file)
            if not self._key:
                raise MissingKeyError(f"No API key: set {settings.api_key_env} in the environment or in {settings.env_file}")
            try:
                import openai
            except ImportError as err:
                raise MissingDependencyError("The 'openai' package is not installed: pip install -r requirements-agent.txt") from err
            self._client = openai.OpenAI(api_key=self._key, timeout=settings.timeout_seconds)
        return self._client

    def complete(self, system, messages, settings):
        try:
            client = self._get_client(settings)
            response = client.chat.completions.create(
                model=settings.name, temperature=settings.temperature, max_tokens=settings.max_output_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, *messages])
            self._keep_usage(response)
            return response.choices[0].message.content or ""
        except (MissingKeyError, MissingDependencyError) as err:
            raise LlmError(str(err)) from None             # these messages name the variable or package, never the key
        except Exception as err:                            # the kind of failure, never the key
            raise LlmError(f"model call failed ({type(err).__name__}): {scrub(str(err), self._key)}") from None


    def _keep_usage(self, response) -> None:
        """Remember the model name and token counts the API reported. Reads only; a response without them leaves None. Never raises."""
        try:
            usage = getattr(response, "usage", None)
            details = getattr(usage, "prompt_tokens_details", None)
            self._local.usage = {"model": getattr(response, "model", None) if isinstance(getattr(response, "model", None), str) else None,
                                 "input_tokens": _count(getattr(usage, "prompt_tokens", None)),
                                 "output_tokens": _count(getattr(usage, "completion_tokens", None)),
                                 "cached_tokens": _count(getattr(details, "cached_tokens", None))}
        except Exception:
            self._local.usage = None

    def take_usage(self):
        usage, self._local.usage = getattr(self._local, "usage", None), None
        return usage


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class FakeChat(ChatModel):
    """
    A scripted model for tests. `replies` is one text, a list of texts used in order (the last one repeats),
    or a function (system, messages) -> text. An Exception in the list is raised instead. Every call is
    recorded in `.calls` with the system prompt, the messages and the model name and temperature it was given.
    """

    def __init__(self, replies="{}", usage=None):
        """`usage` (phase 6c) is what the fake reports for each call, like the API does: a dict {"input_tokens", "output_tokens",
        "cached_tokens", "model"}, or a list of them used in order (the last repeats), or a function (system, messages) -> dict."""
        self.replies, self.calls, self._next = replies, [], 0
        self.usage, self._last_usage = usage, None

    def take_usage(self):
        usage, self._last_usage = self._last_usage, None
        return usage

    def complete(self, system, messages, settings):
        self.calls.append({"system": system, "messages": messages, "model": settings.name,
                           "temperature": settings.temperature})
        if callable(self.usage):
            self._last_usage = self.usage(system, messages)
        elif isinstance(self.usage, list) and self.usage:
            self._last_usage = self.usage[min(len(self.calls) - 1, len(self.usage) - 1)]
        else:
            self._last_usage = self.usage
        if callable(self.replies):
            reply = self.replies(system, messages)
        elif isinstance(self.replies, list):
            reply = self.replies[min(self._next, len(self.replies) - 1)]
            self._next += 1
        else:
            reply = self.replies
        if isinstance(reply, Exception):
            raise reply
        return reply


# --- what a turn did, for the trace (phase 6c) -------------------------------------------------------------------
# One TurnRecorder is made for each `Agent.respond`. The wrapper below and the tool adapter write into it; the tracer reads it after the
# turn. It never changes what a model or a tool is given or what they return, and a failure in it is caught, logged once and ignored.
log = logging.getLogger("agent.capture")
_LOGGED: set = set()
_CURRENT: contextvars.ContextVar = contextvars.ContextVar("turn_recorder", default=None)
_PURPOSE: contextvars.ContextVar = contextvars.ContextVar("model_call_purpose", default="model_call")


def log_capture_failure(where: str, err: BaseException) -> None:
    """One warning per kind of failure (and place), then silence. The text names the place and the error type only."""
    key = f"{where}:{type(err).__name__}"
    if key not in _LOGGED:
        _LOGGED.add(key)
        log.warning("trace capture failed in %s (%s); the turn is not affected. Further errors of this kind are not logged.", where, type(err).__name__)


def safely(where: str, fn, *args, **kwargs):
    """Run a capture step. An error is logged once and swallowed (None is returned); KeyboardInterrupt and SystemExit pass."""
    try:
        return fn(*args, **kwargs)
    except Exception as err:
        log_capture_failure(where, err)
        return None


def short_error(text) -> str:
    """The category of an error text (what is before the first colon, cut), never the rest: that may hold a model's words or a message."""
    return str(text).split(":")[0].strip()[:80] if text else ""


class TurnRecorder:
    """The steps of one turn in the order they started: `seq` counts from 1, `start_ms` is the time since the turn began."""

    def __init__(self):
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()
        self._seq = 0
        self.model_calls: list = []
        self.tool_calls: list = []
        self.searches: list = []
        self.answer_checks: list = []
        self.errors: list = []

    def begin(self) -> tuple:
        """(seq, start time) of a step that is starting now."""
        with self._lock:
            self._seq += 1
            return self._seq, time.perf_counter()

    def _ms(self, t: float) -> float:
        return round((t - self._t0) * 1000, 2)

    def add_model_call(self, seq: int, started: float, kind: str, configured_model: str, status: str, usage: dict | None, error_type: str | None) -> None:
        ended = time.perf_counter()
        usage = usage if isinstance(usage, dict) else {}
        reported = usage.get("model") if isinstance(usage.get("model"), str) and usage.get("model") else None
        self.model_calls.append({"seq": seq, "kind": kind, "model": reported or configured_model, "model_configured": configured_model,
                                 "input_tokens": _count(usage.get("input_tokens")), "output_tokens": _count(usage.get("output_tokens")),
                                 "cached_tokens": _count(usage.get("cached_tokens")), "start_ms": self._ms(started),
                                 "latency_ms": round((ended - started) * 1000, 2), "status": status})
        if error_type:
            self.errors.append({"where": f"model_call:{kind}", "type": error_type, "message": "the model call failed"})

    def add_tool_call(self, seq: int, started: float, name: str, status: str) -> None:
        self.tool_calls.append({"seq": seq, "name": name, "start_ms": self._ms(started),
                                "duration_ms": round((time.perf_counter() - started) * 1000, 2), "status": status})

    def snapshot(self) -> dict:
        """A copy of everything recorded so far, safe to hand to the tracer."""
        return {"model_calls": [dict(c) for c in self.model_calls], "tool_calls": [dict(c) for c in self.tool_calls],
                "searches": [dict(c) for c in self.searches], "answer_checks": [dict(c) for c in self.answer_checks],
                "errors": [dict(e) for e in self.errors]}


def current_recorder() -> TurnRecorder | None:
    return _CURRENT.get()


@contextlib.contextmanager
def recording():
    """Make a TurnRecorder the current one for this turn (and for the threads LangGraph copies the context into)."""
    recorder = safely("recorder start", TurnRecorder)
    token = _CURRENT.set(recorder)
    try:
        yield recorder
    finally:
        _CURRENT.reset(token)


@contextlib.contextmanager
def purpose(kind: str):
    """Name the model call made inside this block (router, confirm_label, refund_method_label, branch, rewrite, answer_retry)."""
    token = _PURPOSE.set(kind)
    try:
        yield
    finally:
        _PURPOSE.reset(token)


class RecordingChat(ChatModel):
    """
    Wraps a ChatModel and records each call (its kind, model, tokens, timing, status) in the current TurnRecorder. It passes the
    arguments through unchanged and returns the text unchanged, and it raises exactly what the model raised. Outside a turn it records nothing.
    """

    def __init__(self, inner: ChatModel):
        self.inner = inner

    def take_usage(self):
        return self.inner.take_usage() if hasattr(self.inner, "take_usage") else None

    def complete(self, system, messages, settings):
        recorder = _CURRENT.get()
        step = safely("model call start", recorder.begin) if recorder is not None else None
        kind = _PURPOSE.get()
        try:
            text = self.inner.complete(system, messages, settings)
        except BaseException as err:
            if step is not None:
                safely("model call end", recorder.add_model_call, step[0], step[1], kind, settings.name, "failed", None, type(err).__name__)
            raise
        if step is not None:
            usage = safely("model usage", lambda: getattr(self.inner, "take_usage", lambda: None)())
            safely("model call end", recorder.add_model_call, step[0], step[1], kind, settings.name, "ok", usage, None)
        return text
