# XiaoYu 1.0 Master Plan

**Date:** 2026-11-18  
**Status:** working master plan  
**Primary objective:** 2026-11 月底前停止主动扩 scope，收成可长期使用的 XiaoYu 1.0。

---

## 1. 项目目标重新定义

XiaoYu 的目标不是做一个功能很多的 Agent，也不是做 DSH、SurfCore、Open-LLM-VTuber 的替代品。

目标是：

> **一个长期连续存在的“小鱼”：有稳定身份和人格，能记住与你共同经历的事情，理解当前环境与时间，能有限主动行动，在桌面、QQ 等入口始终是同一个她，而且能力提升可以被验证。**

所以项目价值排序应当是：

**身份连续性 > 记忆可信度 > 最终回答质量 > 跨入口一致性 > 主动性 > 感知/语音 > 社交扩展。**

---

## 2. 2026-11-18 已确认状态

### 2.1 Core

已经形成统一主链：

```
IdentityStore
  ↓
ProductMemoryBridge
  ↓
turn_runtime
  ↓
model_adapter / provider routing
  ↓
tool_runtime
  ↓
freshness / send guard
  ↓
persist
```

Desktop、Live2D、QQ 都应只通过这一条 Core，不再维护第二套身份/记忆/provider。

最近实测：

- DeepSeek Web 已退出产品路径；
- 主 provider：DeepSeek API / `deepseek-flash`；
- Qwen API fallback；
- API smoke 成功；
- 关键产品回归在最近一轮达到 42/42 PASS；
- API-only 下 Desktop Pet + Core 空闲 Working Set 约 323 MB；
- Core 本身约几十 MB；
- CUDA retrieval worker 已改为热复用；
- 非空真实记忆冷检索约 22.29 s，热检索约 0.012 s；
- 无授权记忆时不再加载 CUDA worker；
- worker 默认空闲 90 s 后释放。

这些数字是 2026-11-18 会话中断开本地连接前的实测快照，不作为永久性能 SLA。

### 2.2 能力研究

- Broad pilot baseline：V8；
- V23：archived / optional / default-off；
- DECADE100：all100 semantic substrate 已 100/100 PASS；
- 当前 frontier：all100 runtime payload preflight + aggregate cost preflight；
- 正式 paid 100-pair 还未启动；
- strong model 当前不是 blocker。

研究目标必须保持 outcome-first：retrieval、TopK、source count 本身不能算产品晋升。

### 2.3 QQ

技术 transport 已打通，但产品状态仍未完成：

- OneBot/NapCat 技术链可用；
- `qq_surface.json` 当时仍 `enabled=false`；
- allowlist=0；
- 尚未完成真实 owner private-chat 配对；
- 所以“QQ已接入”只能说工程准备完成，不能说产品 E2E 已完成。

### 2.4 Live2D / Desktop

Desktop 已与 XiaoYu Core 合并，不应再有单独“大脑”。

当前剩余重点不是再做 UI，而是：

- recovery；
- 多入口连续性；
- vision / voice；
- 生命周期管理。

---

## 3. 还需要做什么

## P0：1.0 必须完成

### P0-1 · 完成 DECADE100

目的不是刷 benchmark，而是回答：

> V8 相对 V5 的提升到底是真实泛化，还是开发集适配？

剩余路径：

```
semantic substrate 100/100 PASS
        ↓
all100 runtime payload
        ↓
aggregate cost preflight
        ↓
full 100-pair V5 vs V8
        ↓
dual judge / source adjudication
        ↓
promotion decision
```

停止规则：

- V8 胜：V8 晋升正式 baseline；
- 基本持平：保留 V8，停止为 benchmark 继续调参；
- 明显输：只允许针对一个最主要、可解释的 failure cluster 做一次 bounded repair，再重测；
- 禁止 V9 → V10 → V11 无限循环。

### P0-2 · Core V1 freeze

冻结的不是实现细节，而是接口和职责边界：

```
Identity
Memory Authority
Turn Runtime
Tool Runtime
Freshness
Provider Routing
Persistence
```

冻结后：

- Vision 不能侵入 identity；
- QQ 不能自己写第二套 history；
- Live2D 不能自己维护 persona；
- Voice 不得改变 canonical turn；
- B站以后只能作为 surface。

### P0-3 · Desktop ↔ QQ 跨入口 E2E

需要证明：

1. QQ 说过的内容 Desktop 下一轮能正确延续；
2. Desktop 的未完成目的 QQ 可以正确接续；
3. 同一 canonical turn sequence；
4. 旧 context 被新入口更新后会正确失效；
5. 不重复写 memory；
6. 崩溃恢复后仍然是同一个 identity；
7. QQ 不配对时保持 fail-closed。

### P0-4 · 恢复、备份、启动

必须有：

- one-click start；
- provider health check；
- identity backup；
- export / restore smoke；
- crash-safe persistence；
- worker cleanup；
- clear status page / logs；
- no secret in repo/export。

---

## P1：1.0 应完成

### P1-1 · 长期记忆生命周期

从“能存取”升级到“能活几年”。

建议三层：

```
Immutable / very-slow identity
  名字、关系、核心边界、不可伪造来源
        ↓
Long-term memory
  共同经历、稳定偏好、长期项目、重要关系事实
        ↓
Transient state
  最近话题、今天状态、当前任务、短期目的
```

必须支持：

- duplicate consolidation；
- contradiction / correction；
- stale / superseded fact；
- importance / salience；
- provenance；
- archive；
- retrieval demotion；
- user-confirmed deletion policy。

重要原则：

**遗忘优先表现为“降低默认检索概率”，不是默默销毁历史。**

### P1-2 · Vision

建议吸收 dsh-see-now 的底层思路，而不是依赖 DSH：

```
screen / camera
    ↓
local change scoring
    ↓
interesting-frame selection
    ↓
storyboard / sheet
    ↓
independent vision provider
    ↓
XiaoYu turn_runtime
```

最小 1.0 能力：

- explicit `看一下屏幕`；
- region watch；
- change-triggered observation；
- “完成了告诉我”类 bounded watch；
- visual evidence 不默认进入长期记忆；
- capture indicator / privacy state；
- explicit retention policy。

不要把 DeepSeek Web 搬回来。主聊天 provider 与 vision provider 分离。

### P1-3 · 有限主动性 / Purpose

最小结构：

```
recent memory + transient state
          ↓
candidate purpose
          ↓
value / urgency / confidence / risk
          ↓
interrupt-worthiness
          ↓
quiet hours / daily cap / focus / owner-active gate
          ↓
Desktop or QQ
```

必须满足：

- 同一个 purpose 不跨 surface 重复打扰；
- 有 cooldown；
- 主人在聊时不抢话；
- 有每日上限；
- 可关闭；
- 有“为什么主动联系”的可审计原因；
- 失败不无限 retry。

### P1-4 · Voice

借鉴 Open-LLM-VTuber / SurfCore 的产品经验，但保持 Core 独立。

推荐：

```
LLM stream
   ↓
sentence chunks
   ↓
TTS queue
   ↓
audio playback
   ↓
Live2D mouth / expression
```

目标：

- 第一段文本出来即可开始说；
- 后续 TTS 在后台合成；
- 可打断；
- 不把动作标签读出来；
- 语音只是 presentation，不是第二条 history。

### P1-5 · 人格演化边界

三层：

```
Immutable identity
Slow-changing traits
Fast state
```

规则：

- immutable 层不能被聊天自动改写；
- slow traits 必须有多条真实经历支持；
- evolution 有版本；
- 用户可查看和回滚；
- fast state 不升级为人格，除非持续证据充分。

---

## P2：1.0 后

这些不应继续阻塞 1.0：

- B站自主生活；
- 多角色整包切换；
- 手机端；
- Quest；
- 长视频连续陪看；
- 大规模自主 computer use；
- 高级情绪建模；
- 群聊社会关系图；
- 长期自治任务；
- 复杂多 Agent；
- 更大 dashboard；
- 完整 OSWorld 类操作能力。

---

## 4. 目标架构

```
                         XiaoYu Core
       ┌──────────────────────────────────────┐
       │ Identity / Persona                   │
       │ Memory authority + provenance        │
       │ Long-term memory lifecycle           │
       │ Canonical turn + recent state        │
       │ Evidence / answer contract           │
       │ Tool runtime                         │
       │ Freshness / persistence              │
       │ Purpose state                        │
       │ Provider routing                     │
       └──────────────────┬───────────────────┘
                          │
         ┌────────────────┼──────────────────┬──────────────────┐
         ↓                ↓                  ↓                  ↓
      Desktop             QQ               Vision             Voice
      Live2D           OneBot/NapCat      see-now-like      TTS / ASR
         │                │                  │                  │
         └────────────────┴──────────────────┴──────────────────┘
                          │
                      same XiaoYu
```

以后 B站 / Mobile / Quest 继续向右加，不改变 Core。

---

## 5. 1.0 验收矩阵

### Identity

- [ ] restart 后 identity id 不变
- [ ] provider switch 后 identity 不变
- [ ] Desktop / QQ 同一 identity
- [ ] persona version 可追溯
- [ ] bootstrap 设定不冒充共同经历

### Memory

- [ ] confirmed memory 可 recall
- [ ] rejected candidate 不 recall
- [ ] correction supersedes old value
- [ ] conflict 可解释
- [ ] archived memory 默认不 recall
- [ ] transient state 不污染 long-term
- [ ] 无 memory 时不加载 expensive retriever
- [ ] memory 数据变化后 retrieval cache 正确失效

### Turn

- [ ] concurrent surface freshness
- [ ] stale reply 不 persist
- [ ] tool events 进入统一 ledger
- [ ] vision bytes 不误写长期 history
- [ ] provider fallback 不改变 canonical identity

### Surface

- [ ] Desktop E2E
- [ ] QQ pair / send / receive E2E
- [ ] cross-surface continuation
- [ ] purpose delivery only once
- [ ] offline / reconnect recovery

### Product

- [ ] one-click start
- [ ] crash recovery
- [ ] backup / restore
- [ ] status / logs
- [ ] API-only
- [ ] no secret leakage
- [ ] idle resource reclaim

### Capability

- [ ] DECADE100 completed
- [ ] frozen prompt / judge / source rules
- [ ] final promotion decision
- [ ] no benchmark-specific endless tuning

---

## 6. 11 月底收口策略

### 11/18–11/21

- DECADE100 runtime/cost；
- QQ E2E；
- Core V1 interface freeze；
- Vision minimal spike；
- memory lifecycle design freeze。

### 11/22–11/25

- Vision minimal product path；
- Purpose minimal engine；
- Streaming TTS；
- full multi-surface recovery regression。

### 11/26–11/28

- 修真正 blocker；
- backup / restore；
- startup / health；
- final docs；
- performance budget。

### 11/29–11/30

停止新机制。

所有未完成项目必须进入二选一：

- `DONE`
- `DONE_WAITING_PROSPECTIVE_EVIDENCE`

禁止因为“还有一个挺有意思的方向”继续延长 1.0。

---

## 7. 最终判断

XiaoYu 当前最大风险已经不是技术做不出来。

最大风险是：

> **每解决一个问题，就继续发现一个合理的新研究方向，于是永远不发布。**

因此 1.0 的核心策略是：

**freeze brain, complete evidence, close product loops, then stop.**
