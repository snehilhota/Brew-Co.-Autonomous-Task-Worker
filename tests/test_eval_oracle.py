import json
import sqlite3

from evals.oracle import grade


def test_oracle_grades_read_only_sql_assertions(tmp_path):
    database = tmp_path / "eval.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE demo(value INTEGER)")
        connection.execute("INSERT INTO demo(value) VALUES (7)")
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"assertions": [{"query": "SELECT value FROM demo", "equals": 7}]}), encoding="utf-8")

    passed, results = grade(database, scenario)

    assert passed
    assert results[0]["actual"] == 7


def test_oracle_rejects_non_select_queries(tmp_path):
    database = tmp_path / "eval.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE demo(value INTEGER)")
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"assertions": [{"query": "DELETE FROM demo", "equals": 0}]}), encoding="utf-8")

    try:
        grade(database, scenario)
    except ValueError as error:
        assert "read-only SELECT" in str(error)
    else:
        raise AssertionError("Expected the oracle to reject a write query.")
