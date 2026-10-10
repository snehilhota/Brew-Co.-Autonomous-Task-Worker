"""Code-enforced risk decisions. Model text never counts as approval."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class GateDecision:
    allowed: bool
    needs_approval: bool = False
    blocked_reason: str | None = None


class ApprovalGate:
    def __init__(self, config_path: Path):
        self.config = json.loads(config_path.read_text(encoding="utf-8"))

    def decide(self, risk: str, amount: int | None) -> GateDecision:
        if risk in {"none", "reversible"}:
            return GateDecision(True)
        if risk == "unannotated_write":
            return GateDecision(False, needs_approval=True)
        if risk != "irreversible":
            return GateDecision(False, blocked_reason="Unknown risk annotation; fail closed.")
        if amount is None:
            return GateDecision(False, needs_approval=True)
        policy = self.config["irreversible"]
        if amount > policy["hard_block_min_amount"]:
            return GateDecision(False, blocked_reason=(
                f"Amount ₹{amount} exceeds the hard block threshold of "
                f"₹{policy['hard_block_min_amount']}. Escalate to the owner."
            ))
        if amount > policy["auto_allow_max_amount"]:
            return GateDecision(False, needs_approval=True)
        return GateDecision(True)


def human_approval(action: str, amount: int | None, url: str | None) -> bool:
    print("\nApproval required by the in-code risk policy.")
    print(f"Action: {action or 'unannotated write'} | Amount: {amount if amount is not None else 'unknown'} | Page: {url or 'unknown'}")
    return input("Type APPROVE to continue, or anything else to deny: ").strip() == "APPROVE"

