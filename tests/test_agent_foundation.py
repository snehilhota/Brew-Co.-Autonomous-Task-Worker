from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from agent.executor import Executor, ToolEnvironment
from agent.gate import ApprovalGate
from agent.llm.gemini import GeminiClient, LLMRequestBudget
from agent.llm.scripted import ScriptedLLM
from agent.loop import AgentLoop
from agent.tools.browser import BrowserSession
from agent.tools.calculate import calculate
from agent.tools.files import FileTools
from agent.tools.registry import definitions
from agent.types import RunState, ToolCall
from agent.trace import Trace
from agent.verifier import Verifier


ROOT = Path(__file__).resolve().parents[1]


def test_safe_calculator_handles_expected_math():
    assert calculate("(60 - 14 + 11) / 12") == 4.75
    assert calculate("3 * 780") == 2340


@pytest.mark.parametrize("expression", ["__import__('os')", "open('secret')", "1 / 0", "2 ** 100"])
def test_safe_calculator_rejects_code_and_unsafe_math(expression):
    with pytest.raises((ValueError, ZeroDivisionError)):
        calculate(expression)


def test_file_tools_read_project_document():
    files = FileTools(ROOT / "env" / "data")
    assert "Purchasing & Operations Policy" in files.read_file("policy.md")
    assert "inbox/" in files.list_files(".")


def test_file_tools_reject_path_traversal():
    files = FileTools(ROOT / "env" / "data")
    with pytest.raises(ValueError, match="escapes"):
        files.read_file("../../.env")


def test_gate_uses_configured_amount_thresholds():
    gate = ApprovalGate(ROOT / "agent" / "gate_config.json")
    assert gate.decide("irreversible", 10000).allowed
    assert gate.decide("irreversible", 10001).needs_approval
    assert gate.decide("irreversible", 50000).needs_approval
    assert gate.decide("irreversible", 50001).blocked_reason
    assert gate.decide("unannotated_write", None).needs_approval


def test_browser_url_allowlist_blocks_other_origins_and_harness_routes():
    browser = BrowserSession("http://127.0.0.1:5000")
    assert browser.resolve_url("/inventory") == "http://127.0.0.1:5000/inventory"
    with pytest.raises(ValueError, match="origin"):
        browser.resolve_url("https://example.com/")
    with pytest.raises(ValueError, match="Harness-only"):
        browser.resolve_url("/__chaos")
    with pytest.raises(ValueError, match="Harness-only"):
        browser.resolve_url("/%5f%5fchaos")
    with pytest.raises(ValueError, match="local HTTP"):
        BrowserSession("https://example.com")


def test_finish_schema_inlines_claim_fields_for_provider_tools():
    finish = definitions()["finish"].declaration()
    claim = finish["parameters"]["properties"]["claims"]["items"]
    assert set(claim["properties"]) == {"claim", "how_to_check", "evidence_ref"}


def test_gemini_adapter_parses_function_calls_without_network(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, payload=json)
        body = {
            "candidates": [{"content": {"parts": [{"functionCall": {
                "name": "calculate", "args": {"expression": "3 * 4"}, "id": "call-1"
            }}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4},
        }
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr("agent.llm.gemini.httpx.post", fake_post)
    client = GeminiClient(api_key="dummy-test-key", model="gemini-test")
    result = client.generate("system", [{"role": "user", "content": "calculate"}], [], 100)

    assert captured["url"].endswith("/models/gemini-test:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "dummy-test-key"
    assert "key=" not in captured["url"]
    assert result.tool_calls[0].name == "calculate"
    assert result.tool_calls[0].args == {"expression": "3 * 4"}
    assert (result.input_tokens, result.output_tokens) == (10, 4)


def test_gemini_adapter_honors_short_rate_limit_retry_delay(monkeypatch):
    calls = []
    waits = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        if len(calls) == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "Please retry in 0.01s."}},
                request=httpx.Request("POST", url),
            )
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("agent.llm.gemini.httpx.post", fake_post)
    monkeypatch.setattr("agent.llm.gemini.time.sleep", waits.append)
    result = GeminiClient(api_key="dummy-test-key", model="gemini-test").generate(
        "system", [{"role": "user", "content": "hello"}], [], 100
    )

    assert result.text == "ok"
    assert len(calls) == 2
    assert waits == [0.01]


def test_gemini_adapter_fails_fast_for_long_quota_reset(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        return httpx.Response(
            429,
            json={"error": {"message": "Please retry in 9h13m10.8s."}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("agent.llm.gemini.httpx.post", fake_post)
    client = GeminiClient(api_key="dummy-test-key", model="gemini-test")

    with pytest.raises(RuntimeError, match="Gemini rate limit reached"):
        client.generate("system", [{"role": "user", "content": "hello"}], [], 100)

    assert len(calls) == 1


def test_gemini_adapter_stops_before_exceeding_shared_request_budget(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(url)
        body = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr("agent.llm.gemini.httpx.post", fake_post)
    budget = LLMRequestBudget(max_requests=1)
    first = GeminiClient(api_key="dummy-test-key", model="gemini-test", request_budget=budget)
    verifier = GeminiClient(api_key="dummy-test-key", model="gemini-test", request_budget=budget)
    first.generate("system", [{"role": "user", "content": "one"}], [], 100)

    with pytest.raises(RuntimeError, match="Per-run LLM request limit reached"):
        verifier.generate("system", [{"role": "user", "content": "two"}], [], 100)

    assert budget.used == 1
    assert len(calls) == 1


class FakeBrowser:
    def __init__(self, click_behavior):
        self.page = SimpleNamespace(url="http://127.0.0.1:5000/orders/new")
        self.last_action_status = None
        self.click_behavior = click_behavior
        self.click_count = 0

    def target_metadata(self, element_id):
        return {"risk": "irreversible", "action": "submit_po", "amount": 5000, "tag": "button"}

    def click(self, element_id):
        self.click_count += 1
        return self.click_behavior(self)

    def open(self, url):
        self.page.url = "http://127.0.0.1:5000" + url
        return "orders observed"

    def observe(self):
        return "page observed"


def make_executor(browser, temp_path):
    environment = ToolEnvironment(ROOT, ROOT / "env" / "data", browser, temp_path)
    return Executor(environment, ApprovalGate(ROOT / "agent" / "gate_config.json"), approval=lambda *_: True)


def test_unknown_write_outcome_blocks_retry_until_relevant_page_read(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FLAKY_TOOL_RATE", "0")

    def timeout(_browser):
        raise TimeoutError("response was lost")

    browser = FakeBrowser(timeout)
    executor = make_executor(browser, tmp_path)
    state = RunState(run_id="test", goal="test")
    call = ToolCall("1", "browser_click", {"element_id": "7"})

    assert not executor.run(call, state).ok
    state.budget["steps"] = 2
    blocked = executor.run(call, state)
    assert blocked.error["type"] == "unknown_outcome"
    assert browser.click_count == 1

    state.budget["steps"] = 3
    executor.run(ToolCall("2a", "browser_open", {"url": "/orders/new"}), state)
    assert not next(iter(state.unknown_outcomes.values()))["resolved"]
    state.budget["steps"] = 4
    executor.run(ToolCall("2", "browser_open", {"url": "/orders"}), state)
    assert next(iter(state.unknown_outcomes.values()))["resolved"]


def test_known_500_does_not_mark_write_outcome_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FLAKY_TOOL_RATE", "0")

    def server_error(browser):
        if browser.click_count == 1:
            browser.last_action_status = 500
            return "server error"
        browser.last_action_status = 200
        return "submitted"

    browser = FakeBrowser(server_error)
    executor = make_executor(browser, tmp_path)
    state = RunState(run_id="test", goal="test")
    call = ToolCall("1", "browser_click", {"element_id": "7"})

    first = executor.run(call, state)
    assert not first.ok
    assert state.unknown_outcomes == {}
    second = executor.run(call, state)
    assert second.ok
    assert browser.click_count == 2


def test_loop_calls_fresh_read_only_verifier_and_writes_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FLAKY_TOOL_RATE", "0")
    browser = FakeBrowser(lambda _browser: "unused")
    environment = ToolEnvironment(ROOT, ROOT / "env" / "data", browser, tmp_path / "evidence")
    gate = ApprovalGate(ROOT / "agent" / "gate_config.json")
    verifier_executor = Executor(environment, gate, read_only=True)
    verifier_llm = ScriptedLLM([
        {"tool_calls": [{"id": "v1", "name": "browser_open", "args": {"url": "/orders"}}]},
        {"tool_calls": [{"id": "v2", "name": "report_verification", "args": {"results": [{"claim": "The order exists", "status": "confirmed", "evidence": "Order list shows it."}]}}]},
    ])
    trace = Trace("scripted-test", tmp_path / "run")
    verifier = Verifier(verifier_llm, verifier_executor, "Internal pages and files are available.", trace)
    executor = Executor(environment, gate, approval=lambda *_: True, trace=trace)
    agent_llm = ScriptedLLM([
        {"tool_calls": [{"id": "f1", "name": "finish", "args": {"status": "success", "summary": "The order is complete.", "claims": [{"claim": "The order exists", "how_to_check": "Read the order list", "evidence_ref": "/orders"}]}}]},
    ])
    state = RunState(run_id="scripted-test", goal="Check the order.")

    result = AgentLoop(agent_llm, executor, verifier, trace).run("Check the order.", "You are a generic worker.", state)

    assert result["status"] == "success"
    assert result["verification"]["ok"]
    assert browser.page.url.endswith("/orders")
    assert (tmp_path / "run" / "trace.jsonl").is_file()
    assert (tmp_path / "run" / "summary.json").is_file()

