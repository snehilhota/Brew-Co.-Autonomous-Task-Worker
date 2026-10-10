# Project decisions

Initial decisions transcribed from the project handoff on 6 October 2026. These are project design context, not instructions that override the builder's choices.

| Topic | Decision | Reason / status |
|---|---|---|
| Language | Python 3.11+ | Chosen to learn Python and use common AI tooling. |
| Mock application | Brew & Co. cafe operations | One narrow environment with inventory, suppliers, purchase orders, and policy documents. |
| Web app | Flask + Jinja2 | Small and easy to inspect locally. |
| Browser automation | Playwright for Python, sync API | The task loop is sequential, so synchronous code keeps the first version simpler. |
| Agent architecture | Hand-written loop; no agent framework | Keep control flow understandable and editable. |
| Agent interface | CLI first | Demo and approvals can happen in the terminal. |
| Model provider | Gemini API through a small adapter | Initial choice from the handoff; use `httpx` and keep model IDs configurable. Check account quota in AI Studio before live calls. |
| Initial model IDs | `gemini-3.8-flash` for agent and verifier | Current stable Flash model listed by Google's model docs; configurable via `.env`. |
| Demo | Recorded video | More reliable than depending on a hosted demo. |
| Repository name | `brew-agent` | Matches the current workspace folder. |
| Verification | Agent-side read-only verifier plus separate evaluation oracle | The agent never gets direct database access. |
| Safety and reliability | Code-enforced approval gate and unknown-outcome write guard | A model response alone must not authorize risky writes or blind retries. |

The initial stack is deliberately replaceable at the adapter boundary. The existing successful `llm_hello.py` call confirmed the configured Gemini key. The agent adapter uses Google's documented `generateContent` function-calling endpoint over the already-installed `httpx` client, so its request/response format can be tested without adding another provider SDK. The configured `AGENT_MODEL` and `VERIFIER_MODEL` remain independently changeable.

## Implementation status (8 Oct 2026)

- M0 environment, repository, smoke test, pytest setup, Gemini hello call, and decisions: completed by the builder.
- M1 mock app, schema, seed data, and pages: implemented and manually checked.
- M2 PO validation, form, risk annotations, and failure switches: implemented; validation and commit-boundary behavior are covered by tests.
- M3 generic tools and executor: implemented; an isolated browser-to-Flask purchase-order flow passed.
- M4 Gemini adapter: implemented and response parsing is tested with a mocked API response; a live tool-call request still needs one quota-approved run.
- M5 loop, working memory, budgets, and trace: deterministic scripted loop and verifier path pass; live S1 is not yet measured.
- M6 gate, approvals, and unknown-outcome guard: implemented and covered by deterministic tests; the timeout-after-commit scenario has not yet been run through Gemini.
- M7 verifier: read-only behavior and loop plumbing are tested with a scripted client; a live independent model verification remains to be demonstrated.
- M8 oracle and S1-S3 scenario definitions: implemented. Automated multi-run scenario orchestration and P1 chaos/ablation metrics remain.
- M10 README and architecture/limitations/demo guidance: prepared. A recorded video and clean-clone run still need to be completed before submission.
