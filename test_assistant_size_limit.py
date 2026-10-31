# -*- coding: utf-8 -*-
from pathlib import Path
import tempfile,unittest
from identity_core import IdentityStore
from send_guard import persist_assistant_if_fresh

class AssistantSizeLimitTests(unittest.TestCase):
    def test_30000_allowed_and_30001_rejected_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            st=IdentityStore(Path(td))
            try:
                gen=st.memory_generation()
                eid=persist_assistant_if_fresh(st,None,gen,[],"A"*30000)
                self.assertEqual(st.conn.execute("SELECT length(content) FROM events WHERE event_id=?",(eid,)).fetchone()[0],30000)
                before=st.conn.execute("SELECT count(*) FROM events").fetchone()[0]
                with self.assertRaisesRegex(ValueError,"Event too large"):
                    persist_assistant_if_fresh(st,None,gen,[],"B"*30001)
                self.assertFalse(st.conn.in_transaction)
                self.assertEqual(st.conn.execute("SELECT count(*) FROM events").fetchone()[0],before)
                follow=st.record("conversation.assistant","assistant","ok")
                self.assertIsInstance(follow,int)
            finally:
                st.close()

if __name__=="__main__":
    unittest.main()
