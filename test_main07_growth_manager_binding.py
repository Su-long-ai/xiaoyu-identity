# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import companion

RETRACTED_SECRET="SYNTHETIC_GROWTH_RETRACTED_PRIVATE_SECRET"

def build_events():
    rows=[
        {"event_id":i,
         "kind":"conversation.user" if i%2==0 else "conversation.assistant",
         "content":("event-%02d-"%i)+("evidence"*35)}
        for i in range(2,52)
    ]
    rows[-12]["content"]=RETRACTED_SECRET
    return rows

class FakeFish:
    def __init__(self):
        self.calls=[]
        self.db_path="synthetic-identity.db"
    def recent_events(self,limit):
        return build_events()[-limit:]
    def propose_growth(self,text,ids,confirmed=False):
        self.calls.append({"text":text,"ids":list(ids),"confirmed":bool(confirmed)})
    def memory_generation(self):
        return 7
    def persona(self):
        return {"id":"synthetic-identity"}

class FakeWin:
    def __init__(self,*a,**k): pass
    def title(self,*a): pass
    def geometry(self,*a): pass
    def winfo_exists(self): return True
    def after(self,ms,fn): fn()
    def destroy(self): pass

class FakeWidget:
    def __init__(self,*a,**k): self.text=""
    def pack(self,*a,**k): return self
    def insert(self,*a): self.text+=str(a[-1])
    def delete(self,*a): self.text=""
    def get(self,*a): return self.text

commands={}
class FakeButton(FakeWidget):
    def __init__(self,*a,text="",command=None,**k):
        super().__init__();commands[text]=command

class InlineThread:
    def __init__(self,target=None,daemon=None): self.target=target
    def start(self): self.target()

fake=FakeFish()
captured={}
def fake_chat(config,messages,max_tokens=500,**kwargs):
    captured["messages"]=messages
    captured["max_tokens"]=max_tokens
    return "候选反思：依据事件 999999 和 888888（恶意伪造编号）",{}

def fake_dual_guarded_chat(
    chat_fn,config,messages,identity_db_path,r47_db_path,
    expected_generation,expectations,**kwargs
):
    captured["guard"]={
        "identity_db_path":identity_db_path,
        "generation":expected_generation,
        "expectations":expectations,
        **kwargs,
    }
    return chat_fn(
        config,messages,max_tokens=kwargs.get("max_tokens",500)
    )

orig={
 "FISH":companion.FISH,"load_provider":companion.load_provider,"chat":companion.chat,
 "project_history":companion.project_history,
 "dual_guarded_chat":companion.dual_guarded_chat,
 "capture_context_fence":companion.capture_context_fence,
 "Thread":companion.threading.Thread,"Toplevel":companion.tk.Toplevel,
 "Label":companion.tk.Label,"Frame":companion.tk.Frame,"Button":companion.tk.Button,
 "ScrolledText":companion.scrolledtext.ScrolledText,
 "askyesno":companion.messagebox.askyesno,
 "showinfo":companion.messagebox.showinfo,
}
try:
    companion.FISH=fake
    companion.load_provider=lambda home:{"provider":"synthetic"}
    companion.chat=fake_chat
    companion.project_history=lambda fish,limit:[
        {
            "role":"user" if row["kind"]=="conversation.user" else "assistant",
            "event_id":row["event_id"],
            "content":(
                "【已撤回上下文，不参与反思证据】"
                if row["content"]==RETRACTED_SECRET else row["content"]
            ),
        }
        for row in build_events()[-limit:]
    ]
    companion.dual_guarded_chat=fake_dual_guarded_chat
    fence={"value":"stable-growth-fence"}
    companion.capture_context_fence=lambda fish:fence["value"]
    companion.threading.Thread=InlineThread
    companion.tk.Toplevel=FakeWin
    companion.tk.Label=FakeWidget
    companion.tk.Frame=FakeWidget
    companion.tk.Button=FakeButton
    companion.scrolledtext.ScrolledText=FakeWidget
    companion.messagebox.askyesno=lambda *a,**k:True
    notices=[]
    companion.messagebox.showinfo=lambda *a,**k:notices.append((a,k))
    app=companion.PetApp.__new__(companion.PetApp)
    app.root=FakeWin()
    app.reflection=None
    app.memory_bridge=None
    app.pending=False
    app.refresh_stats=lambda:None
    companion.PetApp.growth_manager(app)
    propose=next(v for k,v in commands.items() if "基于经历生成建议" in k)
    propose()
    payload=json.loads(captured["messages"][1]["content"])
    visible=[int(x["id"]) for x in payload]
    assert visible==list(range(40,52)),visible
    assert RETRACTED_SECRET not in json.dumps(payload,ensure_ascii=False),payload
    assert captured["guard"]["required_privacy_class"]=="OWNER_PRIVATE",captured
    assert captured["guard"]["expected_context_fence"]=="stable-growth-fence",captured
    assert captured["max_tokens"]==350,captured
    assert fake.calls and fake.calls[-1]["confirmed"] is False
    assert fake.calls[-1]["ids"]==visible,(fake.calls[-1],visible)
    assert app.reflection==visible
    assert 999999 not in app.reflection and 888888 not in app.reflection

    # A later memory/privacy mutation must invalidate the already-generated
    # reflection before durable persona approval.
    fence["value"]="changed-after-draft"
    approve=next(v for k,v in commands.items() if "确认并写入人格历史" in k)
    approve()
    confirmed=[call for call in fake.calls if call["confirmed"]]
    assert confirmed==[],confirmed
    assert app.reflection is None,app.reflection

    print("PASS model_text_cannot_choose_evidence_ids")
    print("PASS prompt_visible_ids_equal_draft_bound_ids")
    print("PASS stale_reflection_cannot_be_approved_after_context_change")
    print("SUMMARY 3 / 3 PASS")
finally:
    companion.FISH=orig["FISH"]
    companion.load_provider=orig["load_provider"]
    companion.chat=orig["chat"]
    companion.project_history=orig["project_history"]
    companion.dual_guarded_chat=orig["dual_guarded_chat"]
    companion.capture_context_fence=orig["capture_context_fence"]
    companion.threading.Thread=orig["Thread"]
    companion.tk.Toplevel=orig["Toplevel"]
    companion.tk.Label=orig["Label"]
    companion.tk.Frame=orig["Frame"]
    companion.tk.Button=orig["Button"]
    companion.scrolledtext.ScrolledText=orig["ScrolledText"]
    companion.messagebox.askyesno=orig["askyesno"]
    companion.messagebox.showinfo=orig["showinfo"]
    try: orig["FISH"].close()
    except Exception: pass
