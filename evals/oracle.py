"""Independent, read-only SQLite assertion runner for scenario JSON files."""

import argparse
import json
import sqlite3
from pathlib import Path


def grade(database: Path, scenario_path: Path) -> tuple[bool, list[dict]]:
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    results = []
    with sqlite3.connect(uri, uri=True) as connection:
        for assertion in scenario.get("assertions", []):
            query = assertion["query"].strip()
            if not query.lower().startswith(("select ", "with ")) or ";" in query.rstrip(";"):
                raise ValueError("Oracle accepts one read-only SELECT query per assertion.")
            row = connection.execute(query).fetchone()
            actual = row[0] if row and len(row) == 1 else list(row) if row else None
            expected = assertion["equals"]
            results.append({"description": assertion.get("description", query), "actual": actual, "expected": expected, "passed": actual == expected})
    return bool(results) and all(item["passed"] for item in results), results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite database to inspect in read-only mode.")
    parser.add_argument("scenario", type=Path, help="Scenario JSON with SQL assertions.")
    args = parser.parse_args()
    passed, results = grade(args.db, args.scenario)
    import json as json_module
    print(json_module.dumps({"scenario": args.scenario.stem, "passed": passed, "assertions": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

