"""
grader_support.py - the parts of the offline reply grader (phase 17). The script is scripts/24_grade_replies.py.

Plain functions, no model call in here except `grade_one`, which takes the chat model as an argument (the tests give it a fake).
Nothing in this file touches the agent: it reads config/grader.toml, config/agent.toml (prices and fixed reply texts), and a run's traces.jsonl.
"""
import csv
import json
import random
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRADER_CONFIG = ROOT / "config" / "grader.toml"
AGENT_CONFIG = ROOT / "config" / "agent.toml"
RUNS_DIR = ROOT / "data" / "experiments" / "runs"
RESULTS_DIR = ROOT / "data" / "evals" / "results"

CUT_MARKER = "..."                         # what agent/tracing.py short() puts at the end of a text it cut
EVIDENCE_KINDS = ("tool_call", "retrieval", "write")     # the step kinds that hold what a tool or a search returned
NOT_ENOUGH = "not_enough_evidence"
CRITERIA = ("answers", "grounded", "no_overpromise", "clear")
ALLOWED = {"answers": ("yes", "partly", "no"), "grounded": ("yes", "no", NOT_ENOUGH), "no_overpromise": ("yes", "no"), "clear": ("yes", "no")}
REQUIRED = ("answers", "grounded", "no_overpromise", "clear", "overall", "reason")
NOT_CAPTURED = "[not captured]"


# -- config -------------------------------------------------------------------------------------------------------------
def load_config(path: Path = GRADER_CONFIG) -> dict:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    for section, keys in {"model": ("name", "token_parameter", "max_output_tokens", "timeout_seconds", "api_key_env", "env_file"),
                          "limits": ("cost_cap_usd", "tool_output_chars", "history_exchanges", "history_chars", "reply_chars"),
                          "estimate": ("chars_per_token", "output_tokens_per_reply"), "summary": ("lowest_count", "reason_chars"),
                          "review": ("sheet_size", "lowest", "seed"), "templates": ("branches", "fixed_tables", "prefix_keys", "min_literal_chars"),
                          "prompt": ("system",)}.items():
        for key in keys:
            if key not in cfg.get(section, {}):
                raise ValueError(f"{path.name}: [{section}].{key} is missing")
    return cfg


def read_agent_toml(path: Path = AGENT_CONFIG) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def price_of(model: str, agent_raw: dict | None = None) -> dict | None:
    """{"input", "output", "cached"} in dollars per million tokens from [pricing."<model>"] of config/agent.toml, or None (never guessed)."""
    table = ((agent_raw if agent_raw is not None else read_agent_toml()).get("pricing") or {}).get(model)
    if not isinstance(table, dict) or "input_per_million" not in table or "output_per_million" not in table:
        return None
    return {"input": float(table["input_per_million"]), "output": float(table["output_per_million"]),
            "cached": float(table["cached_input_per_million"]) if "cached_input_per_million" in table else None}


def cost_usd(price: dict | None, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float | None:
    if price is None:
        return None
    cached = min(max(tokens_cached, 0), tokens_in) if price.get("cached") is not None else 0
    return ((tokens_in - cached) * price["input"] + cached * (price["cached"] or 0) + tokens_out * price["output"]) / 1_000_000


# -- reading a run ------------------------------------------------------------------------------------------------------
def resolve_run(arg: str, runs_dir: Path = RUNS_DIR) -> Path:
    """A run folder given as a path or as a name under data/experiments/runs."""
    for candidate in (Path(arg), runs_dir / arg):
        if (candidate / "traces.jsonl").is_file():
            return candidate
    raise FileNotFoundError(f"no traces.jsonl in {arg!r} (looked at the path and under {runs_dir})")


def read_turns(run_dir: Path) -> list:
    turns = []
    for line in (run_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                turns.append(json.loads(line))
            except ValueError:
                continue                       # a broken line is skipped, as the agent's own reader does
    return turns


def has_reply(turn: dict) -> bool:
    reply = turn.get("reply")
    return isinstance(reply, str) and bool(reply.strip()) and not reply.startswith(NOT_CAPTURED)


def evidence_steps(turn: dict) -> list:
    return [s for s in (turn.get("steps") or []) if s.get("kind") in EVIDENCE_KINDS]


def is_cut(text) -> bool:
    return isinstance(text, str) and text.endswith(CUT_MARKER)


def cut_evidence(turn: dict) -> bool:
    """True when any tool, search or write output of the turn ends with the cut marker: the grader did not see all of it."""
    return any(is_cut(s.get("output")) for s in evidence_steps(turn))


# -- the template flag (an inference: the agent saves none) ------------------------------------------------------------
def fixed_texts(cfg: dict, agent_raw: dict) -> tuple[list, list]:
    """(patterns, prefixes) from the fixed reply tables of config/agent.toml. A text with fields in braces becomes a pattern."""
    t = cfg["templates"]
    patterns, prefixes = [], []
    for table_name in t["fixed_tables"]:
        node = agent_raw
        for part in table_name.split("."):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        for value in (node.values() if isinstance(node, dict) else []):
            if not isinstance(value, str):
                continue
            pieces = re.split(r"\{[^{}]*\}", value)
            if sum(len(p.strip()) for p in pieces) < t["min_literal_chars"]:
                continue                       # too little fixed wording: it would match almost anything
            patterns.append(re.compile(".*?".join(re.escape(p.strip()) for p in pieces), re.DOTALL))
    for dotted in t["prefix_keys"]:
        node = agent_raw
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, str) and node.strip():
            prefixes.append(node.strip())
    return patterns, prefixes


def is_template(turn: dict, cfg: dict, patterns: list, prefixes: list) -> bool:
    if (turn.get("route") or {}).get("branch") in cfg["templates"]["branches"]:
        return True
    reply = (turn.get("reply") or "").strip()
    return any(p.fullmatch(reply) for p in patterns) or any(reply.startswith(x) for x in prefixes)


# -- the grader's input -------------------------------------------------------------------------------------------------
def clip(text, limit: int) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[:max(limit - 3, 0)] + "..."


def fence(text) -> str:
    """Keep data from closing its own block: a closing tag inside the data is broken up."""
    return str(text).replace("</data", "<\\/data")


def history_of(turns: list, index: int, cfg: dict) -> list:
    """The last N exchanges of the same session that come before turns[index]: [(message, reply), ...] oldest first."""
    n = cfg["limits"]["history_exchanges"]
    sid, found = turns[index].get("session_id"), []
    for earlier in reversed(turns[:index]):
        if earlier.get("session_id") == sid and sid is not None:
            found.append((earlier.get("message"), earlier.get("reply")))
            if len(found) == n:
                break
    return list(reversed(found))


def evidence_text(turn: dict, cfg: dict) -> str:
    limit = cfg["limits"]["tool_output_chars"]
    lines = []
    for number, s in enumerate(evidence_steps(turn), 1):
        out, mark = s.get("output"), ""
        if is_cut(out):
            mark = "  [CUT: this result ends early]"
        lines.append(f"{number}. {s.get('name')} ({s.get('kind')}, status {s.get('status')}){mark}\n   input: {clip(s.get('input'), limit)}\n"
                     f"   output: {clip(out, limit)}")
    return "\n".join(lines) if lines else "(no tool or search was used in this turn)"


def passages_text(turn: dict) -> str:
    """The passages the reply cites. The trace keeps their labels only; their text is inside the search output above."""
    rows = [f"[{p.get('number')}] {p.get('citation')} (cited: {p.get('cited')})" for p in (turn.get("passages") or [])]
    return "\n".join(rows) if rows else "(no policy passage in this turn)"


def build_message(turns: list, index: int, cfg: dict, template: bool, cut: bool) -> str:
    """The user message for one reply. Every piece of trace text is placed inside a <data> block."""
    turn, lim = turns[index], cfg["limits"]
    route = turn.get("route") or {}
    history = history_of(turns, index, cfg)
    hist = "\n".join(f"customer: {clip(m, lim['history_chars'])}\nassistant: {clip(r, lim['history_chars'])}" for m, r in history) or "(none)"
    parts = [
        f'<data name="route">\nbranch: {route.get("branch")}\nrouter label: {route.get("router_label")}\nkind: {route.get("kind")}\n'
        f'fixed template reply: {"yes" if template else "no"}\nevidence cut: {"yes" if cut else "no"}\n</data>',
        f'<data name="earlier_exchanges">\n{fence(hist)}\n</data>',
        f'<data name="customer_message">\n{fence(clip(turn.get("message"), lim["reply_chars"]))}\n</data>',
        f'<data name="tool_results">\n{fence(evidence_text(turn, cfg))}\n</data>',
        f'<data name="policy_passages">\n{fence(passages_text(turn))}\n</data>',
        f'<data name="reply_to_grade">\n{fence(clip(turn.get("reply"), lim["reply_chars"]))}\n</data>',
        "Grade the reply in <data name=\"reply_to_grade\">. Answer with the JSON object only.",
    ]
    return "\n\n".join(parts)


def estimate_tokens(text: str, cfg: dict) -> int:
    return max(1, round(len(text) / cfg["estimate"]["chars_per_token"]))


# -- the grader's answer ------------------------------------------------------------------------------------------------
def parse_grade(raw) -> tuple[dict | None, str | None]:
    """(fields, error) from the grader's text. Text around the JSON object is allowed; a missing field or a wrong value is an error."""
    if not isinstance(raw, str) or not raw.strip():
        return None, "empty answer"
    data, decoder = None, json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            value, _ = decoder.raw_decode(raw[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict):
            data = value
            break
    if data is None:
        return None, "no JSON object in the answer"
    for key in REQUIRED:
        if key not in data:
            return None, f"missing field: {key}"
    out = {}
    for key in CRITERIA:
        value = data[key].strip().lower() if isinstance(data[key], str) else data[key]
        if value not in ALLOWED[key]:
            return None, f"wrong value for {key}: {data[key]!r}"
        out[key] = value
    overall = data["overall"]
    if isinstance(overall, str) and overall.strip().isdigit():
        overall = int(overall.strip())
    if isinstance(overall, bool) or not isinstance(overall, int) or not 1 <= overall <= 5:
        return None, f"wrong value for overall: {data['overall']!r}"
    out["overall"] = overall
    out["reason"] = data["reason"] if isinstance(data["reason"], str) else ""
    for key in ("grounded_quote", "overpromise_quote"):
        out[key] = data[key] if isinstance(data.get(key), str) else ""
    return out, None


@dataclass
class Grade:
    """One graded reply, one row of the CSV."""
    turn_id: str = ""
    session_id: str = ""
    branch: str = ""
    router_label: str = ""
    kind: str = ""
    template: bool = False
    cut_evidence: bool = False
    message: str = ""
    reply: str = ""
    answers: str = ""
    grounded: str = ""
    grounded_quote: str = ""
    no_overpromise: str = ""
    overpromise_quote: str = ""
    clear: str = ""
    overall: int | None = None
    reason: str = ""
    error: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = None


GRADE_COLUMNS = list(Grade.__dataclass_fields__)


def grade_one(chat, settings, system: str, turns: list, index: int, cfg: dict, template: bool, price: dict | None) -> Grade:
    """Ask the grader about turns[index]. Never raises: a failure is recorded in `error` and the run goes on."""
    turn, route = turns[index], turns[index].get("route") or {}
    cut = cut_evidence(turn)
    g = Grade(turn_id=str(turn.get("turn_id") or ""), session_id=str(turn.get("session_id") or ""), branch=str(route.get("branch") or ""),
              router_label=str(route.get("router_label") or ""), kind=str(route.get("kind") or ""), template=template, cut_evidence=cut,
              message=str(turn.get("message") or ""), reply=str(turn.get("reply") or ""))
    message = build_message(turns, index, cfg, template, cut)
    try:
        raw = chat.complete(system, [{"role": "user", "content": message}], settings)
    except Exception as err:                                   # a failed call costs nothing here and does not stop the run
        g.error = f"model call failed ({type(err).__name__}): {str(err)[:200]}"
        return g
    usage = chat.take_usage() if hasattr(chat, "take_usage") else None
    g.tokens_in = (usage or {}).get("input_tokens") or estimate_tokens(system + message, cfg)
    g.tokens_out = (usage or {}).get("output_tokens") or estimate_tokens(raw or "", cfg)
    g.cost_usd = cost_usd(price, g.tokens_in, g.tokens_out, (usage or {}).get("cached_tokens") or 0)
    fields, error = parse_grade(raw)
    if error:
        g.error = error
        return g
    for key, value in fields.items():
        setattr(g, key, value)
    if cut:
        g.grounded, g.grounded_quote = NOT_ENOUGH, ""          # decided here, not by the grader: it did not see all the evidence
    return g


# -- the summary --------------------------------------------------------------------------------------------------------
def problem_score(g: Grade) -> int:
    """How many criteria went wrong (used to order replies that share an overall score)."""
    return ((2 if g.answers == "no" else 1 if g.answers == "partly" else 0) + (g.grounded == "no") + (g.no_overpromise == "no") + (g.clear == "no"))


def lowest(grades: list, count: int) -> list:
    graded = [g for g in grades if not g.error and g.overall is not None]
    return sorted(graded, key=lambda g: (g.overall, -problem_score(g)))[:count]


def count_by(grades: list, field_name: str) -> dict:
    out = {}
    for g in grades:
        if not g.error:
            out[getattr(g, field_name)] = out.get(getattr(g, field_name), 0) + 1
    return out


def group_table(grades: list, group_of) -> list:
    """Rows [(group, replies, answers_yes, grounded_yes, no_overpromise_yes, clear_yes, mean_overall)] for the replies without an error."""
    groups = {}
    for g in grades:
        if not g.error:
            groups.setdefault(group_of(g), []).append(g)
    rows = []
    for name in sorted(groups):
        items = groups[name]
        rows.append((name, len(items), *[sum(getattr(g, c) == "yes" for g in items) for c in CRITERIA],
                     round(sum(g.overall for g in items) / len(items), 2)))
    return rows


def summary_markdown(run_name: str, grades: list, cfg: dict, model: str) -> str:
    ok = [g for g in grades if not g.error]
    errors = len(grades) - len(ok)
    cut = sum(g.cut_evidence for g in grades if not g.error)
    spent = sum(g.cost_usd or 0 for g in grades)
    lines = [f"# Reply grades: {run_name}", "",
             f"Grader model: {model}. Replies graded: {len(ok)} of {len(grades)} ({errors} with an error). Cost: ${spent:.4f}.", "",
             f"**{cut} of {len(ok)} replies graded on cut evidence** (a tool or search output ended with the cut marker, so `grounded` is "
             f"`{NOT_ENOUGH}` for them). `answers`, `no_overpromise` and `clear` are graded as normal for those replies.", ""]
    lines += ["## Counts by criterion", "", "| Criterion | Counts |", "| --- | --- |"]
    for criterion in CRITERIA:
        lines.append(f"| {criterion} | {', '.join(f'{k}: {v}' for k, v in sorted(count_by(grades, criterion).items()))} |")
    lines.append(f"| overall | {', '.join(f'{k}: {v}' for k, v in sorted(count_by(grades, 'overall').items()))} |")
    head = ["Group", "Replies", "answers yes", "grounded yes", "no_overpromise yes", "clear yes", "Mean overall"]
    for title, group_of in (("Counts by route (the trace does not save the scenario kind; the route is what it has)", lambda g: g.branch or "(none)"),
                            ("Counts by template", lambda g: "template" if g.template else "model-written")):
        lines += ["", f"## {title}", "", "| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
        lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in group_table(grades, group_of)]
    lines += ["", f"## The {cfg['summary']['lowest_count']} lowest-scored replies to read", ""]
    width = cfg["summary"]["reason_chars"]
    for n, g in enumerate(lowest(grades, cfg["summary"]["lowest_count"]), 1):
        lines += [f"{n}. **overall {g.overall}**, route {g.branch}, turn `{g.turn_id}`" + (" (template)" if g.template else ""),
                  f"   - customer: {clip(g.message, width)}", f"   - reply: {clip(g.reply, width)}",
                  f"   - answers {g.answers}, grounded {g.grounded}, no_overpromise {g.no_overpromise}, clear {g.clear}",
                  f"   - grader: {clip(g.reason, width)}"]
        for label, quote in (("unsupported claim", g.grounded_quote), ("promise", g.overpromise_quote)):
            if quote:
                lines.append(f"   - {label}: {clip(quote, width)}")
    if errors:
        lines += ["", f"## Errors ({errors})", ""] + [f"- turn `{g.turn_id}`: {g.error}" for g in grades if g.error]
    return "\n".join(lines) + "\n"


# -- files --------------------------------------------------------------------------------------------------------------
def free_path(path: Path) -> Path:
    """`path`, or the same name with _2, _3 ... before the extension. An existing file is never overwritten."""
    if not path.exists():
        return path
    n = 2
    while path.with_name(f"{path.stem}_{n}{path.suffix}").exists():
        n += 1
    return path.with_name(f"{path.stem}_{n}{path.suffix}")


def write_grades_csv(path: Path, grades: list) -> None:
    with open(path, "x", newline="", encoding="utf-8") as f:          # "x": refuses to open a file that exists
        w = csv.DictWriter(f, fieldnames=GRADE_COLUMNS)
        w.writeheader()
        for g in grades:
            w.writerow({c: getattr(g, c) for c in GRADE_COLUMNS})


def read_grades_csv(path: Path) -> list:
    grades = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            g = Grade(**{c: row.get(c, "") for c in GRADE_COLUMNS})
            g.template, g.cut_evidence = row.get("template") == "True", row.get("cut_evidence") == "True"
            g.overall = int(row["overall"]) if row.get("overall", "").isdigit() else None
            g.tokens_in, g.tokens_out = int(row.get("tokens_in") or 0), int(row.get("tokens_out") or 0)
            g.cost_usd = float(row["cost_usd"]) if row.get("cost_usd") else None
            grades.append(g)
    return grades


def latest_grades_file(run_name: str, out_dir: Path) -> Path | None:
    """The newest reply_grades_<run>.csv (or _2, _3 ...) of a run."""
    found = [p for p in out_dir.glob(f"reply_grades_{run_name}*.csv") if re.fullmatch(rf"reply_grades_{re.escape(run_name)}(_\d+)?\.csv", p.name)]
    return max(found, key=lambda p: int(re.search(r"_(\d+)\.csv$", p.name).group(1)) if re.search(r"_(\d+)\.csv$", p.name) else 1, default=None)


# -- the review sheet and the agreement ---------------------------------------------------------------------------------
MINE = {"answers": "my_answers", "grounded": "my_grounded", "no_overpromise": "my_no_overpromise", "clear": "my_clear", "overall": "my_overall"}
SHEET_COLUMNS = ["turn_id", "pick", "branch", "template", "cut_evidence", "message", "reply", "answers", "grounded", "no_overpromise", "clear",
                 "overall", "reason", *MINE.values()]


def pick_for_review(grades: list, cfg: dict) -> list:
    """[(grade, "lowest" or "random")]: the lowest scored first, then random ones from the rest (repeatable with the seed)."""
    r = cfg["review"]
    low = lowest(grades, min(r["lowest"], r["sheet_size"]))
    taken = {id(g) for g in low}
    rest = [g for g in grades if not g.error and g.overall is not None and id(g) not in taken]
    rng = random.Random(r["seed"])
    extra = rng.sample(rest, min(len(rest), r["sheet_size"] - len(low)))
    return [(g, "lowest") for g in low] + [(g, "random") for g in extra]


def write_review_sheet(path: Path, grades: list, cfg: dict) -> int:
    picked = pick_for_review(grades, cfg)
    with open(path, "x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        w.writeheader()
        for g, how in picked:
            w.writerow({"turn_id": g.turn_id, "pick": how, "branch": g.branch, "template": g.template, "cut_evidence": g.cut_evidence,
                        "message": g.message, "reply": g.reply, "answers": g.answers, "grounded": g.grounded, "no_overpromise": g.no_overpromise,
                        "clear": g.clear, "overall": g.overall, "reason": g.reason, **{v: "" for v in MINE.values()}})
    return len(picked)


def agreement(sheet: Path) -> dict:
    """Compare the marks in the sheet with the grader's labels. A row counts for a criterion only when that mark is filled in.
    {criterion: (agreed, compared)}; for overall also "overall_within_1": (replies within one point, compared)."""
    result = {c: [0, 0] for c in (*CRITERIA, "overall", "overall_within_1")}
    with open(sheet, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for criterion, mine_col in MINE.items():
                mark = (row.get(mine_col) or "").strip().lower()
                if not mark:
                    continue
                theirs = (row.get(criterion) or "").strip().lower()
                if criterion == "grounded" and theirs == NOT_ENOUGH:
                    continue                                        # the grader gave no label here; nothing to compare
                result[criterion][1] += 1
                result[criterion][0] += mark == theirs
                if criterion == "overall":
                    result["overall_within_1"][1] += 1
                    result["overall_within_1"][0] += mark.isdigit() and theirs.isdigit() and abs(int(mark) - int(theirs)) <= 1
    return {k: tuple(v) for k, v in result.items()}
