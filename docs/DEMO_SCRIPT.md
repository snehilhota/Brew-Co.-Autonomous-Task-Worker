# Demo recording outline (4–5 minutes)

Use mock data only. Record the terminal and local browser/app. Do not show `.env` or API keys.

1. **Problem and goal (0:00–0:30):** explain the worker's task→observe→act→verify loop.
2. **Environment (0:30–1:00):** show inventory, suppliers, ordering system, policy file, and a price notice.
3. **Task and recovery (1:00–2:45):** run the main restock task. Show the agent reading policy and files, comparing available suppliers, entering quantities/dates, recovering from a validation or injected failure, and checking the order list after any uncertain submit.
4. **Approval and verification (2:45–3:30):** show the direct CLI approval for the higher-value order, then the separate verifier's evidence table and the oracle result.
5. **Generalization (3:30–4:10):** run the menu-availability or expiry task without changing agent code.
6. **Engineering judgment (4:10–4:45):** show one trace, explain known limitations, and state what would be built next.

Only show failures and recovery behavior that you have actually reproduced. Keep a fresh seeded database for each task, and note the model ID and approximate run time in the recording notes.
