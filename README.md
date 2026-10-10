# Brew & Co. Autonomous Task Worker

A narrow, explainable AI worker prototype for a simulated back office. It accepts a natural-language task, reads the environment's policy and files, acts through browser and file tools, observes results, applies code-enforced approvals, verifies claims with a separate read-only model context, and writes a JSONL trace.

> This is a local prototype for a job application, not a production purchasing system. It uses mock data and must never be pointed at real company accounts.

## Requirements

- Python 3.11+ (development uses Python 3.12 in the `brew-agent` Conda environment).
- Gemini API key for live model runs. The model IDs are configurable independently through `AGENT_MODEL` and `VERIFIER_MODEL`.
- Playwright Chromium: `python -m playwright install chromium`.

## Quick start (Windows PowerShell)

```powershell
conda activate brew-agent
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Copy `.env.example` to `.env` once and add your Gemini key. Keep `.env` private; Git ignores it. Leave chaos switches off for normal runs.

To initialize mock data, reset then seed the database. **Reset deletes the current local database, including any existing orders.**

```powershell
python env/db/reset.py
python env/db/seed.py
```

Start the mock application in Terminal 1:

```powershell
python env/server.py
```

In Terminal 2, run a task. Required approval prompts appear in this terminal:

```powershell
python -m agent.cli "We're low on stock for the weekend, sort the ordering."
```

Each run saves a JSONL trace, summary, and optional screenshots under `runs/<run_id>/`. The `runs/` directory is ignored by Git.

## Architecture

The `agent/` package is domain-neutral. `env/` contains all business-specific pages, data, and policy. The worker has no database tool; only the evaluation oracle reads SQLite directly.

```text
Task → hand-written loop → Gemini function call → validated executor → risk gate → browser/files
                                  ↑                                     ↓
                                  └──────── observed tool result ───────┘
Finish claims → fresh-context read-only verifier → owner summary + evidence
Evaluation process → SQLite oracle (outside the agent) → scenario assertions
```

Core modules: `agent/loop.py` (step/token/time caps and memory), `agent/executor.py` (Pydantic argument validation, dispatch, failures, and unknown-outcome guard), `agent/gate.py` (risk policy and direct human approval), `agent/tools/` (browser, files, calculator, and human interaction), `agent/llm/gemini.py` (provider adapter), `agent/verifier.py` (fresh-context read-only verification), and `agent/trace.py` (JSONL events). No agent framework is used.

## Safety and reliability

- Browser URLs stay on the configured local origin; `/__*` routes are blocked and downloads are disabled.
- File tools resolve paths under `env/data` and reject traversal outside that root.
- Irreversible UI actions use `data-risk`, `data-action`, and `data-amount`. Amounts up to ₹10,000 are allowed, amounts above ₹10,000 through ₹50,000 require direct human approval, and amounts above ₹50,000 are blocked.
- If an irreversible action has an uncertain result, the identical retry is blocked until the worker observes state again. The optional server duplicate guard defaults off so agent-side protection can be tested.
- Tool output is untrusted data. The model cannot authorize itself or change gate settings.
- Traces record calls, results, approvals, errors, verification, and final status. Screenshots are human evidence and are not sent to the model.

## Checks and evaluations

Run local deterministic tests without Gemini API calls:

```powershell
python -m pytest
```

The validation tests cover V1–V9. The evaluation scenarios in `evals/scenarios/` define the expected results for the main restock, menu availability, and expiry tasks. After running a scenario against a fresh seeded database, grade it with:

```powershell
python -m evals.oracle --db env/db/brew.sqlite3 evals/scenarios/S1_main_restock.json
```

Label runs with `--scenario S1_main_restock`, then aggregate their measured summaries:

```powershell
python -m agent.cli --scenario S1_main_restock "We're low on stock for the weekend, sort the ordering."
python -m evals.report
```

Use a fresh database copy per scenario; unrelated manual orders will affect the results. Live model pass rates, recovery counts, token use, and wall time must be measured from actual runs. This README does not invent benchmark results.

The standard test suite includes the browser integration test. It launches headless Chromium and a local Flask server against a temporary database snapshot; install Chromium first with `python -m playwright install chromium`.

```powershell
python -m pytest
```

## Decisions and assumptions

- A small simulated operations environment makes browser actions real while avoiding unauthorized access and real credentials.
- A hand-written sequential loop keeps control flow, observation, retry, and approval behavior inspectable.
- The agent reads domain rules from files at run time rather than hard-coding them in its code.
- The application date defaults to the computer's current date; set `APP_TODAY` only when a deterministic demo or evaluation needs a fixed date.
- The ordering system's displayed prices are authoritative; orders do not decrement stock because receiving is out of scope.
- One owner approves actions in the CLI; this is a local single-user application with no authentication.
- Provider: Google Gemini. Frameworks and services: Flask/Jinja, SQLite, Playwright sync API, Pydantic, pytest, python-dotenv, and httpx. No LangChain, LlamaIndex, CrewAI, AutoGen, or hosted computer-use service is used.
- AI coding assistance was used during implementation. The builder should review and understand the loop, executor, gate, guard, and verifier before an interview walkthrough.

## Known limitations and demo

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) and [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). Record a demo and add measured live evaluation results before final application submission. Only present failure recovery behavior after reproducing it.

## What I would build next

Add per-run environment/database isolation, a dedicated approval identity and role model, reusable environment connectors, a replay dataset and automated multi-run evaluation runner, and stronger policy checks and long-context memory.
