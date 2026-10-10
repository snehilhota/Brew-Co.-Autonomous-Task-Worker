import json
import os
import re
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, redirect, render_template, request, url_for

try:
    from .validation import is_positive_whole_quantity, validate_purchase_order
except ImportError:  # Supports `python env/server.py` as well as `import env.server` in tests.
    from validation import is_positive_whole_quantity, validate_purchase_order


ENV_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENV_DIR.parent
RUNS_ROOT = PROJECT_ROOT / "runs"
RUN_ID_PATTERN = re.compile(r"r_\d{8}T\d{6}_[a-f0-9]{6}")

load_dotenv(PROJECT_ROOT / ".env")

database_setting = os.getenv("DATABASE_PATH", "env/db/brew.sqlite3")
DATABASE_PATH = Path(database_setting)

if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = PROJECT_ROOT / DATABASE_PATH

app = Flask(__name__, template_folder="templates")


def env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


CHAOS_SLOW_PAGE_MS = max(0, int(os.getenv("CHAOS_SLOW_PAGE_MS", "0")))
CHAOS_SUBMIT_500_ONCE = env_flag("CHAOS_SUBMIT_500_ONCE")
CHAOS_TIMEOUT_AFTER_COMMIT_ONCE = env_flag("CHAOS_TIMEOUT_AFTER_COMMIT_ONCE")
DUPLICATE_GUARD = os.getenv("DUPLICATE_GUARD", "off").strip().lower() == "on"


def get_validation_today() -> date:
    """Use a pinned scenario date for validation, or the real date by default."""
    today_setting = os.getenv("APP_TODAY")
    return date.fromisoformat(today_setting) if today_setting else date.today()


def get_today_label() -> str:
    """Display the computer's actual current date, never the scenario date."""
    return date.today().strftime("%a %d/%m/%Y")


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def read_run_events(run_dir: Path) -> list[dict]:
    trace_path = run_dir / "trace.jsonl"
    if not trace_path.is_file() or trace_path.stat().st_size > 5_000_000:
        return []
    events = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def read_agent_runs(limit: int | None = None) -> list[dict]:
    """Read completed local run summaries for the read-only activity page."""
    runs = []
    if not RUNS_ROOT.is_dir():
        return runs
    for run_dir in RUNS_ROOT.iterdir():
        if not run_dir.is_dir() or not RUN_ID_PATTERN.fullmatch(run_dir.name):
            continue
        try:
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        summary_text = str(summary.get("summary", "No summary recorded."))
        if summary.get("status") == "failed":
            if "quota" in summary_text.lower() or "429" in summary_text:
                summary_text = "Stopped because the model provider request limit was reached."
            elif "503" in summary_text or "service unavailable" in summary_text.lower():
                summary_text = "Stopped because the model provider was temporarily unavailable."
            else:
                summary_text = "Stopped before the task could be verified."
        events = read_run_events(run_dir)
        start_event = next((event for event in events if event.get("type") == "run_start"), {})
        started_at = next((event.get("ts") for event in events if event.get("type") == "run_start"), "")
        runs.append({
            "run_id": run_dir.name,
            "goal": start_event.get("goal", "Task details unavailable"),
            "scenario_id": summary.get("scenario_id"),
            "status": summary.get("status", "unknown"),
            "summary": summary_text,
            "steps": summary.get("steps", 0),
            "api_requests": summary.get("api_requests"),
            "tool_calls": sum(event.get("type") == "tool_call" for event in events),
            "wall_seconds": summary.get("wall_seconds", 0),
            "verification_ok": (summary.get("verification") or {}).get("ok", False),
            "started_at": started_at,
        })
    runs.sort(key=lambda run: run["started_at"], reverse=True)
    return runs[:limit] if limit is not None else runs


def render_order_form(
    errors: list[str] | None = None,
    selected_supplier_id: str = "",
    delivery_date_text: str = "",
    notes: str = "",
    item_ids: list[str] | None = None,
    quantities: list[str] | None = None,
    visible_line_count: int = 1,
    order_total: int = 0,
    draft_id: int | None = None,
) -> str:
    """Load form choices and render the order form."""
    connection = get_db_connection()

    supplier_rows = connection.execute(
        """
        SELECT id, name, status, hold_reason, lead_time_days, min_order_value
        FROM suppliers
        ORDER BY id
        """
    ).fetchall()

    inventory_rows = connection.execute(
        "SELECT id, name, unit FROM inventory_items ORDER BY id"
    ).fetchall()

    offer_rows = connection.execute(
        """
        SELECT supplier_id, item_id, case_size, price_per_case, available
        FROM supplier_items
        ORDER BY supplier_id, item_id
        """
    ).fetchall()

    connection.close()

    return render_template(
        "order_new.html",
        suppliers=supplier_rows,
        inventory_items=inventory_rows,
        supplier_offers=[dict(row) for row in offer_rows],
        today_label=get_today_label(),
        errors=errors or [],
        selected_supplier_id=selected_supplier_id,
        delivery_date_text=delivery_date_text,
        notes=notes,
        item_ids=item_ids or [],
        quantities=quantities or [],
        visible_line_count=visible_line_count,
        order_total=order_total,
        draft_id=draft_id,
    )


@app.get("/")
def home() -> str:
    return render_template(
        "home.html",
        today_label=get_today_label(),
        recent_runs=read_agent_runs(limit=3),
    )


@app.get("/agent")
def agent_activity() -> str:
    return render_template(
        "agent_activity.html",
        today_label=get_today_label(),
        runs=read_agent_runs(),
    )


@app.get("/agent/runs/<run_id>")
def agent_run_detail(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        abort(404)
    run_dir = (RUNS_ROOT / run_id).resolve()
    if RUNS_ROOT.resolve() not in run_dir.parents:
        abort(404)
    run = next((item for item in read_agent_runs() if item["run_id"] == run_id), None)
    if run is None:
        abort(404)

    events = read_run_events(run_dir)
    results_by_call: dict[tuple, list[dict]] = {}
    for event in events:
        if event.get("type") == "tool_result":
            key = (event.get("step"), event.get("tool"))
            results_by_call.setdefault(key, []).append(event)
    actions = []
    for event in events:
        if event.get("type") != "tool_call":
            continue
        result_queue = results_by_call.get((event.get("step"), event.get("tool")), [])
        result = result_queue.pop(0) if result_queue else {}
        actions.append({
            "step": event.get("step"),
            "tool": event.get("tool", "unknown tool"),
            "ok": result.get("ok"),
        })
    return render_template(
        "agent_run.html",
        today_label=get_today_label(),
        run=run,
        actions=actions,
    )


@app.get("/inventory")
def inventory() -> str:
    connection = get_db_connection()
    items = connection.execute(
        """
        SELECT
            inventory_items.id,
            inventory_items.name,
            inventory_items.unit,
            inventory_items.on_hand,
            inventory_items.reorder_point,
            inventory_items.par_level,
            COALESCE(incoming_orders.qty_units, 0) AS on_order,
            inventory_items.on_hand + COALESCE(incoming_orders.qty_units, 0) AS projected_stock,
            inventory_items.expiry_date,
            inventory_items.flagged,
            inventory_items.flag_note,
            suppliers.name AS default_supplier
        FROM inventory_items
        LEFT JOIN suppliers
            ON inventory_items.default_supplier_id = suppliers.id
        LEFT JOIN (
            SELECT purchase_order_lines.item_id, SUM(purchase_order_lines.qty_units) AS qty_units
            FROM purchase_order_lines
            JOIN purchase_orders
                ON purchase_order_lines.po_id = purchase_orders.id
            WHERE purchase_orders.status = 'submitted'
              AND purchase_orders.delivery_date >= ?
            GROUP BY purchase_order_lines.item_id
        ) AS incoming_orders
            ON inventory_items.id = incoming_orders.item_id
        ORDER BY inventory_items.id
        """,
        (get_validation_today().isoformat(),),
    ).fetchall()
    connection.close()

    return render_template(
        "inventory.html",
        items=items,
        today_label=get_today_label(),
    )


@app.get("/suppliers")
def suppliers() -> str:
    connection = get_db_connection()
    supplier_rows = connection.execute(
        """
        SELECT id, name, status, hold_reason, lead_time_days, min_order_value
        FROM suppliers
        ORDER BY id
        """
    ).fetchall()
    connection.close()

    return render_template(
        "suppliers.html",
        suppliers=supplier_rows,
        today_label=get_today_label(),
    )


@app.get("/menu")
def menu() -> str:
    connection = get_db_connection()
    menu_rows = connection.execute(
        """
        SELECT menu_items.id, menu_items.name, menu_items.price, menu_items.available,
               COALESCE(
                   GROUP_CONCAT(
                       inventory_items.name || ': ' ||
                       CAST(menu_ingredients.qty_per_serving AS TEXT) || ' ' || inventory_items.unit ||
                       ' required; stock ' || CAST(inventory_items.on_hand AS TEXT) || ' ' || inventory_items.unit,
                       '; '
                   ),
                   'No ingredients configured'
               ) AS ingredient_details
        FROM menu_items
        LEFT JOIN menu_ingredients ON menu_ingredients.menu_item_id = menu_items.id
        LEFT JOIN inventory_items ON inventory_items.id = menu_ingredients.item_id
        GROUP BY menu_items.id
        ORDER BY menu_items.id
        """
    ).fetchall()
    connection.close()

    return render_template(
        "menu.html",
        menu_items=menu_rows,
        today_label=get_today_label(),
    )


@app.get("/orders")
def orders() -> str:
    connection = get_db_connection()
    order_rows = connection.execute(
        """
        SELECT
            purchase_orders.id,
            suppliers.name AS supplier_name,
            purchase_orders.status,
            purchase_orders.delivery_date,
            purchase_orders.total,
            purchase_orders.created_at
        FROM purchase_orders
        JOIN suppliers ON purchase_orders.supplier_id = suppliers.id
        ORDER BY purchase_orders.id DESC
        """
    ).fetchall()
    connection.close()

    return render_template(
        "orders.html",
        orders=order_rows,
        today_label=get_today_label(),
    )


@app.get("/orders/<int:order_id>")
def order_detail(order_id: int) -> str:
    connection = get_db_connection()
    order = connection.execute(
        """
        SELECT
            purchase_orders.id,
            suppliers.name AS supplier_name,
            purchase_orders.status,
            purchase_orders.delivery_date,
            purchase_orders.total,
            purchase_orders.notes,
            purchase_orders.created_at
        FROM purchase_orders
        JOIN suppliers ON purchase_orders.supplier_id = suppliers.id
        WHERE purchase_orders.id = ?
        """,
        (order_id,),
    ).fetchone()

    if order is None:
        connection.close()
        abort(404)

    lines = connection.execute(
        """
        SELECT
            inventory_items.name AS item_name,
            purchase_order_lines.qty_units,
            purchase_order_lines.cases,
            purchase_order_lines.unit_price_per_case,
            purchase_order_lines.line_total
        FROM purchase_order_lines
        JOIN inventory_items ON purchase_order_lines.item_id = inventory_items.id
        WHERE purchase_order_lines.po_id = ?
        ORDER BY purchase_order_lines.id
        """,
        (order_id,),
    ).fetchall()
    connection.close()

    return render_template(
        "order_detail.html",
        order=order,
        lines=lines,
        today_label=get_today_label(),
    )


@app.post("/orders/<int:order_id>/delete-draft")
def delete_draft(order_id: int) -> Response:
    connection = get_db_connection()
    draft = connection.execute(
        "SELECT status FROM purchase_orders WHERE id = ?",
        (order_id,),
    ).fetchone()
    if draft is None:
        connection.close()
        abort(404)
    if draft["status"] != "draft":
        connection.close()
        abort(409)

    connection.execute("DELETE FROM purchase_order_lines WHERE po_id = ?", (order_id,))
    connection.execute("DELETE FROM purchase_orders WHERE id = ?", (order_id,))
    connection.commit()
    connection.close()
    return redirect(url_for("orders"))


@app.post("/inventory/<int:item_id>/toggle-flag")
def toggle_flag(item_id: int) -> Response:
    desired_flag = request.form.get("flagged")

    if desired_flag not in {"0", "1"}:
        abort(400)

    connection = get_db_connection()
    item = connection.execute(
        "SELECT id FROM inventory_items WHERE id = ?",
        (item_id,),
    ).fetchone()

    if item is None:
        connection.close()
        abort(404)

    if desired_flag == "1":
        flag_note = request.form.get("flag_note", "").strip()
        connection.execute(
            "UPDATE inventory_items SET flagged = 1, flag_note = ? WHERE id = ?",
            (flag_note, item_id),
        )
    else:
        connection.execute(
            "UPDATE inventory_items SET flagged = 0, flag_note = NULL WHERE id = ?",
            (item_id,),
        )

    connection.commit()
    connection.close()
    return redirect(url_for("inventory"))


@app.post("/menu/<int:menu_item_id>/toggle-availability")
def toggle_menu_availability(menu_item_id: int) -> Response:
    connection = get_db_connection()
    cursor = connection.execute(
        """
        UPDATE menu_items
        SET available = CASE available WHEN 1 THEN 0 ELSE 1 END
        WHERE id = ?
        """,
        (menu_item_id,),
    )
    connection.commit()
    changed_rows = cursor.rowcount
    connection.close()

    if changed_rows == 0:
        abort(404)

    return redirect(url_for("menu"))


@app.route("/orders/new", methods=["GET", "POST"])
def new_order() -> str | Response:
    global CHAOS_SUBMIT_500_ONCE, CHAOS_TIMEOUT_AFTER_COMMIT_ONCE
    if request.method == "GET":
        if CHAOS_SLOW_PAGE_MS:
            time.sleep(CHAOS_SLOW_PAGE_MS / 1000)
        draft_id_text = request.args.get("draft_id", "").strip()
        if draft_id_text:
            try:
                draft_id = int(draft_id_text)
            except ValueError:
                abort(404)
            connection = get_db_connection()
            draft = connection.execute(
                "SELECT * FROM purchase_orders WHERE id = ? AND status = 'draft'",
                (draft_id,),
            ).fetchone()
            if draft is None:
                connection.close()
                abort(404)
            draft_lines = connection.execute(
                "SELECT item_id, qty_units FROM purchase_order_lines WHERE po_id = ? ORDER BY id",
                (draft_id,),
            ).fetchall()
            connection.close()
            return render_order_form(
                selected_supplier_id=str(draft["supplier_id"]),
                delivery_date_text=draft["delivery_date"],
                notes=draft["notes"] or "",
                item_ids=[str(line["item_id"]) for line in draft_lines],
                quantities=[str(line["qty_units"]) for line in draft_lines],
                visible_line_count=max(1, len(draft_lines)),
                order_total=draft["total"],
                draft_id=draft_id,
            )
        return render_order_form()

    action = request.form.get("action", "")
    selected_supplier_id = request.form.get("supplier_id", "")
    delivery_date_value = request.form.get("delivery_date", "").strip()
    try:
        delivery_date_text = date.fromisoformat(delivery_date_value).strftime("%d/%m/%Y")
    except ValueError:
        # Keep invalid text for validation so the user gets the normal date-format error.
        delivery_date_text = delivery_date_value
    notes = request.form.get("notes", "").strip()
    item_ids = request.form.getlist("item_id")
    quantities = request.form.getlist("quantity")
    draft_id_text = request.form.get("draft_id", "").strip()
    try:
        draft_id = int(draft_id_text) if draft_id_text else None
    except ValueError:
        abort(404)

    visible_line_count = max(
        (
            index + 1
            for index, (item_id, quantity) in enumerate(zip(item_ids, quantities))
            if item_id or quantity
        ),
        default=1,
    )

    errors = []
    if action not in {"draft", "submit"}:
        errors.append("Choose Save draft or Submit order.")

    try:
        supplier_id = int(selected_supplier_id)
    except ValueError:
        supplier_id = None
        errors.append("Select a supplier.")

    connection = get_db_connection()
    supplier_row = None
    draft_created_at = None

    if draft_id is not None:
        draft = connection.execute(
            "SELECT status, created_at FROM purchase_orders WHERE id = ?",
            (draft_id,),
        ).fetchone()
        if draft is None or draft["status"] != "draft":
            connection.close()
            abort(404)
        draft_created_at = draft["created_at"]

    if supplier_id is not None:
        supplier_row = connection.execute(
            "SELECT * FROM suppliers WHERE id = ?",
            (supplier_id,),
        ).fetchone()

        if supplier_row is None:
            errors.append("Select a valid supplier.")

    lines = []

    for item_text, quantity_text in zip(item_ids, quantities):
        if not item_text and not quantity_text:
            continue

        if not item_text:
            errors.append("Select an item for each order line with a quantity.")
            continue

        try:
            item_id = int(item_text)
        except ValueError:
            errors.append("Select a valid inventory item.")
            continue

        item = connection.execute(
            "SELECT id, name, unit FROM inventory_items WHERE id = ?",
            (item_id,),
        ).fetchone()

        if item is None:
            errors.append("Select a valid inventory item.")
            continue

        offer = None
        if supplier_id is not None:
            offer = connection.execute(
                """
                SELECT case_size, price_per_case, available
                FROM supplier_items
                WHERE supplier_id = ? AND item_id = ?
                """,
                (supplier_id, item_id),
            ).fetchone()

        lines.append(
            {
                "item_id": item_id,
                "item_name": item["name"],
                "unit": item["unit"],
                "quantity": quantity_text,
                "case_size": offer["case_size"] if offer else None,
                "price_per_case": offer["price_per_case"] if offer else 0,
                "available": offer["available"] if offer else None,
            }
        )

    connection.close()

    order_total = 0
    for line in lines:
        case_size = line["case_size"]
        quantity = line["quantity"]

        if case_size and is_positive_whole_quantity(quantity):
            quantity_number = int(quantity)
            cases = (quantity_number + case_size - 1) // case_size
            order_total += cases * line["price_per_case"]

    if supplier_row is not None:
        errors.extend(
            validate_purchase_order(
                delivery_date_text=delivery_date_text,
                today=get_validation_today(),
                supplier=dict(supplier_row),
                lines=lines,
                order_total=order_total,
                submit=(action == "submit"),
            )
        )

    if errors:
        return render_order_form(
            errors=errors,
            selected_supplier_id=selected_supplier_id,
            delivery_date_text=delivery_date_value,
            notes=notes,
            item_ids=item_ids,
            quantities=quantities,
            visible_line_count=visible_line_count,
            order_total=order_total,
            draft_id=draft_id,
        )

    if action == "submit" and CHAOS_SUBMIT_500_ONCE:
        CHAOS_SUBMIT_500_ONCE = False
        abort(500)

    delivery_date_iso = datetime.strptime(
        delivery_date_text,
        "%d/%m/%Y",
    ).date().isoformat()

    created_at = draft_created_at or datetime.now().isoformat(timespec="seconds")
    is_submit = action == "submit"

    connection = get_db_connection()
    if is_submit and DUPLICATE_GUARD:
        matching_orders = connection.execute(
            """SELECT COUNT(*) FROM purchase_orders
               WHERE supplier_id = ? AND status = 'submitted'
                 AND delivery_date = ? AND total = ? AND id != ?""",
            (supplier_id, delivery_date_iso, order_total, draft_id or 0),
        ).fetchone()[0]
        if matching_orders > 0:
            connection.close()
            abort(409)

    if draft_id is None:
        cursor = connection.execute(
            """
            INSERT INTO purchase_orders
                (supplier_id, status, delivery_date, total, notes, created_at, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supplier_id,
                "submitted" if is_submit else "draft",
                delivery_date_iso,
                order_total,
                notes or None,
                created_at,
                created_at if is_submit else None,
            ),
        )
        order_id = cursor.lastrowid
    else:
        connection.execute(
            """UPDATE purchase_orders
               SET supplier_id = ?, status = ?, delivery_date = ?, total = ?, notes = ?, submitted_at = ?
               WHERE id = ? AND status = 'draft'""",
            (
                supplier_id,
                "submitted" if is_submit else "draft",
                delivery_date_iso,
                order_total,
                notes or None,
                created_at if is_submit else None,
                draft_id,
            ),
        )
        connection.execute("DELETE FROM purchase_order_lines WHERE po_id = ?", (draft_id,))
        order_id = draft_id

    for line in lines:
        quantity = int(line["quantity"])
        case_size = line["case_size"] or 0
        cases = (
            (quantity + case_size - 1) // case_size
            if case_size
            else 0
        )
        price_per_case = line["price_per_case"]
        line_total = cases * price_per_case

        connection.execute(
            """
            INSERT INTO purchase_order_lines
                (po_id, item_id, qty_units, cases, unit_price_per_case, line_total)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                line["item_id"],
                quantity,
                cases,
                price_per_case,
                line_total,
            ),
        )

    connection.commit()
    connection.close()

    if action == "submit" and CHAOS_TIMEOUT_AFTER_COMMIT_ONCE:
        CHAOS_TIMEOUT_AFTER_COMMIT_ONCE = False
        abort(504)

    return redirect(url_for("order_detail", order_id=order_id))


if __name__ == "__main__":
    app.run(debug=True)
