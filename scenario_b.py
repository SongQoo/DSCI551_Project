import time
from db import get_conn, get_cursor

CONCERT_ID = 1

def enable_autovacuum():
    """Re-enable autovacuum for maintenance after simulation."""
    with get_conn(autocommit=True) as conn:
        with get_cursor(conn) as cur:
            cur.execute("ALTER TABLE seats SET (autovacuum_enabled = true);")
    print("\n[CLEANUP] Autovacuum re-enabled.")

def get_bloat_stats():
    """Fetch storage metrics using pgstattuple and pgstatindex extensions."""
    with get_conn(autocommit=True) as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT * FROM pgstattuple('seats');")
            heap = dict(cur.fetchone())
            cur.execute("SELECT * FROM pgstatindex('idx_seats_status');")
            idx = dict(cur.fetchone())
    return heap, idx

def print_bloat(label, heap, idx):
    """Print a formatted report of dead tuples and storage bloat."""
    line_width = 100
    print(f"\n{'='*line_width}")
    print(f" [{label}] PHYSICAL STORAGE DIAGNOSTICS (From pgstattuple & pgstatindex)")
    print("-" * line_width)
    print(f"  [HEAP]  Dead Tuple Count : {heap['dead_tuple_count']:<10,}")
    print(f"  [HEAP]  Dead Tuple Ratio : {heap['dead_tuple_percent']:>5.2f}%")
    print(f"  [HEAP]  Free Space       : {heap['free_space']:<10,} bytes")
    print(f"  [INDEX] Total Index Size : {idx['index_size']:<10,} bytes")
    print(f"  [INDEX] Avg Leaf Density : {idx['avg_leaf_density']:>5.2f}%")
    print(f"  [INDEX] Deleted Pages     : {idx['deleted_pages']}")
    print(f"{'='*line_width}\n")

def reset_seats():
    """Prepare a clean state for bloat generation by disabling autovacuum and cleaning heap."""
    print("[RESET] Disabling Autovacuum (ALTER TABLE seats SET (autovacuum_enabled = false)) and clearing stale data...")
    conn1 = get_conn(autocommit=True)
    cur1 = conn1.cursor()

    # disable autovacuum to see if it affects bloat
    cur1.execute("ALTER TABLE seats SET (autovacuum_enabled = false);")
    cur1.execute("UPDATE seats SET status='available', reserved_by=NULL WHERE concert_id=%s", (CONCERT_ID,))
    cur1.close(); conn1.close()

    time.sleep(1)

    print("[RESET] Running VACUUM to stabilize storage metrics...")
    conn2 = get_conn(autocommit=True)
    conn2.set_isolation_level(0)
    cur2 = conn2.cursor()
    cur2.execute("VACUUM ANALYZE seats;")
    cur2.close(); conn2.close()

    time.sleep(1)
    heap_b, idx_b = get_bloat_stats()
    print_bloat("1. INITIAL BASELINE", heap_b, idx_b)

def batch_update_single_tx(all_ids):
    """Execute a massive batch update in a single transaction to generate dead tuples."""
    print(f"\n[WORKLOAD] {len(all_ids)} SEATS MONITORING ...")

    conn = get_conn(autocommit=False)
    cur  = get_cursor(conn)
    try:
        for i, seat_id in enumerate(all_ids):
            cur.execute("UPDATE seats SET status='reserved', reserved_by='batch_worker' WHERE seat_id=%s", (seat_id,))
            if (i+1) % 100 == 0:
                print(f" ... Progress: {i+1}/{len(all_ids)} rows reserved")
        conn.commit()
        print(f"\n[SUCCESS] Transaction Committed.")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Batch transaction failed: {e}")
    finally:
        cur.close(); conn.close()

def run():
    line_width = 100
    print("=" * line_width)
    print(f"{'SCENARIO B: Heap & Index Bloat Analysis (MVCC Storage Side-Effects)':^100}")
    print("=" * line_width)
    
    reset_seats()

    with get_conn(autocommit=True) as conn:
        with get_cursor(conn) as cur:
            cur.execute("SELECT seat_id FROM seats WHERE concert_id=%s", (CONCERT_ID,))
            all_ids = [r['seat_id'] for r in cur.fetchall()]

    time.sleep(1)
    batch_update_single_tx(all_ids)

    heap_a, idx_a = get_bloat_stats()
    
    print("\n[INFO] ALL SEATS ARE SOLD OUT IN SECONDS!\n")
    print_bloat("2. POST-WORKLOAD ", heap_a, idx_a)

    input("\n[WAIT] ⏸  Press ENTER to perform Manual VACUUM (Reclaim Space)...")

    print("\n[VACUUM] Reclaiming dead space (with VERBOSE mode)...")
    # Use a dedicated connection for VACUUM to ensure it runs outside a transaction block
    v_conn = get_conn(autocommit=True)
    v_conn.set_isolation_level(0)
    v_cur = v_conn.cursor()
    
    try:
        # Run VACUUM with VERBOSE and ANALYZE to get detailed internal reports
        v_cur.execute("VACUUM (VERBOSE, ANALYZE) seats;")
        print("[SUCCESS] Manual VACUUM complete.")

        # Print PostgreSQL internal notices (including index row removal details)
        print("\n" + "-"*50)
        print(" [POSTGRES INTERNAL REPORT]")
        print("-"*50)
        for notice in v_conn.notices:
            # Filter and print meaningful reports regarding index and heap cleanup
            print(f" >>> {notice.strip()}")
        print("-"*50)

    finally:
        v_cur.close()
        v_conn.close()

    # Fetch final metrics to see the physical result of the cleanup
    heap_v, idx_v = get_bloat_stats()
    print_bloat("3. POST-VACUUM (Space Reclaimed)", heap_v, idx_v)

    enable_autovacuum()
    
# if __name__ == "__main__":
#     try:
#         run()
#     except Exception as e:
#         print(f"\n[CRITICAL ERROR] Execution failed: {e}")
#         import traceback
#         traceback.print_exc()
#     finally:
#         print("\n[INFO] Scenario B Script Finished.")