"""Shared data structures used across the agent."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    input_tokens: int = 0
    output_tokens: int = 0
    raw_parts: list[dict[str, Any]] = field(default_factory=list)


class LLMClient(Protocol):
    def generate(
        self, system: str, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]], max_tokens: int,
    ) -> LLMResponse: ...


@dataclass
class ToolResult:
    ok: bool
    text: str
    error: dict[str, str] | None = None
    risk: str = "none"
    action: str | None = None
    amount: int | None = None
    url: str | None = None
    data: Any = None


@dataclass
class RunState:
    run_id: str
    goal: str
    scenario_id: str | None = None
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    plan: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    retries: dict[str, int] = field(default_factory=dict)
    unknown_outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, int] = field(default_factory=lambda: {
        "steps": 0, "max_steps": 40, "tokens_in": 0,
        "tokens_out": 0, "max_tokens": 200_000,
    })
    verify_rounds: int = 0
    status: str = "running"

