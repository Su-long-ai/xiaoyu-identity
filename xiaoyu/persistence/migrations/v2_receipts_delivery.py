from __future__ import annotations

import sqlite3

VERSION = 2
NAME = "effect_authorization_and_delivery_uniqueness_v2"


def apply(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(effects)").fetchall()}
    if "authorization_decision_id" not in columns:
        conn.execute("ALTER TABLE effects ADD COLUMN authorization_decision_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_effects_authorization_decision "
        "ON effects(authorization_decision_id)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_deliveries_logical_unique "
        "ON deliveries(identity_id, logical_notification_id)"
    )


def verify(conn: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(effects)").fetchall()}
    if "authorization_decision_id" not in columns:
        raise RuntimeError("migration v2 effects missing authorization_decision_id")
    indexes = {str(row[1]) for row in conn.execute("PRAGMA index_list(deliveries)").fetchall()}
    if "idx_deliveries_logical_unique" not in indexes:
        raise RuntimeError("migration v2 delivery uniqueness index missing")
