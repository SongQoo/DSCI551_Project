import re
import time
from db import get_conn, get_cursor

CONCERT_ID = 1
# Target query for Index-Only Scan demonstration
TEST_QUERY = """
    SELECT status
    FROM seats
    WHERE concert_id = %s AND status = 'available';
"""

def get_val(row, key, index):
    """Helper to handle both DictCursor and Standard Cursor."""
    if row is None: return None
    return row[key] if isinstance(row, dict) else row[index]

def print_full_vm_map(label):
    """Display the Visibility Map status for ALL pages in a table format."""
    with get_conn(autocommit=True) as conn:
        with get_cursor(conn) as cur:
            # Requires pg_visibility extension
            cur.execute("SELECT blkno, all_visible FROM pg_visibility('seats') ORDER BY blkno;")
            rows = cur.fetchall()
            
            print(f"\n [ {label} ] VISIBILITY MAP (VM) SNAPSHOT (From pg_visibility)")
            print("-" * 60)
            print(f"{'Page (Block) No.':<25} | {'All Visible':<25}")
            print("-" * 60)
            for r in rows:
                blk = get_val(r, 'blkno', 0)
                vis = get_val(r, 'all_visible', 1)
                status = "TRUE (Clean)" if vis else "FALSE (Dirty)"
                # Highlight if it's the target page (Example: Page 10)
                print(f"Page {blk:<20} | {status:<25}")
            print("-" * 60 + "\n")

def run_explain(label, page_num):
    """Analyze query execution plans and report performance metrics."""
    conn = get_conn(autocommit=True)
    cur  = get_cursor(conn)
    
    # Pre-execution settings info
    print(f"\n[QUERY PREPARATION]")
    print(f" - Target Query: {TEST_QUERY.strip()}")
    print(f" - Optimization: Setting enable_seqscan = OFF (Forcing Index Usage)")
    
    cur.execute("SET enable_seqscan = OFF;") 
    cur.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + TEST_QUERY, (CONCERT_ID,))
    plan = "\n".join(row[list(row.keys())[0]] for row in cur.fetchall())
    
    scan_type    = "Index Only Scan" if "Index Only Scan" in plan else "Index Scan"
    heap_fetches = re.search(r"Heap Fetches:\s*(\d+)", plan)
    exec_time    = re.search(r"Execution Time:\s*([\d.]+)", plan)

    line_width = 120
    print(f"{'='*line_width}")
    print(f" [{label}] PERFORMANCE ANALYSIS")
    print("-" * line_width)
    print(f"  Scan Methodology : {scan_type}")
    print(f"  Heap Fetches     : {heap_fetches.group(1) if heap_fetches else '0 (I/O Optimized!)'}")
    print(f"  Execution Time   : {exec_time.group(1) if exec_time else 'N/A'} ms")
    print("-" * line_width)
    print("  RAW EXPLAIN PLAN DETAILS:")
    for line in plan.split('\n'):
        if line.strip(): print(f"    {line.strip()}")
    print(f"{'='*line_width}\n")
    
    cur.close(); conn.close()

def run():
    line_width = 100
    print("=" * line_width)
    print(f"{'SCENARIO C: Index-Only Scan Optimization via Visibility Map (VM)':^100}")
    print("=" * line_width)
    
    # 1. Dirty VM Stage
    print(f"\n[ACTION] VM bits are being updated by modifying indexed column 'status'...")
    conn = get_conn(autocommit=True)
    cur = conn.cursor()
    
    # Get target page and initial count
    cur.execute("SELECT ctid FROM seats WHERE concert_id=%s LIMIT 1", (CONCERT_ID,))
    row_temp = cur.fetchone()
    target_page = int(get_val(row_temp, 'ctid', 0).strip('()').split(',')[0])
    
    # Perform update
    cur.execute("UPDATE seats SET status='available' WHERE concert_id=%s", (CONCERT_ID,))
    rows_affected = cur.rowcount
    
    print(f"----------------------------------------------------------------------------------------------------")
    print(f" [UPDATE OPERATION] Target: seats table | Filter: concert_id={CONCERT_ID}")
    print(f" Result: {rows_affected} index column rows updated.")
    print(f" Impact: All tuples in Page {target_page} marked as 'Dirty' in Visibility Map.")
    print(f"----------------------------------------------------------------------------------------------------")
    cur.close(); conn.close()

    # Show Full VM Map (Dirty State)
    print_full_vm_map("PRE-VACUUM STATE")
    run_explain("DIRTY VM: PERFORMANCE TEST", target_page)

    input("\n[WAIT] ⏸  Press ENTER to run VACUUM (This will sync the Visibility Map)...")
    
    # 2. Vacuum Stage
    conn_v = get_conn(autocommit=True)
    conn_v.set_isolation_level(0)
    cur_v = conn_v.cursor()
    try:
        print("\n[VACUUM] Running VACUUM ANALYZE to update VM bits...")
        cur_v.execute("VACUUM ANALYZE seats;")
        print("[SUCCESS] Visibility Map has been synchronized with physical storage.")
    finally:
        cur_v.close(); conn_v.close()

    # 3. Clean VM Stage
    print_full_vm_map("POST-VACUUM STATE")
    run_explain("CLEAN VM: PERFORMANCE TEST", target_page)

# if __name__ == "__main__":
#     try:
#         run()
#     except Exception as e:
#         print(f"\n[CRITICAL ERROR] Execution failed: {e}")
#         import traceback
#         traceback.print_exc()
#     finally:
#         print(f"{'Scenario C Script Finished'}")