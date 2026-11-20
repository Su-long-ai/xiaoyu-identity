"""Read-only cost report over N.E.K.O's existing token_usage.json."""
from __future__ import annotations
import argparse
import html
import json
import math
import os
from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict

ROOT = Path(r"D:\xiaoyu_private_overlay_state\neko-sandbox")
DEFAULT_PRICES = Path(__file__).with_name("api_prices.json")

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def number(value):
    n = float(value or 0)
    if not math.isfinite(n) or n < 0:
        raise ValueError("Non-negative finite amount required")
    return n

def estimate(bucket, tariff, *, aggregate=False):
    """Return a cost range, or None when native units cannot price the model.

    Daily/model buckets aggregate many calls, so tiered per-request pricing can
    only be bounded. Recent individual records can select the exact tier.
    """
    if not tariff:
        return None
    if tariff.get("unit") == "characters":
        chars = number(bucket.get("prompt_chars"))
        if not chars or number(bucket.get("prompt_tokens")) or number(bucket.get("completion_tokens")):
            return None
        rate = number(tariff["cny_per_million_chars"])
        lo_mult = number(tariff.get("char_multiplier_min", 1))
        hi_mult = number(tariff.get("char_multiplier_max", lo_mult))
        if hi_mult < lo_mult:
            raise ValueError("char_multiplier_max must be >= char_multiplier_min")
        return chars * rate * lo_mult / 1e6, chars * rate * hi_mult / 1e6
    if tariff.get("unit") == "token_modal_range":
        if number(bucket.get("prompt_chars")):
            return None
        p = number(bucket.get("prompt_tokens"))
        o = number(bucket.get("completion_tokens"))
        if not p and not o:
            return None
        low = (p * number(tariff["input_min"]) + o * number(tariff["output_min"])) / 1e6
        high = (p * number(tariff["input_max"]) + o * number(tariff["output_max"])) / 1e6
        return low, high
    if tariff.get("unit") != "tokens":
        return None
    p = number(bucket.get("prompt_tokens"))
    o = number(bucket.get("completion_tokens"))
    c = min(p, number(bucket.get("cached_tokens")))
    # Never treat audio/character usage as text tokens.
    if number(bucket.get("prompt_chars")):
        return None
    if not p and not o:
        return None
    rates = tariff["tiers"]

    def price(r):
        uncached = number(r["input"])
        out = number(r["output"])
        cached = r.get("cached")
        low = ((p-c)*uncached + c*(number(cached) if cached is not None else 0) + o*out)/1e6
        high = ((p-c)*uncached + c*(number(cached) if cached is not None else uncached) + o*out)/1e6
        return low, high

    if not aggregate and all("max_prompt_tokens" in r for r in rates):
        for r in rates:
            if p <= number(r["max_prompt_tokens"]):
                return price(r)
        return None

    bounds = [price(r) for r in rates]
    return min(v[0] for v in bounds), max(v[1] for v in bounds)

def summarize(data, prices, today):
    days = data.get("daily_stats", {})
    tariffs = prices.get("models", {})
    rows = []
    features = defaultdict(lambda: {"calls":0,"tokens":0,"chars":0})
    for day, info in sorted(days.items(), reverse=True):
        date.fromisoformat(day)
        for model, b in info.get("by_model", {}).items():
            if model == "app_start":
                continue
            tokens = int(b.get("total_tokens",0))
            chars = int(b.get("prompt_chars",0))
            rows.append({"day":day,"model":model,"calls":int(b.get("call_count",0)),
                         "tokens":tokens,
                         "chars":chars,
                         "has_usage":bool(tokens or chars),
                         "cost":estimate(b, tariffs.get(model), aggregate=True)})
        if day==today.isoformat():
            for k,b in info.get("by_call_type",{}).items():
                if k=="app_start": continue
                features[k]={"calls":int(b.get("call_count",0)),"tokens":int(b.get("total_tokens",0)),
                             "chars":int(b.get("prompt_chars",0))}
    def total(selected):
        known=[r for r in selected if r["cost"] is not None]
        unknown=[r for r in selected if r["has_usage"] and r["cost"] is None]
        no_usage=[r for r in selected if not r["has_usage"]]
        return {"low":sum(r["cost"][0] for r in known),"high":sum(r["cost"][1] for r in known),
                "unknown_calls":sum(r["calls"] for r in unknown),
                "no_usage_calls":sum(r["calls"] for r in no_usage),
                "calls":sum(r["calls"] for r in selected),
                "tokens":sum(r["tokens"] for r in selected),"known_rows":len(known)}
    periods={
        "今日":total([r for r in rows if r["day"]==today.isoformat()]),
        "昨日":total([r for r in rows if r["day"]==(today-timedelta(days=1)).isoformat()]),
        "本月":total([r for r in rows if r["day"].startswith(today.strftime("%Y-%m"))]),
        "已保存历史":total(rows),
    }
    # Recent records are a sample, not an additional ledger. Never add them to totals.
    sample=defaultdict(lambda: {"calls":0,"known_calls":0,"low":0.0,"high":0.0})
    for r in data.get("recent_records",[]):
        if r.get("model")=="app_start": continue
        v=sample[r.get("type","unknown")]
        v["calls"]+=1
        rate=estimate({"prompt_tokens":r.get("pt"),"completion_tokens":r.get("ct"),
                       "cached_tokens":r.get("cch"),"prompt_chars":r.get("pch")},
                      tariffs.get(r.get("model")))
        if rate is not None:
            v["known_calls"]+=1;v["low"]+=rate[0];v["high"]+=rate[1]
    return periods,rows,features,sample

def fmt(r):
    lo,hi=r
    return f"¥{lo:.4f}" if abs(hi-lo)<0.000001 else f"¥{lo:.4f} – ¥{hi:.4f}"

def render(data,prices,today):
    periods,rows,features,sample=summarize(data,prices,today)
    e=lambda v:html.escape(str(v))
    budget=prices.get("daily_budget_cny")
    monthly=prices.get("monthly_budget_cny")
    def status(name, limit):
        if limit is None: return "未设置"
        lim=number(limit); p=periods[name]
        if not p["known_rows"]: return f"¥{lim:g} · 缺少可计价数据"
        state="估算已达预算" if p["low"]>=lim else "估算可能达到预算" if p["high"]>=lim else "已计价部分低于预算"
        return f"¥{lim:g} · {state}（非硬限额）"
    cards="".join(f'<article><small>{e(k)}</small><h2>{fmt((v["low"],v["high"])) if v["known_rows"] else "暂无可计价数据"}</h2><p>{v["tokens"]:,} Token · {v["calls"]:,} 次记录</p><p class="muted">有用量但未计价：{v["unknown_calls"]:,} 次 · 无用量记录：{v["no_usage_calls"]:,} 次</p></article>' for k,v in periods.items())
    modelrows="".join(f'<tr><td>{e(r["day"])}</td><td>{e(r["model"])}</td><td>{r["calls"]:,}</td><td>{r["tokens"]:,}</td><td>{r["chars"]:,}</td><td>{fmt(r["cost"]) if r["cost"] is not None else ("无用量记录" if not r["has_usage"] else "未计价")}</td></tr>' for r in rows)
    frows="".join(f'<tr><td>{e(k)}</td><td>{v["calls"]:,}</td><td>{v["tokens"]:,}</td><td>{v["chars"]:,}</td></tr>' for k,v in sorted(features.items(),key=lambda kv:kv[1]["tokens"],reverse=True))
    srows="".join(f'<tr><td>{e(k)}</td><td>{v["known_calls"]}/{v["calls"]}</td><td>{fmt((v["low"],v["high"])) if v["known_calls"] else "未计价"}</td></tr>' for k,v in sorted(sample.items(),key=lambda kv:kv[1]["high"],reverse=True))
    return f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>小鱼 API 费用</title><style>
body{{font:15px system-ui,sans-serif;background:#12151b;color:#e7eaf0;margin:0;padding:28px;line-height:1.6}}main{{max-width:1100px;margin:auto}}h1{{font-size:28px;margin-bottom:0}}h2{{font-size:22px;margin:7px 0}}h3{{margin-top:30px}}.muted,small{{color:#a8b1c0}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:12px}}article,section{{background:#1b2029;border:1px solid #303847;border-radius:12px;padding:16px}}article p{{margin:4px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;text-align:left;border-bottom:1px solid #343b46}}td:nth-child(n+3),th:nth-child(n+3){{text-align:right}}.scroll{{overflow:auto}}a{{color:#92c6ff}}code{{overflow-wrap:anywhere}}</style><main>
<h1>小鱼 API 费用</h1><p class="muted">N.E.K.O 原生统计 · 最后保存：{e(data.get("last_saved") or "无")} · 价格方案：{e(prices.get("profile","未配置"))}</p>
<p>以下为<strong>本地可观测用量的参考估算</strong>，不代表供应商实际账单。免费额度、折扣、供应商差异及未记录调用等可能造成差异；Realtime 因原生统计未拆分模态而显示保守上下界。价格历史未追踪，按当前配置重估历史。</p>
<div class="cards">{cards}</div><h3>预算提示</h3><section>每日：{e(status("今日",budget))}<br>每月：{e(status("本月",monthly))}<br><small>只读提醒，不会停止 API。修改 api_prices.json 设置预算及价格。</small></section>
<h3>按天 / 模型</h3><section class="scroll"><table><tr><th>日期</th><th>模型</th><th>次数</th><th>Token</th><th>字符</th><th>估算费用</th></tr>{modelrows}</table></section>
<h3>今日功能用量（完整已保存汇总）</h3><section class="scroll"><table><tr><th>功能</th><th>次数</th><th>Token</th><th>字符</th></tr>{frows}</table></section>
<h3>近期功能费用样本（最多 200 条，不等于今日全部）</h3><section class="scroll"><table><tr><th>功能</th><th>已计价/样本</th><th>参考费用</th></tr>{srows}</table></section>
<p class="muted">原生统计约每 60 秒保存。重新打开桌面入口刷新。价格参考：<a href="https://help.aliyun.com/zh/model-studio/model-pricing">阿里云百炼官方价格</a>；实际路由或区域不确定时请修改本地价格配置。未区分实时音频单位的模型不填虚假价格。</p></main></html>"""

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--storage-root",type=Path,default=ROOT)
    parser.add_argument("--prices",type=Path,default=DEFAULT_PRICES)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--open",action="store_true")
    args=parser.parse_args()
    data=read_json(args.storage_root/"config"/"token_usage.json")
    prices=read_json(args.prices)
    out=args.output or args.storage_root/".runtime"/"xiaoyu_api_cost.html"
    out.parent.mkdir(exist_ok=True,parents=True)
    temp=out.with_suffix(".tmp")
    temp.write_text(render(data,prices,date.today()),encoding="utf-8")
    os.replace(temp,out)
    print(json.dumps(summarize(data,prices,date.today())[0],ensure_ascii=True))
    if args.open: os.startfile(str(out))

if __name__=="__main__":
    main()
