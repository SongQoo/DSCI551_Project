# ConcertRush — PostgreSQL Internals Simulator

> **DSCI 551 · Foundations of Data Management · Spring 2026**
> Junhyeon Song · University of Southern California

ConcertRush is a Python CLI application that simulates a concurrent concert ticket reservation system and exposes **PostgreSQL 16 internals in real time** through three instrumented scenarios:

| Scenario | PostgreSQL Internal | Key Observation |
|---|---|---|
| **A** | MVCC / Snapshot Isolation + Row Locking | Readers see pre-commit snapshot; concurrent writer blocks on row-level lock |
| **B** | Heap & Index Bloat (Non-HOT Updates) | Dead tuple accumulation; index growth proportional to write volume |
| **C** | VACUUM & Visibility Map | `Heap Fetches` drops to 0 after VACUUM; Index-Only Scan activated |

---

## Table of Contents

1. [Repository Structure](#1-repository-structure)
2. [Prerequisites](#2-prerequisites)
3. [Step 1 — Install PostgreSQL 16](#3-step-1--install-postgresql-16)
4. [Step 2 — Set the `postgres` User Password](#4-step-2--set-the-postgres-user-password)
5. [Step 3 — Configure `db.py`](#5-step-3--configure-dbpy)
6. [Step 4 — Install Python Dependencies](#6-step-4--install-python-dependencies)
7. [Step 5 — Initialize the Database (Pipeline)](#7-step-5--initialize-the-database-pipeline)
8. [Step 6 — Run the Application](#8-step-6--run-the-application)
9. [Scenario Guide](#9-scenario-guide)
10. [Dataset Information](#10-dataset-information)
11. [Reproducing Results](#11-reproducing-results)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Repository Structure

```
ConcertRush/
├── main.py                    # Entry point — interactive scenario menu
├── db.py                      # Database connection helper
├── scenario_a.py              # MVCC, Snapshot Isolation, Write/Write Locking
├── scenario_b.py              # Heap & Index Bloat generation + VACUUM
├── scenario_c.py              # VACUUM & Index-Only Scan I/O optimization
│
├── setup_db.py                # ⭐ End-to-end DB setup pipeline (createdb + import + verify)
│
├── sql/
│   ├── concertrush_dump.sql   # ⭐ Database dump (extensions + schema + 500 seats)
│   ├── schema.sql             # Raw DDL (reference only)
│   └── input_seed_data.sql    # Raw seed SQL (reference only)
│
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

The two ⭐ files together form the project's **automated data pipeline**:
- `setup_db.py` orchestrates: connect → create database → import dump → verify
- `sql/concertrush_dump.sql` is the synthetic dataset (1 concert + 500 seats)

---

## 2. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **PostgreSQL** | **16.x** | Installation instructions in [Step 1](#3-step-1--install-postgresql-16) |
| **Python** | **3.9+** | 3.11 recommended |
| **pip** | latest | Bundled with Python |
| **OS** | macOS, Windows, or Linux | All supported |

> **macOS users:** Xcode Command Line Tools must be installed before using Homebrew.
> Run: `xcode-select --install`

---

## 3. Step 1 — Install PostgreSQL 16

Choose **one** installation method below based on your operating system.

### 3.1 macOS (Homebrew — Recommended)

**a. Install Homebrew** (skip if already installed):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After installation, follow the on-screen instructions to add Homebrew to your shell PATH (Apple Silicon Macs require an additional step).

Verify:

```bash
brew --version
```

**b. Install PostgreSQL 16:**

```bash
brew install postgresql@16
```

**c. Add PostgreSQL binaries to your PATH:**

For **Apple Silicon (M1/M2/M3/M4)**:

```bash
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

For **Intel Mac**:

```bash
echo 'export PATH="/usr/local/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**d. Start the PostgreSQL service:**

```bash
brew services start postgresql@16
```

Verify it is running:

```bash
brew services list | grep postgresql
# Expected output: postgresql@16   started
```

**e. Verify version:**

```bash
postgres --version
# Expected: postgres (PostgreSQL) 16.x
```

---

### 3.2 macOS / Windows (Official Installer)

**a. Download the installer:**

Visit [https://www.postgresql.org/download/](https://www.postgresql.org/download/) → select your OS → click **Download the installer** (provided by EDB).

Choose version **16.x**.

**b. Run the installer:**

- Double-click the downloaded `.dmg` (macOS) or `.exe` (Windows).
- During installation:
  - **Set a password for the `postgres` superuser** when prompted. **Remember this password** — you will need it later.
  - Default port: `5432` (leave as-is).
  - Select all components: PostgreSQL Server, pgAdmin 4, Stack Builder, Command Line Tools.

**c. Verify installation (open a new terminal):**

```bash
psql --version
# Expected: psql (PostgreSQL) 16.x
```

> **Windows users:** If `psql` is not recognized, add `C:\Program Files\PostgreSQL\16\bin` to your system PATH variable, OR use the full path:
> `"C:\Program Files\PostgreSQL\16\bin\psql.exe"`

---

### 3.3 Linux (Ubuntu / Debian)

```bash
# Add the official PostgreSQL APT repository
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc --fail \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc
sudo sh -c 'echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
  https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list'

# Install PostgreSQL 16 + contrib (required for pgstattuple/pageinspect/pg_visibility)
sudo apt update
sudo apt install -y postgresql-16 postgresql-contrib-16

# Start and enable the service
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Verify
psql --version
```

---

## 4. Step 2 — Set the `postgres` User Password

The application connects as the PostgreSQL superuser `postgres`. The pipeline script (`setup_db.py`) needs this user to be able to create databases and install extensions.

### macOS (Homebrew)

By default, Homebrew's PostgreSQL does not create the `postgres` superuser role. Create it now:

```bash
psql postgres
```

Inside the `psql` shell:

```sql
CREATE USER postgres WITH SUPERUSER PASSWORD '1346123';
\q
```

> If the role already exists, use `ALTER USER postgres WITH SUPERUSER PASSWORD '1346123';` instead.

### macOS / Windows (Official Installer)

The `postgres` user already exists with the password you set during installation. If that password differs from `1346123`, update `db.py` in [Step 3](#5-step-3--configure-dbpy).

### Linux (Ubuntu / Debian)

```bash
sudo -u postgres psql
```

Inside the `psql` shell:

```sql
ALTER USER postgres WITH PASSWORD '1346123';
\q
```

> ⚠️ The default password used in `db.py` is `1346123`. You can either match this password during setup, or update `db.py` to match your own password (next step).

---

## 5. Step 3 — Configure `db.py`

The database connection settings live in **`db.py`**:

```python
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "concertrush",
    "user":     "postgres",
    "password": "1346123"
}
```

**If you set the `postgres` password to `1346123` in Step 2 → no changes needed.**

**If your password is different,** open `db.py` in a text editor and replace `"1346123"` with your actual password.

> Other fields (`host`, `port`, `dbname`, `user`) should not need to change for a default local setup.

---

## 6. Step 4 — Install Python Dependencies

Clone the repository:

```bash
git clone https://github.com/SongQoo/DSCI551_Project
cd ConcertRush
```

Install the required Python package:

```bash
pip install -r requirements.txt
```

**`requirements.txt` contents:**

```
psycopg2-binary>=2.9.0
```

Verify:

```bash
python -c "import psycopg2; print('psycopg2 version:', psycopg2.__version__)"
```

> If `pip` or `python` is not found, use `pip3` and `python3` instead. On Windows, use `py -m pip install -r requirements.txt`.

---

## 7. Step 5 — Initialize the Database (Pipeline)

This is the core data pipeline step. **A single command** does everything:

- Connects to the local PostgreSQL server
- Creates the `concertrush` database (if it does not exist)
- Imports `sql/concertrush_dump.sql` — installs all required extensions, creates schema (tables, indexes, constraints with `fillfactor=70`), and inserts the synthetic dataset (1 concert + 500 seats)
- Verifies that all tables, extensions, row counts, and storage parameters are correct

```bash
python setup_db.py
```

**Expected output:**

```
============================================================
 ConcertRush — Database Setup Pipeline
============================================================
 Host     : localhost:5432
 Database : concertrush
 User     : postgres
 Mode     : SAFE (idempotent)
============================================================

[1/4] Connecting to PostgreSQL & creating database
------------------------------------------------------------
  Creating database 'concertrush'...
  [OK] Database 'concertrush' created

[2/4] Importing sql/concertrush_dump.sql
------------------------------------------------------------
  Loaded sql/concertrush_dump.sql (20,210 bytes)
  Executing against 'concertrush'...
  [OK] Dump imported successfully

[3/4] Verifying import
------------------------------------------------------------
  [OK]   Tables (concerts, seats)            2/2
  [OK]   Extensions (3 required)             3/3
  [OK]   concerts rows                       1 (expected 1)
  [OK]   seats rows                          500 (expected 500)
  [OK]   seats fillfactor=70                 set

[4/4] Setup complete
------------------------------------------------------------
  The database is fully initialized.

  Run the application:
      python main.py
```

**To completely reset the database** (drops all data and recreates from scratch):

```bash
python setup_db.py --reset
```

> **The script is idempotent.** Re-running `python setup_db.py` without `--reset` is safe — it will skip existing objects and re-import the data.

---

### Alternative: Manual Setup (Without the Pipeline Script)

If you prefer to run each step manually with `psql`, the dataset can also be imported directly from the dump file:

```bash
# 1. Create the database
createdb -U postgres concertrush

# 2. Import schema + 500 seats from the dump
psql -U postgres -d concertrush -f sql/concertrush_dump.sql

# 3. Run the application
python main.py
```

The two paths are equivalent. `setup_db.py` is the automated pipeline; the manual commands above achieve the same result.

---

## 8. Step 6 — Run the Application

```bash
python main.py
```

You should see the live dashboard and main menu:

```
================================================================================
  ConcertRush: Seat Reservation Simulator [PostgreSQL 16.x]
================================================================================
 +----------------------------------------------------------------------------+
 | [ DATABASE LIVE MONITORING - Concert ID: 1 ]                               |
 |                                                                            |
 |   * Seat Range : A-01 ~ T-25                                               |
 |   * Total      : 500 seats                                                 |
 |   * Reserved   : 0 seats                                                   |
 |   * Available  : 500 seats                                                 |
 +----------------------------------------------------------------------------+

                         >> SELECT SIMULATION SCENARIO <<

 + -------------------------------------------------------------------------- +
 | [1] Scenario A: MVCC & Snapshot Isolation Analysis                         |
 | [2] Scenario B: Heap & Index Bloat & VACUUM                                |
 | [3] Scenario C: VACUUM & I/O Optimization (Index-Only Scan)                |
 + -------------------------------------------------------------------------- +
 | [0] Exit System                                                            |
 + -------------------------------------------------------------------------- +

 Select an option (0-3) ->
```

Type `1`, `2`, or `3` and press ENTER to run a scenario. Type `0` to exit.

---

## 9. Scenario Guide

### Scenario A — MVCC & Snapshot Isolation + Write Locking

**Demonstrates:**

1. **Read/Write Isolation (MVCC):** While Writer 1 holds an open transaction on seat `A-01`, concurrent readers observe the pre-commit snapshot (`status = 'available'`). After commit, new readers observe the updated value (`status = 'reserved'`).
2. **Write/Write Locking:** While Writer 1 is open, Writer 2 attempts to UPDATE the same seat — it is placed in a row-level lock-wait queue and unblocks only after Writer 1 commits.

**Run:** Select option `[1]` from the main menu.

**Interactive flow:**

1. Writer 1 opens a transaction and updates seat `A-01` (uncommitted).
2. Reader observes `'available'` (pre-commit snapshot).
3. Writer 2 (background thread) attempts the same UPDATE → blocks on row lock.
4. `pg_locks` output shows the blocking/blocked relationship.
5. **Press ENTER** when prompted → Writer 1 commits.
6. Writer 2 unblocks and completes (or fails because seat is no longer available).
7. Final MVCC tuple chain printed via `heap_page_items()`.

**Key things to observe:**

- `[READER]` line shows `status: available` while Writer 1 is uncommitted.
- `pg_locks` shows `granted = False` for Writer 2.
- Pre-commit CLOG status is `IN PROGRESS`; post-commit becomes `COMMITTED`.
- Old and new tuple versions both visible in the heap.

---

### Scenario B — Heap & Index Bloat

**Demonstrates:** PostgreSQL's append-only MVCC produces dead tuples after bulk updates. Because `status` is indexed and `fillfactor=70` blocks HOT updates, every UPDATE creates a new index entry — measurable via `pgstattuple` and `pgstatindex`.

**Run:** Select option `[2]` from the main menu.

**Interactive flow:**

1. Autovacuum is disabled on the `seats` table; baseline VACUUM runs.
2. Initial bloat metrics printed (dead tuples = 0).
3. All 500 seats are updated to `'reserved'` in a single transaction.
4. Post-workload metrics show `dead_tuple_count = 500`.
5. **Press ENTER** when prompted → Manual `VACUUM (VERBOSE, ANALYZE)` runs.
6. Post-VACUUM metrics show `dead_tuple_count = 0` (space reclaimed).
7. Autovacuum re-enabled.

**Key things to observe:**

- Initial baseline: `dead_tuple_count = 0`.
- After workload: `dead_tuple_count = 500`, `dead_tuple_percent > N%`.
- VACUUM VERBOSE notices: removed N dead row versions, index entries cleaned.
- Post-VACUUM: `dead_tuple_count = 0`, free space recovered.

---

### Scenario C — VACUUM & Index-Only Scan Optimization

**Demonstrates:** Before VACUUM, dirty Visibility Map (VM) bits force the planner to fetch heap pages even with an index. After VACUUM sets the VM bits, the planner switches to an Index-Only Scan (`Heap Fetches = 0`).

**Run:** Select option `[3]` from the main menu.

**Interactive flow:**

1. All seats are updated → VM bits cleared (dirty state).
2. `pg_visibility` output: all pages show `FALSE (Dirty)`.
3. `EXPLAIN ANALYZE` on `SELECT status WHERE concert_id=1 AND status='available'`:
   - Scan type: `Index Scan`
   - `Heap Fetches: N` (non-zero)
4. **Press ENTER** when prompted → `VACUUM ANALYZE` runs.
5. `pg_visibility` output: all pages flip to `TRUE (Clean)`.
6. `EXPLAIN ANALYZE` runs again:
   - Scan type: `Index Only Scan`
   - `Heap Fetches: 0` (I/O optimized)

**Key things to observe:**

- Pre-VACUUM: `Index Scan`, `Heap Fetches > 0`.
- VM bits flip from `FALSE` to `TRUE` after VACUUM.
- Post-VACUUM: `Index Only Scan`, `Heap Fetches = 0`.

---

## 10. Dataset Information

ConcertRush uses **synthetically generated data** — no external dataset is required.

| Table | Rows | Description |
|---|---|---|
| `concerts` | 1 | BTS World Tour 2026 at Olympic Gymnasium, Seoul |
| `seats` | 500 | Seat codes A-01 through T-25 (20 rows × 25 columns), all initially `'available'` |

### How the Pipeline Generates and Loads Data

The full data pipeline is implemented in **`setup_db.py`**, which executes the following sequence:

1. **Connect to PostgreSQL** as the `postgres` superuser using credentials from `db.py`.
2. **Create the `concertrush` database** if it does not already exist.
3. **Read `sql/concertrush_dump.sql`** — a pre-generated PostgreSQL dump file included in this repository — and execute its contents against the new database. The dump file contains:
   - `CREATE EXTENSION` statements for `pgstattuple`, `pageinspect`, `pg_visibility`
   - `CREATE TABLE` statements for `concerts` and `seats` (with `fillfactor=70` on `seats`)
   - `CREATE INDEX` statements for `idx_seats_status` and `idx_seats_concert_status`
   - `INSERT` statements for 1 concert and 500 seats (synthesized as the Cartesian product of rows A–T × columns 01–25)
   - `setval` calls to advance the SERIAL sequences
4. **Verify the import** by checking row counts, extension presence, and the `fillfactor=70` storage parameter.

**Application execution** is then a separate command (`python main.py`), which reads from the populated database and runs the three interactive scenarios.

The synthetic dataset is also provided directly in this repository as `sql/concertrush_dump.sql` (the generated dataset file). Reference DDL/seed SQL is included in `sql/schema.sql` and `sql/input_seed_data.sql`.

---

## 11. Reproducing Results

Follow the steps below from a clean state to reproduce the results shown in the project report.

### 11.1 Full Setup Walkthrough

```bash
# 1. Start PostgreSQL
brew services start postgresql@16          # macOS Homebrew
# sudo systemctl start postgresql          # Linux

# 2. Clone the repository and install dependencies
git clone https://github.com/SongQoo/DSCI551_Project
cd ConcertRush
pip install -r requirements.txt

# 3. Run the data pipeline (creates DB + imports 500 seats)
python setup_db.py

# 4. Launch the application
python main.py
```

To reset the database to its initial state at any time:

```bash
python setup_db.py --reset
```

---

### 11.2 Expected Results per Scenario

#### Scenario A — MVCC & Snapshot Isolation + Write Locking

Select `[1]` from the main menu.

| Step | What you should see |
|---|---|
| Initial state | `status: available`, `xmax: 0` |
| Writer 1 updates (uncommitted) | CLOG shows `IN PROGRESS` for Writer 1's XID |
| Reader queries during open transaction | `status: available` (pre-commit snapshot — unchanged) |
| Writer 2 attempts same UPDATE | `pg_locks`: `granted = False` for Writer 2 |
| Press ENTER → Writer 1 commits | CLOG flips to `COMMITTED` |
| Writer 2 unblocks | `UPDATE FAILED` (seat no longer available) or `UPDATE SUCCESSFUL` |
| Final heap inspection | Two tuple versions visible: old (`xmax` set) + new (`xmin` = Writer 1's XID) |

#### Scenario B — Heap & Index Bloat

Select `[2]` from the main menu.

| Step | What you should see |
|---|---|
| Initial baseline | `dead_tuple_count = 0`, `dead_tuple_percent = 0.00%` |
| After 500-seat batch UPDATE | `dead_tuple_count = 500`, `dead_tuple_percent > 0%` |
| After manual VACUUM | `dead_tuple_count = 0`, free space recovered |
| VACUUM VERBOSE output | Reports N index entries removed, N heap pages cleaned |

#### Scenario C — VACUUM & Index-Only Scan

Select `[3]` from the main menu.

| Step | What you should see |
|---|---|
| After bulk UPDATE (dirty VM) | All pages show `FALSE (Dirty)` in `pg_visibility` |
| EXPLAIN ANALYZE (pre-VACUUM) | `Scan Methodology: Index Scan`, `Heap Fetches: N` (N > 0) |
| After VACUUM ANALYZE | All pages flip to `TRUE (Clean)` in `pg_visibility` |
| EXPLAIN ANALYZE (post-VACUUM) | `Scan Methodology: Index Only Scan`, `Heap Fetches: 0` |

---

## 12. Troubleshooting

### `psycopg2.OperationalError: could not connect to server`

PostgreSQL is not running. Start the service:

```bash
# macOS Homebrew
brew services start postgresql@16

# Linux systemd
sudo systemctl start postgresql

# Check status
pg_isready -U postgres -h localhost
```

---

### `FATAL: password authentication failed for user "postgres"`

The password in `db.py` does not match the actual `postgres` user password.

**Fix 1 — change the postgres user password to match `db.py`:**

```bash
psql postgres -c "ALTER USER postgres WITH PASSWORD '1346123';"
```

**Fix 2 — change `db.py` to match your password:**

Edit `db.py` and update the `password` field.

---

### `FATAL: role "postgres" does not exist`

The `postgres` superuser role was not created (common with Homebrew on macOS).

```bash
createuser -s postgres
psql postgres -c "ALTER USER postgres WITH PASSWORD '1346123';"
```

---

### `ERROR: could not open extension control file ".../pgstattuple.control"`

The PostgreSQL `contrib` package is missing.

**Ubuntu / Debian:**

```bash
sudo apt install postgresql-contrib-16
```

**macOS Homebrew:** `contrib` extensions are bundled with `postgresql@16` by default. Reinstall if necessary:

```bash
brew reinstall postgresql@16
brew services restart postgresql@16
```

**Windows:** The official installer bundles `contrib` automatically. Re-run the installer if files are missing.

---

### `ERROR: extension "pg_visibility" is not available`

Same fix as above — install `postgresql-contrib-16`.

---

### `ERROR: must be superuser to create extension "pgstattuple"`

The user importing the dump does not have superuser privileges.

```bash
psql postgres -c "ALTER USER postgres WITH SUPERUSER;"
```

---

### `setup_db.py` reports `[FAIL]` on verification

Run with `--reset` to drop and reinitialize the database from scratch:

```bash
python setup_db.py --reset
```

---

### Authentication mode mismatch (`peer` vs `md5`)

If `psql` works without a password but Python rejects the connection, edit `pg_hba.conf` to use password authentication:

```bash
# Find the location
psql -U postgres -c "SHOW hba_file;"
```

Open the file and change `peer` or `ident` to `md5` or `scram-sha-256` for local connections. Reload PostgreSQL:

```bash
# macOS Homebrew
brew services restart postgresql@16

# Linux
sudo systemctl reload postgresql
```

---

### Windows: `psql` is not recognized as a command

Add PostgreSQL's `bin` directory to your system PATH:

1. Press `Win + R`, type `sysdm.cpl`, press Enter
2. Go to **Advanced** → **Environment Variables**
3. Under **System variables**, find and edit **Path**
4. Add: `C:\Program Files\PostgreSQL\16\bin`
5. Restart your terminal

---

*ConcertRush · DSCI 551 Final Project · Junhyeon Song · USC · Spring 2026*
