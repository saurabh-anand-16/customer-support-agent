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
import string
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
    history_turns: int
    max_message_chars: int
    max_question_chars: int
    rewrite_follow_ups: bool
    rewrite_max_chars: int
    policy_top_k: int
    max_passage_chars: int
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
class EvalSettings:
    test_fraction: float


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
    replies: dict     # kind -> text, plus person_offer, not_built, blank_message
    eval: EvalSettings


# The labels the code itself relies on: out_of_scope picks a fixed reply, clarify asks a question.
REQUIRED_LABELS = ("out_of_scope", "clarify")
EXTRA_REPLIES = ("person_offer", "not_built", "blank_message")

# [branches]: the prompts and fixed reply texts the code needs, and the fields a reply text may contain.
BRANCH_PROMPTS = ("common", "order_status", "policy_question", "rewrite", "return_or_replace", "cancel_item")
BRANCH_REPLIES = ("no_policy_match", "sources_line", "tool_limit", "branch_error", "ask_generic", "item_not_found",
                  "ask_resolution", "confirm_return", "approval_note", "confirm_cancel", "explain_window_expired",
                  "explain_non_returnable", "explain_change_of_mind_not_allowed", "explain_not_yet_delivered",
                  "explain_return_already_opened", "explain_item_cancelled", "explain_guidance_only", "explain_other",
                  "cancel_shipped", "cancel_delivered", "cancel_cancelled", "cancel_other",
                  "escalation_not_built_late", "escalation_not_built_human")
BRANCH_RESOLUTIONS = ("refund", "replacement", "exchange", "brand_service")
BRANCH_APPROVALS = ("account_restricted", "high_value", "repeat_returner")
BRANCH_REPLY_FIELDS = {"product_name", "item_id", "order_id", "amount", "reason", "resolution", "options", "condition_note",
                       "approval_note", "approval_reasons", "order_part", "delivered_at", "day_number", "window_days",
                       "last_eligible_date", "days_late", "days_left", "return_id", "sources"}

CONFIRM_REPLIES = ("done_return", "done_return_refund_line", "done_cancel", "declined", "unclear_ask", "unclear_drop", "expired",
                   "approval_needed", "refund_method_needed", "refused")
CONFIRM_REPLY_FIELDS = {"product_name", "item_id", "order_id", "return_id", "resolution", "refund_line", "next_step", "question",
                        "message", "options", "amount", "method", "timeline"}
ANSWER_CHECK_REPLIES = ("fallback_intro", "fallback_order_line", "fallback_item_line", "fallback_return_line", "fallback_timeline_line",
                        "fallback_policy_line", "fallback_nothing")
ANSWER_CHECK_REPLY_FIELDS = {"order_id", "ordered_at", "product_name", "item_id", "item_status", "delivered_at", "return_id", "return_status",
                             "refund_line", "order_type", "refund_method", "time_text", "passage", "sources", "payment_type"}
RETRY_FIELDS = {"problems", "facts"}

_SPEC = {
    "model": (ModelSettings, {"name": str, "temperature": float, "max_output_tokens": int, "timeout_seconds": int,
                              "api_key_env": str, "env_file": str}),
    "session": (SessionSettings, {"history_keep": int, "off_topic_limit": int, "friendly_kinds": list, "offer_in_reply": list}),
    "router": (RouterSettings, {"history_turns": int, "max_message_chars": int, "max_question_chars": int,
                                "generic_clarify": str, "system_prompt": str, "labels": dict, "kinds": dict}),
    "scope": (ScopeSettings, {"statement": str}),
    "branches": (BranchSettings, {"name": str, "temperature": float, "max_output_tokens": int, "tool_round_limit": int,
                                  "history_turns": int, "max_message_chars": int, "max_question_chars": int,
                                  "rewrite_follow_ups": bool, "rewrite_max_chars": int, "policy_top_k": int,
                                  "max_passage_chars": int, "prompts": dict, "reason_texts": dict,
                                  "resolution_texts": dict, "approval_texts": dict, "replies": dict}),
    "confirm": (ConfirmSettings, {"name": str, "temperature": float, "max_output_tokens": int, "max_message_chars": int,
                                  "pending_max_turns": int, "max_unclear_asks": int, "prompt": str, "replies": dict}),
    "answer_check": (AnswerCheckSettings, {"enabled": bool, "max_retries": int, "max_facts_listed": int, "max_passage_chars": int,
                                           "allowed_text": list, "retry_instruction": str, "replies": dict}),
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
        if key not in _SPEC and key != "replies":
            raise AgentConfigError(f"{where}: unknown section [{key}]. Allowed: {', '.join([*_SPEC, 'replies'])}")
    built = {name: _build(name, raw.get(name), cls, spec, where) for name, (cls, spec) in _SPEC.items()}
    replies = raw.get("replies")
    if not isinstance(replies, dict):
        raise AgentConfigError(f"{where}: [replies] is missing or is not a table")

    cfg = AgentConfig(root=ROOT, replies=dict(replies), **built)
    _check(cfg, where)
    return cfg


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


class OpenAIChat(ChatModel):
    """The real model. Asks for a JSON object. For tests, pass a `client` shaped like openai.OpenAI()."""

    def __init__(self, root: Path = ROOT, client=None):
        self.root, self._client, self._key = root, client, None

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
            return response.choices[0].message.content or ""
        except (MissingKeyError, MissingDependencyError) as err:
            raise LlmError(str(err)) from None             # these messages name the variable or package, never the key
        except Exception as err:                            # the kind of failure, never the key
            raise LlmError(f"model call failed ({type(err).__name__}): {scrub(str(err), self._key)}") from None


class FakeChat(ChatModel):
    """
    A scripted model for tests. `replies` is one text, a list of texts used in order (the last one repeats),
    or a function (system, messages) -> text. An Exception in the list is raised instead. Every call is
    recorded in `.calls` with the system prompt, the messages and the model name and temperature it was given.
    """

    def __init__(self, replies="{}"):
        self.replies, self.calls, self._next = replies, [], 0

    def complete(self, system, messages, settings):
        self.calls.append({"system": system, "messages": messages, "model": settings.name,
                           "temperature": settings.temperature})
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
