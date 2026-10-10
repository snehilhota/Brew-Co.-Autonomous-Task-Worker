import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from agent.executor import Executor, ToolEnvironment
from agent.gate import ApprovalGate
from agent.tools.browser import BrowserSession
from agent.types import RunState, ToolCall
from env import server as app_module


ROOT = Path(__file__).resolve().parents[1]


def element_id(observation: str, dom_id: str) -> str:
    match = re.search(rf"\[(\d+)\][^\n]*#{re.escape(dom_id)}(?:\s|$)", observation)
    assert match, f"Could not find #{dom_id} in browser observation:\n{observation}"
    return match.group(1)


@pytest.fixture
def running_isolated_app(tmp_path, monkeypatch):
    source = sqlite3.connect(f"file:{app_module.DATABASE_PATH.as_posix()}?mode=ro", uri=True)
    database_path = tmp_path / "browser-integration.sqlite3"
    target = sqlite3.connect(database_path)
    source.backup(target)
    target.close()
    source.close()
    monkeypatch.setattr(app_module, "DATABASE_PATH", database_path)
    monkeypatch.setenv("APP_TODAY", "2026-10-05")
    app_module.app.config.update(TESTING=False)
    http_server = make_server("127.0.0.1", 0, app_module.app, threaded=True)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{http_server.server_port}", database_path
    finally:
        http_server.shutdown()
        thread.join(timeout=3)


def test_executor_submits_through_real_browser_ui(running_isolated_app, tmp_path, monkeypatch):
    monkeypatch.setenv("CHAOS_FLAKY_TOOL_RATE", "0")
    base_url, database_path = running_isolated_app
    browser = BrowserSession(base_url)
    environment = ToolEnvironment(ROOT, ROOT / "env" / "data", browser, tmp_path / "evidence")
    executor = Executor(environment, ApprovalGate(ROOT / "agent" / "gate_config.json"), approval=lambda *_: True)
    state = RunState(run_id="browser-test", goal="Submit a valid order through the browser tools.")

    def run(name, **args):
        nonlocal state
        state.budget["steps"] += 1
        return executor.run(ToolCall(str(state.budget["steps"]), name, args), state)

    try:
        with closing(sqlite3.connect(database_path)) as connection:
            before = connection.execute("SELECT COUNT(*) FROM purchase_orders WHERE status='submitted'").fetchone()[0]

        observation = run("browser_open", url="/orders/new").text
        observation = run("browser_select", element_id=element_id(observation, "supplier-id"), option="FreshFarm Dairy & Bakery (active)").text
        observation = run("browser_type", element_id=element_id(observation, "delivery-date"), text="2026-10-06").text
        observation = run("browser_select", element_id=element_id(observation, "item-1"), option="Whole milk (L)").text
        observation = run("browser_type", element_id=element_id(observation, "quantity-1"), text="36").text
        submit_id = element_id(observation, "submit-order")
        assert executor.env.browser.target_metadata(submit_id)["amount"] == 2340
        result = run("browser_click", element_id=submit_id)

        assert result.ok, result.text
        assert "Purchase order" in result.text
        assert "₹2340" in result.text
        with closing(sqlite3.connect(database_path)) as connection:
            after = connection.execute("SELECT COUNT(*) FROM purchase_orders WHERE status='submitted'").fetchone()[0]
            total = connection.execute("SELECT total FROM purchase_orders ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert after == before + 1
        assert total == 2340
    finally:
        browser.close()
