"""
config.py - the app's settings: the [app] section of config/agent.toml, and the personas file.

The agent's own loader lets the [app] section be there but does not read it. This module reads it, checks that
every key is present and is text, and turns the paths into absolute ones. Nothing here reads the API key.
"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "agent.toml"
PERSONAS_FILE = Path(__file__).resolve().parent / "personas.toml"

_KEYS = ("source_db_path", "demo_db_path", "corner_tag", "fixed_date_line", "waiting_line", "error_reply", "missing_key_help", "manager_label", "claim_stale_minutes", "poll_seconds", "close_without_reply_note", "suggested_messages")


class AppConfigError(ValueError):
    """The [app] section or the personas file is wrong. The message says where."""


@dataclass(frozen=True)
class AppSettings:
    source_db: Path          # the real database (only ever copied from)
    demo_db: Path            # the copy the app works on
    corner_tag: str
    fixed_date_line: str
    waiting_line: str
    error_reply: str
    missing_key_help: str
    root: Path = ROOT
    manager_label: str = "Manager (demo)"     # phase 8: decided_by of the Manager page
    claim_stale_minutes: int = 10             # phase 8: a claim older than this looks stuck
    poll_seconds: int = 3                     # phase 8b: how often the chat and the sidebar look for news (a Streamlit fragment, no JavaScript)
    suggested_messages: tuple = ("Where is my refund?",)   # phase 8c: the general chips under the chat box (from [app].suggested_messages)
    close_without_reply_note: str = "Closed without a reply."   # phase 8b: the private note "Close without a reply" records (decide() needs a note)


def product_name_limit(path: Path | None = None) -> int:
    """[review].product_name_max_chars: the one length a product name is cut to on a card, a header or a notice (phase 8c)."""
    with open(Path(path) if path else CONFIG_FILE, "rb") as f:
        value = tomllib.load(f).get("review", {}).get("product_name_max_chars", 60)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 10 else 60


def load_app_settings(path: Path | None = None) -> AppSettings:
    path = Path(path) if path else CONFIG_FILE
    with open(path, "rb") as f:
        raw = tomllib.load(f).get("app")
    if not isinstance(raw, dict):
        raise AppConfigError(f"{path.name}: the [app] section is missing")
    for key in raw:
        if key not in _KEYS:
            raise AppConfigError(f"{path.name}: unknown key '{key}' in [app]. Allowed: {', '.join(_KEYS)}")
    for key in _KEYS:
        if key == "suggested_messages":
            continue                                                  # checked below
        if key in ("claim_stale_minutes", "poll_seconds"):
            if not isinstance(raw.get(key), int) or isinstance(raw.get(key), bool) or raw[key] < 1:
                raise AppConfigError(f"{path.name}: [app].{key} must be a whole number, 1 or more")
        elif not isinstance(raw.get(key), str) or not raw[key].strip():
            raise AppConfigError(f"{path.name}: [app].{key} must be non-empty text")
    chips = raw.get("suggested_messages")
    if not isinstance(chips, list) or not chips or not all(isinstance(c, str) and c.strip() for c in chips):
        raise AppConfigError(f"{path.name}: [app].suggested_messages must be a list of non-empty text")
    root = path.resolve().parent.parent
    return AppSettings(suggested_messages=tuple(chips), source_db=root / raw["source_db_path"], demo_db=root / raw["demo_db_path"], corner_tag=raw["corner_tag"],
                       fixed_date_line=raw["fixed_date_line"], waiting_line=raw["waiting_line"], error_reply=raw["error_reply"],
                       missing_key_help=raw["missing_key_help"], root=root,
                       manager_label=raw["manager_label"].strip(), claim_stale_minutes=raw["claim_stale_minutes"],
                       poll_seconds=raw["poll_seconds"], close_without_reply_note=raw["close_without_reply_note"].strip())


@dataclass(frozen=True)
class Persona:
    customer_id: str
    label: str          # short label shown in the picker and in "Now playing"
    hint: str           # one line about the situation; no amounts, items or days
    title: str          # card title
    story: str          # card text; no amounts, items or days
    start_here: bool = False
    card: bool = True   # False: only in the "any customer" list (a hint, no card)
    item_id: str | None = None   # optional: the story item; the card and the chat header read it live
    try_text: str | None = None  # phase 8c: optional first message a customer could type; Home shows it, the chat offers it as the first chip


def load_personas(path: Path | None = None) -> list[Persona]:
    path = Path(path) if path else PERSONAS_FILE
    with open(path, "rb") as f:
        rows = tomllib.load(f).get("persona")
    if not isinstance(rows, list) or not rows:
        raise AppConfigError(f"{path.name}: no [[persona]] entries")
    out, seen = [], set()
    for row in rows:
        cid = row.get("customer_id")
        if not isinstance(cid, str) or not cid:
            raise AppConfigError(f"{path.name}: a persona has no customer_id")
        if cid in seen:
            raise AppConfigError(f"{path.name}: {cid} is listed twice")
        seen.add(cid)
        card = bool(row.get("card", True))
        need = ("label", "hint") + (("title", "story") if card else ())
        for key in need:
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise AppConfigError(f"{path.name}: {cid} needs '{key}' (text)")
        if row.get("try") is not None and (not isinstance(row["try"], str) or not row["try"].strip()):
            raise AppConfigError(f"{path.name}: {cid} has a 'try' that is not text")
        out.append(Persona(cid, row["label"], row["hint"], row.get("title", ""), row.get("story", ""), bool(row.get("start_here", False)), card, row.get("item_id"), (row.get("try") or None)))
    return out
