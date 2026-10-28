# -*- coding: utf-8 -*-
"""Apply one-shot UI upgrade to explicit provenance and memory proposal review."""
from pathlib import Path
p=Path(__file__).with_name("companion.py")
s=p.read_text("utf-8")
if "待确认记忆" in s and "review_proposal" in s:
    print("UI_V2_ALREADY_APPLIED")
    raise SystemExit(0)
a="f\"经历 {FISH.event_count()} 条\""
b=('f"消息 {FISH.actual_progress()[\'user_messages\']} · 回复 '
   '{FISH.actual_progress()[\'assistant_replies\']} · 互动 '
   '{FISH.actual_progress()[\'pet_actions\']} · 真实记忆 '
   '{FISH.actual_progress()[\'confirmed_memories\']} · 待确认 '
   '{FISH.actual_progress()[\'pending_candidates\']} 条"')
if s.count(a)!=1: raise RuntimeError("Cannot find stats anchor")
s=s.replace(a,b)
start=s.index('        event_id=FISH.record("conversation.user","user",message)')
end=s.index('        sysmsg=FISH.identity_context(message)',start)
s=s[:start]+'''        event_id=FISH.record("conversation.user","user",message)
        proposed_id=FISH.propose_from_user_event(event_id,message)
        if proposed_id:
            self.logline("系统：发现一条可保留的原话，已放入「长期记忆 → 待确认」，并未直接写入记忆。")
'''+s[end:]
start=s.index('    def memory_manager(self):')
end=s.index('    def growth_manager(self):',start)
s=s[:start]+'''
    def memory_manager(self):
        win=tk.Toplevel(self.root)
        win.title("小鱼 · 记忆来源与审阅")
        win.geometry("760x530")
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
                prop_lb.insert("end",f"#{item['proposal_id']} {item['text'][:220]}")
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
            provenance.set(f"来源事件 #{v['source_event']} · {v['evidence_at']}\n"
                           f"原话：{v['evidence_text'][:400]}")
        prop_lb.bind("<<ListboxSelect>>",show_evidence)
        def manually_add():
            phrase=simpledialog.askstring("手动保存","要长期保存的内容（将记为你主动提供）:",parent=win)
            if phrase:
                try:
                    FISH.add_memory(phrase)
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
                redraw()
                self.refresh_stats()
        def review(approve):
            picks=prop_lb.curselection()
            if not picks or picks[0]>=len(proposal_items):return
            item=proposal_items[picks[0]]
            action="确认记住" if approve else "忽略"
            if not messagebox.askyesno("核实记忆来源",
                f"来源：你亲自发送的第 {item['source_event']} 号消息。\n"
                f"原话：{item['evidence_text'][:450]}\n\n"
                f"将执行：{action}。是否继续？",parent=win):
                return
            try:
                FISH.review_proposal(item["proposal_id"],approve)
                redraw()
                self.refresh_stats()
                provenance.set(f"候选 #{item['proposal_id']} 已{('批准' if approve else '忽略')}。")
            except ValueError as err:
                messagebox.showerror("审阅失败",str(err),parent=win)
        buttons=tk.Frame(win)
        buttons.pack(pady=(2,12))
        for title,callback in [
            ("手动保存",manually_add),("归档选中记忆",archive),
            ("确认候选",lambda:review(True)),("忽略候选",lambda:review(False)),
            ("关闭",win.destroy)]:
            tk.Button(buttons,text=title,command=callback,padx=8,pady=5).pack(side="left",padx=5)
        redraw()
        if proposal_items:tabs.select(tab_pending)

'''+s[end:]
s=s.replace('''        win=tk.Toplevel(self.root)
        win.title("小鱼 · 成长反思（需确认才改变人格）")''',
'''        win=tk.Toplevel(self.root)
        self.reflection=None
        win.title("小鱼 · 成长反思（需确认才改变人格）")''')
s=s.replace('''            if not text or "可以手动写下" in text or "正在生成" in text:return
            if messagebox.askyesno''',
'''            if not text or "可以手动写下" in text or "正在生成" in text:return
            if not self.reflection:
                messagebox.showinfo("缺少证据",
                    "人格成长必须有真实共同经历的事件编号作证据。"
                    "目前请先互动，随后点「基于经历生成建议」。",parent=win)
                return
            if messagebox.askyesno''')
p.write_text(s,"utf-8")
print("UI_V2_PATCHED")
