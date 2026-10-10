"""Hand-written observe/act/adapt loop with budgets, trace, and verification."""

import json
import time
from typing import Any

from agent.prompt import render_memory
from agent.tools.registry import FinishArgs
from agent.types import LLMClient, RunState, ToolCall


class AgentLoop:
    def __init__(
        self, llm: LLMClient, executor, verifier, trace,
        max_steps: int = 40, max_seconds: int = 900, request_budget=None,
    ):
        self.llm = llm
        self.executor = executor
        self.verifier = verifier
        self.trace = trace
        self.max_steps = max_steps
        self.max_seconds = max_seconds
        self.request_budget = request_budget

    @staticmethod
    def _compact(messages: list[dict[str, Any]], state: RunState) -> list[dict[str, Any]]:
        compacted = [messages[0]] if messages else []
        tail = messages[1:]
        exchanges = []
        index = 0
        while index < len(tail):
            exchange = [tail[index]]
            if index + 1 < len(tail) and tail[index].get("role") == "model":
                exchange.append(tail[index + 1])
                index += 2
            else:
                index += 1
            exchanges.append(exchange)
        old_count = max(0, len(exchanges) - 6)
        for exchange_index, exchange in enumerate(exchanges):
            if exchange_index < old_count and len(exchange) == 2:
                model_message, result_message = exchange
                calls = [part.get("functionCall", {}).get("name") for part in model_message.get("parts", [])]
                response_parts = result_message.get("parts", [])
                for call_index, part in enumerate(response_parts):
                    response = part.get("functionResponse", {}).get("response", {})
                    result = response.get("result")
                    tool_name = calls[call_index] if call_index < len(calls) else ""
                    if isinstance(result, str) and tool_name.startswith("browser_"):
                        response["result"] = "[Earlier browser observation elided; reopen the page for current state.]"
                    elif isinstance(result, str):
                        response["result"] = result[:1500]
            compacted.extend(exchange)
        compacted.insert(1, {"role": "user", "content": render_memory(state)[:6000]})
        return compacted

    def run(self, goal: str, system: str, state: RunState) -> dict[str, Any]:
        started = time.monotonic()
        messages: list[dict[str, Any]] = [{"role": "user", "content": goal}]
        nudges = 0
        self.trace.log("run_start", goal=goal)
        final: dict[str, Any] = {"status": "failed", "summary": "Run did not reach a verified finish.", "verification": {"ok": False, "results": []}}
        try:
            for step in range(1, self.max_steps + 1):
                if time.monotonic() - started > self.max_seconds:
                    final = {"status": "failed", "summary": "Wall-clock budget reached.", "verification": {"ok": False, "results": []}}
                    break
                state.budget["steps"] = step
                if state.budget["tokens_in"] + state.budget["tokens_out"] >= state.budget["max_tokens"]:
                    final = {"status": "failed", "summary": "Token budget reached.", "verification": {"ok": False, "results": []}}
                    break
                self.trace.log("llm_request", step=step)
                response = self.llm.generate(system, self._compact(messages, state), self.executor.declarations(), 4096)
                state.budget["tokens_in"] += response.input_tokens
                state.budget["tokens_out"] += response.output_tokens
                self.trace.log("llm_response", step=step, text=response.text, tool_calls=[{"id": c.id, "name": c.name, "args": c.args} for c in response.tool_calls], input_tokens=response.input_tokens, output_tokens=response.output_tokens)
                if not response.tool_calls:
                    nudges += 1
                    messages.append({"role": "model", "parts": [{"text": response.text or ""}]})
                    if nudges > 2:
                        final = {"status": "failed", "summary": "The model did not call a tool after repeated reminders.", "verification": {"ok": False, "results": []}}
                        break
                    messages.append({"role": "user", "content": "Use an available tool, ask_user, or call finish. Do not only describe the actions."})
                    continue
                nudges = 0
                model_parts = list(response.raw_parts)
                if not model_parts:
                    if response.text:
                        model_parts.append({"text": response.text})
                    for call in response.tool_calls:
                        model_parts.append({"functionCall": {"name": call.name, "args": call.args, "id": call.id}})
                messages.append({"role": "model", "parts": model_parts})
                function_results = []
                for call in response.tool_calls:
                    self.trace.log("tool_call", step=step, tool=call.name, args=call.args)
                    if call.name == "finish":
                        try:
                            finish = FinishArgs.model_validate(call.args).model_dump()
                        except Exception as exc:
                            result_text = f"Invalid finish arguments: {exc}"
                            function_results.append({"functionResponse": {"name": "finish", "response": {"result": result_text}}})
                            continue
                        verification = self.verifier.check(goal, finish, state)
                        state.budget["tokens_in"] += verification.get("input_tokens", 0)
                        state.budget["tokens_out"] += verification.get("output_tokens", 0)
                        self.trace.log("verification", step=step, report=verification)
                        if verification.get("ok") or state.verify_rounds >= 2:
                            status = finish["status"]
                            summary_text = finish["summary"]
                            if not verification.get("ok") and status == "success":
                                status = "partial"
                                summary_text += " Verification was incomplete or found a contradiction; review the verifier evidence below."
                            final = {"status": status, "summary": summary_text, "claims": finish["claims"], "verification": verification}
                            self.trace.log("finish", step=step, status=final["status"], summary=final["summary"])
                            return self._complete(final, state, started)
                        state.verify_rounds += 1
                        report_text = json.dumps(verification, ensure_ascii=False)
                        function_results.append({"functionResponse": {"name": "finish", "response": {"result": report_text}}})
                        continue

                    result = self.executor.run(call, state)
                    self.trace.log("tool_result", step=step, tool=call.name, ok=result.ok, text=result.text[:6000], error=result.error, risk=result.risk, action=result.action, amount=result.amount, url=result.url)
                    state.history.append({"step": step, "tool": call.name, "args": call.args, "ok": result.ok, "summary": result.text[:500]})
                    if not result.ok:
                        state.errors.append({"step": step, "tool": call.name, **(result.error or {}), "message": result.text[:1000]})
                        retry_key = call.name + json.dumps(call.args, sort_keys=True)
                        state.retries[retry_key] = state.retries.get(retry_key, 0) + 1
                        if state.retries[retry_key] == 3:
                            result.text += "\nWarning: this identical action has failed three times; change approach or stop."
                        if state.retries[retry_key] >= 5:
                            result.text += "\nThe repeated-action safety cap has been reached."
                    function_results.append({"functionResponse": {"name": call.name, "response": {"result": result.text[:6000]}}})
                if function_results:
                    messages.append({"role": "user", "parts": function_results})
                if any(count >= 5 for count in state.retries.values()):
                    final = {"status": "failed", "summary": "Repeated identical tool calls reached the safety cap.", "verification": {"ok": False, "results": []}}
                    break
            else:
                final = {"status": "failed", "summary": "Maximum step budget reached.", "verification": {"ok": False, "results": []}}
        except Exception as exc:
            final = {"status": "failed", "summary": f"Run stopped after an internal error: {type(exc).__name__}: {exc}", "verification": {"ok": False, "results": []}}
            self.trace.log("error", message=final["summary"])
        return self._complete(final, state, started)

    def _complete(self, final, state, started):
        elapsed = round(time.monotonic() - started, 3)
        failed_signatures = set()
        recovered_signatures = set()
        for entry in state.history:
            signature = entry["tool"] + json.dumps(entry["args"], sort_keys=True)
            if not entry["ok"]:
                failed_signatures.add(signature)
            elif signature in failed_signatures:
                recovered_signatures.add(signature)
        summary = {**final, "run_id": state.run_id, "scenario_id": state.scenario_id, "steps": state.budget["steps"], "input_tokens": state.budget["tokens_in"], "output_tokens": state.budget["tokens_out"], "tool_errors": len(state.errors), "errors_recovered": len(recovered_signatures), "approvals": state.approvals, "evidence": state.evidence, "wall_seconds": elapsed}
        if self.request_budget is not None:
            summary["api_requests"] = self.request_budget.used
            summary["api_request_limit"] = self.request_budget.max_requests
        self.trace.log("run_end", status=summary["status"], steps=summary["steps"], wall_seconds=elapsed)
        self.trace.write_summary(summary)
        return summary

