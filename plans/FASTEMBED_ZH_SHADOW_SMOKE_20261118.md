# FastEmbed Chinese semantic shadow smoke — 2026-11-18

Status: **SHADOW PASS / NOT PRODUCT-PROMOTED**

## Reused capability

- FastEmbed: 0.9.1
- Model: BAAI/bge-small-zh-v1.5
- Model role: read-side semantic ranking only
- XiaoYu authority role: unchanged
- Installation used for smoke: repository-external temporary Python 3.11 venv

The product branch does not require FastEmbed at import time. The adapter is lazy and
optional. R9 still filters CURRENT / principal / audience / context candidates before
the semantic ranker sees any document.

## Chinese semantic smoke

Frozen synthetic documents:

- coffee: 用户通常最喜欢喝手冲咖啡，偏好浅烘焙。
- oolong: 用户喜欢乌龙茶，尤其是凤凰单丛。
- project: 用户的小鱼项目目标是在十二月前完成。
- city: 用户更偏好上海的工作机会。

Observed rank-1 results:

| Query | Rank 1 |
| --- | --- |
| 我平时最喜欢喝什么咖啡？ | coffee |
| 我爱喝什么茶？ | oolong |
| 小鱼项目什么时候想做完？ | project |
| 找工作更想去哪里？ | city |

All 4/4 smoke queries ranked the intended document first.

## Warm latency probe

100 candidate documents, same local CPU process, model already loaded:

- runs: 5
- milliseconds: 97.87, 98.88, 99.95, 99.61, 99.07
- median: **99.07 ms**
- persistent vector cache/store: **none**

Interpretation: this is small enough for shadow evaluation. It does not prove scaling
or product quality, and it does not justify adding another vector database yet.

## Lexical path

The product-side candidate ranker now uses SQLite FTS5 instead of XiaoYu-maintained
character/bigram overlap postings:

- unicode61 FTS5 for English/alphanumeric terms
- SQLite trigram FTS5 for Chinese phrase candidates
- RRF combines lexical sources
- recency remains only a deterministic tail fallback

## Safety boundary

- semantic rankers only receive candidates already admitted by R9 read filters
- unknown fact IDs returned by an external ranker are discarded
- semantic failure degrades to FTS5
- no semantic component can create/correct/delete a fact
- no semantic component can widen audience/principal/context

## Promotion gate

Do **not** enable FastEmbed as the default semantic ranker from this smoke.

Next promotion evidence must be a fixed paired retrieval evaluation against the
current product retriever, measuring at least:

- evidence completeness
- multi-hop completeness
- final answer delta with frozen answerer
- stale/deleted injection rate
- context token cost
- retrieval latency

If the paired result is not globally positive, retain FTS5 and keep the semantic
component shadow-only.
