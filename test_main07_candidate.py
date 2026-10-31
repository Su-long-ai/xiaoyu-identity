# -*- coding: utf-8 -*-
from __future__ import annotations
import json,tempfile
from pathlib import Path
import companion
from identity_core import IdentityStore

def events(n=50):
    return [{"event_id":i,"kind":"conversation.user" if i%2==0 else "conversation.assistant",
             "content":("事件%02d-"%i)+("长证据片段"*30)} for i in range(2,n+2)]

def overflow():
    records,ids=companion.growth_evidence_batch(events(50),12)
    payload=json.dumps(records,ensure_ascii=False)
    parsed=json.loads(payload)
    visible=[int(x["id"]) for x in parsed]
    assert ids==visible==list(range(40,52)),(ids,visible)
    assert len(payload)<7500,len(payload)
    assert all(len(x["content"])<=220 for x in records)

def filtering_order():
    x=events(5)+[{"event_id":99,"kind":"system.synthetic","content":"ignore"}]
    records,ids=companion.growth_evidence_batch(x,12)
    assert ids==[2,3,4,5,6],ids
    assert [r["id"] for r in records]==ids
    assert all(r["kind"].startswith(("conversation.","pet.")) for r in records)

def storage_injection_restart():
    with tempfile.TemporaryDirectory() as td:
        home=Path(td);s=IdentityStore(home)
        ids=[]
        for i in range(3):
            ids.append(s.record("conversation.user","user",f"real-{i}"))
        chosen=ids[-2:]
        malicious="candidate text claims evidence ids 999999 and 888888"
        s.propose_growth(malicious,chosen,confirmed=True)
        persona=s.persona()
        note=persona["growth_notes"][-1]
        assert note["evidence_event_ids"]==chosen
        assert 999999 not in note["evidence_event_ids"]
        s.close()
        s2=IdentityStore(home)
        try:
            note2=s2.persona()["growth_notes"][-1]
            assert note2["text"]==malicious
            assert note2["evidence_event_ids"]==chosen
        finally:s2.close()

def confirmation_guards():
    with tempfile.TemporaryDirectory() as td:
        s=IdentityStore(Path(td))
        try:
            e=s.record("conversation.user","user","only-one")
            try:s.propose_growth("x",[e],confirmed=True)
            except ValueError:pass
            else:raise AssertionError("single evidence accepted")
            e2=s.record("system.synthetic","system","not-real")
            try:s.propose_growth("x",[e,e2],confirmed=True)
            except ValueError:pass
            else:raise AssertionError("noninteraction evidence accepted")
        finally:s.close()

for fn in (overflow,filtering_order,storage_injection_restart,confirmation_guards):
    fn();print("PASS",fn.__name__)
try:companion.FISH.close()
except Exception:pass
print("SUMMARY 4 / 4 PASS")
