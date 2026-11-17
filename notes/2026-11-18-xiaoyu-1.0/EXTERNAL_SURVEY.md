# XiaoYu 1.0 · External Survey

**Research date:** 2026-11-18  
**Purpose:** 只调查能直接影响 XiaoYu 1.0 架构和收口决策的项目/论文，不做泛泛“AI伴侣大全”。

---

## 1. SurfCore

Repository: https://github.com/Mieksido/surfcore  
License: MIT  
Current public positioning at research time: DSH agent identity / QQ / B站 / desktop pet / memory / purpose / voice / budget.

### 已验证的关键设计

SurfCore 把系统分成 DSH 内插件 + 独立 bridge 两部分，QQ、B站、桌宠共享：

- memory card；
- purpose engine；
- token budget；
- persona / character package。

其主动机制包含：

- quiet hours；
- daily cap；
- owner is chatting；
- focus mode；
- token budget；
- delivery carrier selection（QQ / desktop pet）；
- watchdog / receipt。

QQ 产品层已经包含引用、分条、表情、图片、语音、拍一拍、上线补历史、收尾/潜水等大量真实社交行为。

记忆采用：

- decayed card：进入 prompt；
- full archive：append-only，不默认注入；
- scope：qq / bili / pet / shared；
- capacity alert / compression。

### 对 XiaoYu 的启示

**直接参考：**

1. purpose / proactive gate；
2. social delivery policy；
3. token / cost budget；
4. QQ 产品行为；
5. voice presentation；
6. local admin console 的产品形态。

**不要吸收：**

1. DSH 作为 XiaoYu identity authority；
2. 多角色切换作为默认身份模型；
3. SurfCore memory card 替代 XiaoYu provenance memory；
4. 每个平台维护独立 session truth。

### 原因

SurfCore 更像“让 Agent 在网络中生活的社会化操作系统”。

XiaoYu 更强调：

- 一个长期连续身份；
- provenance；
- human-confirmed persona evolution；
- evidence / answer contract；
- prospective capability evaluation。

所以正确关系是：

**XiaoYu Core + SurfCore-like social layer**

不是 SurfCore 替换 XiaoYu。

### 许可注意

SurfCore 本仓 MIT，但其 QQ 侧依赖/生态涉及 SnowLuma 等第三方组件，许可证与平台服务条款需要单独核对。即使只借鉴架构，也不应默认把第三方实现直接搬入 XiaoYu。

---

## 2. dsh-see-now

Repository: https://github.com/SAOS-3624/dsh-see-now  
Current package observed: `dsh-see-now 0.2.4`  
License verified from repository: Apache-2.0  
Node engine: >=20.

### 已验证的关键设计

它解决的是“实时视觉采集成本”，不是 identity / memory。

主要链路：

```
screen / webcam / video
        ↓
frame capture
        ↓
64×36 HSV change score
        ↓
cut / accumulated motion selection
        ↓
multi-frame sheet
        ↓
vision model
```

公开 README 给出的主要设计点：

- 每帧变化检测约 0.2 ms 量级；
- 静止画面几乎不出图；
- scene change / accumulated motion 保留关键帧；
- 4–8 帧压到同一张图；
- Windows 优先 `ddagrab`，失败回退 `gdigrab`；
- 支持 screen / camera / file；
- 支持 region；
- 可做连续 watch；
- 可附音频/转写时间线；
- 核心包导出 `capture` / `pipeline` / `png` 等模块；
- README 明确说明包本体不必依赖 DSH 才能作为普通 Node 库使用。

### 对 XiaoYu 的启示

这是非常适合“直接吸收底层”的项目。

建议：

```
XiaoYu Vision Runtime
  ├─ dsh-see-now capture
  ├─ dsh-see-now pipeline
  ├─ local frame selection
  └─ XiaoYu-owned vision provider adapter
```

不要：

```
XiaoYu → DSH → dsh-see-now
```

因为那会重新引入第二个 agent host。

### 1.0 最小视觉范围

- explicit peek；
- bounded watch；
- region watch；
- scene/change trigger；
- independent vision provider；
- privacy indicator；
- no default long-term persistence of raw images。

### 特别值得保留的原则

**“先判断值不值得看，再决定是否调用视觉模型。”**

这比“每 N 秒全屏截图”更适合桌宠长期常驻。

---

## 3. Open-LLM-VTuber

Repository: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber

### 已验证能力

公开项目强调：

- hands-free voice；
- voice interruption；
- Live2D；
- desktop pet mode；
- visual perception；
- proactive speech；
- persistent chat history；
- broad LLM support；
- broad ASR/TTS support；
- modular agent interface；
- 部分版本/文档接 Letta 做长期记忆。

### 对 XiaoYu 的启示

最有价值的不是复制它的 Core，而是：

1. streaming TTS；
2. interruptible speech；
3. Live2D mouth/expression state；
4. backend/frontend 解耦；
5. LLM / ASR / TTS provider 全部可替换。

推荐直接借鉴 producer-consumer 音频思路：

```
LLM stream
   ↓
text segmenter
   ↓
TTS producer
   ↓
audio queue
   ↓
playback consumer
```

这样第一句可以先开口，不必等整段回答结束。

---

## 4. Letta / MemGPT 路线

Repository: https://github.com/letta-ai/letta

Letta 当前定位是 stateful agents with memory that can learn and improve over time，并提供跨 channel / SDK / server 的持久 agent。

### 对 XiaoYu 的启示

它证明了“长期 agent state 应该是独立于单次模型调用的第一等对象”。

这和 XiaoYu 的方向一致：

```
identity/memory truth
    !=
provider chat context
```

但 XiaoYu 不需要把 Core 迁到 Letta。

我们已经有：

- event provenance；
- canonical identity；
- human-confirmed persona；
- turn freshness；
- evaluation governance。

迁移只会增加宿主依赖。

---

## 5. LoCoMo

Paper: https://aclanthology.org/2024.acl-long.747/  
Project: https://snap-research.github.io/locomo/

### 关键事实

LoCoMo 专门评估 very long-term conversational memory，覆盖：

- QA；
- event summarization；
- multimodal dialog generation；
- single-hop；
- multi-hop；
- temporal；
- commonsense/world knowledge；
- adversarial。

原论文指出，long-context 和 RAG 虽然改善长期记忆表现，但仍显著落后人类，尤其 temporal / causal reasoning。

### 对 XiaoYu 的启示

XiaoYu 不能把“检索到了相关片段”当作记忆能力完成。

必须分别测：

```
authorized history
   ↓
retrieved evidence
   ↓
actual model input
   ↓
reasoning
   ↓
final answer
```

这与当前 H/R/P/W/A 拆分方向一致。

---

## 6. 2026 年最新 LoCoMo 方法学提醒

Paper: https://arxiv.org/abs/2611.19199  
Title: *What Moves a LoCoMo Score? Memory Context, Answer Prompts and Judges*

### 重要发现

该研究报告：

- 仅替换 judge，分数可移动最多约 7.2 points；
- 仅替换 answer prompt，最多约 9.3 points；
- 同一 memory system 在不同 answer model 下优势可能明显变化。

### 对 XiaoYu 的直接影响

这强烈支持当前 DECADE100 的做法：

- freeze prompt；
- freeze judge；
- freeze baseline layout；
- frozen manifest；
- paired comparison；
- source adjudication；
- held-out / prospective pool。

因此 DECADE100 不应为了“跑得更好看”中途改 judge 或 prompt。

---

## 7. LOCOMO-CONV

Paper: https://arxiv.org/abs/2609.03467  
Title: *When Users Don't Ask: Benchmarking Context-Driven Memory Retrieval in Conversational Agents*

### 关键发现

它把记忆评测从“直接问事实”扩展到：

- dialog；
- implicit；
- counterfactual；
- composed query。

报告指出：

- conversational framing 会暴露 QA benchmark 看不到的 retrieval gap；
- strong retrieval 不一定转化成 strong final response；
- implicit query 可能出现 silent grounding：记忆确实改善回答，但不会显式复述 gold fact。

### 对 XiaoYu 的启示

1. 未来不能只靠“你还记得 X 吗？”类问题；
2. 要测自然对话中是否正确利用旧记忆；
3. retrieval recall 和 final answer quality 必须分开；
4. DECADE100 之后建议保留一小组 conversational implicit regression，不需要再做大 benchmark。

---

## 8. MemoryAgentBench

Repository: https://github.com/HUST-AI-HYZ/MemoryAgentBench  
ICLR 2026.

它把 memory agent 能力拆成多个维度，包括：

- Accurate Retrieval；
- Test-Time Learning；
- Long-Range Understanding；
- Conflict Resolution。

### 对 XiaoYu 的启示

XiaoYu 记忆回归不应只测 recall。

1.0 后最值得增加的四个长期回归维度就是：

```
retrieval
learning/update
long-range understanding
conflict resolution
```

尤其 conflict resolution 与我们的人格/事实修正非常相关。

---

## 9. OSWorld

Paper: https://arxiv.org/abs/2404.07972  
Project: https://os-world.github.io/

OSWorld 提供真实 computer environment、跨 app、可执行结果验证。

### 对 XiaoYu 的启示

XiaoYu 1.0 不需要成为完整 computer-use agent。

但 Vision / Tool E2E 的测试方法应该借鉴 OSWorld：

**不要只验证模型“说它看见了什么”，要验证最终状态。**

例如：

- “下载完成告诉我” → 文件是否真的出现；
- “窗口变成完成状态告诉我” → UI 状态是否真的匹配；
- “看着安装过程” → 是否在正确变化后触发；
- region watch → 是否只受目标区域变化影响。

视觉能力应有 execution/state based tests，而不是只做截图 QA。

---

## 10. 外部调查后的总判断

### 现在不缺的

- 又一套 Agent framework；
- 又一套 provider abstraction；
- 又一套 memory database；
- 又一套 persona prompt；
- 又一套 tool host。

### 真正缺的

1. Core freeze；
2. longitudinal memory lifecycle；
3. product-grade proactive policy；
4. cheap continuous vision；
5. streaming voice；
6. real multi-surface E2E；
7. evaluation closure。

### 推荐吸收矩阵

| 外部项目 | 直接吸收 | 只参考 | 不吸收 |
|---|---|---|---|
| SurfCore | purpose gates / QQ UX ideas | memory decay / console / budget | DSH as identity host |
| dsh-see-now | capture / pipeline / change filtering | window / speech extras | DSH ownership |
| Open-LLM-VTuber | TTS queue / interruption patterns | Live2D UX / provider modularity | whole backend |
| Letta | stateful-agent principles | memory API concepts | replace XiaoYu Core |
| LoCoMo | evaluation dimensions | benchmark methodology | use score as sole release criterion |
| MemoryAgentBench | conflict / long-range test ideas | eval harness ideas | transplant system |
| OSWorld | execution-based eval style | task design | full computer-use scope in 1.0 |

---

## 11. Sources

### Projects

- SurfCore: https://github.com/Mieksido/surfcore
- SurfCore Architecture: https://github.com/Mieksido/surfcore/blob/main/docs/guides/ARCHITECTURE.md
- SurfCore License: https://github.com/Mieksido/surfcore/blob/main/LICENSE
- dsh-see-now: https://github.com/SAOS-3624/dsh-see-now
- Open-LLM-VTuber: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber
- Letta: https://github.com/letta-ai/letta
- MemoryAgentBench: https://github.com/HUST-AI-HYZ/MemoryAgentBench
- OSWorld: https://os-world.github.io/

### Papers

- LoCoMo / ACL 2024: https://aclanthology.org/2024.acl-long.747/
- What Moves a LoCoMo Score?: https://arxiv.org/abs/2611.19199
- LOCOMO-CONV: https://arxiv.org/abs/2609.03467
- OSWorld: https://arxiv.org/abs/2404.07972

### Source-quality note

部分 DSH 第三方索引站对 dsh-see-now 许可证显示过互相冲突的信息。本调查最终以**仓库当前 README、LICENSE 和 package.json**为准：三者均指向 Apache-2.0。
