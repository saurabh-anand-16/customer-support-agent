"""
branch_helpers.py - fixed settings and fakes for the phase 4b tests.

The branch tests must not depend on config/agent.toml (prompts, reply wording, round limit), because those are meant
to be tuned. They build their config from FIXED_BRANCHES, below, and change only the setting a test is about.
The policy search is a fake with canned passages, so tuning retrieval later cannot break them. Only the tests
marked LIVE FILE read the real config/agent.toml.
"""
import json

REASONS = ["damaged", "defective", "wrong_item", "not_as_described", "changed_mind"]

FIXED_BRANCHES = {
    "name": "branch-test-model", "temperature": 0.3, "max_output_tokens": 222, "tool_round_limit": 3, "history_turns": 2,
    "max_message_chars": 300, "max_question_chars": 60, "rewrite_follow_ups": True, "rewrite_max_chars": 80,
    "policy_top_k": 3, "max_passage_chars": 200,
    "prompts": {
        "common": "COMMON PROMPT. TOOLS:\n{tools}\nPROTOCOL: {{\"action\": \"final\"}}",
        "order_status": "TASK order_status",
        "policy_question": "TASK policy_question",
        "rewrite": "TASK rewrite {{\"question\": \"x\"}}",
        "return_or_replace": "TASK return_or_replace REASONS: {reasons}",
        "cancel_item": "TASK cancel_item",
    },
    "reason_texts": {r: f"REASON[{r}]" for r in REASONS},
    "resolution_texts": {r: f"DO[{r}]" for r in ("refund", "replacement", "exchange", "brand_service")},
    "approval_texts": {r: f"APPROVAL[{r}]" for r in ("account_restricted", "high_value", "repeat_returner")},
    "replies": {
        "no_policy_match": "NO-MATCH-REPLY",
        "sources_line": "SOURCES: {sources}",
        "tool_limit": "TOOL-LIMIT-REPLY",
        "branch_error": "BRANCH-ERROR-REPLY",
        "ask_generic": "ASK-GENERIC",
        "item_not_found": "ITEM-NOT-FOUND",
        "ask_resolution": "ASK-RESOLUTION {product_name} options={options}",
        "confirm_return": "CONFIRM-RETURN {resolution} | {product_name} | {item_id}{order_part} | INR {amount} | {reason} | {approval_note}{condition_note}",
        "approval_note": "NEEDS-APPROVAL({approval_reasons}) ",
        "confirm_cancel": "CONFIRM-CANCEL {product_name} | {item_id}{order_part} | INR {amount}",
        "explain_window_expired": "LATE {product_name} delivered={delivered_at} day={day_number} window={window_days} last={last_eligible_date} late={days_late}",
        "explain_non_returnable": "EXPLAIN-NON-RETURNABLE {product_name}",
        "explain_change_of_mind_not_allowed": "EXPLAIN-NO-CHANGE-OF-MIND {product_name}",
        "explain_not_yet_delivered": "EXPLAIN-NOT-DELIVERED {product_name}",
        "explain_return_already_opened": "EXPLAIN-RETURN-EXISTS {product_name} {return_id}",
        "explain_item_cancelled": "EXPLAIN-CANCELLED {product_name}",
        "explain_guidance_only": "EXPLAIN-BRAND-SERVICE {product_name}",
        "explain_other": "EXPLAIN-OTHER {product_name}",
        "cancel_shipped": "CANCEL-SHIPPED {product_name}",
        "cancel_delivered": "CANCEL-DELIVERED {product_name}",
        "cancel_cancelled": "CANCEL-ALREADY {product_name}",
        "cancel_other": "CANCEL-OTHER {product_name}",
    },
}


# --- what a scripted model says ------------------------------------------------------------------------
def call(tool, **arguments) -> str:
    return json.dumps({"action": "call_tool", "tool": tool, "arguments": arguments})


def final(**fields) -> str:
    return json.dumps({"action": "final", **fields})


def router(route, **extra) -> str:
    return json.dumps({"route": route, "reason": "because", **extra})


# --- a fake policy search --------------------------------------------------------------------------------
PASSAGES = [
    {"source_file": "refund-policy.md", "heading_path": "Refunds > Timing", "text": "Refunds take up to 5 working days. " * 4,
     "score": 9.0, "copied_on": "2026-01-01", "in_scope": True, "provenance": {}},
    {"source_file": "returns-policy.md", "heading_path": "Returns > Window", "text": "Items can be returned within the window.",
     "score": 7.0, "copied_on": "2026-01-02", "in_scope": True, "provenance": {}},
    {"source_file": "third-party-seller-returns.md", "heading_path": "Seller > Steps", "text": "Contact the seller.",
     "score": 6.0, "copied_on": "2026-01-03", "in_scope": False, "provenance": {}},
]


class FakePolicy:
    """Stands in for PolicySearch. `results` is what a search returns (or [] for a no-match); every query is recorded."""

    def __init__(self, results=None, ok=True):
        self.results = PASSAGES[:2] if results is None else results
        self.ok, self.queries, self.kwargs = ok, [], []

    def search_policy(self, query, top_k=None, include_out_of_scope=False):
        self.queries.append(query)
        self.kwargs.append({"top_k": top_k, "include_out_of_scope": include_out_of_scope})
        if not self.ok:
            return {"ok": False, "error_code": "index_out_of_date", "error": "The index is out of date."}
        out = {"ok": True, "query": query, "profile": "fake", "index_fingerprint": "x", "results": list(self.results)}
        if not self.results:
            out["note"] = "No passage answers this."
        return out

    def citation(self, result):
        return f"{result['heading_path']} ({result['source_file']})"


# --- phase 4c: the confirm step and the answer check (fixed, recognisable wording; the tests never read config/agent.toml) ---
FIXED_CONFIRM = {
    "name": "confirm-test-model", "temperature": 0.1, "max_output_tokens": 77, "max_message_chars": 100, "pending_max_turns": 3,
    "max_unclear_asks": 1, "prompt": "CONFIRM PROMPT {\"label\": \"x\"}",
    "replies": {
        "done_return": "DONE-RETURN {resolution} | {product_name} | {item_id} | {return_id} | {refund_line}{next_step}",
        "done_return_refund_line": "REFUND INR {amount} to {method} in {timeline}. ",
        "done_cancel": "DONE-CANCEL {product_name} | {item_id} | {next_step}",
        "declined": "DECLINED-NOTHING-DONE",
        "unclear_ask": "UNCLEAR-ASK {question}",
        "unclear_drop": "UNCLEAR-DROPPED",
        "expired": "EXPIRED-NOTHING-DONE",
        "refund_method_needed": "REFUND-METHOD-NEEDED {options}",
        "refused": "REFUSED {message}",
    },
}

FIXED_ANSWER_CHECK = {
    "enabled": True, "max_retries": 1, "max_facts_listed": 30, "max_passage_chars": 60, "allowed_text": [],
    "retry_instruction": "RETRY. PROBLEMS: {problems}. FACTS: {facts}.",
    "replies": {
        "fallback_intro": "FALLBACK-INTRO",
        "fallback_order_line": "ORDER {order_id} placed {ordered_at}",
        "fallback_item_line": "ITEM {product_name} | {item_id} | {item_status}{delivered_at}",
        "fallback_return_line": "RETURN {return_id} | {product_name} | {item_id} | {return_status}{refund_line}",
        "fallback_timeline_line": "TIMELINE {order_type} | {refund_method} | {time_text}",
        "fallback_policy_line": "POLICY: {passage}",
        "fallback_nothing": "FALLBACK-NOTHING",
    },
}


# --- phase 5a: the review queue (fixed, recognisable wording; the tests never read config/agent.toml) ---
FIXED_REVIEW = {
    "excerpt_messages": 4, "excerpt_message_chars": 40, "dedupe_open_items": True,
    "reply_template": "QUEUED-FOR-A-PERSON ref={reference}",
    "error_reply": "QUEUE-WRITE-FAILED",
    "reasons": {
        "customer_asked_for_person": "REASON person",
        "late_request": "REASON late item={item_id} day={day_number} window={window_days} late={days_late} last={last_eligible_date}",
        "approval_required": "REASON approval {resolution} item={item_id} because={approval_reasons}",
    },
}


# --- phase 4d: the refund-method question (fixed, recognisable wording; the tests never read config/agent.toml) ---
FIXED_REFUND_METHOD = {
    "name": "method-test-model", "temperature": 0.2, "max_output_tokens": 55, "max_message_chars": 100,
    "not_offered": ["paper_cheque"], "escalation_kind": "customer_asked_for_person",
    "prompt": "METHOD PROMPT {\"label\": \"x\"}",
    "option_texts": {"neft_bank_account": "OPT-NEFT", "amazon_pay_balance": "OPT-PAYBAL"},
    "notes": {"neft_bank_account": "NOTE-NEFT-ACCOUNT-MUST-BE-ADDED"},
    "replies": {
        "ask": "ASK-METHOD {product_name} | {options}",
        "chosen_line": "METHOD-CHOSEN {method} {note}",
        "cheque_reply": "CHEQUE-EXCEPTIONAL ref={reference}",
    },
}
