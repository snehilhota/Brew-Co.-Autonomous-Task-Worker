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

The initial stack is deliberately replaceable at the adapter boundary. Before the first API call, confirm the selected model and available quota in the account's AI Studio project.
