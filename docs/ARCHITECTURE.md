# Architecture

The project separates the generic worker from the mock business environment. `agent/` contains a hand-written loop, a Gemini adapter, typed tool definitions, a sandboxed file reader, a same-origin Playwright browser, a safe arithmetic parser, a code-enforced risk gate, an unknown-outcome guard, a fresh-context verifier, and JSONL tracing. It contains no business-specific rules.

The environment is `env/`: a Flask/Jinja application, SQLite schema and seed data, domain policy and supplier documents, and validation. The manifest gives the agent only a base URL, file root, and brief; the agent must read policy from the file tools.

```text
Task → Loop → Gemini decision → Executor → Gate → Tool → Environment
                 ↑                  ↓         ↓
                 └── observation ←──┘      JSONL trace
Task finish → fresh read-only verifier → final claims and evidence
Evaluation oracle (separate process) → reads SQLite directly for grading
```

The evaluation oracle is not registered as an agent tool. The agent can interact with the system only through browser and file tools, plus calculator, notes, and human prompts.
