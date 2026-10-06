import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

database_setting = os.getenv("DATABASE_PATH", "env/db/brew.sqlite3")
database_path = Path(database_setting)

if not database_path.is_absolute():
    database_path = PROJECT_ROOT / database_path


suppliers = [
    (1, "FreshFarm Dairy & Bakery", "active", None, 1, 1500),
    (2, "GreenLeaf Wholesale", "active", None, 2, 3000),
    (3, "BeanBros Roasters", "hold", "Unpaid invoice INV-2291", 3, 2000),
]

inventory_items = [
    (1, "Whole milk", "L", 14, 20, 60, "2026-10-08", 1),
    (2, "Oat milk (barista)", "L", 0, 12, 36, "2027-01-15", 1),
    (3, "Espresso beans", "kg", 3, 5, 12, "2027-02-01", 3),
    (4, "Decaf beans", "kg", 4, 2, 8, "2027-03-01", 3),
    (5, "Sugar", "kg", 5, 5, 20, None, 2),
    (6, "Vanilla syrup", "bottle", 0, 3, 9, "2027-06-01", 2),
    (7, "Chocolate sauce", "bottle", 5, 3, 9, "2027-05-01", 2),
    (8, "Paper cups 8oz", "pack (100)", 8, 10, 30, None, 2),
    (9, "Cup lids", "pack (100)", 15, 10, 30, None, 2),
    (10, "Butter croissant", "piece", 20, 24, 48, "2026-10-07", 1),
    (11, "Blueberry muffin", "piece", 10, 12, 36, "2026-10-06", 1),
    (12, "Chai concentrate", "L", 9, 4, 18, "2026-11-20", 2),
]

# Fields: supplier ID, inventory item ID, case size, case price, available.
supplier_items = [
    (1, 1, 12, 780, 1),
    (1, 2, 12, 1950, 0),
    (1, 10, 12, 600, 1),
    (1, 11, 12, 660, 1),
    (2, 1, 12, 840, 1),
    (2, 2, 12, 2100, 1),
    (2, 3, 1, 850, 1),
    (2, 4, 1, 880, 1),
    (2, 5, 5, 260, 1),
    (2, 6, 3, 1260, 1),
    (2, 7, 3, 1050, 1),
    (2, 8, 5, 1100, 1),
    (2, 9, 5, 800, 1),
    (2, 12, 6, 1200, 1),
    (3, 3, 1, 720, 1),
    (3, 4, 1, 760, 1),
]

# Fields: menu item ID, name, price, available.
menu_items = [
    (1, "Espresso", 120, 1),
    (2, "Americano", 140, 1),
    (3, "Cappuccino", 180, 1),
    (4, "Latte", 190, 1),
    (5, "Oat Milk Latte", 230, 1),
    (6, "Vanilla Latte", 220, 1),
    (7, "Mocha", 230, 0),
    (8, "Masala Chai", 150, 1),
    (9, "Butter Croissant", 110, 1),
    (10, "Blueberry Muffin", 130, 1),
]

# Fields: menu item ID, inventory item ID, quantity used per serving.
menu_ingredients = [
    (1, 3, 0.018),
    (2, 3, 0.018),
    (3, 3, 0.018),
    (3, 1, 0.15),
    (4, 3, 0.018),
    (4, 1, 0.25),
    (5, 3, 0.018),
    (5, 2, 0.25),
    (6, 3, 0.018),
    (6, 1, 0.25),
    (6, 6, 0.03),
    (7, 3, 0.018),
    (7, 1, 0.25),
    (7, 7, 0.04),
    (8, 12, 0.05),
    (8, 1, 0.2),
    (9, 10, 1),
    (10, 11, 1),
]


connection = sqlite3.connect(database_path)

connection.executemany(
    """
    INSERT INTO suppliers
        (id, name, status, hold_reason, lead_time_days, min_order_value)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
    suppliers,
)

connection.executemany(
    """
    INSERT INTO inventory_items
        (id, name, unit, on_hand, reorder_point, par_level, expiry_date, default_supplier_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
    inventory_items,
)

connection.executemany(
    """
    INSERT INTO supplier_items
        (supplier_id, item_id, case_size, price_per_case, available)
    VALUES (?, ?, ?, ?, ?)
    """,
    supplier_items,
)

connection.executemany(
    """
    INSERT INTO menu_items (id, name, price, available)
    VALUES (?, ?, ?, ?)
    """,
    menu_items,
)

connection.executemany(
    """
    INSERT INTO menu_ingredients
        (menu_item_id, item_id, qty_per_serving)
    VALUES (?, ?, ?)
    """,
    menu_ingredients,
)

connection.commit()
connection.close()

print(
    f"Seeded {len(suppliers)} suppliers, "
    f"{len(inventory_items)} inventory items, "
    f"{len(supplier_items)} supplier offers, "
    f"{len(menu_items)} menu items, and "
    f"{len(menu_ingredients)} menu ingredient links."
)