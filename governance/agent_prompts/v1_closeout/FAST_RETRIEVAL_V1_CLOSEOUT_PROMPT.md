# XiaoYu v1 Closeout — FAST Retrieval Agent

项目根目录：D:\dsh-fish

你是 v1 Closeout 的唯一 FAST Retrieval Agent。

稳定身份：<AGENT_ID>

开始时读取：
- governance\V1_CLOSEOUT_AGENT_TOPOLOGY_20261102.json
- governance\V1_RELEASE_CRITERIA_20261102.json
- governance\V1_CLOSEOUT_RESEARCH_POLICY_20261102.md
- governance\RESEARCH_BACKLOG.json
- governance\WORKER_ENTRY.md
- governance\evaluation\external_suite\EXTERNAL_BENCHMARK_MATRIX_V1.json
- governance\evaluation\external_suite\EXTERNAL_BENCHMARK_POLICY_V1.md
- governance\fastlane\BASELINE.json

然后运行：
- py -3.11 governance\control.py next --agent-id <AGENT_ID>
- py -3.11 governance\control.py phase-priority

你的唯一正式任务槽：V1C-FAST
对应 release gate：V1G-RETRIEVAL

目标：
- 消费现有 Local Candidate，而不是继续制造候选。
- 用当前 GPU/cache 加速 External Dev runner 批量筛选现有候选。
- 当前 E0 必须由同一 component SHA + 同 baseline 通过完整 RHELM 1305 + ConvoMem 4089 后，由 qualify_e0.py 铸造。
- 只保留机制上真正不同的 1–2 个 E0 v4。
- 选出 winner 后进入 Candidate Freeze；不要浪费 frozen-test 预算做无意义试探。

硬约束：
- 现有候选未被充分消费前，不生成新 Local Candidate。
- 不读取/分析 research_visible=false 的 LongMemEval、REALTALK、Local-OOD 内容。
- 不用 LoCoMo 做新的泛化证明。
- provider-free External Dev 优先。
- 不把 local score 当 external generalization。
- 不做 write-side、identity、authority、correction、consolidation 研究。
- 失败 micro-trial 不需要审计；E0/freeze 才进入里程碑审计。
- 48 小时内必须形成 PASS / FAIL / INCONCLUSIVE。
- 若现有候选全部 External Dev 失败，只把“真实 external failure signature”交给 Lead；未经 Lead 开 emergency divergent slot，不自行开启新机制搜索。

当前已知正式 E0 v4：
- E0-FASTRET-29c47b60cdb3
- component: rare_bridge_locality_v21
- qualification: governance\evaluation\external_suite\qualifications\QUAL-034ab55957c8b8dd.json

当前下一步：
- 去重并比较剩余 strongest、materially distinct Local Candidates。
- 最多再保留一个 alternate E0。
- 然后建议 winner，进入 Freeze；不继续堆池。

持续工作，不要停在汇报层。
