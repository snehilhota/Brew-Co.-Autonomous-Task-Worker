"""Append-only JSONL event trace and per-run summary writer."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Trace:
    def __init__(self, run_id: str, run_dir: Path):
        self.run_id = run_id
        self.run_dir = run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "trace.jsonl"

    def log(self, event_type: str, **fields: Any) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "type": event_type,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def write_summary(self, summary: dict[str, Any]) -> None:
        (self.run_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

