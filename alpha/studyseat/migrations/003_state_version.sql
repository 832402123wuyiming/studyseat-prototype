-- Add a monotonic precondition for cyclic leave/return commands and preserve old data.
ALTER TABLE reservations ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0);
