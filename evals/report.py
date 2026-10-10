"""Aggregate measured run summaries into a reproducible Markdown table."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean


def collect(runs_dir: Path) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for summary_path in runs_dir.glob("*/summary.json"):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        scenario = summary.get("scenario_id") or "unlabeled"
        grouped[scenario].append(summary)
    return dict(grouped)


def render_table(grouped: dict[str, list[dict]]) -> str:
    lines = [
        "| Scenario | Runs | Pass rate | Mean steps | Tool errors | Recoveries | Approvals | Mean tokens | Mean seconds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, runs in sorted(grouped.items()):
        passed = sum(run.get("status") == "success" for run in runs)
        mean_value = lambda key: mean(run.get(key, 0) for run in runs)
        approvals = mean(len(run.get("approvals", [])) for run in runs)
        tokens = mean(run.get("input_tokens", 0) + run.get("output_tokens", 0) for run in runs)
        lines.append(
            f"| {scenario} | {len(runs)} | {passed}/{len(runs)} ({passed / len(runs):.0%}) "
            f"| {mean_value('steps'):.1f} | {mean_value('tool_errors'):.1f} "
            f"| {mean_value('errors_recovered'):.1f} | {approvals:.1f} "
            f"| {tokens:.0f} | {mean_value('wall_seconds'):.2f} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    args = parser.parse_args()
    grouped = collect(args.runs_dir)
    if not grouped:
        print("No run summaries found; execute scenarios before reporting metrics.")
        return 1
    print(render_table(grouped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
