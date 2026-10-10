"""Fresh-context, read-only verification of final claims."""

import json
from typing import Any

from agent.executor import Executor
from agent.prompt import render_system_prompt
from agent.types import LLMClient, RunState, ToolCall


class Verifier:
    def __init__(self, llm: LLMClient, executor: Executor, brief: str, trace=None, max_steps: int = 8):
        self.llm = llm
        self.executor = executor
        self.system = render_system_prompt(brief) + "\nYou are now the independent verifier. Use only read-only tools. Never change state. Check each claim and report confirmed, contradicted, or unverifiable with concise evidence. Finish by calling report_verification."
        self.trace = trace
        self.max_steps = max_steps

    def check(self, goal: str, finish_args: dict[str, Any], parent_state: RunState) -> dict[str, Any]:
        claims = finish_args.get("claims", [])
        if not claims:
            return {"ok": False, "results": [], "message": "No claims were supplied for independent verification."}
        state = RunState(run_id=parent_state.run_id, goal=goal)
        messages: list[dict[str, Any]] = [{"role": "user", "content": json.dumps({"goal": goal, "claims": claims}, ensure_ascii=False)}]
        input_tokens = output_tokens = 0
        for step in range(1, self.max_steps + 1):
            response = self.llm.generate(self.system, messages, self.executor.declarations(), 2048)
            input_tokens += response.input_tokens
            output_tokens += response.output_tokens
            if self.trace:
                self.trace.log("verification_llm_response", step=step, text=response.text, tool_calls=[{"name": call.name, "args": call.args} for call in response.tool_calls], input_tokens=response.input_tokens, output_tokens=response.output_tokens)
            parts = list(response.raw_parts)
            if not parts and response.text:
                parts.append({"text": response.text})
            if response.tool_calls and not response.raw_parts:
                for call in response.tool_calls:
                    parts.append({"functionCall": {"name": call.name, "args": call.args, "id": call.id}})
            if parts:
                messages.append({"role": "model", "parts": parts})
            if not response.tool_calls:
                continue
            results = []
            for call in response.tool_calls:
                if call.name == "report_verification":
                    try:
                        report = self.executor.registry[call.name].model.model_validate(call.args).model_dump()
                        reported = {item["claim"].strip().casefold(): item for item in report["results"]}
                        complete_results = []
                        for requested in claims:
                            claim_text = requested.get("claim", "").strip()
                            checked = reported.get(claim_text.casefold())
                            if checked is None:
                                complete_results.append({
                                    "claim": claim_text,
                                    "status": "unverifiable",
                                    "evidence": "Verifier omitted this claim.",
                                })
                            else:
                                complete_results.append(checked)
                        all_confirmed = bool(complete_results) and all(
                            item["status"] == "confirmed" for item in complete_results
                        )
                        return {
                            "ok": all_confirmed,
                            "results": complete_results,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                        }
                    except Exception as exc:
                        if self.trace:
                            self.trace.log("verification_error", message=str(exc))
                        continue
                result = self.executor.run(call, state)
                results.append({"functionResponse": {"name": call.name, "response": {"result": result.text}}})
            if results:
                messages.append({"role": "user", "parts": results})
        return {
            "ok": False,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "results": [{"claim": item.get("claim", ""), "status": "unverifiable", "evidence": "Verifier reached its step limit."} for item in claims],
        }

