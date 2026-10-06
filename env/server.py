import os
import sqlite3
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, abort, redirect, render_template, request, url_for


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
def new_order() -> str:
    connection = get_db_connection()
    supplier_rows = connection.execute(
        """
        SELECT id, name, status, hold_reason
        FROM suppliers
        ORDER BY id
        """
    ).fetchall()
    inventory_rows = connection.execute(
        """
        SELECT id, name, unit
        FROM inventory_items
        ORDER BY id
        """
    ).fetchall()
    connection.close()

    return render_template(
        "order_new.html",
        suppliers=supplier_rows,
        inventory_items=inventory_rows,
        today_label=get_today_label(),
    )


if __name__ == "__main__":
    app.run(debug=True)