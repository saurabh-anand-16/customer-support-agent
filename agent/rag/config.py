"""
config.py - loads config/rag.toml into typed objects.

What it does:
  1. Reads the TOML file with the standard library (`tomllib`, Python 3.11+).
  2. Applies the chosen profile (argument, else RAG_PROFILE, else `default_profile`).
  3. Rejects unknown keys, missing keys, wrong types and bad values with a clear message.
  4. Computes the index fingerprint: a hash of the settings that shape the index.

It never reads secrets. API keys stay in .env.
"""
import copy
import hashlib
import json
import os
import re
import tomllib
import typing
from dataclasses import dataclass, fields
from pathlib import Path

from .types import CHUNK_FIELDS

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PATH = ROOT / "config" / "rag.toml"
PROFILE_ENV_VAR = "RAG_PROFILE"


class ConfigError(ValueError):
    """The config file is wrong. The message says where and why."""


# --- one dataclass per [section]; the field names are the allowed keys ---------------------
@dataclass(frozen=True)
class Sources:
    policy_dir: str
    include_glob: str
    exclude_files: list[str]
    readme_file: str
    copy_date_pattern: str
    page_type_heading_level: int
    out_of_scope_files: list[str]


@dataclass(frozen=True)
class Chunking:
    strategy: str
    max_chars: int
    overlap_chars: int
    include_heading_in_text: bool
    heading_levels: list[int]
    merge_empty_headings: bool
    table_handling: str


@dataclass(frozen=True)
class Metadata:
    fields: list[str]
    heading_path_separator: str
    export_path: str


@dataclass(frozen=True)
class Text:
    remove_toc: bool
    toc_label: str
    toc_item_pattern: str
    collapse_blank_lines: bool


@dataclass(frozen=True)
class Embedding:
    provider: str
    model: str
    dimensions: int
    batch_size: int
    normalize: bool
    query_prefix: str
    cache_path: str       # embedding cache file; empty text turns the cache off
    api_key_env: str      # name of the environment variable that holds the API key (never the key itself)
    env_file: str         # file read for that variable when it is not already set


@dataclass(frozen=True)
class Store:
    kind: str
    path: str
    collection: str
    distance: str
    meta_path: str        # where the index fingerprint is also written, as JSON


@dataclass(frozen=True)
class Retrieval:
    strategy: str
    top_k: int
    candidate_k: int
    bm25_k1: float
    bm25_b: float


@dataclass(frozen=True)
class Fusion:
    method: str
    rrf_k: int
    weight_bm25: float
    weight_vector: float


@dataclass(frozen=True)
class Rerank:
    method: str
    top_n: int
    cross_encoder_model: str
    llm_model: str


@dataclass(frozen=True)
class NoMatch:
    min_score: float
    min_hits: int
    note: str


@dataclass(frozen=True)
class Citations:
    format: str
    show_copied_on: bool


SECTIONS = {
    "sources": Sources, "chunking": Chunking, "metadata": Metadata, "text": Text,
    "embedding": Embedding, "store": Store, "retrieval": Retrieval, "fusion": Fusion,
    "rerank": Rerank, "no_match": NoMatch, "citations": Citations,
}

# What goes into the index fingerprint: these sections whole (minus the keys listed next),
# plus only the model and dimensions of the embedding section.
_FINGERPRINT_SECTIONS = ["sources", "chunking", "metadata", "text"]
_NOT_IN_FINGERPRINT = {("metadata", "export_path")}   # where the CSV goes does not change the index
_FINGERPRINT_EMBEDDING_KEYS = ["model", "dimensions"]


def _as_dict(section) -> dict:
    return {f.name: getattr(section, f.name) for f in fields(section)}


@dataclass(frozen=True)
class RagConfig:
    profile: str
    root: Path
    sources: Sources
    chunking: Chunking
    metadata: Metadata
    text: Text
    embedding: Embedding
    store: Store
    retrieval: Retrieval
    fusion: Fusion
    rerank: Rerank
    no_match: NoMatch
    citations: Citations

    @property
    def fingerprint(self) -> str:
        """Hash of the settings that shape the index. Search-only settings are left out."""
        shaping = {}
        for name in _FINGERPRINT_SECTIONS:
            values = _as_dict(getattr(self, name))
            shaping[name] = {k: v for k, v in values.items() if (name, k) not in _NOT_IN_FINGERPRINT}
        emb = _as_dict(self.embedding)
        shaping["embedding"] = {k: emb[k] for k in _FINGERPRINT_EMBEDDING_KEYS}
        blob = json.dumps(shaping, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# --- type checking ------------------------------------------------------------------------
def _type_ok(value, tp) -> bool:
    if typing.get_origin(tp) is list:
        (item_type,) = typing.get_args(tp)
        return isinstance(value, list) and all(_type_ok(v, item_type) for v in value)
    if tp is bool:
        return isinstance(value, bool)
    if tp is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if tp is float:   # a whole number such as 1 is fine where a decimal is expected
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, tp)


def _type_name(tp) -> str:
    if typing.get_origin(tp) is list:
        return f"list of {_type_name(typing.get_args(tp)[0])}"
    return {str: "text", int: "whole number", float: "number", bool: "true/false"}[tp]


def _build_section(name: str, cls, data: dict, where: str):
    """Turn one table of values into its dataclass, checking keys and types."""
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: [{name}] must be a table")
    allowed = [f.name for f in fields(cls)]
    for key in data:
        if key not in allowed:
            raise ConfigError(f"{where}: unknown key '{key}' in [{name}]. Allowed keys: {', '.join(allowed)}")
    hints = typing.get_type_hints(cls)
    for key in allowed:
        if key not in data:
            raise ConfigError(f"{where}: [{name}] is missing the key '{key}'")
        if not _type_ok(data[key], hints[key]):
            raise ConfigError(
                f"{where}: [{name}].{key} must be a {_type_name(hints[key])}, got {data[key]!r}")
    kwargs = {k: float(v) if hints[k] is float else v for k, v in data.items()}
    return cls(**kwargs)


def _merge(base: dict, override: dict) -> dict:
    """Copy of `base` with the keys of `override` replaced, one table level deep."""
    merged = copy.deepcopy(base)
    for section, values in override.items():
        if not isinstance(values, dict):
            raise ConfigError(f"profile override [{section}] must be a table")
        merged.setdefault(section, {}).update(values)
    return merged


# --- value checks that go beyond types ----------------------------------------------------
def _check_values(cfg: RagConfig, where: str) -> None:
    c, m = cfg.chunking, cfg.metadata
    if c.max_chars <= 0:
        raise ConfigError(f"{where}: [chunking].max_chars must be above 0")
    if not 0 <= c.overlap_chars < c.max_chars:
        raise ConfigError(f"{where}: [chunking].overlap_chars must be 0 or more and less than max_chars")
    if c.table_handling not in ("keep_whole", "split_rows"):
        raise ConfigError(f'{where}: [chunking].table_handling must be "keep_whole" or "split_rows"')
    if any(level < 1 or level > 6 for level in c.heading_levels):
        raise ConfigError(f"{where}: [chunking].heading_levels must be numbers from 1 to 6")
    for name in m.fields:
        if name not in CHUNK_FIELDS:
            raise ConfigError(
                f"{where}: [metadata].fields has unknown field '{name}'. Allowed: {', '.join(CHUNK_FIELDS)}")
    for required in ("chunk_id", "text"):
        if required not in m.fields:
            raise ConfigError(f"{where}: [metadata].fields must include '{required}'")
    for pattern_name, pattern in (("sources.copy_date_pattern", cfg.sources.copy_date_pattern),
                                  ("text.toc_item_pattern", cfg.text.toc_item_pattern)):
        try:
            re.compile(pattern)
        except re.error as err:
            raise ConfigError(f"{where}: {pattern_name} is not a valid pattern: {err}") from err


def load_config(profile: str | None = None, path: str | Path | None = None) -> RagConfig:
    """
    Load and validate the config.

    profile: a name from [profiles.*]. If None, RAG_PROFILE is used, then `default_profile`.
    path:    config file to read. Defaults to config/rag.toml in the project root.
    """
    path = Path(path) if path else DEFAULT_PATH
    where = path.name
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as err:
        raise ConfigError(f"Config file not found: {path}") from err
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{where}: not valid TOML: {err}") from err

    default_profile = raw.pop("default_profile", None)
    if not isinstance(default_profile, str):
        raise ConfigError(f"{where}: 'default_profile' (text) is required at the top of the file")
    profiles = raw.pop("profiles", {})
    for key in raw:
        if key not in SECTIONS:
            raise ConfigError(f"{where}: unknown section [{key}]. Allowed: {', '.join(SECTIONS)}")

    chosen = profile or os.environ.get(PROFILE_ENV_VAR) or default_profile
    if chosen not in profiles:
        raise ConfigError(f"{where}: no profile named '{chosen}'. Available: {', '.join(sorted(profiles))}")
    override = profiles[chosen]
    for section in override:
        if section not in SECTIONS:
            raise ConfigError(f"{where}: profile '{chosen}' has unknown section [{section}]")

    merged = _merge(raw, override)
    built = {name: _build_section(name, cls, merged.get(name, {}), where) for name, cls in SECTIONS.items()}
    cfg = RagConfig(profile=chosen, root=ROOT, **built)
    _check_values(cfg, where)
    return cfg
