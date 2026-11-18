import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys
MIGRATION_DIR = Path(__file__).resolve().parents[1] / "migration"
sys.path.insert(0, str(MIGRATION_DIR))
import export_legacy_xiaoyu  # noqa: E402


class MigrationExportTests(unittest.TestCase):
    def _db(self, root: Path) -> Path:
        db = root / "identity.sqlite3"
        con = sqlite3.connect(db)
        con.executescript(
            """
            create table persona_versions(
              version integer, at text, persona_json text, reason text, evidence_json text
            );
            create table settings(key text, value text);
            create table events(event_id text, at text, kind text, actor text, content text, extra text);
            create table memories(
              memory_id text, created_at text, updated_at text, category text, text text,
              source_event text, priority integer, status text, change_seq integer
            );
            """
        )
        persona = {
            "id": "fixture-internal",
            "created_at": "2026-01-01",
            "name": "XiaoYu",
            "identity_commitments": ["remember continuity"],
            "style": {"language": "zh", "length": "short"},
            "growth_notes": ["grows from evidence"],
            "bond_description": "continuing companion",
        }
        con.execute(
            "insert into persona_versions values(1,'2026-01-01',?,'seed','[]')",
            (json.dumps(persona),),
        )
        con.execute(
            "insert into memories values(?,?,?,?,?,?,?,?,?)",
            ("m-bootstrap", "1", "1", "bootstrap", "do not import", "e0", 3, "bootstrap", 1),
        )
        con.execute(
            "insert into memories values(?,?,?,?,?,?,?,?,?)",
            ("m-active", "2", "2", "preference", "likes tea", "e1", 4, "active", 2),
        )
        con.execute(
            "insert into events values('e1','2','conversation.user','owner','private fixture','{}')"
        )
        con.commit()
        con.close()
        return db

    def test_export_is_fail_closed_for_bootstrap_and_keeps_current_memory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._db(root)
            out = root / "out"
            manifest = export_legacy_xiaoyu.export(db, out)

            self.assertEqual(manifest["memory_rows_total"], 2)
            self.assertEqual(manifest["memory_rows_selected"], 1)
            self.assertEqual(len(manifest["memory_rows_excluded"]), 1)
            self.assertEqual(
                manifest["memory_rows_excluded"][0]["reason"],
                "status_not_current:bootstrap",
            )
            self.assertIn("likes tea", (out / "MEMORY.md").read_text(encoding="utf-8"))

    def test_soul_omits_internal_id_and_created_at(self):
        soul = export_legacy_xiaoyu.render_soul({
            "id": "internal-secret-id",
            "created_at": "2020",
            "name": "XiaoYu",
            "identity_commitments": ["stay continuous"],
            "style": {"language": "zh"},
        })
        self.assertIn("XiaoYu", soul)
        self.assertIn("stay continuous", soul)
        self.assertNotIn("internal-secret-id", soul)
        self.assertNotIn("2020", soul)


if __name__ == "__main__":
    unittest.main()
