# Known limitations

- The environment is a single local mock application; there is no authentication or multi-user permission system.
- Browser observations use visible DOM text, not screenshots or general desktop vision. Downloads and cross-origin navigation are blocked.
- Gemini output is nondeterministic, can make poor plans, and is subject to account quotas and network availability.
- The verifier is another model call and can make mistakes. The separate SQLite oracle provides stronger evaluation evidence.
- Human approvals happen in the CLI. Approval decisions are bound to the observed action, amount, and URL during that run.
- Context compaction is intentionally simple, and the first version supports one sequential run at a time.
- Tool failure injection is intended for local reliability experiments, not production fault simulation.
- The simulated database does not decrement stock or record receipts. For reorder planning, submitted orders with delivery dates today or later count as incoming; a submitted order is assumed received on its delivery date, so past-due orders stop counting. Delivery and receiving workflows are out of scope.
