from __future__ import annotations

import sqlite3

VERSION = 4
NAME = "delivery_attempts_v4"


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS delivery_attempts (
            attempt_id TEXT PRIMARY KEY,
            identity_id TEXT NOT NULL,
            delivery_id TEXT NOT NULL,
            logical_notification_id TEXT NOT NULL,
            effect_id TEXT NOT NULL UNIQUE,
            surface TEXT NOT NULL,
            state TEXT NOT NULL,
            external_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (delivery_id) REFERENCES deliveries(delivery_id),
            FOREIGN KEY (effect_id) REFERENCES effects(effect_id)
        )"""
    )
    conn.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_attempt_active
           ON delivery_attempts(identity_id, logical_notification_id)
           WHERE state IN ('QUEUED','DISPATCHING','UNKNOWN')"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_delivery_attempt_effect
           ON delivery_attempts(effect_id)"""
    )


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "delivery_attempts" not in tables:
        raise RuntimeError("migration v4 delivery_attempts table missing")
    indexes = {
        str(row[1])
        for row in conn.execute(
            "PRAGMA index_list(delivery_attempts)"
        ).fetchall()
    }
    if "idx_delivery_attempt_active" not in indexes:
        raise RuntimeError("migration v4 active-attempt index missing")
