"""Validates and safely runs tool calls from a model."""

import json
import os
import random
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from pydantic import ValidationError

from agent.gate import ApprovalGate, human_approval
from agent.tools.browser import BrowserSession
from agent.tools.calculate import calculate
from agent.tools.files import FileTools
from agent.tools.registry import definitions
from agent.types import RunState, ToolCall, ToolResult


class ToolEnvironment:
    def __init__(self, project_root: Path, file_root: Path, browser: BrowserSession, evidence_dir: Path):
        self.project_root = project_root
        self.files = FileTools(file_root)
        self.browser = browser
        self.evidence_dir = evidence_dir


class Executor:
    def __init__(
        self, env: ToolEnvironment, gate: ApprovalGate,
        approval: Callable[[str, int | None, str | None], bool] = human_approval,
        read_only: bool = False, trace=None,
    ):
        self.env = env
        self.gate = gate
        self.approval = approval
        self.read_only = read_only
        self.trace = trace
        self.registry = definitions(read_only=read_only)
        self.flaky_rate = min(1.0, max(0.0, float(os.getenv("CHAOS_FLAKY_TOOL_RATE", "0"))))

    def declarations(self) -> list[dict[str, Any]]:
        return [item.declaration() for item in self.registry.values()]

    @staticmethod
    def _guard_key(action: str | None, url: str | None, amount: int | None) -> str:
        return json.dumps([action, url, amount], sort_keys=True)

    @staticmethod
    def _area_for(action: str | None, url: str | None) -> str:
        if action == "submit_po":
            return "/orders"
        return urlparse(url or "").path or "/"

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        definition = self.registry.get(call.name)
        if definition is None:
            return ToolResult(False, f"Unknown tool: {call.name}", {"type": "unknown_tool", "message": call.name})
        try:
            args = definition.model.model_validate(call.args).model_dump()
        except ValidationError as exc:
            detail = str(exc)[:1200]
            return ToolResult(False, f"Invalid arguments: {detail}", {"type": "invalid_args", "message": detail})

        risk = definition.risk
        action = call.name
        amount = None
        url = self.env.browser.page.url if self.env.browser.page else None
        if call.name == "browser_click":
            try:
                metadata = self.env.browser.target_metadata(args["element_id"])
                risk = str(metadata.get("risk") or "unannotated_write")
                action = str(metadata.get("action") or "browser_click")
                amount = metadata.get("amount")
                tag = metadata.get("tag")
                if not metadata.get("risk") and tag == "a":
                    risk = "none"
            except Exception as exc:
                return ToolResult(False, str(exc), {"type": "tool_error", "message": str(exc)}, url=url)

        if risk == "dynamic" or risk == "unannotated_write":
            risk = "unannotated_write"
        if call.name == "browser_click" and risk == "irreversible":
            key = self._guard_key(action, url, amount)
            pending = state.unknown_outcomes.get(key)
            if pending and not pending["resolved"]:
                message = "Previous attempt may have succeeded. Re-read the relevant page and confirm before retrying."
                return ToolResult(False, message, {"type": "unknown_outcome", "message": message}, risk, action, amount, url)
        decision = self.gate.decide(risk, amount)
        if self.trace:
            self.trace.log(
                "gate_decision", step=state.budget["steps"], tool=call.name,
                risk=risk, action=action, amount=amount, allowed=decision.allowed,
                needs_approval=decision.needs_approval,
                blocked_reason=decision.blocked_reason,
            )
        if decision.blocked_reason:
            return ToolResult(False, decision.blocked_reason, {"type": "blocked_by_gate", "message": decision.blocked_reason}, risk, action, amount, url)
        if decision.needs_approval:
            if self.trace:
                self.trace.log("approval_request", step=state.budget["steps"], action=action, amount=amount, url=url)
            approved = self.approval(action, amount, url)
            state.approvals.append({"step": state.budget["steps"], "action": action, "amount": amount, "url": url, "decision": "approved" if approved else "denied"})
            if not approved:
                if self.trace:
                    self.trace.log("approval_response", step=state.budget["steps"], decision="denied", action=action, amount=amount, url=url)
                return ToolResult(False, "The human denied this action.", {"type": "denied_by_user", "message": "Approval was denied."}, risk, action, amount, url)
            if self.trace:
                self.trace.log("approval_response", step=state.budget["steps"], decision="approved", action=action, amount=amount, url=url)

        if self.read_only and call.name not in {"list_files", "read_file", "search_files", "browser_open", "browser_observe", "browser_screenshot", "calculate", "report_verification"}:
            return ToolResult(False, "Verifier only permits read-only tools.", {"type": "blocked_by_gate", "message": "Read-only verifier."})

        if self.flaky_rate and random.random() < self.flaky_rate:
            return ToolResult(False, "Injected flaky-tool failure before execution.", {"type": "tool_error", "message": "Injected flaky-tool failure."}, risk, action, amount, url)

        if call.name == "browser_click" and risk == "irreversible":
            key = self._guard_key(action, url, amount)
            pending = state.unknown_outcomes.get(key)
            if pending and not pending["resolved"]:
                message = "Previous attempt may have succeeded. Re-read the relevant page and confirm before retrying."
                return ToolResult(False, message, {"type": "unknown_outcome", "message": message}, risk, action, amount, url)

        try:
            value = self._invoke(call.name, args, state)
            status = self.env.browser.last_action_status if call.name == "browser_click" else None
            if call.name == "browser_click" and status is not None and status >= 500:
                message = f"Browser action received HTTP {status}. Read the page and recover before continuing."
                if status != 500 and risk == "irreversible":
                    key = self._guard_key(action, url, amount)
                    state.unknown_outcomes[key] = {"step": state.budget["steps"], "resolved": False, "action": action, "url": url, "amount": amount, "area": self._area_for(action, url)}
                return ToolResult(False, message, {"type": "unknown_outcome" if status != 500 else "tool_error", "message": message}, risk, action, amount, url)
            if call.name in {"browser_open", "browser_observe"}:
                self._resolve_unknowns(state)
                url = self.env.browser.page.url if self.env.browser.page else url
            return ToolResult(True, str(value), risk=risk, action=action, amount=amount, url=url, data=value)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if call.name == "browser_click" and risk == "irreversible" and self.env.browser.last_action_status != 500:
                key = self._guard_key(action, url, amount)
                state.unknown_outcomes[key] = {"step": state.budget["steps"], "resolved": False, "action": action, "url": url, "amount": amount, "area": self._area_for(action, url)}
            error_type = "unknown_outcome" if call.name == "browser_click" and risk == "irreversible" and self.env.browser.last_action_status != 500 else ("timeout" if "timeout" in type(exc).__name__.lower() else "tool_error")
            return ToolResult(False, message, {"type": error_type, "message": message}, risk, action, amount, url)

    def _resolve_unknowns(self, state: RunState) -> None:
        observed_path = urlparse(self.env.browser.page.url if self.env.browser.page else "").path or "/"
        for entry in state.unknown_outcomes.values():
            area = entry.get("area", "/")
            if entry.get("action") == "submit_po":
                suffix = observed_path.removeprefix("/orders/")
                same_area = observed_path == "/orders" or (suffix.isdigit() and bool(suffix))
            else:
                same_area = observed_path == area or observed_path.startswith(area.rstrip("/") + "/")
            if not entry["resolved"] and state.budget["steps"] > entry["step"] and same_area:
                entry["resolved"] = True

    def _invoke(self, name: str, args: dict[str, Any], state: RunState) -> Any:
        if name == "list_files": return self.env.files.list_files(args["dir"])
        if name == "read_file": return self.env.files.read_file(args["path"], args["offset"])
        if name == "search_files": return self.env.files.search_files(args["query"], args["dir"])
        if name == "browser_open": return self.env.browser.open(args["url"])
        if name == "browser_observe": return self.env.browser.observe()
        if name == "browser_click":
            return self.env.browser.click(args["element_id"])
        if name == "browser_type": return self.env.browser.type_text(args["element_id"], args["text"], args["clear"])
        if name == "browser_select": return self.env.browser.select(args["element_id"], args["option"])
        if name == "browser_screenshot":
            safe_label = "".join(char for char in args["label"] if char.isalnum() or char in "-_ ").strip().replace(" ", "_")[:60] or "page"
            target = self.env.evidence_dir / f"{state.budget['steps']:03d}_{safe_label}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            path = self.env.browser.screenshot(str(target))
            state.evidence.append({"step": state.budget["steps"], "kind": "screenshot", "path": path})
            return f"Screenshot saved as evidence at {path}; image bytes were not sent to the model."
        if name == "calculate": return calculate(args["expression"])
        if name == "note":
            state.facts[args["key"]] = {"value": args["value"], "step": state.budget["steps"]}
            return f"Saved note {args['key']!r}."
        if name == "ask_user":
            print("\nThe agent needs your input:")
            print(args["question"])
            for index, option in enumerate(args["options"], 1): print(f"  {index}. {option}")
            return input("Your answer: ").strip()
        if name == "report_verification": return args
        raise ValueError(f"No handler registered for {name}.")


