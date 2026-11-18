"""
policy_question.py - "how does X work?" questions, answered from the policy pages.

Steps for one message:
  1. If [branches].rewrite_follow_ups is on and there are earlier exchanges, one model call turns the message into a
     standalone question ("why not?" -> "why can't a ... be returned?"). The trace records the original and the result.
  2. search_policy runs (through the adapter, out-of-scope passages never asked for). If no passage counts as an
     answer, the reply is the fixed no_policy_match text and the model is not asked anything more.
  3. The model sees the numbered passages and may call get_refund_timeline (or search again). It answers using only
     them and lists the numbers it used. The citations in the reply are written by code from the passages it used:
     a number that was not returned is dropped, and an answer with no valid citation becomes the no-match reply.
"""
from ..checks import check
from .base import (Branch, BranchContext, BranchResult, Run, ask_model, check_answer, conversation_text, fill, parse_object,
                   tool_loop)


class PolicyQuestionBranch(Branch):
    name = "policy_question"
    allowed_tools = ("search_policy", "get_refund_timeline")

    # -- step 1 ------------------------------------------------------------------------------------------
    def standalone_question(self, ctx: BranchContext, run: Run) -> str:
        b = ctx.cfg.branches
        message = ctx.message.strip()[:b.max_message_chars]
        info = {"enabled": b.rewrite_follow_ups, "called": False, "original": message, "query": message, "error": None}
        run.notes["rewrite"] = info
        if not b.rewrite_follow_ups or not ctx.session.recent(b.history_turns):
            return message
        info["called"] = True
        raw = ask_model(ctx, run, "rewrite", b.prompts["rewrite"].format(), [{"role": "user", "content": conversation_text(ctx)}])
        if raw is None:
            info["error"], run.error = run.error, None            # a failed rewrite is not fatal: use the message as it is
            return message
        data, error = parse_object(raw)
        question = (data or {}).get("question")
        if error or not isinstance(question, str) or not question.strip() or len(question.strip()) > b.rewrite_max_chars:
            info["error"] = error or "the rewritten question was empty, too long or not text"
            return message
        info["query"] = question.strip()
        return question.strip()

    # -- the passages ------------------------------------------------------------------------------------
    def add_passages(self, ctx: BranchContext, run: Run, record: dict) -> str:
        """Number the passages of one search_policy record (continuing the numbering) and return them as text."""
        limit = ctx.cfg.branches.max_passage_chars
        lines = []
        for hit in (record["output"] or {}).get("results", []):
            number = len(run.passages) + 1
            run.passages.append({"number": number, "citation": hit["citation"], "source_file": hit["source_file"],
                                 "heading_path": hit["heading_path"], "text": hit["text"], "cited": False})
            lines.append(f"[{number}] {hit['citation']}\n{hit['text'][:limit]}")
        return "\n\n".join(lines)

    def fallback(self, ctx: BranchContext, run: Run) -> BranchResult:
        """The model's answer failed the answer check: a template from the tool data (refund times, then the top passage)."""
        a, b = ctx.cfg.answer_check, ctx.cfg.branches
        lines = []
        for call in run.tool_calls:
            out = call["output"] or {}
            if call["tool"] == "get_refund_timeline" and not call["refused"] and out.get("ok") is True:
                for t in out["timelines"]:
                    lines.append(fill(a.replies["fallback_timeline_line"], order_type=out["order_type"].replace("_", " "),
                                      refund_method=t["refund_method"].replace("_", " "), time_text=t["time_text"]))
        sources = ""
        if run.passages:
            top = run.passages[0]
            passage = top["text"].strip()
            passage = passage[:a.max_passage_chars].rstrip() + ("..." if len(passage) > a.max_passage_chars else "")
            lines.append(fill(a.replies["fallback_policy_line"], passage=passage))
            top["cited"] = True
            sources = "\n" + fill(b.replies["sources_line"], sources=top["citation"])
        if not lines:
            return BranchResult(b.replies["no_policy_match"], run)
        return BranchResult("\n".join(lines) + sources, run)

    def run(self, ctx: BranchContext) -> BranchResult:
        b = ctx.cfg.branches
        run = Run()
        query = self.standalone_question(ctx, run)

        record = ctx.adapter.call(ctx.session, "search_policy", {"query": query}, self.allowed_tools)
        run.tool_calls.append(record)
        output = record["output"] or {}
        if not output.get("ok"):
            run.error = f"search_policy failed: {output.get('error_code')}"
            return self.failed(ctx, run)
        if not output.get("results"):                          # nothing counts as an answer: fixed reply, no answer call
            run.notes["no_match"] = True
            return BranchResult(b.replies["no_policy_match"], run)

        shown = self.add_passages(ctx, run, record)
        first = f"{conversation_text(ctx)}\n\nStandalone question: {query}\n\nPolicy passages:\n{shown}"

        def show_result(rec):
            if rec["tool"] == "search_policy" and (rec["output"] or {}).get("ok"):
                return self.add_passages(ctx, run, rec) or "No passage answers this."
            return None

        final = tool_loop(ctx, run, self.system_prompt(ctx), first, self.allowed_tools, show_result)
        if final is None:
            return self.failed(ctx, run)

        answer = final.get("answer")
        if isinstance(answer, str) and answer.strip():
            checked = check_answer(ctx, run, final, "answer")      # numbers, dates and file names must come from the tools
            if checked.used == "fallback":
                return self.fallback(ctx, run)
            final, answer = checked.final, checked.text
        cited = final.get("cited")
        numbers = [n for n in (cited if isinstance(cited, list) else []) if isinstance(n, int) and not isinstance(n, bool)]
        valid = sorted({n for n in numbers if 1 <= n <= len(run.passages)})
        run.notes["cited_dropped"] = [n for n in numbers if n not in valid]
        if run.notes["cited_dropped"]:
            run.checks.append(check("citations", False, f"passage number(s) {run.notes['cited_dropped']} were not returned by the search and were dropped"))
        elif valid:
            run.checks.append(check("citations", True, "every cited passage was returned by the search"))
        if not isinstance(answer, str) or not answer.strip() or not valid:
            run.notes["no_match"] = "the answer was empty or cited no returned passage"
            return BranchResult(b.replies["no_policy_match"], run)
        for n in valid:
            run.passages[n - 1]["cited"] = True
        sources = "; ".join(run.passages[n - 1]["citation"] for n in valid)
        return BranchResult(f"{answer.strip()}\n{fill(b.replies['sources_line'], sources=sources)}", run)
