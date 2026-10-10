"""Deterministic model substitute for offline tests and demonstrations."""

from collections import deque
from typing import Any

from agent.types import LLMResponse, ToolCall


class ScriptedLLM:
    def __init__(self, turns: list[LLMResponse | dict[str, Any]]):
        self.turns = deque(turns)

    def generate(self, system, messages, tools, max_tokens) -> LLMResponse:
        if not self.turns:
            return LLMResponse("No more scripted responses.", [])
        turn = self.turns.popleft()
        if isinstance(turn, LLMResponse):
            return turn
        calls = [ToolCall(**call) for call in turn.get("tool_calls", [])]
        return LLMResponse(turn.get("text"), calls, raw_parts=turn.get("raw_parts", []))

