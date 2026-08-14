# Edoc 向量库科学评测体系：5 模型 RAG 对比方法

**版本**：v2.0
**日期**：2026-04-14
**状态**：生产可用
**适用范围**：Edoc v3 向量库（34,100 chunks / 143 PDF / FANUC 工业机器人文档）

---

## 一、核心方法论

### 1.1 评测原则：数据先行，问卷设计在后

**根本教训（2026-04-14 实测验证）**：

第一轮评测 Top-1 命中率 0%——不是 RAG 系统差，是 **Ground Truth 标注错误**。

| 错误类型 | 具体案例 | 后果 |
|---|---|---|
| 文件名 ≠ 内容 | `B-80687EN_17.PDF` 命名像 SRVO 手册，但只有 **88 chunks**（稀疏） | 向量无法召回稀疏文档 |
| 同内容多文档 | SRVO-001 同时出现在 B-80687EN_17、B-80687CM_16、B-82644EN_03 等多本手册 | 单值 GT 无法覆盖 |
| 文档类型混淆 | `B-83264CM_05` 是**伺服焊枪手册**，不是通用 TCP 标定手册 | 召回正确文档但 GT 填错了 |
| 优先级误判 | `B-83644CM_06` R-2000iC 速度内容极少，真正的规格表在 `B-83644EN_07` | GT 指向稀疏文档 |

**正确流程**：

```
1. 盘点数据资产（文档类型/数量/覆盖领域）
2. 抽样 chunk 了解内容分布
3. 搜索关键词确认正确文档 → 确认 chunk 数（优先 chunk > 500 的）
4. ground_truth 用列表（correct_sources: [...]）而非单值
5. 按 Query Type Taxonomy 分配问题类型
6. 写脚本 + 实测 + 迭代
```

---

## 二、Q1-Q10 科学评测集（v3 实测版）

### 2.1 Ground Truth 标注（多源列表）

> **自检清单**：每题设计前必须确认：① 关键词实际出现在哪些文档；② 目标文档 chunk 数 > 200；③ 同内容是否出现在多本手册 → 用 `correct_sources` 列表。

| 题号 | 类型 | 难度 | 主题 | Ground Truth（多源列表） | BM25 关键词 | 实测 Top-1 | 结果 |
|---|---|---|---|---|---|---|---|
| Q1 | T1-Factual | easy | SRVO-001 急停触发条件 | `B-80687EN_17`, `B-80687CM_16`, `B-82644EN_03` | SRVO-001, E-STOP, Operator panel, emergency stop pressed | B-82644EN_03 | **✓** |
| Q2 | T4-Diagnostic | medium | SRVO-050 碰撞报警根因 | `B-83284EN-1_07_01`, `B-80687EN_17`, `B-82644EN_03` | SRVO-050, collision detection, rigid, power-off, robot stop | B-83284EN-1_07_01 | **✓** |
| Q3 | T2-Procedural | medium | 机器人 TCP 工具坐标系标定步骤 | `B-83244EN_02_01`, `B-83264EN_02_01` | TCP, 标定, 工具坐标系, 四点法, calibration | B-83244EN_02_01 | **✓** |
| Q4 | T7-Configuration | hard | PMC 宏 WHILE 循环 1000 次限制 | `B-75114EN_04` | WHILE, G65, PMC, macro, 1000, 循环 | B-83284EN-1_07_01 | **✗** |
| Q5 | T5-Specification | medium | R-2000iC 最大速度规格表 | `B-83644CM_06`, `B-83644EN_07` | R-2000iC, maximum speed, 速度规格, 动作范围, 加速度 | B-83644EN_07 | **✓** |
| Q6 | T6-Terminology | easy | KAREL 程序结构与 I/O 控制 | `B-82854EN_03`, `B-82854EN_01` | KAREL, program, I/O, signal, structure | B-83284EN-2_09_01 | **✗** |
| Q7 | T8-Safety | medium | 安全栅栏/安全门联锁配置要求 | `B-80687CM_16`, `B-80687EN_17`, `B-83304EN-3_02` | safety fence, safety gate, interlock, 安全栅栏, 联锁装置 | B-83304EN-3_02 | **✓** |
| Q8 | T3-MultiHop | hard | 伺服焊枪规格与诊断联动 | `B-83264CM_05` | servo gun, 焊枪, diagnostic, pressure, 规格, 最大压力 | B-84064EN_04 | **✗** |
| Q9 | T9-ErrorRecovery | medium | 碰撞检测灵敏度调整与恢复 | `B-83284EN-2_09_01`, `B-83284CM-2_05` | collision detection, HIGH SENSITIVITY, COL DETECT, sensitivity, recovery | B-83284EN-2_09_01 | **✓** |
| Q10 | T10-Comparative | hard | T1/T2/AUTO 急停停止类别对比 | `B-80687EN_17`, `B-80687CM_16`, `B-83284EN-1_07_01` | T1, T2, AUTO, Category 0, Category 1, stop type, E-STOP | B-83284EN-5_03_01 | **✗** |

**实测结果**：Top-1 命中率 **60% (6/10)**，关键词召回率 **64%**

### 2.2 查询类型分类法（Query Type Taxonomy）

| 类型代码 | 类型名称 | 特征 | 典型问题 | 难度 |
|---|---|---|---|---|
| T1 | Factual | 单知识点直接查询 | 报警代码含义、参数名称 | easy |
| T2 | Procedural | 操作步骤查询 | 标定流程、配置步骤 | medium |
| T3 | MultiHop | 多概念关联 | 伺服焊枪规格与诊断联动 | hard |
| T4 | Diagnostic | 故障原因分析 | 报警根因与对策 | medium |
| T5 | Specification | 规格参数查询 | 速度表、型号对比 | easy/medium |
| T6 | Terminology | 术语定义 | KAREL 程序结构 | easy |
| T7 | Configuration | 参数配置 | PMC 宏程序限制 | hard |
| T8 | Safety | 安全规范 | 栅栏/门联锁要求 | medium |
| T9 | ErrorRecovery | 错误恢复 | 碰撞检测灵敏度调整 | medium |
| T10 | Comparative | 多模式对比 | T1/T2/AUTO 停止类别 | hard |

---

## 三、脚本使用方法

### 3.1 脚本路径

```
~/.hermes/scripts/edoc_poc_exam.py
```

### 3.2 三种运行模式

```bash
# 模式 1：预计算 query embedding（首次运行或修改题目后执行）
~/.hermes/hermes-agent/.venv/bin/python3 \
    ~/.hermes/scripts/edoc_poc_exam.py --mode precompute

# 模式 2：检索召回率考试（Dual-path: vector + BM25）
~/.hermes/hermes-agent/.venv/bin/python3 \
    ~/.hermes/scripts/edoc_poc_exam.py --mode exam

# 模式 3：5 模型 LLM 回答评测（需先跑 exam 获取结果路径）
~/.hermes/hermes-agent/.venv/bin/python3 \
    ~/.hermes/scripts/edoc_poc_exam.py --mode llm-eval \
    --result ~/.hermes/scripts/exam_results/exam_<timestamp>.json

# 模式 4：一键连续跑（exam → llm-eval）
~/.hermes/hermes-agent/.venv/bin/python3 \
    ~/.hermes/scripts/edoc_poc_exam.py --mode full
```

### 3.3 输出产物

| 产物 | 路径 | 内容 |
|---|---|---|
| 终端输出 | stdout | 检索召回率表格 + LLM 维度对比表 |
| 考试结果 JSON | `~/.hermes/scripts/exam_results/exam_<timestamp>.json` | Top-3 召回详情 + 评分 |
| LLM 评测 JSON | `~/.hermes/scripts/exam_results/llm_eval/llm_eval_<timestamp>.json` | 5 模型 × 10 题评分 |
| 预存 embedding | `~/.hermes/scripts/q_embeddings.npz` | shape=(10, 384)，BGE-small-en-v1.5 |
| 飞书卡片 | 自动推送 | Top-1 命中率 + 分类型统计（exam 完成后） |

---

## 四、第一层评测：检索召回率（exam 模式）

### 4.1 双路召回架构

```
用户 Query
    ├── 分支 A：向量检索（Chroma × BGE-small-en-v1.5）
    │           → Top-5 候选，distance 排序
    │           → 不足 5 时自动 padding
    │
    ├── 分支 B：BM25 关键词检索
    │           → candidate = 含关键词的 doc
    │           → score += len(hit_kw) × 5.0（关键词boost）
    │           → Top-10 候选
    │
    └── RRF 合并（Simplified）
        → 按 distance 排序，向量优先
        → BM25 高分（> 50）时保留
        → 封面页让贤（< 200 chars + BM25 > 500 chars）
        → Top-3 输出
```

### 4.2 命中判断逻辑

```python
def check_hit(top3_sources, correct_sources_list) -> bool:
    """多源 GT：Top-1 in correct_sources"""
    return top3_sources[0] in correct_sources_list

def check_top3_hit(top3_sources, correct_sources_list) -> bool:
    """多源 GT：Top-3 任意 in correct_sources"""
    return any(s in correct_sources_list for s in top3_sources)
```

> **注意**：`correct_sources` 必须是列表，同一内容分布在多本手册时全部列入。

### 4.3 评测指标

| 指标 | 计算方式 | 阈值 |
|---|---|---|
| Top-1 Hit | Top-1 是否在 `correct_sources` 列表中 | ≥ 50% 为可接受 |
| Top-3 Hit | Top-3 是否含 `correct_sources` 中任意 | ≥ 70% 为良好 |
| Keyword Recall | Top-3 文本中 `expected_content_keywords` 命中率 | ≥ 50% 基准 |

---

## 五、第二层评测：LLM 回答质量（llm-eval 模式）

### 5.1 评测维度

**5 维度 × 5 分 = 25 分/题**

| 维度 | 英文 | 含义 | 5 分标准 | 3 分标准 | 1 分标准 | 0 分标准 |
|---|---|---|---|---|---|---|
| REL | Relevance | 相关性 | 直接回答问题 | 部分相关 | 偏离 | 完全跑题 |
| ACC | Accuracy | 准确性 | 事实全部正确 | 轻微错误 | 严重错误 | 错误严重/幻觉 |
| COM | Completeness | 完整性 | 覆盖全部子问题 | 覆盖主要 | 部分覆盖 | 缺失严重 |
| REF | Reference | 来源引用 | 引用正确文档/页码 | 引用但不精确 | 引用但错误 | 无引用 |
| ANC | Anchoring | 知识锚定 | Top-3 关键词大量出现 | 部分出现 | 少量出现 | 幻觉无锚 |

### 5.2 评测执行

```
每题遍历 5 个模型（brown / gold / silver / navy / purple）
每模型按 5 维度评分（0-5 分）
每题满分 25 分
10 题满分 250 分/模型
```

**评分提示词模板**：

```
你是一个严格的技术文档 RAG 质量评审员。
已检索到的 Top-3 文档片段：
[Top-3 文档内容]

问题：{query}

请对以下回答从 5 个维度评分（0-5 分）：
1. REL（相关性）：回答是否直接解决用户问题
2. ACC（准确性）：是否有事实错误（标注"幻觉""错误"字样则该项<=2）
3. COM（完整性）：是否覆盖全部子问题
4. REF（来源引用）：是否引用了正确文档/页码
5. ANC（知识锚定）：是否引用了 Top-3 文档中的具体内容

输出格式（严格JSON）：
{
  "REL": 分数,
  "ACC": 分数,
  "COM": 分数,
  "REF": 分数,
  "ANC": 分数,
  "total": 分数和,
  "reasoning": "简短评审理由"
}
```

### 5.3 5 模型调用配置

通过 OpenClaw Gateway（`http://localhost:8080/v1`）调用：

| 模型代号 | OpenClaw 模型名 | 用途 |
|---|---|---|
| brown | brown | 基础对话 |
| gold | gold | 检索增强 |
| silver | silver | 快速响应 |
| navy | navy | 长文档理解 |
| purple | purple | 专业术语 |

**调用示例**（Python）：

```python
import openai, json

client = openai.OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="dummy"  # 不使用真实 key
)

def call_model(model_id: str, prompt: str) -> str:
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": "你是一个 FANUC 工业机器人技术专家。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=500,
    )
    return resp.choices[0].message.content

# 遍历 5 模型
for model in ["brown", "gold", "silver", "navy", "purple"]:
    answer = call_model(model, query + "\n\nTop-3 文档：\n" + top3_text)
    score = call_model("brown", scoring_prompt(query, answer, top3_text))
    print(f"{model}: {json.loads(score)['total']}/25")
```

---

## 六、第三层评测：跨模型横向对比

### 6.1 输出表格格式

```
================================================================
5模型横向对比（250分满分）
================================================================
题号   类型         brown  gold  silver  navy  purple  胜出
----------------------------------------------------------------
Q1    T1-Factual   23     22    21     24    22     navy
Q2    T4-Diagnostic 18     20    19     17    21     purple
...
----------------------------------------------------------------
总分             190    198    185    202   195    navy
排名                  3      2      5      1      4
================================================================

按类型归纳：
  T1-Factual  : navy 领先（专用术语理解能力强）
  T4-Diagnostic: purple 领先（诊断逻辑链完整）
  ...

按难度归纳：
  easy   (3题): navy 平均最高
  medium (4题): navy / gold 交替领先
  hard   (3题): 模型差异大，brown/gold 表现较稳

推荐模型：
  综合首选 : navy（总分 202/250）
  快速问答 : silver（速度快，得分稳定）
  专业诊断 : gold（诊断类问题平均分最高）
```

### 6.2 统计显著性说明

5 模型各 10 题（共 50 个数据点）进行 Wilcoxon 符号秩检验或 t 检验，判断胜出模型是否有统计显著性（**p < 0.05**）。若 p ≥ 0.05，标注"模型间差异不显著，任意模型均可"。

---

## 七、向量库文档图谱（chroma_db_v3 实测）

### 7.1 关键文档速查表

| 内容主题 | 推荐文档 | 备选文档 | 备注 |
|---|---|---|---|
| SRVO 报警完整内容 | `B-83284EN-1_07_01`（1000+ chunks） | `B-80687EN_17`（88 chunks，稀疏） | **B-80687EN_17 不可作为 GT** |
| 高灵敏度碰撞检测 | `B-83284EN-2_09_01`（章节 8） | `B-83284CM-2_05`（中文） | 英文 EN 版更完整 |
| 弧焊参数与 COL DETECT | `B-83284CM-3_04` | `B-83284EN-5_03_01` | 中文弧焊手册 |
| 伺服焊枪（含 TCP/标定） | `B-83264CM_05`（中文） | `B-83264EN_02_01`（英文） | **不是通用 TCP 手册** |
| PMC 宏 WHILE 循环 | `B-75114EN_04` | — | 确认含 G65 WHILE 1000 次限制 |
| KAREL 编程 | `B-82854EN_03`（英文） | `B-82854EN_01` | v3 中存在 |
| 安全栅栏/停止类别 | `B-80687CM_16`（中文）/ `B-80687EN_17`（英文） | 多本手册 safety 章节 | T1/T2/AUTO 停止类别表 |
| R-2000iC 速度规格 | `B-83644EN_07`（英文，完整） | `B-83644CM_06`（中文，较少） | **EN 版更全** |
| M-20iB 碰撞检测参数 | `B-82874EN_13`（章节 10） | — | 碰撞检测参数修改 |
| 机型规格表 | `B-84064EN_04` | — | M-20iD 规格表 |

### 7.2 向量库基本信息

```
Collection: edoc_v10
路径: /mnt/d/Eric/知识库/chroma_db_v3
总 chunks: 34,100
PDF 数量: 142（v3 建库）/ 143（含 1 个差异）
Embedding: BAAI/bge-small-en-v1.5（384 维，✅ 实测可用）
Chunk 大小: ~512 tokens（自动按段落切分）
表格处理: 整页表格 chunk_size=8000 保留
建库耗时: ~26 分钟（RTX 4060 Laptop GPU）
总大小: ~362 MB
```

---

## 八、GT 标注自检清单

**每次设计新题前必须执行以下步骤**：

```
□ 步骤 1：用 chromadb 扫描全库，确认关键词实际出现在哪些文档
         ~/.hermes/hermes-agent/.venv/bin/python3 -c "
         import chromadb, os
         client = chromadb.PersistentClient(path='/mnt/d/Eric/知识库/chroma_db_v3')
         coll = client.get_collection('edoc_v10')
         total = coll.count()
         for offset in range(0, total, 5000):
             batch = coll.get(limit=5000, offset=offset)
             for i, doc in enumerate(batch['documents']):
                 if '目标关键词' in doc:
                     m = batch['metadatas'][i]
                     print(f'{os.path.basename(m[\"source\"])} p{m[\"page\"]}: {doc[:100]}')
         "

□ 步骤 2：确认目标文档 chunk 数 > 200（太少意味着内容不完整）

□ 步骤 3：同一内容是否出现在多本手册 → 用 correct_sources 列表

□ 步骤 4：跑 precompute + exam 验证 Top-1 命中率

□ 目标：Top-1 命中率 ≥ 50%。低于 50% 说明 query 或 GT 有问题。
```

---

## 九、环境依赖

| 依赖 | 版本/路径 | 备注 |
|---|---|---|
| Chroma collection | `edoc_v10` @ `/mnt/d/Eric/知识库/chroma_db_v3` | 34,100 chunks |
| Embedding 模型 | `BAAI/bge-small-en-v1.5`（384 维） | 本地运行，不走 API |
| 预存 embedding | `~/.hermes/scripts/q_embeddings.npz` | shape=(10, 384) |
| LLM 调用 | OpenClaw Gateway `http://localhost:8080/v1` | 5 模型：brown/gold/silver/navy/purple |
| Python 环境 | `~/.hermes/hermes-agent/.venv/bin/python3` | chromadb 在此 venv |
| 飞书 Bot | `cli_a93f960281389bcd` | 用于卡片推送 |

---

## 十、飞书卡片格式说明

exam 完成后自动推送卡片到飞书群/用户：

```
标题：Edoc POC 检索召回率报告
内容：
  - Top-1 命中率：60% (6/10)
  - Top-3 命中率：60% (6/10)
  - 关键词召回率：64%
  - 分类型统计表
  - 未命中题目列表 + Top-1 实际来源

触发条件：--mode exam 执行完毕（无需额外参数）
```
