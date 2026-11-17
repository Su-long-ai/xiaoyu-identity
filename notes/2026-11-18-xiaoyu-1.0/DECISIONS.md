# XiaoYu 1.0 · Design Decisions

**Date:** 2026-11-18

这份文件只记录“决定”，防止以后看到新项目又把架构推倒重来。

---

## D1 · XiaoYu 永远只有一个 Core

**ACCEPTED**

Core 是身份与记忆真相源。

任何新 surface：

- Desktop
- QQ
- Vision
- Voice
- B站
- Mobile
- Quest

只能接入 Core，不能再发明自己的 identity / memory / canonical history。

---

## D2 · 不迁移到 DSH / SurfCore / Letta

**ACCEPTED**

可以复用模块与设计，但不迁宿主。

原因：

1. XiaoYu 已有 provenance-aware identity；
2. 已有 canonical turn；
3. 已有 freshness；
4. 已有 provider abstraction；
5. 已有 outcome-first evaluation；
6. 迁移风险远高于收益。

---

## D3 · SurfCore 的社会化层值得吸收

**ACCEPTED WITH SCOPE**

优先吸收思想：

- purpose engine；
- proactive gate；
- quiet hours；
- daily cap；
- owner-active gate；
- delivery carrier selection；
- QQ 产品交互；
- voice UX；
- token budget；
- local console 思路。

不吸收：

- DSH session 作为 identity truth；
- 多角色切换作为 XiaoYu 默认模型；
- memory card 替换 IdentityStore / ProductMemoryBridge。

---

## D4 · dsh-see-now 作为 Vision substrate 首选

**ACCEPTED**

优先复用/移植：

- capture；
- pipeline；
- change detection；
- sheet packing；
- region；
- bounded watch。

保持：

- XiaoYu-owned vision provider；
- XiaoYu-owned retention；
- XiaoYu-owned purpose；
- XiaoYu-owned tool permissions。

许可证当前从官方仓库核验为 Apache-2.0。

---

## D5 · Vision provider 与聊天 provider 分离

**ACCEPTED**

当前 text 主链保持：

```
DeepSeek API
  ↓ fallback
Qwen API
```

Vision 单独配置。

禁止为了视觉恢复 DeepSeek Web / 专用 Chrome 中转。

---

## D6 · 记忆“遗忘”默认等于降权，而不是删除

**ACCEPTED**

除非用户明确要求删除且系统实现了合规删除链，否则：

- 原始事件保留 provenance；
- 旧事实可标记 superseded；
- archived / stale 降低默认 retrieval；
- 不把历史静默抹掉。

---

## D7 · 人格演化分三层

**ACCEPTED**

```
immutable identity
slow traits
fast state
```

immutable 不允许自动改。

slow trait 必须真实证据 + 版本 + 可回滚。

fast state 不自动升级为人格。

---

## D8 · DECADE100 是 1.0 的研究终点，不是新一轮起点

**ACCEPTED**

DECADE100 完成后：

- win → promote；
- tie → stop；
- loss → 最多一次 bounded repair；
- 禁止为了 benchmark 开无限代际。

Judge / prompt / source / manifest 中途不得因为结果调整。

---

## D9 · 1.0 需要主动性，但必须“有限”

**ACCEPTED**

主动行为必须经过：

```
purpose candidate
  ↓
value / urgency / confidence / risk
  ↓
quiet / focus / active-chat / cooldown / daily-cap
  ↓
single carrier
```

没有“值得打扰”的理由就不发。

---

## D10 · Voice 是 presentation，不是第二条对话链

**ACCEPTED**

TTS 不产生新的 canonical user/assistant event。

ASR 输入要先转成 canonical user turn。

Live2D 表情/嘴型是 presentation state。

---

## D11 · Vision raw frames 默认不写长期记忆

**ACCEPTED**

默认：

- transient；
- bounded retention；
- 只有模型/用户形成可确认的语义事件才进入 memory candidate；
- 敏感画面不默认上传或长期保存。

---

## D12 · B站不是 1.0 blocker

**ACCEPTED**

SurfCore 已证明这个方向可做，但它不是 XiaoYu 核心价值的当前缺口。

放到 1.x / 2.0。

---

## D13 · 11 月底停止新增机制

**ACCEPTED**

11/29 起只允许：

- blocker fix；
- regression fix；
- docs；
- packaging；
- backup/recovery；
- release hygiene。

禁止：

- 新 memory architecture；
- 新 provider framework；
- 新 multi-agent topology；
- 新 social platform；
- 新 benchmark family；
- 大规模重构。

---

## D14 · 1.0 完成标签

满足 MASTER_PLAN 的验收后，必须创建明确 release / status：

```
XIAOYU_1_0_DONE
```

未来需要时间自然成熟的 prospective evidence 不阻塞工程完结，状态改为：

```
DONE_WAITING_PROSPECTIVE_EVIDENCE
```

---

## D15 · “外部项目出现”不等于“本项目要迁移”

**ACCEPTED**

以后看到新仓库时统一问四个问题：

1. 它补的是 Core 缺口还是 surface 缺口？
2. 可以作为 library / sidecar 吗？
3. 会不会建立第二套 identity / memory truth？
4. 集成后是否减少我们的代码，而不是只增加依赖？

只有全局收益明确才吸收。

---

## Final architecture rule

> **XiaoYu owns who she is. External projects may give her eyes, voice, hands, or social habits, but they must not become a second brain.**
