import time
import threading
import os
from db import get_conn, get_cursor

# Configuration
TARGET_SEAT = "A-01"
CONCERT_ID  = 1

def get_val(row, key, index):
    """
    Helper function to handle both DictCursor and Standard Cursor.
    Prevents KeyError: 0 or TypeError: tuple indices must be integers.
    """
    if row is None: return None
    return row[key] if isinstance(row, dict) else row[index]

def reset_seat():
    """Reset the seat status and clean up dead tuples using VACUUM."""
    with get_conn(autocommit=True) as conn:
        with get_cursor(conn) as cur:
            cur.execute("UPDATE seats SET status = 'available', reserved_by = NULL WHERE concert_id = %s", (CONCERT_ID,))
    
    conn = get_conn(autocommit=True)
    conn.set_isolation_level(0) # Required for VACUUM
    cur = conn.cursor()
    cur.execute("VACUUM ANALYZE seats;")
    cur.close(); conn.close()
    print("[RESET] Target seat initialized & VACUUM complete.\n")

def print_seat_status(cur, label):
    """Print the logical view of the seat including system columns."""
    cur.execute("SELECT seat_code, status, reserved_by, ctid, xmin, xmax FROM seats WHERE seat_code = %s AND concert_id = %s", (TARGET_SEAT, CONCERT_ID))
    row = cur.fetchone()
    if row:
        seat_code = get_val(row, 'seat_code', 0)
        status    = get_val(row, 'status', 1)
        res_by    = get_val(row, 'reserved_by', 2)
        ctid      = get_val(row, 'ctid', 3)
        xmin      = get_val(row, 'xmin', 4)
        xmax      = get_val(row, 'xmax', 5)
        print(f"[{label:^24}] {seat_code} | Status: {status:<10} | reserved_by: {str(res_by):<8} | ctid: {ctid:<8} | xmin: {xmin:<8} | xmax: {xmax}")

def print_tuple_headers(cur, label, xid_list, page_num):
    """Examine physical tuple headers and track the MVCC chain with precise alignment."""
    placeholders = ', '.join(['%s'] * len(xid_list))
    xid_params = [str(x) for x in xid_list]

    cur.execute(f"""
        SELECT lp, t_xmin, t_xmax, t_ctid, 
               (t_infomask & 256)  > 0 AS xmin_committed, 
               (t_infomask & 512)  > 0 AS xmin_aborted,
               (t_infomask & 1024) > 0 AS xmax_committed,
               (t_infomask & 2048) > 0 AS xmax_invalid
        FROM heap_page_items(get_raw_page('seats', {page_num}))
        WHERE t_xmin::text IN ({placeholders}) OR t_xmax::text IN ({placeholders})
        ORDER BY t_xmin::text::bigint DESC; 
    """, xid_params + xid_params)
    rows = cur.fetchall()
    
    line_width = 115
    print(f"\n{'='*line_width}")
    print(f" [{label}] Raw Page Inspection (From heap_page_items) (Page: {page_num}, Tracking XIDs: {xid_list})")
    print("-" * line_width)
    header = (f"{'lp':<4} | {'t_xmin':<8} | {'t_xmax':<8} | {'t_ctid':<10} | "
              f"{'xmin_commit':<11} | {'xmin_abort':<11} | {'xmax_commit':<11} | {'xmax_invalid':<12}")
    print(header)
    print("-" * line_width)
    
    for r in rows:
        lp          = get_val(r, 'lp', 0)
        t_xmin      = get_val(r, 't_xmin', 1)
        t_xmax      = get_val(r, 't_xmax', 2)
        t_ctid      = get_val(r, 't_ctid', 3)
        xmin_comm   = get_val(r, 'xmin_committed', 4)
        xmin_abort  = get_val(r, 'xmin_aborted', 5)
        xmax_comm   = get_val(r, 'xmax_committed', 6)
        xmax_inv    = get_val(r, 'xmax_invalid', 7)
        print(f"{str(lp):<4} | {str(t_xmin):<8} | {str(t_xmax):<8} | {str(t_ctid):<10} | "
              f"{str(xmin_comm):<11} | {str(xmin_abort):<11} | {str(xmax_comm):<11} | {str(xmax_inv):<12}")
    print("=" * line_width + "\n")

def print_clog_status(cur, label, xid):
    """Query the true transaction state from the CLOG (pg_xact)."""
    cur.execute("SELECT pg_xact_status(%s::text::xid8) AS status;", (str(xid),))
    row = cur.fetchone()
    status = get_val(row, 'status', 0) if row else "UNKNOWN"
    print(f"[{label:^24}] CLOG Status for XID {xid} ➔ {status.upper()}\n")

def print_lock_status(cur, label):
    """Check pg_locks to identify transactions waiting for RowExclusiveLock."""
    cur.execute("""
        SELECT locktype, mode, granted, pid
        FROM pg_locks
        WHERE relation = 'seats'::regclass OR locktype = 'transactionid';
    """)
    rows = cur.fetchall()
    print(f"\n{'-'*100}")
    print(f" [{label}] Active Locks on 'seats' table (from pg_locks)")
    print("-" * 100)
    print(f"{'Lock Type':<15} | {'Mode':<20} | {'Granted':<8} | {'PID':<8}")
    for r in rows:
        lt = get_val(r, 'locktype', 0)
        md = get_val(r, 'mode', 1)
        gr = get_val(r, 'granted', 2)
        pd = get_val(r, 'pid', 3)
        print(f"{str(lt):<15} | {str(md):<20} | {str(gr):<8} | {str(pd)}")
    print("-" * 100 + "\n")

def writer2_attempt(w2_xid):
    """Worker function for Writer 2 (XID included in logs)."""
    print(f"\n[WRITER 2] Attempting to UPDATE {TARGET_SEAT} (Expected to block/hang)...")
    conn2 = get_conn(autocommit=True)
    cur2 = conn2.cursor()
    cur2.execute("""
        UPDATE seats 
        SET status = 'reserved', reserved_by = 'writer_2' 
        WHERE seat_code = %s AND concert_id = %s AND status = 'available'
    """, (TARGET_SEAT, CONCERT_ID))
    
    if cur2.rowcount == 0:
        print(f"\n[WRITER 2] !!! UPDATE FAILED !!! Reason: Seat is no longer AVAILABLE.\n")
    else:
        print(f"\n[WRITER 2] !!! UPDATE SUCCESSFUL !!!")
    cur2.close(); conn2.close()

def run():
    print("=" * 100)
    print(f"{'SCENARIO A: Comprehensive MVCC, Tuple Headers, CLOG & Locking':^100}")
    print("=" * 100)
    
    reset_seat()

    # 1. Establish connections
    conn_writer1 = get_conn(autocommit=False)
    cur_writer1  = get_cursor(conn_writer1)
    conn_writer2_pre = get_conn(autocommit=True)
    cur_writer2_pre = conn_writer2_pre.cursor()
    conn_reader  = get_conn(autocommit=True)
    cur_reader   = get_cursor(conn_reader)

    # 2. Find the current page number safely
    cur_reader.execute("SELECT ctid FROM seats WHERE seat_code = %s AND concert_id = %s", (TARGET_SEAT, CONCERT_ID))
    res_ctid = cur_reader.fetchone()
    if res_ctid:
        ctid_str = get_val(res_ctid, 'ctid', 0)
        page_num = int(ctid_str.strip('()').split(',')[0])
    else:
        print("[ERROR] Target seat not found.")
        return

    # 3. Get XIDs for both writers
    cur_writer1.execute("SELECT txid_current() AS xid;")
    w1_xid = get_val(cur_writer1.fetchone(), 'xid', 0)
    
    cur_writer2_pre.execute("SELECT txid_current() AS xid;")
    w2_xid = get_val(cur_writer2_pre.fetchone(), 'xid', 0)
    cur_writer2_pre.close(); conn_writer2_pre.close()

    # 4. Scenario Execution
    print_seat_status(cur_reader, "1. INITIAL STATE")

    print(f"\n[WRITER 1 (XID: {w1_xid})] Starting Transaction...")

    # Writer 1 Update Operation
    cur_writer1.execute("UPDATE seats SET status='reserved', reserved_by='writer_1' WHERE seat_code=%s AND concert_id=%s", (TARGET_SEAT, CONCERT_ID))
    print(f"[WRITER 1 (XID: {w1_xid})] Tuple Updated (Pending COMMIT)\n")

    print_clog_status(cur_reader, "CLOG(Commit Log): PRE-COMMIT", w1_xid)
    print_tuple_headers(cur_writer1, f"WRITER 1 (XID: {w1_xid}) UNCOMMITTED", [w1_xid], page_num)
    print_seat_status(cur_reader, "2. READER (CONCURRENT)")

    w2_thread = threading.Thread(target=writer2_attempt, args=(w2_xid,))
    w2_thread.start()
    time.sleep(1) 

    print_lock_status(cur_reader, f"LOCK ANALYSIS: W2({w2_xid}) WAITING FOR W1({w1_xid})")
    
    input(f"[WAIT] ⏸  Press ENTER to COMMIT Writer 1 (XID: {w1_xid}) Transaction...\n")
    conn_writer1.commit()
    print(f"[WRITER 1 (XID: {w1_xid})] Transaction Committed Successfully.")

    # Wait for Writer 2 to finish
    w2_thread.join()

    print_clog_status(cur_reader, f"CLOG(Commit Log): W1({w1_xid}) POST-COMMIT", w1_xid)
    print_seat_status(cur_reader, "3. FINAL STATE (POST-W2)")
    print_tuple_headers(cur_writer1, f"FULL MVCC CHAIN (W1:{w1_xid})", [w1_xid], page_num)

    cur_writer1.close(); conn_writer1.close()
    cur_reader.close(); conn_reader.close()

# if __name__ == "__main__":
#     try:
#         run()
#     except Exception as e:
#         print(f"\n[CRITICAL ERROR] Execution failed: {e}")
#         import traceback
#         traceback.print_exc() # Show exactly where it failed
#     finally:
#         print("\n[INFO] Scenario A Script Finished.")