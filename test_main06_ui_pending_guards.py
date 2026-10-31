# -*- coding: utf-8 -*-
from __future__ import annotations
import copy
import companion

class DummyRoot:
    def __init__(self): self.calls=[]
    def after(self,ms,fn): self.calls.append((ms,fn))

app=companion.PetApp.__new__(companion.PetApp)
app.pending=True
app.root=DummyRoot()

before_state=copy.deepcopy(companion.STATE)
before_store=companion.FISH.state()
before_events=companion.FISH.event_count()

# Already-open action callback must fail closed while a request is pending.
companion.PetApp.activity(app,"feed")
assert companion.STATE==before_state
assert companion.FISH.state()==before_store
assert companion.FISH.event_count()==before_events

# Scheduled clock callback must defer model-visible state mutation while pending.
companion.PetApp.clock(app)
assert companion.STATE==before_state
assert companion.FISH.state()==before_store
assert companion.FISH.event_count()==before_events
assert len(app.root.calls)==1 and app.root.calls[0][0]==60000

# Open the growth manager while idle, then simulate a request becoming pending
# before the already-created approve button callback is invoked.
commands={}
infos=[]
class FakeWidget:
    def __init__(self,*args,**kwargs): pass
    def pack(self,*args,**kwargs): return self
    def insert(self,*args,**kwargs): pass
    def delete(self,*args,**kwargs): pass
    def get(self,*args,**kwargs): return "synthetic growth text"
class FakeWin(FakeWidget):
    def title(self,*args): pass
    def geometry(self,*args): pass
    def winfo_exists(self): return True
    def after(self,*args,**kwargs): pass
    def destroy(self): pass
class FakeButton(FakeWidget):
    def __init__(self,*args,text="",command=None,**kwargs):
        super().__init__()
        commands[text]=command

orig={
    "Toplevel":companion.tk.Toplevel,
    "Label":companion.tk.Label,
    "Frame":companion.tk.Frame,
    "Button":companion.tk.Button,
    "ScrolledText":companion.scrolledtext.ScrolledText,
    "showinfo":companion.messagebox.showinfo,
}
try:
    companion.tk.Toplevel=FakeWin
    companion.tk.Label=FakeWidget
    companion.tk.Frame=FakeWidget
    companion.tk.Button=FakeButton
    companion.scrolledtext.ScrolledText=FakeWidget
    companion.messagebox.showinfo=lambda *a,**k: infos.append((a,k))
    app.pending=False
    companion.PetApp.growth_manager(app)
    approve=next(v for k,v in commands.items() if "确认并写入人格历史" in k)
    before_growth=companion.FISH.actual_progress()["approved_growth"]
    before_growth_events=companion.FISH.event_count()
    app.pending=True
    approve()
    assert companion.FISH.actual_progress()["approved_growth"]==before_growth
    assert companion.FISH.event_count()==before_growth_events
    assert infos,"pending growth callback should explain why it was rejected"
finally:
    companion.tk.Toplevel=orig["Toplevel"]
    companion.tk.Label=orig["Label"]
    companion.tk.Frame=orig["Frame"]
    companion.tk.Button=orig["Button"]
    companion.scrolledtext.ScrolledText=orig["ScrolledText"]
    companion.messagebox.showinfo=orig["showinfo"]

companion.FISH.close()
print("PASS activity_pending_guard")
print("PASS clock_pending_guard")
print("PASS already_open_growth_approve_pending_guard")
print("SUMMARY 3 / 3 PASS")
