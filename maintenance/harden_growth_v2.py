from pathlib import Path
p=Path("D:/dsh-fish/identity_core.py")
s=p.read_text(encoding="utf-8")
old='''        ids = [int(x) for x in (evidence_event_ids or [])][:12]
        with self.conn:
            kind = "reflection.accepted" if confirmed else "reflection.draft"'''
new='''        ids = list(dict.fromkeys(int(x) for x in (evidence_event_ids or [])))[:12]
        if confirmed:
            if len(ids) < 2:
                raise ValueError("人格成长需要至少两个独立的真实互动事件作为证据")
            sources=self.conn.execute(
                "SELECT event_id,kind FROM events WHERE event_id IN ("
                + ",".join("?" for _ in ids) + ")", ids).fetchall()
            evidence_ids={int(x["event_id"]) for x in sources
                          if x["kind"].startswith(("conversation.","pet."))}
            if evidence_ids != set(ids):
                raise ValueError("人格成长证据必须是实际的对话或养成互动")
        with self.conn:
            kind = "reflection.accepted" if confirmed else "reflection.draft"'''
if s.count(old)!=1:raise SystemExit("GROWTH_PATCH_ANCHOR_ERROR")
p.write_text(s.replace(old,new),encoding="utf-8")
print("GROWTH_EVIDENCE_VALIDATION_ADDED")
