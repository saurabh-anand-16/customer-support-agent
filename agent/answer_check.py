"""
answer_check.py - are the numbers, money amounts, dates and citations in a model-written reply backed by the tools?

Pure functions, no model and no database. The branch (agent/branches/base.py) uses them like this:

  facts    = facts_from(tool_calls, today, extra_texts)   what this turn's SUCCESSFUL tool results (and config text) say
  problems = find_problems(reply, facts)                  every number, money amount, date or citation not backed

A tool result with ok False is not a source: a number that depends on a failed call has no support. Only the result's
values count, never its keys. Dates are taken out of a text before its numbers are read, so "2026-11-17" does not make
2026, 11 or 17 acceptable as plain numbers. A word with letters and digits ("OI000001", "R000012") is an id, not a number.
Formats are compared by value: INR 1,099 and 1099.00 are the same amount; 17 Nov, 17 November 2026 and 2026-11-17 are
the same date (a date without a year matches on day and month). Number words ("five") are not read: a known gap.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTH = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"

_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\b\.?(?:,?\s+(\d{{4}})\b)?", re.I)
_MONTH_DAY = re.compile(rf"\b{_MONTH}\b\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}})\b)?", re.I)
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")              # day first, as written in India
_NUMBER = re.compile(r"(?<![\w.])((?:₹|Rs\.?|INR)\s*)?(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:st|nd|rd|th)?(?!\w)", re.I)
_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s+")
_SOURCE_FILE = re.compile(r"\b[\w\-]+\.md\b")


@dataclass(frozen=True)
class Problem:
    kind: str          # "number", "money", "date" or "citation"
    text: str          # as written in the reply
    why: str

    def __str__(self) -> str:
        return f"{self.text} ({self.why})"


@dataclass
class Facts:
    numbers: set = field(default_factory=set)        # Decimal values
    dates: set = field(default_factory=set)          # datetime.date (a date written without a year is kept in year 2000)
    sources: set = field(default_factory=set)        # policy files named by a search result of the turn


# --- reading a text ------------------------------------------------------------------------------------------
def _month(word: str) -> int:
    return MONTHS[word[:3].lower()]


def _valid(year, month, day) -> bool:
    try:
        date(year if year else 2000, month, day)      # 2000 is a leap year, so 29 Feb without a year is accepted
        return True
    except ValueError:
        return False


def read_dates(text: str):
    """([(year or None, month, day, as written, is a real date)], the text with the dates blanked out)."""
    found = []

    def take(pattern, build):
        nonlocal text

        def repl(m):
            year, month, day = build(m)
            found.append((year, month, day, m.group(0).strip(" ,."), _valid(year, month, day)))
            return " "
        text = pattern.sub(repl, text)

    take(_ISO, lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3))))
    take(_NUMERIC_DATE, lambda m: (int(m.group(3)), int(m.group(2)), int(m.group(1))))
    take(_DAY_MONTH, lambda m: (int(m.group(3)) if m.group(3) else None, _month(m.group(2)), int(m.group(1))))
    take(_MONTH_DAY, lambda m: (int(m.group(3)) if m.group(3) else None, _month(m.group(1)), int(m.group(2))))
    return found, text


def read_numbers(text: str) -> list:
    """[(Decimal value, as written, is money)] for each number in a text that has no dates in it."""
    text = _LIST_MARKER.sub("", text)
    out = []
    for m in _NUMBER.finditer(text):
        try:
            out.append((Decimal(m.group(2).replace(",", "")), m.group(0).strip(), bool(m.group(1))))
        except InvalidOperation:
            continue
    return out


# --- what the tools say ----------------------------------------------------------------------------------------
def _walk(value, texts: list, numbers: set):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers.add(Decimal(str(value)))
    elif isinstance(value, str):
        texts.append(value)
    elif isinstance(value, dict):
        for v in value.values():              # values only, never keys
            _walk(v, texts, numbers)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk(v, texts, numbers)


def _add_text(facts: Facts, text: str) -> None:
    dates, rest = read_dates(text)
    for year, month, day, _, valid in dates:
        if valid:
            facts.dates.add(date(year or 2000, month, day))
    for value, _, _ in read_numbers(rest):
        facts.numbers.add(value)


def facts_from(tool_calls: list, today: date | None = None, extra_texts=()) -> Facts:
    """What the turn's successful tool results, today's date and the config texts allow."""
    facts = Facts()
    for call in tool_calls:
        output = call.get("output")
        if call.get("refused") or not isinstance(output, dict) or output.get("ok") is not True:
            continue                          # a refused or failed call supports nothing
        texts, numbers = [], set()
        _walk(output, texts, numbers)
        facts.numbers |= numbers
        for text in texts:
            _add_text(facts, text)
        if call.get("tool") == "search_policy":
            facts.sources |= {r["source_file"] for r in output.get("results", []) if isinstance(r, dict) and r.get("source_file")}
    for text in extra_texts:
        _add_text(facts, text)
    if today is not None:
        facts.dates.add(today)
    return facts


def _date_supported(year, month, day, facts: Facts) -> bool:
    if year:
        return date(year, month, day) in facts.dates
    return any(d.month == month and d.day == day for d in facts.dates)


# --- the check ----------------------------------------------------------------------------------------------------
def find_problems(text: str, facts: Facts) -> list:
    """Every value in `text` that the facts do not back. An empty list means the text passes."""
    problems = []
    dates, rest = read_dates(text)
    for year, month, day, written, valid in dates:
        if not valid:
            problems.append(Problem("date", written, "not a real date"))
        elif not _date_supported(year, month, day, facts):
            problems.append(Problem("date", written, "not a date in the tool results"))
    for value, written, money in read_numbers(rest):
        if value not in facts.numbers:
            problems.append(Problem("money" if money else "number", written, "not in the tool results"))
    for name in _SOURCE_FILE.findall(text):
        if name not in facts.sources:
            problems.append(Problem("citation", name, "not a page the policy search returned"))
    return problems


def describe_problems(problems: list) -> str:
    return "; ".join(str(p) for p in problems)


def describe_facts(facts: Facts, limit: int) -> str:
    """The allowed numbers and dates as one line for the retry message (at most `limit` values, numbers first)."""
    numbers = [f"{n.normalize():f}" for n in sorted(facts.numbers)]
    dates = [d.isoformat() if d.year != 2000 else f"{d.day:02d}-{d.month:02d}" for d in sorted(facts.dates)]
    shown = [*numbers, *dates][:limit]
    return ", ".join(shown) if shown else "(none: there are no facts for this turn, so leave out every number, amount and date)"
