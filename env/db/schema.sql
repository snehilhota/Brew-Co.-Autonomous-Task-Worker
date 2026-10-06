CREATE TABLE suppliers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','hold')), hold_reason TEXT,
  lead_time_days INTEGER NOT NULL, min_order_value INTEGER NOT NULL);

CREATE TABLE inventory_items (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, unit TEXT NOT NULL,
  on_hand REAL NOT NULL, reorder_point REAL NOT NULL, par_level REAL NOT NULL,
  expiry_date TEXT,
  default_supplier_id INTEGER REFERENCES suppliers(id),
  flagged INTEGER NOT NULL DEFAULT 0, flag_note TEXT);

CREATE TABLE supplier_items (
  supplier_id INTEGER, item_id INTEGER,
  case_size INTEGER NOT NULL, price_per_case INTEGER NOT NULL,
  available INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (supplier_id, item_id));

CREATE TABLE purchase_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_id INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('draft','submitted','cancelled')),
  delivery_date TEXT,
  total INTEGER NOT NULL DEFAULT 0, notes TEXT,
  created_at TEXT NOT NULL, submitted_at TEXT);

CREATE TABLE purchase_order_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT, po_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
  qty_units INTEGER NOT NULL, cases INTEGER NOT NULL,
  unit_price_per_case INTEGER NOT NULL, line_total INTEGER NOT NULL);

CREATE TABLE menu_items (
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  price INTEGER NOT NULL, available INTEGER NOT NULL);

CREATE TABLE menu_ingredients (
  menu_item_id INTEGER, item_id INTEGER,
  qty_per_serving REAL NOT NULL,
  PRIMARY KEY (menu_item_id, item_id));

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  entity TEXT NOT NULL, entity_id INTEGER, action TEXT NOT NULL, details TEXT);

CREATE TABLE app_config (
  key TEXT PRIMARY KEY, value TEXT NOT NULL);