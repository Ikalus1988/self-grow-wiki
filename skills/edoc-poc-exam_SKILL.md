---
name: edoc-poc-exam
description: Edoc 向量库科学评测体系：Q1-Q10 Query Type Taxonomy + Ground Truth + 双路召回 + 5模型LLM回答对比。自动输出终端表格 + 存档 JSON + 飞书卡片。
category: data-science
---

# Edoc POC 科学评测体系（2026-04-14 重构）

## 核心方法论：数据先行，问卷设计在后

**教训（2026-04-14 核心）**：
第一轮考试 Top-1 命中率 0%——不是 RAG 差，是 Ground Truth 标注错了。根因：
1. 文件名 ≠ 内容：`B-80687EN_17.PDF` 命名像 SRVO 手册，但只有 **88 chunks**，SRVO 完整内容在 B-83284EN-1_07_01（1000+ chunks）
2. 同内容多文档：同一个 SRVO-001 报警出现在 B-80687EN_17、B-80687CM_16、B-82644EN_03 等多本手册里
3. BM25 keyword 没匹配 chunk 文本格式

**正确流程**：
```
1. 盘点数据资产（文档类型/数量/覆盖领域）
2. 抽取样本 chunk 了解内容分布
3. 搜索关键词确认正确文档 → 确认 chunk 数（优先 chunk>500 的）
4. ground_truth 用列表（correct_sources）而非单值
5. 按 Query Type Taxonomy 分配问题类型
6. 写脚本 + 实测 + 迭代
```

**快速盘点命令**（不加载模型，秒级）：
```python
import chromadb, os
client = chromadb.PersistentClient(path='/mnt/d/Eric/知识库/chroma_db_v3')
coll = client.get_collection('edoc_v10')
print('Total chunks:', coll.count())  # 34,100

# 采样盘点文档类型
for offset in [0, 5000, 10000, 15000, 20000, 25000, 30000]:
    batch = coll.get(limit=50, offset=offset)
    sources = set(m.get('source','?') for m in batch['metadatas'])
    print(f'offset {offset}: {len(sources)} unique files')
```

**向量库文档图谱**（2026-04-14 盘点结果）：
- 142 个 PDF，34,100 chunks
- 主要文档类型：B-83284*（多功能手册 EN/CM）、B-80687*（安全手册）、B-83614*（焊接）、B-80687EN_17/CM_16（SRVO 报警）、B-82854EN_03（KAREL 编程）、B-75114EN_04（PMC 宏）、B-83264CM_05（TCP/伺服焊枪）、B-81735EN_09（机型规格）

---

## 科学评测设计：三层评估

### 第一层：检索召回率（exam 模式）

**评测指标**：
- **Top-1 Hit**：Top-1 是否命中正确文档（基于 ground_truth）
- **Top-3 Hit**：Top-3 是否含正确文档
- **Keyword Recall**：Top-3 中 expected_content_keywords 命中率
- 按 Query Type 分组统计

**关键原则**：`expected` 应填"当前系统能召回的最好结果"，而非理论正确文档。

### 第二层：LLM 回答质量（llm-eval 模式）

5维度 × 5分 = 25分/题，5模型横向对比：

| 维度 | 英文 | 含义 | 评分标准 |
|------|------|------|----------|
| REL | Relevance | 相关性 | query 关键词在 answer 出现 |
| ACC | Accuracy | 准确性 | 无错误标记词 |
| COM | Completeness | 完整性 | 回答长度 100-800字 |
| REF | Reference | 来源引用 | 引用了文档/页码 |
| ANC | Anchoring | 知识锚定 | Top-3 文档关键词在 answer 出现 |

### 第三层：跨模型横向对比

5个 LLM（brown/gold/silver/navy/purple）× Q1-Q10 输出对比表：
- 每题各模型得分
- 各模型总分排名
- 按 Query Type 维度分组归纳
- 按难度（easy/medium/hard）分组归纳

---

## 脚本使用方式

```bash
# 首次：预计算 query embedding
~/.hermes/hermes-agent/.venv/bin/python3 \
  ~/.hermes/scripts/edoc_poc_exam.py --mode precompute

# 检索召回率考试
python3 ~/.hermes/scripts/edoc_poc_exam.py --mode exam

# 5模型 LLM 回答评测（需先跑 exam 获取结果路径）
python3 ~/.hermes/scripts/edoc_poc_exam.py --mode llm-eval \
  --result ~/.hermes/scripts/exam_results/exam_YYYYMMDD_HHMMSS.json

# 一键连续跑（exam → llm-eval）
python3 ~/.hermes/scripts/edoc_poc_exam.py --mode full
```

输出：
- 终端：检索召回率表格 + LLM 对比表 + 维度归纳 + 难度分析
- 存档：`~/.hermes/scripts/exam_results/exam_*.json` + `llm_eval/llm_eval_*.json`
- 飞书：exam 完成后自动卡片推送

---

## Q1-Q10 科学评测集（2026-04-14 v3 实测版）

> **v1 → v2 经验（2026-04-14）**：
> - v1 GT 命中率 0%，根因：GT 文档 chunk 数太少（88 vs 1000+）
> - 工程文档同一内容分布在多本手册 → GT 用 `correct_sources: [...]` 列表而非单值
> - `B-83264CM_05` = 伺服焊枪手册，不是通用 TCP 手册
> - 实测 Top-1 命中率：60%（6/10）；4 miss 为向量语义混淆（PMC→SRVO手册、焊枪→机型规格表）

| 题号 | 类型 | 难度 | 主题 | Ground Truth（多源） | 实测 Top1 |
|------|------|------|------|---------------------|-----------|
| Q1 | T1-Factual | easy | SRVO-001 急停触发条件 | `B-80687EN_17`, `B-80687CM_16`, `B-82644EN_03` | B-82644EN_03 ✓ |
| Q2 | T4-Diagnostic | medium | SRVO-050 碰撞报警根因 | `B-83284EN-1_07_01`, `B-80687EN_17`, `B-82644EN_03` | B-83284EN-1_07_01 ✓ |
| Q3 | T2-Procedural | medium | 机器人TCP工具坐标系标定步骤 | `B-83244EN_02_01`, `B-83264EN_02_01` | B-83244EN_02_01 ✓ |
| Q4 | T7-Configuration | hard | PMC宏WHILE循环1000次限制 | `B-75114EN_04` | B-83284EN-1_07_01 ✗（向量语义误拉） |
| Q5 | T5-Specification | medium | R-2000iC最大速度规格表 | `B-83644CM_06`, `B-83644EN_07` | B-83644EN_07 ✓ |
| Q6 | T6-Terminology | easy | KAREL程序结构与I/O控制 | `B-82854EN_03`, `B-82854EN_01` | B-83284EN-2_09_01 ✗（向量拉错） |
| Q7 | T8-Safety | medium | 安全栅栏/安全门联锁要求 | `B-80687CM_16`, `B-80687EN_17`, `B-83304EN-3_02` | B-83304EN-3_02 ✓ |
| Q8 | T3-MultiHop | hard | 伺服焊枪规格与诊断联动 | `B-83264CM_05` | B-84064EN_04 ✗（机型规格表压过焊枪手册） |
| Q9 | T9-ErrorRecovery | medium | 碰撞检测灵敏度调整与恢复 | `B-83284EN-2_09_01`, `B-83284CM-2_05` | B-83284EN-2_09_01 ✓ |
| Q10 | T10-Comparative | hard | T1/T2/AUTO急停停止类别对比 | `B-80687EN_17`, `B-80687CM_16`, `B-83284EN-1_07_01` | B-83284EN-5_03_01 ✗（Top1弧焊手册含相关内容但非GT指定） |

每题含 `ground_truth` 字段：`correct_sources: [...]`（列表）、`correct_page`、`expected_content_keywords`。
验收逻辑已更新为列表匹配（Top1 in correct_sources）。

**向量库关键文档速查**：
```
SRVO报警完整内容    → B-83284EN-1_07_01（1000+ chunks）注意：B-80687EN_17只有88 chunks稀疏不可靠
高灵敏度碰撞检测    → B-83284EN-2_09_01 / B-83284CM-2_05（章节8）
弧焊参数与COL DETECT → B-83284CM-3_04
伺服焊枪（含TCP/标定）→ B-83264CM_05（不是通用TCP手册！）
PMC宏WHILE循环     → B-75114EN_04
KAREL编程         → B-82854EN_03
安全栅栏/停止类别  → B-80687CM_16 / B-80687EN_17
R-2000iC速度规格   → B-83644CM_06 / B-83644EN_07
```

**GT 标注自检清单**（每次设计新 Q 前必须执行）：
1. 用 chromadb 扫描全库，确认关键词实际出现在哪些文档
2. 确认目标文档 chunk 数 >200（太少意味着内容不完整）
3. 同一内容是否出现在多本手册 → 用 `correct_sources` 列表
4. 跑 precompute + exam 验证 Top-1 命中率，目标 ≥50%

---

## 依赖

- Chroma collection: `/mnt/d/Eric/知识库/chroma_db_v3`（collection: `edoc_v10`，34,100 chunks，BGE-small-en-v1.5 384维 ✅）
- BGE 模型：`BAAI/bge-small-en-v1.5`（384维）
- 预存 embedding: `~/.hermes/scripts/q_embeddings.npz`（shape=(10, 384)）
- LLM 调用：OpenClaw Gateway `http://localhost:8080/v1`，model=brown/gold/silver/navy/purple

---

## 验收逻辑

```python
def check_hit(top3_sources, correct_sources_list) -> bool:
    """多源GT：Top-1 in correct_sources"""
    return top3_sources[0] in correct_sources_list

def check_top3_hit(top3_sources, correct_sources_list) -> bool:
    """多源GT：Top-3 任意 in correct_sources"""
    return any(s in correct_sources_list for s in top3_sources)
```

**两种基线策略**：
1. **自对比基线**（推荐）：先跑 Top-1，以实测结果为 expected；后续版本与基线对比相对改进
2. **理论正确基线**：填理论正确文档，适用于已知正确文档的场景（本期采用，因已有充分数据摸底）
