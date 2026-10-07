import os
import sqlite3
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, redirect, render_template, request, url_for
from datetime import date, datetime
from validation import is_positive_whole_quantity, validate_purchase_order


ENV_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ENV_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

today_setting = os.getenv("APP_TODAY", "2026-10-05")
APP_TODAY = date.fromisoformat(today_setting)

database_setting = os.getenv("DATABASE_PATH", "env/db/brew.sqlite3")
DATABASE_PATH = Path(database_setting)

if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = PROJECT_ROOT / DATABASE_PATH

app = Flask(__name__, template_folder="templates")


def get_today_label() -> str:
    return APP_TODAY.strftime("%a %d/%m/%Y")


def get_db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


@app.get("/")
def home() -> str:
    return render_template(
        "home.html",
        today_label=get_today_label(),
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
            inventory_items.expiry_date,
            inventory_items.flagged,
            inventory_items.flag_note,
            suppliers.name AS default_supplier
        FROM inventory_items
        LEFT JOIN suppliers
            ON inventory_items.default_supplier_id = suppliers.id
        ORDER BY inventory_items.id
        """
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
        SELECT id, name, price, available
        FROM menu_items
        ORDER BY id
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

@app.get("/orders/new")
def render_order_form(
    errors: list[str] | None = None,
    selected_supplier_id: str = "",
    delivery_date_text: str = "",
    notes: str = "",
    item_ids: list[str] | None = None,
    quantities: list[str] | None = None,
    visible_line_count: int = 1,
    order_total: int = 0,
) -> str:
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
    )


@app.route("/orders/new", methods=["GET", "POST"])
def new_order() -> str | Response:
    if request.method == "GET":
        return render_order_form()

    action = request.form.get("action", "")
    selected_supplier_id = request.form.get("supplier_id", "")
    delivery_date_text = request.form.get("delivery_date", "").strip()
    notes = request.form.get("notes", "").strip()
    item_ids = request.form.getlist("item_id")
    quantities = request.form.getlist("quantity")

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
                today=APP_TODAY,
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
            delivery_date_text=delivery_date_text,
            notes=notes,
            item_ids=item_ids,
            quantities=quantities,
            visible_line_count=visible_line_count,
            order_total=order_total,
        )

    delivery_date_iso = datetime.strptime(
        delivery_date_text,
        "%d/%m/%Y",
    ).date().isoformat()

    created_at = datetime.now().isoformat(timespec="seconds")
    is_submit = action == "submit"

    connection = get_db_connection()
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

    return redirect(url_for("order_detail", order_id=order_id))


if __name__ == "__main__":
    app.run(debug=True)