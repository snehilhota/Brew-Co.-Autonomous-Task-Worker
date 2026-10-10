"""Command-line entry point for a single task run."""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from agent.executor import Executor, ToolEnvironment
from agent.gate import ApprovalGate
from agent.llm.gemini import GeminiClient, LLMRequestBudget
from agent.loop import AgentLoop
from agent.prompt import render_system_prompt
from agent.tools.browser import BrowserSession
from agent.trace import Trace
from agent.types import RunState
from agent.verifier import Verifier


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the generic computer-use worker on a task.")
    parser.add_argument("task", help="Natural-language task for the worker.")
    parser.add_argument("--scenario", help="Optional evaluation scenario id for trace metadata.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    manifest_path = ROOT / "env" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    base_url = os.getenv(manifest.get("base_url_env", "ENV_BASE_URL"), os.getenv("APP_BASE_URL", "http://127.0.0.1:5000")).rstrip("/")
    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme != "http" or parsed_base_url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        print("For safety, the worker only connects to the local mock environment.", file=sys.stderr)
        return 2
    try:
        response = httpx.get(base_url, timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Environment is not reachable at {base_url}: {exc}", file=sys.stderr)
        print("Start the environment in another terminal with: python env/server.py", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("r_%Y%m%dT%H%M%S_") + uuid.uuid4().hex[:6]
    run_dir = ROOT / "runs" / run_id
    trace = Trace(run_id, run_dir)
    browser = BrowserSession(base_url)
    file_root = (ROOT / manifest.get("file_root", "env/data")).resolve()
    environment = ToolEnvironment(ROOT, file_root, browser, run_dir / "evidence")
    gate = ApprovalGate(ROOT / "agent" / "gate_config.json")
    request_budget = LLMRequestBudget(
        int(os.getenv("LLM_MAX_REQUESTS_PER_RUN", "12"))
    )
    agent_llm = GeminiClient(model=os.getenv("AGENT_MODEL"), request_budget=request_budget)
    verifier_llm = GeminiClient(
        model=os.getenv("VERIFIER_MODEL", os.getenv("AGENT_MODEL")),
        request_budget=request_budget,
    )
    executor = Executor(environment, gate, trace=trace)
    verifier_executor = Executor(environment, gate, read_only=True, trace=trace)
    brief = manifest.get("brief", "Use only the configured tools to complete the task.")
    verifier = Verifier(verifier_llm, verifier_executor, brief, trace)
    state = RunState(run_id=run_id, goal=args.task)
    state.scenario_id = args.scenario
    agent = AgentLoop(agent_llm, executor, verifier, trace, request_budget=request_budget)
    print(f"Run {run_id} | Environment: {base_url}")
    try:
        if args.scenario:
            trace.log("scenario", scenario_id=args.scenario)
        result = agent.run(args.task, render_system_prompt(brief), state)
    finally:
        browser.close()
    print("\n--- Run result ---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\nTrace and evidence: {run_dir}")
    return 0 if result["status"] in {"success", "partial", "blocked"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

