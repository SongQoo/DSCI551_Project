-- ============================================================
-- seed.sql
-- ============================================================

INSERT INTO concerts (name, venue, event_date)
VALUES ('BTS World Tour 2026', 'Olympic Gymnasium, Seoul', '2026-07-15');

-- create seats: A~T rows × 1~25 cols = 500 seats
INSERT INTO seats (concert_id, seat_code, status)
SELECT
    1,
    chr(64 + row_num) || '-' || LPAD(col_num::text, 2, '0'),
    'available'
FROM
    generate_series(1, 20) AS row_num,
    generate_series(1, 25) AS col_num;

-- check the result
SELECT COUNT(*) AS total_seats FROM seats;  -- → 500
