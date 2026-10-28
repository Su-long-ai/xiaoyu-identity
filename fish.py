# -*- coding: utf-8 -*-
"""小鱼：纯标准库本地桌宠；仅用户主动聊天时调用 DeepSeek Flash。"""
from __future__ import annotations
import json, os, queue, sys, threading, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

HOME = Path(__file__).resolve().parent
DATA = HOME / "fish_data.json"
MEMORY = HOME / "MEMORY.md"
DEFAULT = {"name": "小鱼", "born": "2026-10-26", "stage": "幼鱼",
           "mood": 80, "hunger": 20, "energy": 90, "bond": 0,
           "last_tick": time.time(), "chat": [], "total_calls": 0, "usage": {}}

def clamp(x): return max(0, min(100, int(x)))

def load_data():
    d = dict(DEFAULT)
    if DATA.exists():
        try:
            raw = json.loads(DATA.read_text(encoding="utf-8"))
            if isinstance(raw, dict): d.update(raw)
        except (ValueError, OSError):
            pass
    for key in ("mood", "hunger", "energy", "bond"):
        d[key] = clamp(d.get(key, DEFAULT[key]))
    if not isinstance(d.get("chat"), list): d["chat"] = []
    return d

def save_data(d):
    tmp = DATA.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA)

def update_time(d):
    now = time.time()
    elapsed = max(0, min(7 * 24 * 3600, now - float(d.get("last_tick", now))))
    hours = int(elapsed // 3600)
    if hours:
        d["hunger"] = clamp(d["hunger"] + min(30, hours * 2))
        d["energy"] = clamp(d["energy"] - min(20, hours))
        d["mood"] = clamp(d["mood"] - min(12, hours // 3))
    d["last_tick"] = now

def model_reply(d, message):
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未检测到 DEEPSEEK_API_KEY 环境变量。请先配置密钥；不要把密钥发到聊天里。")
    memory = MEMORY.read_text(encoding="utf-8")[:1800] if MEMORY.exists() else ""
    system = (
        "你是小鱼，一条友善、好奇、有点调皮的虚拟 AI 小鱼。"
        "用简短自然的中文聊天，通常 1~4 句，适当保留自己的个性；别频繁卖萌。"
        "你不是真正的生物，不声称自己有意识或真实感情。"
        "你只在本地桌宠程序中和主人交流；本阶段不接 QQ、B 站或其他平台。"
        "游戏状态是模拟数值，不是现实身体状况。"
        f"当前养成状态：心情{d['mood']}，饥饿{d['hunger']}，精力{d['energy']}，亲密度{d['bond']}。\n"
        f"已有记忆：\n{memory}"
    )
    history = []
    for turn in d["chat"][-14:]:
        if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            history.append({"role": turn["role"], "content": turn["content"][:1500]})
    payload = json.dumps({"model": "deepseek-flash", "messages":
                          [{"role": "system", "content": system}] + history +
                          [{"role": "user", "content": message}],
                          "max_tokens": 480, "stream": False},
                         ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.deepseek.com/chat/completions", data=payload, method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=75) as response:
            obj = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 不打印请求、Authorization 或响应正文，以免暴露密钥和私人聊天。
        raise RuntimeError(f"DeepSeek API 返回 HTTP {e.code}。请检查余额、模型与密钥。") from None
    except urllib.error.URLError as e:
        raise RuntimeError("网络无法连接 DeepSeek API。") from None
    choices = obj.get("choices") or []
    if not choices: raise RuntimeError("API 未返回有效回答。")
    content = (choices[0].get("message") or {}).get("content") or ""
    usage = obj.get("usage") or {}
    return content.strip() or "咕噜……我刚刚走神啦。", usage

def selftest():
    d = load_data()
    update_time(d)
    assert 0 <= d["hunger"] <= 100
    assert "name" in d
    save_data(d)
    d2 = load_data()
    assert d2["name"] == d["name"]
    print("SELFTEST_OK; api_called=false; data=" + str(DATA))

def run_ui():
    import tkinter as tk
    from tkinter import scrolledtext
    root = tk.Tk()
    root.title("小鱼 · DeepSeek Flash")
    root.geometry("690x700")
    root.minsize(570, 590)
    root.configure(bg="#ecf8ff")
    fish = load_data()
    update_time(fish)
    save_data(fish)
    results = queue.Queue()
    pending = [False]
    tick = [0]
    canvas = tk.Canvas(root, height=265, bg="#d7f2ff", highlightthickness=0)
    canvas.pack(fill="x", padx=18, pady=(18, 8))
    header = tk.Label(root, text="🐟  小鱼 · 幼鱼期", font=("Microsoft YaHei UI", 17, "bold"),
                      bg="#ecf8ff", fg="#145f82")
    header.pack()
    status = tk.StringVar()
    tk.Label(root, textvariable=status, font=("Microsoft YaHei UI", 10),
             bg="#ecf8ff", fg="#337a9b").pack(pady=5)
    actions = tk.Frame(root, bg="#ecf8ff")
    actions.pack(pady=(4, 10))
    log = scrolledtext.ScrolledText(root, wrap="word", height=11,
                                   font=("Microsoft YaHei UI", 10), bg="#ffffff",
                                   fg="#23465d", relief="flat", padx=10, pady=10)
    log.pack(fill="both", expand=True, padx=18, pady=(0, 9))
    log.insert("end", "小鱼：咕噜～我醒啦！可以和我聊天，也可以喂食、玩耍或让我休息。\n")
    for item in fish["chat"][-10:]:
        who = "你" if item.get("role") == "user" else "小鱼"
        log.insert("end", f"{who}：{item.get('content','')}\n")
    log.see("end")
    sendbar = tk.Frame(root, bg="#ecf8ff")
    sendbar.pack(fill="x", padx=18, pady=(0, 13))
    entry = tk.Entry(sendbar, font=("Microsoft YaHei UI", 11), relief="flat",
                     bg="white", fg="#24506b")
    entry.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))

    def draw():
        tick[0] += 1
        import math
        canvas.delete("all")
        w = max(570, canvas.winfo_width())
        y = 140 + math.sin(tick[0]/11) * 7
        x = w / 2 + math.sin(tick[0]/70) * 20
        canvas.create_oval(0, 200, w, 320, fill="#b6e8ff", outline="")
        canvas.create_polygon(x-105, y, x-174, y-47, x-174, y+47,
                              fill="#3eabd9", outline="#3283ac", width=2)
        canvas.create_oval(x-118, y-70, x+117, y+68,
                           fill="#65c3ef", outline="#2588b7", width=3)
        canvas.create_polygon(x-22, y-56, x+4, y-92, x+40, y-56,
                              fill="#43b5e8", outline="")
        canvas.create_oval(x+51, y-28, x+68, y-9, fill="white", outline="")
        canvas.create_oval(x+59, y-25, x+67, y-14, fill="#1e4c6a", outline="")
        canvas.create_arc(x+62, y+9, x+96, y+40, start=195, extent=118,
                          outline="#2c709b", width=3, style="arc")
        for j in range(5):
            by = 230 - (tick[0]*2+j*52) % 235
            bx = 40 + j*31
            canvas.create_oval(bx-6,by-6,bx+6,by+6,outline="#88d5f0",width=2)
        root.after(90, draw)

    def sync_status():
        status.set(f"心情 {fish['mood']}/100    饥饿 {fish['hunger']}/100    "
                   f"精力 {fish['energy']}/100    亲密度 {fish['bond']}/100")
        save_data(fish)

    def activity(kind):
        if kind == "feed":
            fish["hunger"] = clamp(fish["hunger"] - 35)
            fish["mood"] = clamp(fish["mood"] + 3)
            fish["bond"] = clamp(fish["bond"] + 1)
            msg = "小鱼：啊呜！谢谢投喂！"
        elif kind == "play":
            fish["mood"] = clamp(fish["mood"] + 12)
            fish["hunger"] = clamp(fish["hunger"] + 4)
            fish["energy"] = clamp(fish["energy"] - 8)
            fish["bond"] = clamp(fish["bond"] + 2)
            msg = "小鱼：咕噜咕噜！再玩一会儿！"
        else:
            fish["energy"] = clamp(fish["energy"] + 40)
            fish["hunger"] = clamp(fish["hunger"] + 5)
            fish["bond"] = clamp(fish["bond"] + 1)
            msg = "小鱼：呼噜……睡得真舒服。"
        log.insert("end", msg + "\n")
        log.see("end")
        sync_status()

    for label, kind in [("🍤 喂食", "feed"), ("🎾 玩耍", "play"), ("💤 休息", "rest")]:
        tk.Button(actions, text=label, command=lambda k=kind: activity(k),
                  font=("Microsoft YaHei UI", 10), fg="#17587a", bg="#c8eafc",
                  relief="flat", padx=15, pady=5).pack(side="left", padx=7)

    def send(event=None):
        if pending[0]: return
        msg = entry.get().strip()
        if not msg: return
        entry.delete(0, "end")
        log.insert("end", f"你：{msg}\n")
        log.insert("end", "小鱼：正在想……\n")
        log.see("end")
        pending[0] = True
        sendbtn.config(state="disabled")
        snapshot = {**fish, "chat": list(fish["chat"])}
        def work():
            try:
                reply, usage = model_reply(snapshot, msg)
                results.put((msg, reply, usage, None))
            except Exception as e:
                results.put((msg, "", {}, str(e)))
        threading.Thread(target=work, daemon=True).start()

    sendbtn = tk.Button(sendbar, text="发送", command=send,
                        font=("Microsoft YaHei UI", 10), fg="white",
                        bg="#2289bd", relief="flat", padx=21, pady=8)
    sendbtn.pack(side="right")
    entry.bind("<Return>", send)

    def pump():
        try:
            while True:
                msg, reply, usage, error = results.get_nowait()
                pending[0] = False
                sendbtn.config(state="normal")
                log.delete("end-2l", "end-1l") # 删除上一行“正在想”
                if error:
                    log.insert("end", "小鱼：" + error + "\n")
                else:
                    log.insert("end", f"小鱼：{reply}\n")
                    fish["chat"].extend([{"role": "user", "content": msg},
                                         {"role": "assistant", "content": reply}])
                    fish["chat"] = fish["chat"][-60:]
                    fish["bond"] = clamp(fish["bond"] + 1)
                    fish["total_calls"] = int(fish.get("total_calls", 0)) + 1
                    for k in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens"):
                        fish["usage"][k] = int(fish["usage"].get(k, 0)) + int(usage.get(k, 0))
                    sync_status()
                log.see("end")
        except queue.Empty:
            pass
        root.after(180, pump)

    def clock():
        update_time(fish)
        sync_status()
        root.after(60_000, clock)

    def on_close():
        save_data(fish)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    sync_status()
    root.after(60, draw)
    root.after(180, pump)
    root.after(60_000, clock)
    entry.focus_set()
    root.mainloop()

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        selftest()
    else:
        run_ui()
