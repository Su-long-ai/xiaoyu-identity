# Scientific Result vs Promotion Evidence Separation Policy

生效：2026-10-31

核心原则：预算、token cap、budget scope、调用 provenance、行政预注册字段等属于 promotion evidence qualification。它们可以使某次提交无法晋升，但不能单独证明科研假设是错的。

两个独立维度：
- scientific_outcome: POSITIVE | NEGATIVE | INCONCLUSIVE | NOT_TESTED
- promotion_evidence_status: VALID | INVALID_ADMINISTRATIVE | INCOMPLETE | NOT_APPLICABLE
- scientific_falsifier_observed: boolean

标签映射：
- LEAD_READY: 必须 POSITIVE + VALID + falsifier=false
- NONPASS: 必须 NEGATIVE + falsifier=true
- 正面结果 + 行政证据无效：保留为 EVIDENCE_ONLY / supporting evidence，必要时干净复验
- 实际资源成本只有在它本来就是预冻结评价指标时，才是工程证伪依据；行政 cap 不是科研 falsifier

R37 历史校正：
R37 两轮 32/32 是其冻结集合上的正面科学观察。该轮因 scope mismatch 和 26,525 > 25,000 raw tokens，promotion evidence 无效，但不能据此否定方向。更强的 lossless event-sequence 主张后来由 R40 的合规 prospective 29/32 x2、重复同三类 transient-history omission 科学证伪。因此历史应解释为：
R37 scientific positive / promotion invalid -> R40 clean scientific falsification of stronger claim。
