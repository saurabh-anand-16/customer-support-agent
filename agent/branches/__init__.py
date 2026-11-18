"""
branches: the five flows a routed message can take (phase 4b).

BRANCHES maps a router label to the branch class that handles it. A label in config/agent.toml that is not here
still gets the "not built yet" stub from the graph. The tools each branch may use are listed in its class
(`allowed_tools`); no list contains a writer.
"""
from .base import WRITERS, Branch, BranchContext, BranchResult, Run
from .cancel_item import CancelItemBranch
from .human_help import HumanHelpBranch
from .order_status import OrderStatusBranch
from .policy_question import PolicyQuestionBranch
from .return_or_replace import ReturnOrReplaceBranch

BRANCHES = {cls.name: cls for cls in (OrderStatusBranch, PolicyQuestionBranch, ReturnOrReplaceBranch,
                                      CancelItemBranch, HumanHelpBranch)}

__all__ = ["BRANCHES", "WRITERS", "Branch", "BranchContext", "BranchResult", "Run"]
