"""
tool_adapter.py - the safe view of the tools that the model gets.

The model never calls `ReturnsTools` directly. It asks this adapter, which

  * shows it schemas that do not contain `customer_id`, `confirmed` or `staff_approved` (and nothing else that is not
    an argument the user could sensibly give: the schemas are written out below, never taken from the tools' own code);
  * fills `customer_id` in from the SESSION and drops any argument that is not in the schema (those three, or anything
    else) if the model supplies one, recording that it did;
  * refuses a tool that is not in the calling branch's list, and a tool that does not exist (which includes the two
    writers, `create_return` and `cancel_order`: they are not in this module's table at all);
  * strips `customer_id` out of every result before the model, the evidence or the trace sees it;
  * wraps `PolicySearch.search_policy` as the `search_policy` tool (out-of-scope passages are never asked for).

It never raises for something the model did: a refusal or a bad argument comes back as a record with ok False.
"""
from dataclasses import dataclass
from typing import Callable

from .eligibility import REASONS

# Names that must never be in a schema shown to the model, and are dropped if the model sends them anyway
# (any argument that is not in a tool's schema is dropped, these three included).
FORBIDDEN = ("customer_id", "confirmed", "staff_approved")
# Keys removed from every tool result before anything else sees it.
HIDDEN_IN_RESULTS = ("customer_id",)


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    properties: dict          # JSON-schema properties the model may fill in
    required: tuple
    run: Callable             # run(adapter, customer_id, args) -> dict


def _hide(value):
    """A copy of a tool result without the keys the model must never see."""
    if isinstance(value, dict):
        return {k: _hide(v) for k, v in value.items() if k not in HIDDEN_IN_RESULTS}
    if isinstance(value, list):
        return [_hide(v) for v in value]
    return value


def _bad(message: str) -> dict:
    return {"ok": False, "error_code": "invalid_argument", "message": message}


def _text(args: dict, key: str, optional: bool = False):
    value = args.get(key)
    if value is None and optional:
        return None, None
    if not isinstance(value, str) or not value.strip():
        return None, _bad(f"'{key}' must be non-empty text")
    return value.strip(), None


class ToolAdapter:
    def __init__(self, tools=None, policy_search=None, tools_factory=None, policy_factory=None, top_k: int = 4):
        """
        `tools` is a ReturnsTools and `policy_search` a PolicySearch (or fakes with the same methods). Either can
        be given later through a factory, so nothing is opened until a tool is really used.
        """
        self._tools, self._policy = tools, policy_search
        self._tools_factory, self._policy_factory = tools_factory, policy_factory
        self.top_k = top_k
        self._defs = {d.name: d for d in self._build_defs()}

    # -- the things behind the tools ---------------------------------------------------------------
    @property
    def tools(self):
        if self._tools is None:
            self._tools = self._tools_factory()
        return self._tools

    @property
    def policy(self):
        if self._policy is None:
            self._policy = self._policy_factory()
        return self._policy

    # -- what the model may see --------------------------------------------------------------------
    def names(self) -> list[str]:
        return list(self._defs)

    def schema(self, name: str) -> dict:
        d = self._defs[name]
        return {"type": "function", "function": {
            "name": d.name, "description": d.description,
            "parameters": {"type": "object", "properties": d.properties, "required": list(d.required),
                           "additionalProperties": False}}}

    def schemas(self, allowed) -> list[dict]:
        return [self.schema(name) for name in allowed if name in self._defs]

    def describe(self, allowed) -> str:
        """The tool list as text for a prompt: a name, what it does, and its arguments."""
        lines = []
        for name in allowed:
            d = self._defs[name]
            args = ", ".join(f"{k} ({v.get('type', 'text')}{'' if k in d.required else ', optional'})" for k, v in d.properties.items())
            lines.append(f"  - {d.name}({args}): {d.description}")
        return "\n".join(lines)

    # -- a call ------------------------------------------------------------------------------------
    def call(self, session, name, arguments, allowed) -> dict:
        """
        Run one tool for the model. Returns a record:
          {"tool", "input" (what was really passed, without customer id), "dropped_arguments" (names the model sent
           that were not allowed), "output" (customer id removed), "refused" (None or why)}
        """
        record = {"tool": name if isinstance(name, str) else str(name), "input": {}, "dropped_arguments": [],
                  "output": None, "refused": None}
        args = arguments if isinstance(arguments, dict) else {}
        if not isinstance(name, str) or name not in self._defs:
            record["refused"] = "unknown tool"
            record["dropped_arguments"] = sorted(args)
            record["output"] = {"ok": False, "error_code": "unknown_tool", "message": "There is no such tool."}
            return record
        if name not in allowed:
            record["refused"] = "not allowed in this branch"
            record["dropped_arguments"] = sorted(args)
            record["output"] = {"ok": False, "error_code": "tool_not_allowed", "message": "This tool cannot be used here."}
            return record
        d = self._defs[name]
        record["dropped_arguments"] = sorted(k for k in args if k not in d.properties)
        clean = {k: v for k, v in args.items() if k in d.properties}
        record["input"] = clean
        missing = [k for k in d.required if clean.get(k) in (None, "")]
        if missing:
            record["output"] = _bad(f"missing argument(s): {', '.join(missing)}")
            return record
        try:
            output = d.run(self, session.customer_id, clean)      # the id comes from the session, never from `args`
        except Exception as err:                                   # a tool that fails must not end the conversation
            output = {"ok": False, "error_code": "tool_error", "message": f"The tool failed ({type(err).__name__})."}
        record["output"] = _hide(output)
        return record

    # -- the tools ---------------------------------------------------------------------------------
    def _build_defs(self) -> list[ToolDef]:
        def list_orders(a, cid, args):
            limit = args.get("limit", 10)
            if not isinstance(limit, int) or isinstance(limit, bool):
                return _bad("'limit' must be a whole number")
            return a.tools.list_orders(cid, limit)

        def get_order(a, cid, args):
            order_id, err = _text(args, "order_id")
            return err or a.tools.get_order(cid, order_id)

        def check_eligibility(a, cid, args):
            item_id, err = _text(args, "item_id")
            if err:
                return err
            reason, err = _text(args, "reason")
            return err or a.tools.check_eligibility(cid, item_id, reason)

        def get_refund_timeline(a, cid, args):
            order_type, err = _text(args, "order_type")
            if err:
                return err
            method, err = _text(args, "refund_method", optional=True)
            return err or a.tools.get_refund_timeline(order_type, method)

        def get_return_status(a, cid, args):
            item_id, err = _text(args, "item_id", optional=True)
            if err:
                return err
            return_id, err = _text(args, "return_id", optional=True)
            return err or a.tools.get_return_status(cid, item_id, return_id)

        def search_policy(a, cid, args):
            query, err = _text(args, "query")
            if err:
                return err
            found = a.policy.search_policy(query, top_k=a.top_k)       # never include_out_of_scope
            if not found.get("ok"):
                return {"ok": False, "error_code": found.get("error_code", "search_failed"), "message": found.get("error", "Search failed.")}
            results = [{"source_file": r["source_file"], "heading_path": r["heading_path"], "text": r["text"],
                        "copied_on": r.get("copied_on"), "citation": a.policy.citation(r)}
                       for r in found.get("results", []) if r.get("in_scope", True)]
            out = {"ok": True, "query": query, "results": results}
            if not results:
                out["note"] = found.get("note", "No policy passage answers this.")
            return out

        return [
            ToolDef("list_orders", "The customer's most recent orders, newest first, with the items of each.",
                    {"limit": {"type": "integer", "description": "how many orders (1 to 25)"}}, (), list_orders),
            ToolDef("get_order", "One order with its items: status, delivery date, price, whether an item can be cancelled.",
                    {"order_id": {"type": "string"}}, ("order_id",), get_order),
            ToolDef("check_eligibility", "Whether one item can be returned or replaced for one reason. This is the only source of that decision.",
                    {"item_id": {"type": "string"}, "reason": {"type": "string", "enum": list(REASONS)}},
                    ("item_id", "reason"), check_eligibility),
            ToolDef("get_refund_timeline", "How long a refund takes, in the policy's own words.",
                    {"order_type": {"type": "string", "enum": ["prepaid", "pay_on_delivery"]},
                     "refund_method": {"type": "string", "description": "for example upi, credit_debit_card"}},
                    ("order_type",), get_refund_timeline),
            ToolDef("get_return_status", "The status of a return that already exists, by item or by return id.",
                    {"item_id": {"type": "string"}, "return_id": {"type": "string"}}, (), get_return_status),
            ToolDef("search_policy", "Search the policy pages for passages that explain a rule. Explanations only, not numbers for an order.",
                    {"query": {"type": "string"}}, ("query",), search_policy),
        ]
