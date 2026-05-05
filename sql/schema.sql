-- for Bloat Analysis (슈퍼유저 권한 필요)
CREATE EXTENSION IF NOT EXISTS pgstattuple;
CREATE EXTENSION IF NOT EXISTS pageinspect;

CREATE TABLE IF NOT EXISTS concerts (
    concert_id  SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    venue       TEXT        NOT NULL,
    event_date  DATE        NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Create seats table
-- fillfactor=70: fill only max 70% the table so that Non-HOT update can be generated
CREATE TABLE IF NOT EXISTS seats (
    seat_id     SERIAL      PRIMARY KEY,
    concert_id  INTEGER     REFERENCES concerts(concert_id) ON DELETE CASCADE,
    seat_code   VARCHAR(10) NOT NULL,
	status      VARCHAR(20) NOT NULL DEFAULT 'available',
    reserved_by TEXT,
    reserved_at TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
) WITH (fillfactor = 70);

-- Create Index
CREATE INDEX IF NOT EXISTS idx_seats_status
    ON seats(status);

CREATE INDEX IF NOT EXISTS idx_seats_concert_status
    ON seats(concert_id, status);

-- Make constraints about seat's status
ALTER TABLE seats
    ADD CONSTRAINT chk_status
    CHECK (status IN ('available', 'reserved', 'cancelled'));