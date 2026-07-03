"""
migrate_to_postgres.py
======================
Sprint V5.5 – SpaManager SQLite → PostgreSQL Data Migration Script

Usage:
    python migrate_to_postgres.py

Prerequisites:
    1. PostgreSQL must be running and the target database must exist.
    2. Set SQLITE_DB_PATH and POSTGRES_URL in this script or via environment variables.
    3. psycopg2 must be installed: pip install psycopg2-binary

Migration order (respects foreign key dependencies):
    users → customers → services → settings →
    appointments → invoices → invoice_details →
    activity_logs

The script preserves all original IDs, then resets PostgreSQL sequences
to MAX(id) + 1 to prevent future insert conflicts.
"""
import os
import sys
import sqlite3
from datetime import datetime

# ─── Configuration ────────────────────────────────────────────────────────────
SQLITE_DB_PATH = os.getenv("SQLITE_DB_PATH", os.path.join(os.path.dirname(__file__), "database", "spa.db"))
POSTGRES_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")

# ─── Validation ───────────────────────────────────────────────────────────────
if not POSTGRES_URL:
    print("[ERROR] POSTGRES_URL or DATABASE_URL environment variable is not set.")
    print("        Example: set DATABASE_URL=postgresql://user:password@host:5432/spadb")
    sys.exit(1)

if not os.path.exists(SQLITE_DB_PATH):
    print(f"[ERROR] SQLite database not found at: {SQLITE_DB_PATH}")
    sys.exit(1)

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("[ERROR] psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def get_sqlite_rows(sqlite_conn, table, columns):
    """Fetch all rows from a SQLite table as a list of dicts."""
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.cursor()
    try:
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError as e:
        log(f"Skipping table '{table}': {e}", "WARN")
        return []


def insert_rows_pg(pg_conn, table, columns, rows, conflict_column="id"):
    """Insert rows into PostgreSQL, ignoring existing conflicts on 'id'."""
    if not rows:
        log(f"  No rows to migrate for table '{table}'. Skipping.")
        return 0

    cur = pg_conn.cursor()
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_column}) DO NOTHING"
    )

    values = [[row.get(c) for c in columns] for row in rows]
    inserted = 0
    for val in values:
        try:
            cur.execute(sql, val)
            inserted += cur.rowcount
        except Exception as e:
            log(f"  Row insert error in '{table}': {e}", "WARN")
            pg_conn.rollback()

    pg_conn.commit()
    return inserted


def reset_sequence(pg_conn, table, pk_col="id"):
    """Reset PostgreSQL auto-increment sequence to max(id) + 1."""
    cur = pg_conn.cursor()
    cur.execute(f"SELECT MAX({pk_col}) FROM {table}")
    result = cur.fetchone()
    max_id = result[0] if result[0] is not None else 0
    seq_name = f"{table}_{pk_col}_seq"
    cur.execute(f"SELECT setval('{seq_name}', %s, true)", (max(max_id, 1),))
    pg_conn.commit()
    log(f"  Sequence '{seq_name}' reset to {max(max_id, 1)}")


# ─── Table Migration Definitions ──────────────────────────────────────────────
# Order matters: parent tables must come before child tables (FK deps).
MIGRATION_PLAN = [
    {
        "table": "users",
        "columns": [
            "id", "username", "password_hash", "full_name", "avatar",
            "role", "is_active", "last_login", "email", "email_verified",
            "auth_provider", "oauth_id", "created_at", "updated_at"
        ]
    },
    {
        "table": "customers",
        "columns": [
            "id", "name", "phone", "email", "address",
            "created_at", "deleted_at", "deleted_by"
        ]
    },
    {
        "table": "services",
        "columns": [
            "id", "name", "price", "duration", "description",
            "category", "deleted_at", "deleted_by"
        ]
    },
    {
        "table": "settings",
        "columns": ["id", "key", "value"]
    },
    {
        "table": "appointments",
        "columns": [
            "id", "customer_id", "service_id", "appointment_time",
            "status", "notes", "created_at", "deleted_at", "deleted_by"
        ]
    },
    {
        "table": "invoices",
        "columns": [
            "id", "customer_id", "invoice_date", "subtotal", "discount",
            "total_amount", "payment_method", "notes", "created_at",
            "deleted_at", "deleted_by"
        ]
    },
    {
        "table": "invoice_details",
        "columns": ["id", "invoice_id", "service_id", "price", "quantity"]
    },
    {
        "table": "activity_logs",
        "columns": [
            "id", "created_at", "module", "action", "description",
            "reference_id", "user_id", "severity"
        ]
    },
]

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("SpaManager SQLite → PostgreSQL Migration")
    log("=" * 60)
    log(f"Source  : {SQLITE_DB_PATH}")
    log(f"Target  : {POSTGRES_URL[:40]}...")
    log("")

    # Open connections
    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    try:
        pg_conn = psycopg2.connect(POSTGRES_URL)
    except Exception as e:
        log(f"Cannot connect to PostgreSQL: {e}", "ERROR")
        sys.exit(1)

    summary = []
    for spec in MIGRATION_PLAN:
        table = spec["table"]
        columns = spec["columns"]

        log(f"Migrating table: {table} ...")
        rows = get_sqlite_rows(sqlite_conn, table, columns)
        log(f"  Found {len(rows)} rows in SQLite.")

        # Filter only columns that exist in the row data
        if rows:
            available_cols = [c for c in columns if c in rows[0]]
        else:
            available_cols = columns

        count = insert_rows_pg(pg_conn, table, available_cols, rows)
        log(f"  Inserted {count} rows into PostgreSQL.")
        reset_sequence(pg_conn, table)
        summary.append((table, len(rows), count))

    sqlite_conn.close()
    pg_conn.close()

    log("")
    log("=" * 60)
    log("MIGRATION SUMMARY")
    log("=" * 60)
    log(f"{'Table':<20} {'SQLite Rows':>12} {'Inserted':>10}")
    log("-" * 45)
    for table, src, dst in summary:
        status = "OK" if src == dst else "PARTIAL"
        log(f"{table:<20} {src:>12} {dst:>10}  [{status}]")
    log("=" * 60)
    log("Migration complete.")


if __name__ == "__main__":
    main()
