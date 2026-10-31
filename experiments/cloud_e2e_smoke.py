"""Dependency-free E0 smoke of XiaoYu's actual send_guard.py against synthetic SQLite.

Run: python -m experiments.cloud_e2e_smoke --json-out results.json
No private identity data, model API, network or production writes.
"""
import argparse
import hashlib
import json
import platform
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import send_guard

EXPECTED_GIT_BLOB = '6595e36cfce9d0e7907271164785b062176c5053'
SOURCE_COMMIT = '781394b9d70795f0a289c7c84ca643b141d21416'


def git_blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


class SendGuardSynthetic(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.identity_path = base / 'identity.sqlite3'
        self.r47_path = base / 'r47.sqlite3'
        self.conn = sqlite3.connect(self.identity_path)
        self.addCleanup(self.conn.close)
        self.rconn = sqlite3.connect(self.r47_path)
        self.addCleanup(self.rconn.close)
        self.conn.executescript('''
          CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE memories(memory_id INTEGER PRIMARY KEY,text TEXT,status TEXT,change_seq INTEGER);
          CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT,role TEXT,content TEXT);
          INSERT INTO settings VALUES ('memory_change_seq','1');
          INSERT INTO memories VALUES(1,'用户喜欢红茶','active',1);
        ''')
        self.rconn.executescript('''
          CREATE TABLE source_messages(source_message_id TEXT PRIMARY KEY,lifecycle TEXT);
          CREATE TABLE claims(claim_id TEXT PRIMARY KEY,source_message_id TEXT,claim_text TEXT,
              source_role TEXT,authority_base TEXT,relation_kind TEXT,status TEXT,
              ordinal INTEGER,created_order INTEGER);
          CREATE TABLE claim_relations(child_claim_id TEXT,parent_claim_id TEXT,relation TEXT);
          INSERT INTO source_messages VALUES ('s1','active');
          INSERT INTO claims VALUES ('c1','s1','用户喜欢红茶','user','user_assertion','NEW','active',1,1);
        ''')
        self.conn.commit()
        self.rconn.commit()
        self.expectations = [{'memory_id':1, 'text':'用户喜欢红茶', 'source_message_id':'s1'}]

    def check(self):
        send_guard._validate_identity(self.conn,1,self.expectations)
        send_guard._validate_r47(self.rconn,self.expectations)

    def test_valid_selected_memory_passes(self):
        self.check()

    def test_generation_change_fails_closed(self):
        self.conn.execute("UPDATE settings SET value='2' WHERE key='memory_change_seq'")
        self.conn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'identity_generation_changed'):
            self.check()

    def test_memory_text_change_fails_closed(self):
        self.conn.execute("UPDATE memories SET text='用户喜欢绿茶' WHERE memory_id=1")
        self.conn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'identity_selected_memory_changed'):
            self.check()

    def test_archived_memory_fails_closed(self):
        self.conn.execute("UPDATE memories SET status='archived' WHERE memory_id=1")
        self.conn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'identity_selected_memory_changed'):
            self.check()

    def test_inactive_source_fails_closed(self):
        self.rconn.execute("UPDATE source_messages SET lifecycle='archived' WHERE source_message_id='s1'")
        self.rconn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'r47_source_not_active'):
            self.check()

    def test_authority_inversion_fails_closed(self):
        self.rconn.execute("UPDATE claims SET source_role='assistant' WHERE claim_id='c1'")
        self.rconn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'r47_claim_authority_changed'):
            self.check()

    def test_multiple_claims_fails_closed(self):
        self.rconn.execute("INSERT INTO claims VALUES ('c2','s1','用户喜欢红茶','user','user_assertion','NEW','active',2,2)")
        self.rconn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'r47_claim_cardinality_changed'):
            self.check()

    def test_active_user_conflict_fails_closed(self):
        self.rconn.execute("INSERT INTO source_messages VALUES('s2','active')")
        self.rconn.execute("INSERT INTO claims VALUES('c2','s2','用户不喜欢红茶','user','user_assertion','NEW','active',1,2)")
        self.rconn.execute("INSERT INTO claim_relations VALUES('c2','c1','CONFLICTS')")
        self.rconn.commit()
        with self.assertRaisesRegex(send_guard.FreshnessChanged,'r47_selected_claim_conflicted'):
            self.check()

    def test_chat_dispatch_callback_releases_locks(self):
        def fake_chat(_config,_messages,on_dispatched):
            on_dispatched()
            with sqlite3.connect(self.identity_path, timeout=0.2) as other:
                other.execute("UPDATE settings SET value='2' WHERE key='memory_change_seq'")
            return 'sent'
        result = send_guard.dual_guarded_chat(fake_chat,{},[],self.identity_path,self.r47_path,1,self.expectations)
        self.assertEqual(result,'sent')

    def test_chat_blocks_stale_generation_before_dispatch(self):
        self.conn.execute("UPDATE settings SET value='2' WHERE key='memory_change_seq'")
        self.conn.commit()
        called=[]
        with self.assertRaises(send_guard.FreshnessChanged):
            send_guard.dual_guarded_chat(lambda *_: called.append(1),{},[],self.identity_path,self.r47_path,1,self.expectations)
        self.assertEqual(called,[])

    def test_persistence_success_and_rollback_on_stale(self):
        def insert_event(kind,role,content):
            cur=self.conn.execute('INSERT INTO events(type,role,content) VALUES(?,?,?)',(kind,role,content))
            return cur.lastrowid
        store=SimpleNamespace(conn=self.conn,_insert_event=insert_event)
        bridge=SimpleNamespace(db_path=self.r47_path)
        eid=send_guard.persist_assistant_if_fresh(store,bridge,1,self.expectations,'正常回复')
        self.assertEqual(eid,1)
        self.conn.execute("UPDATE settings SET value='2' WHERE key='memory_change_seq'")
        self.conn.commit()
        with self.assertRaises(send_guard.FreshnessChanged):
            send_guard.persist_assistant_if_fresh(store,bridge,1,self.expectations,'过期回复')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertFalse(self.conn.in_transaction)

    def test_oversize_assistant_event_rolls_back(self):
        store=SimpleNamespace(conn=self.conn,_insert_event=lambda *a:self.conn.execute(
            'INSERT INTO events(type,role,content) VALUES(?,?,?)',a).lastrowid)
        bridge=SimpleNamespace(db_path=self.r47_path)
        with self.assertRaisesRegex(ValueError,'Event too large'):
            send_guard.persist_assistant_if_fresh(store,bridge,1,self.expectations,'x'*30001)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0],0)
        self.assertFalse(self.conn.in_transaction)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--json-out',required=True)
    args=parser.parse_args()
    path=Path(send_guard.__file__)
    raw=path.read_bytes()
    # GitHub source was CRLF at its recorded blob; local checkout can normalize EOL.
    raw_lf=raw.replace(b'\r\n',b'\n')
    actual_candidates=[git_blob_sha(raw), git_blob_sha(raw_lf),git_blob_sha(raw_lf.replace(b'\n',b'\r\n'))]
    if EXPECTED_GIT_BLOB not in actual_candidates:
        raise RuntimeError(f'send_guard source mismatch: {actual_candidates}')
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(SendGuardSynthetic)
    runner=unittest.TextTestRunner(verbosity=2)
    result=runner.run(suite)
    output={
      'schema':'xiaoyu.cloud_e2e.v1','evidence_label':'E0_ENGINEERING_SMOKE_NOT_E1_E2_E3',
      'source_commit_main_at_start':SOURCE_COMMIT,'source_path':'send_guard.py',
      'source_git_blob_sha1':EXPECTED_GIT_BLOB,
      'runner':'chatgpt_python', 'python':platform.python_version(),
      'platform':platform.platform(),'dependencies':'python_stdlib_only',
      'dataset':'ephemeral_synthetic_sqlite_no_private_data',
      'experiment':'send_guard freshness, provenance, conflict, dispatch and reply persistence',
      'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
      'failed':len(result.failures)+len(result.errors), 'skipped':len(result.skipped),
      'total':result.testsRun,
      'success':result.wasSuccessful(),
      'limitations':['synthetic smoke only','not independent auditor replication',
                     'not paid LLM or model-accuracy evaluation','not governance lease/submission'],
    }
    out=Path(args.json_out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('RESULT_JSON',out, json.dumps(output,ensure_ascii=False))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    sys.exit(main())
