# Brew & Co. Autonomous Task Worker

A small, explainable AI worker prototype for completing tasks in a simulated cafe back office. The worker will use browser and file tools, observe what happened, verify important changes, and ask before risky actions.

## Current progress

The project is at **M0: repository and tooling setup**. The Python stack and initial design choices are recorded in [docs/DECISIONS.md](docs/DECISIONS.md). The mock environment and agent loop have not been built yet.

## Setup

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Add a Gemini API key to `.env` before making live model calls. Keep that file private; it is ignored by Git.

Run the project checks:

```powershell
python -m pytest
```

## Planned build order

1. Mock cafe environment and seed data.
2. File and browser tools.
3. Executor and in-code approval gate.
4. LLM adapter and hand-written agent loop.
5. Verification, traces, and evaluation scenarios.
6. Documentation and demo.

See the project handoff's milestone table for acceptance criteria and scope priorities.
