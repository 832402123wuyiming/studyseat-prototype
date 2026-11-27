-- Additive migration: preserve every v1 reservation, rule, session and audit row.
CREATE TABLE operation_receipts (
  actor_id TEXT NOT NULL REFERENCES users(id),
  idempotency_key TEXT NOT NULL,
  operation TEXT NOT NULL,
  target_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(actor_id, idempotency_key)
);
ALTER TABLE audit_events ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}';
CREATE INDEX reservations_status ON reservations(status);
