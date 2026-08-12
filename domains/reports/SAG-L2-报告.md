# SAG-Lite L2 Event-Entity 索引 + 混合检索

> 完成时间: 2026-06-30 20:38

## L2 交付

| 交付物 | 路径 | 规模 |
|--------|------|------|
| `sag_hybrid.py` | `SAG-poc/sag_hybrid.py` | 115 行, 独立模块 |
| `entities_v2` 表 | `sag_lite.db` | 63K entities (4类型) |
| `entity_edges` 表 | `sag_lite.db` | 165K 关系边 |
| 混合检索函数 | `hybrid_search()` | Entity-exact + Entity-hop |

## Entity 覆盖

| 类型 | 唯一值 | 记录数 |
|------|--------|--------|
| signal (DI/DO/RI/RO) | 2,704 | 20,390 |
| manual (B-8xxxx) | 231 | 33,338 |
| alarm_code (SRVO-xxx) | 470 | 4,379 |
| model_num (R-30iB等) | 188 | 4,745 |

## 混合检索性能

| 查询 | 结果 | 耗时 | 方法 |
|------|------|------|------|
| SRVO-066 + DI425 | 5 | 0.012s | exact-match + entity-hop |
| SRVO-062 + SRVO-075 | 4 | 0.008s | exact + hop (→B-83284CM) |
| R-30iB + SRVO-050 | 3 | 0.002s | exact + hop |

## 对飞轮缺陷的修复

| 飞轮发现 | 修复 |
|---------|------|
| 变量/IO混淆 (F01/F02) | signal entity 精确匹配 DI[n]/DO[n]，与 alarm entity 通过 entity-hop 关联 |
| 跨文档归纳弱 (C01/C03 60%) | entity-hop 自动发现 SRVO-062→B-83284CM 等跨文档关联 |
| 混入其他答案 | entity-exact 精确匹配，不依赖语义相似度 |

## 与现有 RAG 集成点

```python
# 替换 rag_core.retrieve() 的检索阶段
from sag_hybrid import hybrid_search as entity_search

def enhanced_retrieve(query, top_k=10):
    # 1. SAG entity 精确匹配
    entity_results = entity_search(query, top_k=5)
    # 2. 向量语义检索 (补充)
    vector_results = rag_core.retrieve(query, top_k=5)
    # 3. 合并去重, entity 结果优先
    return merge_results(entity_results, vector_results)
```
