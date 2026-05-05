"""
setup_db.py
===========
ConcertRush — End-to-end database setup pipeline.

This single script automates the entire database initialization:
  1. Connects to PostgreSQL (admin connection to the default 'postgres' DB)
  2. Creates the 'concertrush' database if it does not exist
  3. Imports concertrush_dump.sql (extensions + schema + 500 seats)
  4. Verifies the import succeeded

After running this, the database is fully ready.
Run the application with:  python main.py

Usage:
    python setup_db.py            # full pipeline (idempotent — safe to re-run)
    python setup_db.py --reset    # drop & recreate the database from scratch
"""

import os
import sys
import argparse
import psycopg2
from psycopg2 import sql

# Reuse the same connection settings used by the application
from db import DB_CONFIG

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DUMP_FILE = os.path.join(BASE_DIR, "sql", "concertrush_dump.sql")


# ── Helpers ──────────────────────────────────────────────────────────────────
def get_admin_conn():
    """Connect to the default 'postgres' database — required for CREATE DATABASE."""
    cfg = dict(DB_CONFIG)
    cfg["dbname"] = "postgres"   # always exists
    conn = psycopg2.connect(**cfg)
    conn.autocommit = True       # CREATE DATABASE cannot run inside a transaction
    return conn


def get_target_conn():
    """Connect to the project database (concertrush)."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    return conn


def database_exists(cur, dbname):
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,))
    return cur.fetchone() is not None


def section(num, total, label):
    print(f"\n[{num}/{total}] {label}")
    print("-" * 60)


# ── Pipeline steps ───────────────────────────────────────────────────────────
def step_create_database(reset=False):
    section(1, 4, "Connecting to PostgreSQL & creating database")

    try:
        conn = get_admin_conn()
    except psycopg2.OperationalError as e:
        print(f"  [ERROR] Cannot connect to PostgreSQL.")
        print(f"  {e}")
        print()
        print("  Check the following:")
        print("    1. PostgreSQL service is running")
        print("       macOS:  brew services start postgresql@16")
        print("       Linux:  sudo systemctl start postgresql")
        print("    2. db.py credentials match your local 'postgres' user password")
        print("    3. PostgreSQL is listening on localhost:5432")
        sys.exit(1)

    cur = conn.cursor()
    target_db = DB_CONFIG["dbname"]

    if reset and database_exists(cur, target_db):
        print(f"  --reset: dropping existing database '{target_db}'...")
        # Terminate any active connections to the target DB before dropping
        cur.execute("""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid();
        """, (target_db,))
        cur.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target_db)))
        print(f"  [OK] Dropped '{target_db}'")

    if database_exists(cur, target_db):
        print(f"  [SKIP] Database '{target_db}' already exists")
    else:
        print(f"  Creating database '{target_db}'...")
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
        print(f"  [OK] Database '{target_db}' created")

    cur.close()
    conn.close()


def step_import_dump():
    section(2, 4, f"Importing {DUMP_FILE}")

    if not os.path.exists(DUMP_FILE):
        print(f"  [ERROR] {DUMP_FILE} not found in current directory")
        print(f"  Make sure you are running this script from the repository root.")
        sys.exit(1)

    with open(DUMP_FILE, "r", encoding="utf-8") as f:
        sql_text = f.read()

    print(f"  Loaded {DUMP_FILE} ({len(sql_text):,} bytes)")
    print(f"  Executing against '{DB_CONFIG['dbname']}'...")

    conn = get_target_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql_text)
        print(f"  [OK] Dump imported successfully")
    except psycopg2.Error as e:
        print(f"  [ERROR] Import failed: {e}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def step_verify():
    section(3, 4, "Verifying import")

    conn = get_target_conn()
    cur = conn.cursor()

    checks = []

    # Tables exist
    cur.execute("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name IN ('concerts', 'seats');
    """)
    table_count = cur.fetchone()[0]
    checks.append(("Tables (concerts, seats)", table_count == 2, f"{table_count}/2"))

    # Extensions installed
    cur.execute("""
        SELECT COUNT(*) FROM pg_extension
        WHERE extname IN ('pgstattuple', 'pageinspect', 'pg_visibility');
    """)
    ext_count = cur.fetchone()[0]
    checks.append(("Extensions (3 required)", ext_count == 3, f"{ext_count}/3"))

    # Row counts
    cur.execute("SELECT COUNT(*) FROM concerts;")
    c_count = cur.fetchone()[0]
    checks.append(("concerts rows", c_count == 1, f"{c_count} (expected 1)"))

    cur.execute("SELECT COUNT(*) FROM seats;")
    s_count = cur.fetchone()[0]
    checks.append(("seats rows", s_count == 500, f"{s_count} (expected 500)"))

    # fillfactor setting
    cur.execute("""
        SELECT reloptions FROM pg_class WHERE relname = 'seats';
    """)
    opts = cur.fetchone()[0]
    has_ff = opts is not None and any("fillfactor=70" in o for o in opts)
    checks.append(("seats fillfactor=70", has_ff, "set" if has_ff else "missing"))

    cur.close()
    conn.close()

    all_ok = True
    for label, ok, detail in checks:
        marker = "[OK]  " if ok else "[FAIL]"
        print(f"  {marker} {label:<35} {detail}")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\n  [WARN] Some checks failed. Review the messages above.")
        sys.exit(1)


def step_done():
    section(4, 4, "Setup complete")
    print("  The database is fully initialized.")
    print()
    print("  Run the application:")
    print("      python main.py")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="ConcertRush database setup pipeline"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DROP and recreate the database from scratch (destructive!)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print(" ConcertRush — Database Setup Pipeline")
    print("=" * 60)
    print(f" Host     : {DB_CONFIG['host']}:{DB_CONFIG['port']}")
    print(f" Database : {DB_CONFIG['dbname']}")
    print(f" User     : {DB_CONFIG['user']}")
    print(f" Mode     : {'RESET (drop & recreate)' if args.reset else 'SAFE (idempotent)'}")
    print("=" * 60)

    if args.reset:
        confirm = input("\nThis will DROP all existing data. Type 'yes' to continue: ").strip()
        if confirm.lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    step_create_database(reset=args.reset)
    step_import_dump()
    step_verify()
    step_done()


if __name__ == "__main__":
    main()
