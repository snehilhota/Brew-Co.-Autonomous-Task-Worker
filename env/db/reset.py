"""Recreate the local database from schema.sql."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_DIR = PROJECT_ROOT / "env" / "db"
SCHEMA_PATH = DB_DIR / "schema.sql"


def main() -> None:
    # Read local settings, including DATABASE_PATH, from .env.
    load_dotenv(PROJECT_ROOT / ".env")

    database_setting = os.getenv("DATABASE_PATH", "env/db/brew.sqlite3")
    database_path = Path(database_setting)

    # Resolve relative paths from the project root.
    if not database_path.is_absolute():
        database_path = PROJECT_ROOT / database_path
    database_path = database_path.resolve()

    # This script deletes the old database, so restrict it to env/db.
    if database_path.parent != DB_DIR.resolve():
        raise SystemExit("DATABASE_PATH must point to a file directly inside env/db.")
    if database_path.suffix.lower() not in {".db", ".sqlite3"}:
        raise SystemExit("DATABASE_PATH must end in .db or .sqlite3.")

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    # Remove the old generated database, if present, then recreate its tables.
    database_path.unlink(missing_ok=True)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.executescript(schema_sql)

    print(f"Created a fresh database at {database_path}")


if __name__ == "__main__":
    main()