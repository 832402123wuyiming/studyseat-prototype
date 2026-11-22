CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('student','admin')),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id),
  csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL,
  opens_minute INTEGER NOT NULL CHECK(opens_minute BETWEEN 0 AND 1439),
  closes_minute INTEGER NOT NULL CHECK(closes_minute BETWEEN 1 AND 1440),
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
  CHECK(opens_minute < closes_minute)
);
CREATE TABLE IF NOT EXISTS seats (
  id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES rooms(id), label TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)), UNIQUE(room_id,label)
);
CREATE TABLE IF NOT EXISTS rule_versions (
  id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL, created_by TEXT REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
  id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES users(id),
  seat_id TEXT NOT NULL REFERENCES seats(id), start_at TEXT NOT NULL, end_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('PENDING_CHECKIN','IN_USE','ON_LEAVE','COMPLETED','EXPIRED','CANCELLED')),
  rule_version_id INTEGER NOT NULL REFERENCES rule_versions(id), rule_snapshot_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL, created_at TEXT NOT NULL,
  checked_in_at TEXT, leave_started_at TEXT, leave_deadline TEXT, ended_at TEXT,
  CHECK(start_at < end_at), UNIQUE(student_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS reservations_seat_time ON reservations(seat_id,start_at,end_at);
CREATE INDEX IF NOT EXISTS reservations_student_time ON reservations(student_id,start_at,end_at);
CREATE TABLE IF NOT EXISTS resource_closures (
  id TEXT PRIMARY KEY, room_id TEXT REFERENCES rooms(id), seat_id TEXT REFERENCES seats(id),
  reason TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
  reopened_at TEXT, CHECK((room_id IS NULL) != (seat_id IS NULL))
);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY, actor_id TEXT REFERENCES users(id), reservation_id TEXT REFERENCES reservations(id),
  action TEXT NOT NULL, target_id TEXT, occurred_at TEXT NOT NULL
);
-- These records verify storage only; they are never reservations or occupancy.
CREATE TABLE IF NOT EXISTS persistence_notes (
  id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
  content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 200), created_at TEXT NOT NULL
);
