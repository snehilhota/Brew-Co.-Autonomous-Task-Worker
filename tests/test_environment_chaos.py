import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest

from env import server


@pytest.fixture
def isolated_app_db(tmp_path, monkeypatch):
    source = sqlite3.connect(f"file:{server.DATABASE_PATH.as_posix()}?mode=ro", uri=True)
    target_path = tmp_path / "test-environment.sqlite3"
    target = sqlite3.connect(target_path)
    source.backup(target)
    target.close()
    source.close()
    monkeypatch.setattr(server, "DATABASE_PATH", target_path)
    monkeypatch.setenv("APP_TODAY", "2026-10-05")
    server.app.config.update(TESTING=False)
    return target_path


def submitted_orders(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT COUNT(*) FROM purchase_orders WHERE status='submitted'").fetchone()[0]


def test_menu_page_exposes_recipe_needs_and_current_stock(isolated_app_db):
    response = server.app.test_client().get("/menu")

    assert response.status_code == 200
    assert "Ingredients per serving and current stock" in response.get_data(as_text=True)
    assert "Oat milk (barista): 0.25 L required; stock 0.0 L" in response.get_data(as_text=True)
    assert "Vanilla syrup: 0.03 bottle required; stock 0.0 bottle" in response.get_data(as_text=True)


def test_inventory_projects_submitted_incoming_quantity_for_reorder_decisions(isolated_app_db):
    with closing(sqlite3.connect(isolated_app_db)) as connection:
        connection.execute(
            """INSERT INTO purchase_orders
               (supplier_id, status, delivery_date, total, created_at)
               VALUES (2, 'submitted', '2026-10-06', 780, '2026-10-05T10:00:00')"""
        )
        submitted_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute(
            """INSERT INTO purchase_order_lines
               (po_id, item_id, qty_units, cases, unit_price_per_case, line_total)
               VALUES (?, 5, 15, 3, 260, 780)""",
            (submitted_id,),
        )
        connection.execute(
            """INSERT INTO purchase_orders
               (supplier_id, status, delivery_date, total, created_at)
               VALUES (2, 'draft', '2026-10-06', 260, '2026-10-05T10:00:00')"""
        )
        draft_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.execute(
            """INSERT INTO purchase_order_lines
               (po_id, item_id, qty_units, cases, unit_price_per_case, line_total)
               VALUES (?, 5, 100, 20, 260, 5200)""",
            (draft_id,),
        )
        connection.commit()

    response = server.app.test_client().get("/inventory")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    sugar_row = html.split('id="inventory-row-5"', 1)[1].split("</tr>", 1)[0]
    assert "<td>5.0</td>" in sugar_row  # on hand
    assert "<td>15</td>" in sugar_row  # submitted order quantity
    assert "<td>20.0</td>" in sugar_row  # projected stock reaches the par level


def test_new_order_page_hides_empty_validation_message(isolated_app_db):
    response = server.app.test_client().get("/orders/new")

    assert response.status_code == 200
    assert 'id="form-errors"' not in response.get_data(as_text=True)


def test_new_order_page_uses_native_date_picker(isolated_app_db):
    response = server.app.test_client().get("/orders/new")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="delivery-date"' in html
    assert 'name="delivery_date"' in html
    assert 'type="date"' in html


def test_agent_activity_pages_show_read_only_run_evidence(tmp_path, monkeypatch):
    run_id = "r_20261008T100000_abcdef"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        '{"status":"success","summary":"Order checked.","scenario_id":"S1_main_restock",'
        '"steps":2,"tool_errors":0,"errors_recovered":0,"wall_seconds":3.5,'
        '"api_requests":2,"verification":{"ok":true}}',
        encoding="utf-8",
    )
    (run_dir / "trace.jsonl").write_text(
        '{"type":"run_start","run_id":"r_20261008T100000_abcdef","goal":"Check stock and prepare an order."}\n'
        '{"type":"tool_call","step":1,"tool":"browser_open"}\n'
        '{"type":"tool_result","step":1,"tool":"browser_open","ok":true}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "RUNS_ROOT", tmp_path / "runs")
    client = server.app.test_client()

    home = client.get("/").get_data(as_text=True)
    history = client.get("/agent").get_data(as_text=True)
    detail = client.get(f"/agent/runs/{run_id}").get_data(as_text=True)

    assert "Autonomous task worker" in home
    assert "Check stock and prepare an order." in home
    assert "Task run history" in history
    assert "Order checked." in history
    assert "Browser Open" in detail
    assert "The verifier confirmed the final claims." in detail


def test_agent_run_route_rejects_invalid_run_id():
    response = server.app.test_client().get("/agent/runs/not-a-valid-run")

    assert response.status_code == 404


def valid_submit_form():
    return {
        "action": "submit",
        "supplier_id": "1",
        "delivery_date": "2026-10-06",
        "item_id": ["1"],
        "quantity": ["36"],
        "notes": "isolated chaos test",
    }


def test_submit_500_happens_before_database_commit(isolated_app_db, monkeypatch):
    before = submitted_orders(isolated_app_db)
    monkeypatch.setattr(server, "CHAOS_SUBMIT_500_ONCE", True)

    response = server.app.test_client().post("/orders/new", data=valid_submit_form())

    assert response.status_code == 500
    assert submitted_orders(isolated_app_db) == before
    assert server.CHAOS_SUBMIT_500_ONCE is False


def test_timeout_switch_commits_then_returns_504(isolated_app_db, monkeypatch):
    before = submitted_orders(isolated_app_db)
    monkeypatch.setattr(server, "CHAOS_TIMEOUT_AFTER_COMMIT_ONCE", True)

    response = server.app.test_client().post("/orders/new", data=valid_submit_form())

    assert response.status_code == 504
    assert submitted_orders(isolated_app_db) == before + 1
    assert server.CHAOS_TIMEOUT_AFTER_COMMIT_ONCE is False


def test_saved_draft_can_be_edited_and_submitted(isolated_app_db):
    client = server.app.test_client()
    form = valid_submit_form()
    form["action"] = "draft"
    draft_response = client.post("/orders/new", data=form)
    assert draft_response.status_code == 302
    draft_id = int(draft_response.headers["Location"].rsplit("/", 1)[-1])

    detail = client.get(f"/orders/{draft_id}").get_data(as_text=True)
    assert 'id="edit-draft"' in detail
    assert 'id="delete-draft"' in detail
    order_list = client.get("/orders").get_data(as_text=True)
    assert f'id="edit-draft-{draft_id}"' in order_list
    assert f'id="delete-draft-{draft_id}"' in order_list

    edit_page = client.get(f"/orders/new?draft_id={draft_id}")
    edit_html = edit_page.get_data(as_text=True)
    assert edit_page.status_code == 200
    assert f'name="draft_id" value="{draft_id}"' in edit_html
    assert 'value="2026-10-06"' in edit_html

    edited_form = {**form, "action": "submit", "draft_id": str(draft_id), "quantity": ["48"]}
    submitted = client.post("/orders/new", data=edited_form)
    assert submitted.status_code == 302
    assert submitted.headers["Location"].endswith(f"/orders/{draft_id}")

    with closing(sqlite3.connect(isolated_app_db)) as connection:
        order = connection.execute(
            "SELECT status, total FROM purchase_orders WHERE id = ?", (draft_id,)
        ).fetchone()
        lines = connection.execute(
            "SELECT qty_units FROM purchase_order_lines WHERE po_id = ?", (draft_id,)
        ).fetchall()
    assert order == ("submitted", 3120)
    assert lines == [(48,)]


def test_saved_draft_can_be_deleted_without_affecting_submitted_orders(isolated_app_db):
    client = server.app.test_client()
    form = valid_submit_form()
    form["action"] = "draft"
    draft_response = client.post("/orders/new", data=form)
    draft_id = int(draft_response.headers["Location"].rsplit("/", 1)[-1])
    before = submitted_orders(isolated_app_db)

    deleted = client.post(f"/orders/{draft_id}/delete-draft")

    assert deleted.status_code == 302
    assert deleted.headers["Location"].endswith("/orders")
    assert submitted_orders(isolated_app_db) == before
    with closing(sqlite3.connect(isolated_app_db)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE id = ?", (draft_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM purchase_order_lines WHERE po_id = ?", (draft_id,)
        ).fetchone()[0] == 0


def test_optional_duplicate_guard_stops_matching_second_submit(isolated_app_db, monkeypatch):
    monkeypatch.setattr(server, "DUPLICATE_GUARD", True)
    delivery_day = date(2040, 1, 1)
    with closing(sqlite3.connect(isolated_app_db)) as connection:
        existing_dates = {
            row[0]
            for row in connection.execute(
                "SELECT delivery_date FROM purchase_orders WHERE supplier_id=1 AND total=2340 AND status='submitted'"
            )
        }
    while delivery_day.weekday() >= 5 or delivery_day.isoformat() in existing_dates:
        delivery_day += timedelta(days=1)
    form = valid_submit_form()
    form["delivery_date"] = delivery_day.strftime("%d/%m/%Y")
    before = submitted_orders(isolated_app_db)
    client = server.app.test_client()

    first = client.post("/orders/new", data=form)
    second = client.post("/orders/new", data=form)

    assert first.status_code == 302
    assert second.status_code == 409
    assert submitted_orders(isolated_app_db) == before + 1

