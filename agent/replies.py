"""
replies.py - the fixed reply texts. All of them come from [replies] in config/agent.toml.

The model only picks a kind (and, for clarify, writes one short question). It never writes a reply, so
no answer can come from the model's own knowledge. None of these functions is given the customer's
message, so a reply can never repeat anything from it (important for prompt-injection and
other-customer requests).
"""
from .llm import AgentConfig


class Replies:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

    def for_kind(self, kind: str) -> str:
        """The fixed text for an out-of-scope kind. An unknown kind gets the text for "other"."""
        texts, kinds = self.cfg.replies, self.cfg.router.kinds
        if kind in kinds:
            return texts[kind]
        return texts["other" if "other" in kinds else next(iter(kinds))]

    def person_offer(self) -> str:
        return self.cfg.replies["person_offer"]

    def with_person_offer(self, reply: str) -> str:
        return f"{reply} {self.person_offer()}"

    def not_built(self, branch: str) -> str:
        return self.cfg.replies["not_built"].format(branch=branch)

    def blank_message(self) -> str:
        return self.cfg.replies["blank_message"]

    def clarify(self, question: str | None) -> str:
        """The question the model wrote (already checked by the router), or the generic one from config."""
        return question or self.cfg.router.generic_clarify
