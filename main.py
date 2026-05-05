import os
import time
from db import get_conn, get_cursor

# Import individual scenario modules
import scenario_a
import scenario_b
import scenario_c

CONCERT_ID = 1

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_pg_version():
    try:
        with get_conn(autocommit=True) as conn:
            with get_cursor(conn) as cur:
                cur.execute("SELECT version();")
                res = cur.fetchone()
                full_version = res['version'] if isinstance(res, dict) else res[0]
                return full_version.split(' on ')[0]
    except:
        return "PostgreSQL (Unknown Version)"

def display_dashboard():
    pg_ver = get_pg_version()
    try:
        with get_conn(autocommit=True) as conn:
            with get_cursor(conn) as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) as total_seats,
                        SUM(CASE WHEN status = 'reserved' THEN 1 ELSE 0 END) as reserved_seats,
                        SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END) as available_seats,
                        MIN(seat_code) as first_seat,
                        MAX(seat_code) as last_seat
                    FROM seats
                    WHERE concert_id = %s
                """, (CONCERT_ID,))
                row = cur.fetchone()
                
                total = row['total_seats'] or 0
                reserved = row['reserved_seats'] or 0
                available = row['available_seats'] or 0
                first_seat = row['first_seat'] or 'N/A'
                last_seat = row['last_seat'] or 'N/A'
                
                # 상단 헤더
                print("=" * 80)
                print(f"  ConcertRush: Seat Reservation Simulator [{pg_ver}]")
                print("=" * 80)
                
                # 모니터링 섹션 (박스 벽면 정렬 최적화)
                print(f" +{'-' * 76}+")
                print(f" | [ DATABASE LIVE MONITORING - Concert ID: {CONCERT_ID} ]".ljust(78) + "|")
                print(f" |".ljust(78) + "|")
                print(f" |   * Seat Range : {first_seat} ~ {last_seat}".ljust(78) + "|")
                print(f" |   * Total      : {total:,} seats".ljust(78) + "|")
                print(f" |   * Reserved   : {reserved:,} seats".ljust(78) + "|")
                print(f" |   * Available  : {available:,} seats".ljust(78) + "|")
                print(f" +{'-' * 76}+")
    except Exception as e:
        print(f" [ERROR] Dashboard failure: {e}")

def main():
    while True:
        clear_screen()
        display_dashboard()
        
        # 메뉴 섹션 (ljust를 사용해 우측 벽면 강제 정렬)
        print("\n" + " " * 25 + ">> SELECT SIMULATION SCENARIO <<\n")
        
        print(" + " + "-" * 74 + " +")
        print(f" | [1] Scenario A: MVCC & Snapshot Isolation Analysis".ljust(78) + "|")
        print(f" | [2] Scenario B: Heap & Index Bloat & VACUUM".ljust(78) + "|")
        print(f" | [3] Scenario C: VACUUM & I/O Optimization (Index-Only Scan)".ljust(78) + "|")
        print(" + " + "-" * 74 + " +")
        print(f" | [0] Exit System".ljust(78) + "|")
        print(" + " + "-" * 74 + " +")
        
        choice = input("\n Select an option (0-3) -> ").strip()
        
        if choice == '1':
            clear_screen()
            scenario_a.run()
            input("\n[MAIN] Press ENTER to return...")
        elif choice == '2':
            clear_screen()
            scenario_b.run()
            input("\n[MAIN] Press ENTER to return...")
        elif choice == '3':
            clear_screen()
            scenario_c.run()
            input("\n[MAIN] Press ENTER to return...")
        elif choice == '0':
            print("\n System Terminated. Bye!\n")
            break
        else:
            time.sleep(1.0)

if __name__ == "__main__":
    main()