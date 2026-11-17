# -*- coding: utf-8 -*-
"""Portable 小鱼 GUI: model can change, local identity does not."""
from __future__ import annotations
import datetime
import json
import math
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, scrolledtext, ttk
from identity_core import IdentityStore
from model_adapter import PROVIDERS, load_provider, save_provider, chat, project_history
from product_memory_bridge import ProductMemoryBridge, safe_product_recall
from xiaoyu.runtime.provider_registry import stable_digest
from send_guard import (
    FreshnessChanged,
    capture_context_fence,
    capture_expectations,
    dual_guarded_chat,
    persist_assistant_if_fresh,
)

HOME=Path(__file__).resolve().parent
FISH=IdentityStore(HOME)
STATE=FISH.state()

def clamp(n): return max(0,min(100,int(n)))

def growth_evidence_batch(events, limit=12, budget=7500):
    """Pack complete interaction records under the exact model-visible JSON character budget."""
    real=[e for e in events if str(e.get("kind","")).startswith(("conversation.","pet."))]
    chosen=real[-max(2,min(12,int(limit))):]
    records=[]
    for e in chosen:
        row={"id":int(e["event_id"]),"kind":str(e["kind"]),"content":str(e["content"])[:220]}
        trial=records+[row]
        if len(json.dumps(trial,ensure_ascii=False))>int(budget):
            break
        records.append(row)
    return records,[x["id"] for x in records]

def tick_state():
    import time
    now=time.time()
    elapsed=max(0,min(7*24*3600,now-float(STATE.get("last_tick",now))))
    hours=int(elapsed//3600)
    if hours:
        STATE["hunger"]=clamp(STATE.get("hunger",20)+min(30,hours*2))
        STATE["energy"]=clamp(STATE.get("energy",90)-min(20,hours))
        STATE["mood"]=clamp(STATE.get("mood",80)-min(12,hours//3))
    STATE["last_tick"]=now
    FISH.set_state(STATE)

class PetApp:
    def __init__(self,root):
        self.root=root
        self.root.title("小鱼 · 持久化身份")
        self.root.geometry("740x770")
        self.root.minsize(620,650)
        self.root.configure(bg="#ebf7ff")
        self.tick=0
        self.queue=queue.Queue()
        self.pending=False
        self.reflection=None
        self.memory_bridge=None
        self.memory_bridge_error=None
        try:
            self.memory_bridge=ProductMemoryBridge(HOME,FISH)
        except Exception as err:
            # Chat remains available, but long-term memory injection fails closed.
            self.memory_bridge_error=type(err).__name__+": "+str(err)
        tick_state()
        top=tk.Frame(root,bg="#ebf7ff")
        top.pack(fill="x",padx=18,pady=(10,0))
        tk.Label(top,text="小鱼  ·  会积累经历的 AI 伴侣",
                 font=("Microsoft YaHei UI",16,"bold"),bg="#ebf7ff",fg="#145d85").pack(side="left")
        self.model_text=tk.StringVar()
        tk.Label(top,textvariable=self.model_text,bg="#ebf7ff",
                 fg="#597e94",font=("Microsoft YaHei UI",9)).pack(side="right")
        self.canvas=tk.Canvas(root,height=220,bg="#d7f2ff",highlightthickness=0)
        self.canvas.pack(fill="x",padx=18,pady=(12,5))
        self.status=tk.StringVar()
        tk.Label(root,textvariable=self.status,bg="#ebf7ff",fg="#32789b",
                 font=("Microsoft YaHei UI",10)).pack(pady=4)
        actions=tk.Frame(root,bg="#ebf7ff")
        actions.pack(pady=(3,8))
        for text,kind in [("🍤 喂食","feed"),("🎾 玩耍","play"),("💤 休息","rest")]:
            tk.Button(actions,text=text,command=lambda k=kind:self.activity(k),
                      bg="#c5e8fa",fg="#155e82",relief="flat",
                      padx=13,pady=5,font=("Microsoft YaHei UI",10)).pack(side="left",padx=5)
        tools=tk.Frame(root,bg="#ebf7ff")
        tools.pack(fill="x",padx=18,pady=(0,7))
        for text,fn in [("长期记忆",self.memory_manager),("成长反思",self.growth_manager),
                        ("切换模型",self.provider_manager),("导出身份",self.export_identity)]:
            tk.Button(tools,text=text,command=fn,relief="flat",
                      bg="#e2edf4",fg="#2d617d",padx=11,pady=6,
                      font=("Microsoft YaHei UI",9)).pack(side="left",padx=(0,7))
        self.log=scrolledtext.ScrolledText(root,wrap="word",height=13,
                                          bg="#ffffff",fg="#204a60",relief="flat",
                                          padx=11,pady=11,font=("Microsoft YaHei UI",10))
        self.log.pack(fill="both",expand=True,padx=18,pady=(0,10))
        self.log.insert("end","小鱼：咕噜～这次我有自己的身份档案啦，模型换了也不会丢失我们的经历。\n")
        for turn in FISH.latest_dialog(14):
            who="你" if turn["role"]=="user" else "小鱼"
            self.log.insert("end",f"{who}：{turn['content']}\n")
        self.log.see("end")
        chatbar=tk.Frame(root,bg="#ebf7ff")
        chatbar.pack(fill="x",padx=18,pady=(0,13))
        self.entry=tk.Entry(chatbar,font=("Microsoft YaHei UI",11),
                            relief="flat",bg="white",fg="#1f526e")
        self.entry.pack(side="left",fill="x",expand=True,ipady=11,padx=(0,8))
        self.sendbtn=tk.Button(chatbar,text="发送",command=self.send,
                               font=("Microsoft YaHei UI",10),bg="#2288b8",
                               fg="white",relief="flat",padx=20,pady=9)
        self.sendbtn.pack(side="right")
        self.entry.bind("<Return>",self.send)
        self.root.protocol("WM_DELETE_WINDOW",self.close)
        self.refresh_stats()
        self.draw()
        self.pump()
        self.root.after(60000,self.clock)
        self.entry.focus_set()

    def logline(self,line):
        self.log.insert("end",line+"\n")
        self.log.see("end")

    def refresh_stats(self):
        self.status.set(
            f"心情 {STATE.get('mood',80)}/100   饥饿 {STATE.get('hunger',20)}/100   "
            f"精力 {STATE.get('energy',90)}/100   亲密度 {STATE.get('bond',0)}/100   "
            f"消息 {FISH.actual_progress()['user_messages']} · 回复 {FISH.actual_progress()['assistant_replies']} · 互动 {FISH.actual_progress()['pet_actions']} · 真实记忆 {FISH.actual_progress()['confirmed_memories']} · 待确认 {FISH.actual_progress()['pending_candidates']} 条")
        c=load_provider(HOME)
        if self.memory_bridge is None:
            bridge_label=" | ⚠记忆桥不可用"
        elif self.memory_bridge_error:
            bridge_label=" | ⚠记忆桥异常"
        else:
            bridge_status=self.memory_bridge.status()
            runtime_core=str(bridge_status.get("runtime_memory_core") or "")
            if runtime_core=="r47_confirmed_product_adapter":
                bridge_label=" | R47记忆桥"
            elif bridge_status.get("r52_runtime_loaded") is True:
                bridge_label=" | R52记忆桥"
            else:
                bridge_label=" | 记忆桥"
        self.model_text.set(c["provider"]+" | "+c["model"]+bridge_label)
        FISH.set_state(STATE)

    def _sync_memory_bridge(self):
        if self.memory_bridge is None:
            return
        try:
            result=self.memory_bridge.sync()
            status=self.memory_bridge.status()
            quarantined=int(status.get("quarantined_rows") or 0)
            if quarantined:
                self.memory_bridge_error=f"quarantined_memories:{quarantined}"
            elif result.get("warnings"):
                self.memory_bridge_error="; ".join(result["warnings"][:3])
            else:
                self.memory_bridge_error=None
        except Exception as err:
            self.memory_bridge_error=type(err).__name__+": "+str(err)

    def activity(self,kind):
        if self.pending:
            return
        if kind=="feed":
            STATE["hunger"]=clamp(STATE.get("hunger",20)-35)
            STATE["mood"]=clamp(STATE.get("mood",80)+3)
            STATE["bond"]=clamp(STATE.get("bond",0)+1)
            say="小鱼：啊呜！谢谢投喂。"
        elif kind=="play":
            STATE["mood"]=clamp(STATE.get("mood",80)+12)
            STATE["energy"]=clamp(STATE.get("energy",90)-8)
            STATE["hunger"]=clamp(STATE.get("hunger",20)+4)
            STATE["bond"]=clamp(STATE.get("bond",0)+2)
            say="小鱼：咕噜咕噜，再玩一会儿！"
        else:
            STATE["energy"]=clamp(STATE.get("energy",90)+40)
            STATE["hunger"]=clamp(STATE.get("hunger",20)+5)
            STATE["bond"]=clamp(STATE.get("bond",0)+1)
            say="小鱼：呼噜……感觉清醒多啦。"
        FISH.record("pet."+kind,"user",kind)
        self.logline(say)
        self.refresh_stats()

    def send(self,event=None):
        if self.pending:return
        message=self.entry.get().strip()
        if not message:return
        self.entry.delete(0,"end")
        self.logline("你："+message)
        self.logline("小鱼：正在想……")
        event_id=FISH.record("conversation.user","user",message)
        proposed_id=FISH.propose_from_user_event(event_id,message)
        if proposed_id:
            self.logline("系统：发现一条可保留的原话，已放入「长期记忆 → 待确认」，并未直接写入记忆。")
        identity_db_path=str(FISH.db_path)
        r47_db_path=(str(self.memory_bridge.db_path)
                     if self.memory_bridge is not None else "")
        # Build from one stable identity/profile/history snapshot. A memory,
        # persona, state or conversation mutation during assembly forces a
        # rebuild instead of blessing stale messages with a newer fence.
        for assembly_attempt in range(2):
            context_fence_before=capture_context_fence(FISH)
            memory_generation=FISH.memory_generation()
            memory_rows, recall_error=safe_product_recall(
                self.memory_bridge,message,limit=7
            )
            memory_expectations=capture_expectations(
                self.memory_bridge,memory_rows
            )
            if recall_error == "memory_bridge_unavailable":
                if not self.memory_bridge_error:
                    self.memory_bridge_error=recall_error
            else:
                self.memory_bridge_error=recall_error
            sysmsg=FISH.identity_context(
                message,memories_override=memory_rows
            )
            hard_memory_failure=bool(
                recall_error
                and not str(recall_error).startswith("quarantined_memories:")
            )
            history=[
                {"role":m["role"],"content":m["content"]}
                for m in project_history(
                    FISH,16,
                    fail_closed_current_event_id=(
                        event_id if hard_memory_failure else None
                    ),
                )
            ]
            context_fence=capture_context_fence(FISH)
            if context_fence==context_fence_before:
                break
        else:
            # Remove the pending placeholder first, then surface the fail-closed
            # outcome so the UI cannot remain stuck on “正在想……”.
            self.log.delete("end-2l","end-1l")
            self.logline(
                "系统：上下文在组装期间持续变化，本次未发送；请重试。"
            )
            return
        config=load_provider(HOME)
        routing_policy_digest=stable_digest(config)
        canonical_identity_id=str(FISH.persona()["id"])
        self.pending=True
        self.sendbtn.configure(state="disabled")
        def worker():
            try:
                text,usage=dual_guarded_chat(
                    chat,config,[{"role":"system","content":sysmsg}]+history,
                    identity_db_path,r47_db_path,
                    memory_generation,memory_expectations,
                    expected_context_fence=context_fence,
                    identity_id=canonical_identity_id,
                    principal_id="owner",
                    owner_principal_id="owner",
                    audience_scope="PRIVATE",
                    context_space="PERSONAL",
                    required_privacy_class="OWNER_PRIVATE",
                    routing_policy_digest=routing_policy_digest,
                    context_state_provider=lambda:{
                        "identity_id":str(FISH.persona()["id"]),
                        "principal_id":"owner",
                        "audience_scope":"PRIVATE",
                        "context_space":"PERSONAL",
                        "authorization_digest":None,
                        "routing_policy_digest":stable_digest(
                            load_provider(HOME)
                        ),
                        "tool_result_digest":None,
                        "tool_implementation_digest":None,
                        "tool_schema_digest":None,
                    },
                )
                self.queue.put((
                    "reply",text,usage,
                    {"generation":memory_generation,
                     "expectations":memory_expectations,
                     "context_fence":context_fence},
                ))
            except Exception as err:
                self.queue.put(("error",str(err),{},None))
        threading.Thread(target=worker,daemon=True).start()

    def pump(self):
        try:
            while True:
                item=self.queue.get_nowait()
                kind,result,usage=item[:3]
                freshness=item[3] if len(item)>3 else None
                self.pending=False
                self.sendbtn.configure(state="normal")
                # Remove placeholder line without mutating persistent conversation.
                self.log.delete("end-2l","end-1l")
                if kind=="reply":
                    try:
                        persist_assistant_if_fresh(
                            FISH,self.memory_bridge,
                            freshness["generation"],freshness["expectations"],result,
                            expected_context_fence=freshness.get("context_fence"),
                        )
                    except FreshnessChanged:
                        self.logline(
                            "系统：上下文在回复生成期间发生了变化，旧回复已丢弃；请重新发送。"
                        )
                    else:
                        self.logline("小鱼："+result)
                        STATE["bond"]=clamp(STATE.get("bond",0)+1)
                    STATE["total_calls"]=int(STATE.get("total_calls",0))+1
                    totals=STATE.setdefault("usage",{})
                    for k in ("prompt_tokens","completion_tokens","prompt_cache_hit_tokens"):
                        totals[k]=int(totals.get(k,0))+int(usage.get(k,0))
                else:
                    self.logline("小鱼："+result)
                    FISH.record("model.error","system","Model request failed (details shown in UI).")
                self.refresh_stats()
        except queue.Empty:
            pass
        self.root.after(180,self.pump)

    def clock(self):
        if not self.pending:
            tick_state()
            self.refresh_stats()
        self.root.after(60000,self.clock)

    def draw(self):
        self.tick+=1
        c=self.canvas
        c.delete("all")
        w=max(c.winfo_width(),620)
        x=w/2+math.sin(self.tick/75)*19
        y=111+math.sin(self.tick/13)*8
        c.create_oval(-30,170,w+30,275,fill="#bce9ff",outline="")
        c.create_polygon(x-94,y,x-162,y-43,x-162,y+43,
                         fill="#3baddd",outline="#3484ad",width=2)
        c.create_oval(x-106,y-58,x+110,y+57,fill="#68c6f1",outline="#258cb6",width=3)
        c.create_polygon(x-21,y-48,x+10,y-82,x+35,y-47,fill="#43b5e8")
        c.create_oval(x+48,y-24,x+65,y-8,fill="white",outline="")
        c.create_oval(x+55,y-22,x+63,y-10,fill="#244c6d",outline="")
        c.create_arc(x+59,y+2,x+97,y+30,start=190,extent=115,
                     outline="#266b9a",width=3,style="arc")
        for i in range(6):
            yy=220-(self.tick*2+i*43)%220
            xx=40+i*33
            c.create_oval(xx-5,yy-5,xx+5,yy+5,outline="#89d6ef",width=2)
        self.root.after(95,self.draw)


    def memory_manager(self):
        win=tk.Toplevel(self.root)
        win.title("小鱼 · 记忆来源与审阅")
        win.geometry("900x560")
        tk.Label(win,text=(
            "真实记忆：经用户确认并能追溯来源。待确认：原话候选，不会自动使用。"
            " 初始设定：开发时写入，不属于共同经历。"),
            wraplength=720,justify="left").pack(padx=12,pady=10)
        counts=tk.StringVar()
        tk.Label(win,textvariable=counts,fg="#256d8b").pack()
        tabs=ttk.Notebook(win)
        tabs.pack(fill="both",expand=True,padx=12,pady=8)
        tab_mem=ttk.Frame(tabs)
        tab_pending=ttk.Frame(tabs)
        tab_boot=ttk.Frame(tabs)
        tabs.add(tab_mem,text="已确认长期记忆")
        tabs.add(tab_pending,text="待确认记忆")
        tabs.add(tab_boot,text="初始设定（只读）")
        mem_lb=tk.Listbox(tab_mem,font=("Microsoft YaHei UI",10))
        mem_lb.pack(fill="both",expand=True,padx=5,pady=5)
        prop_lb=tk.Listbox(tab_pending,font=("Microsoft YaHei UI",10))
        prop_lb.pack(fill="both",expand=True,padx=5,pady=5)
        boot_lb=tk.Listbox(tab_boot,font=("Microsoft YaHei UI",10))
        boot_lb.pack(fill="both",expand=True,padx=5,pady=5)
        provenance=tk.StringVar(value="选择待确认项可查看原始证据。")
        tk.Label(tab_pending,textvariable=provenance,
                 wraplength=700,justify="left").pack(padx=8,pady=6)
        mem_ids=[]
        proposal_items=[]
        def redraw():
            mem_lb.delete(0,"end")
            prop_lb.delete(0,"end")
            boot_lb.delete(0,"end")
            mem_ids.clear()
            proposal_items.clear()
            for item in FISH.list_memories():
                mem_ids.append(item["memory_id"])
                mem_lb.insert("end",f"#{item['memory_id']} [{item['category']}] {item['text']}")
            for item in FISH.list_proposals():
                proposal_items.append(item)
                freshness=" [需重新确认当前仍成立]" if item.get("requires_reconfirmation") else ""
                prop_lb.insert("end",f"#{item['proposal_id']}{freshness} {item['text'][:220]}")
            for item in FISH.list_bootstrap():
                boot_lb.insert("end",f"初始设定 #{item['memory_id']}: {item['text']}")
            p=FISH.actual_progress()
            counts.set(f"已确认记忆 {p['confirmed_memories']} · "
                       f"待审核 {p['pending_candidates']} · "
                       f"初始设定 {p['bootstrap_notes']} · "
                       f"真实用户消息 {p['user_messages']}")
        def show_evidence(event=None):
            picks=prop_lb.curselection()
            if not picks or picks[0]>=len(proposal_items):
                provenance.set("选择待确认项可查看原始证据。")
                return
            v=proposal_items[picks[0]]
            freshness_note=""
            if v.get("requires_reconfirmation"):
                freshness_note=(
                    "\n状态：这条候选早于后来确认/失效证据，不能直接沿用旧来源。"
                    "若仍然成立，批准时会记录一次新的当前用户确认。"
                )
            provenance.set(f"来源事件 #{v['source_event']} · {v['evidence_at']}\n"
                           f"原话：{v['evidence_text'][:400]}{freshness_note}")
        prop_lb.bind("<<ListboxSelect>>",show_evidence)
        def manually_add():
            phrase=simpledialog.askstring("手动保存","要长期保存的内容（将记为你主动提供）:",parent=win)
            if phrase:
                try:
                    FISH.add_memory(phrase)
                    self._sync_memory_bridge()
                    redraw()
                    self.refresh_stats()
                except ValueError as err:
                    messagebox.showerror("保存失败",str(err),parent=win)
        def archive():
            picks=mem_lb.curselection()
            if not picks or picks[0]>=len(mem_ids):return
            if messagebox.askyesno("归档长期记忆",
                                   "归档后不再参与检索；原始事件及此前备份仍保留。继续？",
                                   parent=win):
                FISH.archive_memory(mem_ids[picks[0]])
                self._sync_memory_bridge()
                redraw()
                self.refresh_stats()
        def correct():
            picks=mem_lb.curselection()
            if not picks or picks[0]>=len(mem_ids):return
            memory_id=mem_ids[picks[0]]
            current=mem_lb.get(picks[0])
            replacement=simpledialog.askstring(
                "更正长期记忆",
                "输入更正后的内容。旧记忆会保留在历史中，但不再参与当前召回：",
                parent=win)
            if not replacement:return
            try:
                new_id=FISH.correct_memory(memory_id,replacement)
                self._sync_memory_bridge()
                redraw()
                self.refresh_stats()
                provenance.set(f"记忆 #{memory_id} 已更正为新记忆 #{new_id}。")
            except ValueError as err:
                messagebox.showerror("更正失败",str(err),parent=win)
        def retract():
            picks=mem_lb.curselection()
            if not picks or picks[0]>=len(mem_ids):return
            memory_id=mem_ids[picks[0]]
            if not messagebox.askyesno(
                "撤回长期记忆",
                "撤回后该记忆退出当前召回，但历史证据仍保留。继续？",
                parent=win):
                return
            if FISH.retract_memory(memory_id):
                self._sync_memory_bridge()
                redraw()
                self.refresh_stats()
                provenance.set(f"记忆 #{memory_id} 已撤回。")
        def review(approve):
            picks=prop_lb.curselection()
            if not picks or picks[0]>=len(proposal_items):return
            item=proposal_items[picks[0]]
            stale=bool(item.get("requires_reconfirmation"))
            if approve and stale:
                action=(
                    "重新确认这条内容现在仍然成立，并以“当前重新确认”的新来源写入长期记忆。"
                    "旧消息本身不会被重新当作当前事实。"
                )
            else:
                action="确认记住" if approve else "忽略"
            if not messagebox.askyesno("核实记忆来源",
                f"来源：你亲自发送的第 {item['source_event']} 号消息。\n"
                f"原话：{item['evidence_text'][:450]}\n\n"
                f"将执行：{action}\n是否继续？",parent=win):
                return
            try:
                FISH.review_proposal(
                    item["proposal_id"],approve,
                    reconfirm_stale=bool(approve and stale),
                )
                self._sync_memory_bridge()
                redraw()
                self.refresh_stats()
                provenance.set(f"候选 #{item['proposal_id']} 已{('批准' if approve else '忽略')}。")
            except ValueError as err:
                messagebox.showerror("审阅失败",str(err),parent=win)
        buttons=tk.Frame(win)
        buttons.pack(pady=(2,12))
        for title,callback in [
            ("手动保存",manually_add),("更正",correct),("撤回",retract),("归档",archive),
            ("确认候选",lambda:review(True)),("忽略候选",lambda:review(False)),
            ("关闭",win.destroy)]:
            tk.Button(buttons,text=title,command=callback,padx=8,pady=5).pack(side="left",padx=5)
        redraw()
        if proposal_items:tabs.select(tab_pending)

    def growth_manager(self):
        win=tk.Toplevel(self.root)
        self.reflection=None
        win.title("小鱼 · 成长反思（需确认才改变人格）")
        win.geometry("650x480")
        tk.Label(win,text="成长不是随机改性格。反思需基于互动经历，确认后才加入人格历史。",
                 wraplength=610,justify="left").pack(padx=15,pady=12)
        edit=scrolledtext.ScrolledText(win,height=12,font=("Microsoft YaHei UI",10))
        edit.pack(fill="both",expand=True,padx=15,pady=5)
        edit.insert("end","可以手动写下我们相处后产生的新认识，也可以根据真实互动生成候选反思。\n"
                    "删除此提示后再写内容；不会自动将草稿加入人格。")
        def propose():
            # Recent shared history is owner-private input too. Assemble it
            # behind the same prompt-source fence as the main chat path.
            for assembly_attempt in range(2):
                growth_fence_before=capture_context_fence(FISH)
                ev=FISH.recent_events(50)
                real=[
                    e for e in ev
                    if e["kind"].startswith(("conversation.","pet."))
                ]
                evidence,evidence_ids=growth_evidence_batch(real,12)
                growth_generation=FISH.memory_generation()
                growth_fence=capture_context_fence(FISH)
                if growth_fence==growth_fence_before:
                    break
            else:
                edit.delete("1.0","end")
                edit.insert(
                    "end",
                    "上下文持续变化，未向模型发送旧的私人经历；请重试。",
                )
                return
            if len(real)<4:
                messagebox.showinfo("经历不足","再聊一段时间、有几次真实互动后才能生成有依据的反思。",parent=win)
                return
            config=load_provider(HOME)
            routing_policy_digest=stable_digest(config)
            canonical_identity_id=str(FISH.persona()["id"])
            identity_db_path=str(FISH.db_path)
            r47_db_path=(
                str(self.memory_bridge.db_path)
                if getattr(self,"memory_bridge",None) is not None else ""
            )
            edit.delete("1.0","end")
            edit.insert("end","正在生成仅供你审阅的反思建议……")
            def work():
                system=("根据给定的真实事件，写一条最多120字的性格成长候选。"
                        "用具体事件编号支持；不要凭空捏造经历，不要擅自改变核心价值观。"
                        "只写候选文本，不给指令。")
                try:
                    payload=json.dumps(evidence,ensure_ascii=False)
                    response,_=dual_guarded_chat(
                        chat,config,
                        [{"role":"system","content":system},
                         {"role":"user","content":payload}],
                        identity_db_path,r47_db_path,
                        growth_generation,[],
                        max_tokens=350,
                        expected_context_fence=growth_fence,
                        identity_id=canonical_identity_id,
                        principal_id="owner",
                        owner_principal_id="owner",
                        audience_scope="PRIVATE",
                        context_space="PERSONAL",
                        required_privacy_class="OWNER_PRIVATE",
                        routing_policy_digest=routing_policy_digest,
                        context_state_provider=lambda:{
                            "identity_id":str(FISH.persona()["id"]),
                            "principal_id":"owner",
                            "audience_scope":"PRIVATE",
                            "context_space":"PERSONAL",
                            "authorization_digest":None,
                            "routing_policy_digest":stable_digest(
                                load_provider(HOME)
                            ),
                            "tool_result_digest":None,
                            "tool_implementation_digest":None,
                            "tool_schema_digest":None,
                        },
                    )
                    self.queue_reflect.put((
                        "ok",response,list(evidence_ids),growth_fence
                    ))
                except Exception as err:
                    self.queue_reflect.put(("error",str(err),[],None))
            self.queue_reflect=queue.Queue()
            threading.Thread(target=work,daemon=True).start()
            def check():
                if not win.winfo_exists():return
                try:
                    status,content,ids,response_fence=(
                        self.queue_reflect.get_nowait()
                    )
                    edit.delete("1.0","end")
                    if status=="ok":
                        if capture_context_fence(FISH)!=response_fence:
                            edit.insert(
                                "end",
                                "上下文在反思生成后已变化，旧候选已丢弃；请重新生成。",
                            )
                            self.reflection=None
                            return
                        edit.insert("end",content)
                        FISH.propose_growth(content,ids,confirmed=False)
                        self.reflection=ids
                    else:
                        edit.insert("end",content)
                except queue.Empty:
                    win.after(200,check)
            win.after(200,check)
        def approve():
            if self.pending:
                messagebox.showinfo(
                    "请求进行中",
                    "当前回复仍在生成。为避免人格上下文在请求期间漂移，请在本次回复结束后再确认人格成长。",
                    parent=win,
                )
                return
            text=edit.get("1.0","end").strip()
            if not text or "可以手动写下" in text or "正在生成" in text:return
            if not self.reflection:
                messagebox.showinfo("缺少证据",
                    "人格成长必须有真实共同经历的事件编号作证据。"
                    "目前请先互动，随后点「基于经历生成建议」。",parent=win)
                return
            if messagebox.askyesno("确认人格成长","只有你批准后，这段成长认识才会保存为新的人格版本。是否保存？",parent=win):
                FISH.propose_growth(text,self.reflection or [],confirmed=True)
                self.reflection=None
                self.refresh_stats()
                messagebox.showinfo("保存成功","已创建新的人格版本；可随完整身份档案一起导出。",parent=win)
                win.destroy()
        row=tk.Frame(win)
        row.pack(pady=10)
        tk.Button(row,text="基于经历生成建议（调用模型）",command=propose).pack(side="left",padx=5)
        tk.Button(row,text="确认并写入人格历史",command=approve).pack(side="left",padx=5)

    def provider_manager(self):
        config=load_provider(HOME)
        win=tk.Toplevel(self.root)
        win.title("小鱼 · 更换思考引擎")
        win.geometry("550x330")
        tk.Label(win,text="更换模型不会修改身份数据库。密钥只从环境变量读取。",
                 wraplength=510,justify="left").pack(pady=12)
        provider=tk.StringVar(value=config["provider"])
        model=tk.StringVar(value=config["model"])
        url=tk.StringVar(value=config["url"])
        key_env=tk.StringVar(value=config["key_env"])
        form=tk.Frame(win)
        form.pack(fill="x",padx=18)
        def field(row,label,widget):
            tk.Label(form,text=label,width=12,anchor="w").grid(row=row,column=0,pady=7)
            widget.grid(row=row,column=1,sticky="ew",pady=7)
        form.columnconfigure(1,weight=1)
        select=ttk.Combobox(form,textvariable=provider,values=list(PROVIDERS),state="readonly")
        field(0,"服务商",select)
        field(1,"模型",tk.Entry(form,textvariable=model))
        field(2,"API 地址",tk.Entry(form,textvariable=url))
        field(3,"密钥变量名",tk.Entry(form,textvariable=key_env))
        def changed(event=None):
            base=PROVIDERS[provider.get()]
            model.set(base["model"])
            url.set(base["url"])
            key_env.set(base["key_env"])
        select.bind("<<ComboboxSelected>>",changed)
        def save():
            try:
                save_provider(HOME,provider.get(),model.get(),url.get(),key_env.get())
                self.refresh_stats()
                win.destroy()
            except Exception as err:
                messagebox.showerror("配置错误",str(err),parent=win)
        tk.Button(win,text="保存模型配置（身份不变）",command=save,padx=13,pady=7).pack(pady=12)

    def export_identity(self):
        stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        exports=HOME/"exports"
        exports.mkdir(exist_ok=True)
        path=filedialog.asksaveasfilename(parent=self.root,
            title="导出完整身份和共同经历（包含隐私）",
            initialdir=str(exports),initialfile="xiaoyu-soul-"+stamp+".zip",
            defaultextension=".zip",filetypes=[("Portable Companion Archive","*.zip")])
        if not path:return
        try:
            out=FISH.export(path)
            messagebox.showinfo("导出成功",
                "人格、成长版本、记忆及互动事件已导出：\n"+str(out)+"\n\n"
                "不含 API Key 和模型配置。文件含私人对话，请妥善保管。",
                parent=self.root)
        except Exception as err:
            messagebox.showerror("导出失败",str(err),parent=self.root)

    def close(self):
        if self.pending and not messagebox.askyesno("请求未完成",
            "模型请求尚未完成，关闭会丢失该次尚未返回的回答。仍要退出吗？",parent=self.root):
            return
        FISH.set_state(STATE)
        if self.memory_bridge is not None:
            try:self.memory_bridge.close()
            except Exception:pass
        FISH.close()
        self.root.destroy()

if __name__=="__main__":
    tkroot=tk.Tk()
    PetApp(tkroot)
    tkroot.mainloop()
