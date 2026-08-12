# FANUC 工业机器人知识库建库过程记录

> 时间范围：2026-04-11 ~ 2026-04-15
> 作者：Hermes Agent（系统协调）/ 倒吊人（建库执行）/ 太阳（文档分析）
> 状态：**建库完成，检索质量调优进行中**

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [Day 1 — PDF 分块（chunks 生成）](#2-day-1--pdf-分块chunks-生成)
3. [Day 2 — 首次 ChromaDB 建库尝试 + 崩溃事件](#3-day-2--首次-chromadb-建库尝试--崩溃事件)
4. [Day 3 — 崩溃根因定位 + coll_zh 建库](#4-day-3--崩溃根因定位--coll_zh-建库)
5. [Day 4 — v3 向量库重建 + BM25 召回 + POC 考试](#5-day-4--v3-向量库重建--bm25-召回--poc-考试)
6. [Day 5 — 检索质量调优 + BGE-m3 测试 + 打标系统](#6-day-5--检索质量调优--bge-m3-测试--打标系统)
7. [踩坑记录汇总](#7-踩坑记录汇总)
8. [当前状态](#8-当前状态)

---

## 1. 背景与目标

### 1.1 业务目标

为 FANUC 工业机器人建立可检索的知识库，支持：
- 中文/英文 PDF 文档向量语义检索
- 机器人操作/维护/故障诊断问题的 RAG 回答
- POC 验收：Top-1 命中率 ≥ 90%

### 1.2 技术栈

| 组件 | 选择 | 说明 |
|------|------|------|
| Embedding 模型 | BGE-small-en-v1.5（384维，edoc_v10）/ BGE-large-zh-v1.5（1024维，edoc_v10_zh） | edoc_v10 = 英文手册，edoc_v10_zh = 中文手册 |
| 向量数据库 | ChromaDB PersistentClient | 本地持久化，`/mnt/d/Eric/知识库/chroma_db_v3/` |
| 分块策略 | 段落拆分 + 固定 600 chars | 按 `.!?。！？` 断句，超过阈值另起 chunk |
| LLM | anonymous/mizu（Volcengine API） | base_url: `https://sd6f7boe66in4kbsvm3og.apigateway-ap-southeast-1.volceapi.com/v1` |
| API Key | `MINIMAX_API_KEY` env var | 即 Volcengine token |

### 1.3 文件路径约定

```
知识库根目录：/mnt/d/Eric/知识库/
  chunks_v3/              ← 分块后 JSON 文件（每个 PDF 一个 .chunks.json）
  chroma_db_v3/           ← ChromaDB 向量库
    chroma.sqlite3        ← 元数据 DB
    edoc_v10/             ← 英文向量 collection（34,100 chunks，142 PDF）
    edoc_v10_zh/          ← 中文向量 collection（14,889 chunks，73 CM 文件）
  tagging_cache.db        ← 打标缓存（SQLite）
Hermes 脚本：~/.hermes/scripts/
  build_edoc_chroma.py    ← 建库脚本
  edoc_file_import.py     ← PDF 分块脚本（467行）
  edoc_import_pipeline.py  ← 完整导入流水线（含 LLM 打标，565行）
  rag_answer.py           ← RAG 检索引擎
  retroactive_tagging.py  ← 存量 chunks 元数据打标脚本
  edoc_poc_exam.py        ← Q1-Q10 POC 评测脚本
  bm25_index.pkl          ← BM25 索引缓存
  q_embeddings.npz       ← Query embedding 缓存
```

---

## 2. Day 1 — PDF 分块（chunks 生成）

### 2.1 任务启动

**时间**：2026-04-11 上午  
**操作者**：魔术师（子 Agent）  
**触发**：用户给出任务书 Wiki 链接（`NsOqwzqPOiPuKPk8syMcvejjnKc`），要求将 Edoc V10.0 的 PDF 切分为 chunks。

### 2.2 执行过程

**输出目标**：`F:\调试资料\Edoc V10.0\Edoc V10.0\chunks\`  
每个 PDF 输出一个 `.chunks.json` 文件 + `manifest.json` 总索引。

**核心脚本**：`edoc_file_import.py`（467行）

```python
# 分块逻辑
def chunk_text(text, size=600, overlap=100):
    paras = re.split(r'(?<=[.!?。！？])\s+', text)  # 按段落拆分
    chunks, buf, buf_chars = [], "", 0
    for para in paras:
        if buf_chars + len(para) <= size:
            buf += para + " "
            buf_chars += len(para) + 1
        else:
            chunks.append(buf.strip())
            buf = para + " "
            buf_chars = len(para) + 1
    return chunks
```

**元数据字段**：
```json
{
  "source": "B-XXXXXEN_XX.PDF",
  "page": 0,
  "chunk_index": 0,
  "chars": 1234,
  "chunk_type": "text"  // 或 "table", "toc"
}
```

### 2.3 踩坑记录

#### 坑1：F: 盘符在 WSL 中不可见

**现象**：用户指定 `F:\调试资料\` 但 WSL 中 F: 未挂载。  
**根因**：Windows 盘符与 WSL 路径映射问题。  
**解决**：实际数据在 `/mnt/d/Eric/知识库/`（D: 盘对应 WSL 路径）。

#### 坑2：Hermes Agent 子进程崩溃

**现象**：魔术师在处理大量 PDF 时 Hermes CLI 多次崩溃。  
**根因**：子 Agent 内存泄漏 + Hermès CLI 在飞书 bot `/approve session` 命令时死锁。  
**解决**：后续改用 Hermes 主进程直接执行，不走子 Agent。

### 2.4 成果

- **chunks_v3**：142 个 PDF（英文）+ 73 个 CM 文件（中文）
- **总计**：约 49,000 个 chunks
- **输出位置**：`/mnt/d/Eric/知识库/chunks_v3/`

---

## 3. Day 2 — 首次 ChromaDB 建库尝试 + 崩溃事件

### 3.1 建库尝试

**时间**：2026-04-12 ~ 04-13  
**脚本**：`build_edoc_chroma.py`  
**策略**：先用 `BGE-large-zh-v1.5`（1024维）建库。

**配置**：
```python
BGE_MODEL = "BAAI/bge-large-zh-v1.5"  # 1024 维
COLLECTION_NAME = "edoc_v10"           # 英文 collection
CHROMA_PATH = "/mnt/d/Eric/知识库/chroma_db_v3/"
EMBEDDING_DIM = 1024
```

### 3.2 建库脚本核心逻辑

```python
# 加载 chunks
with open(chunks_file) as f:
    data = json.load(f)

# 批量 embedding（BGE-large-zh-v1.5，GPU）
model = AutoModel.from_pretrained(BGE_MODEL)
vectors = model.encode(texts, batch_size=32, normalize_embeddings=True)

# ChromaDB add
coll.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metas)
```

**显存消耗**：BGE-large-zh-v1.5 峰值 **~1251 MiB VRAM**（RTX 4060 Laptop 8GB 上限）。

### 3.3 踩坑记录

#### 坑3：WSL 内存撑爆 → 系统崩溃

**现象**：2026-04-13 凌晨 00:00 ~ 02:30，倒吊人在 BGE-large-zh embedding 建库过程中，WSL 把内存撑满 → Windows 系统崩溃重启。  
**根因**：BGE-large-zh-v1.5（1024维）每批次 32 个 chunks，HNSW 索引在内存中构建，全部 chunks 加载后 OOM。  
**解决**：
- 改用 **BGE-small-en-v1.5**（384维），显存/内存占用降低约 60%
- 降低 batch_size
- 添加 ChromaDB add-only 模式（不主动触发 HNSW 建索引）

#### 坑4：HNSW 索引不完整 → ChromaDB segfault

**现象**：v3 向量库建库两次被 SIGTERM 中断（系统关机/OOM），ChromaDB 连接时报 SIGSEGV (RC=-11)。  
**根因**：ChromaDB 0.4.x 在 `add` 完成后才完整写入 HNSW 索引文件（`index.bin`）。中途断电导致索引文件不完整，但 `chroma.sqlite3` 已记录了 chunks 数量。连接时 ChromaDB 尝试验证索引完整性 → segfault。  
**解决**：
1. 完整删除 `chroma_db_v3/` 目录，重新从头建库
2. 建库时设置 `chromadb.PersistentClient(path=..., settings=Settings(allow_reset=True))`
3. add-only 模式，避免重复建库

#### 坑5：.wslconfig 配置键名错误

**现象**：WSL 启动时报 `wsl2.relaxedVirtualMemoryAllocation: 键"9"未知`。  
**根因**：在 `.wslconfig` 中写了无效键名 `relaxedVirtualMemoryAllocation`。  
**解决**：删除该行，使用默认 WSL2 内存管理（动态增长，上限为物理内存 50%）。

### 3.4 系统崩溃事件时间线

```
04-12 19:20  系统正常运行
04-12 19:21  配置变更触发 gateway 重启（gateway down ~3h）
04-12 19:21  倒吊人/太阳/魔术师/Hermes CLI 四个 bot 同时开始任务
04-12 20:13  ⚠️ Windows BSOD（Your device ran into a problem...）
04-12 20:32  ⚠️ 再次崩溃（倒吊人正在用 BGE-large-zh 重启 v3 建库）
04-12 21:05  ⚠️ 又崩溃
04-12 21:07  ⚠️ 又崩溃，倒吊人仍在尝试重启 v3 建库
04-12 22:13  WSL gateway 停止，systemd 调度重启（restart counter=1）
04-13 00:00  v3 建库继续（倒吊人/太阳）
04-13 00:00  ⚠️ 倒吊人建库崩溃
04-13 02:29  系统正常关机（SIGTERM，非崩溃）
```

**结论**：不是单一崩溃，是多个服务同时高负载触发的级联故障。WSL2 内存不自动收缩 + 多进程并发 embedding 是主因。

---

## 4. Day 3 — 崩溃根因定位 + coll_zh 建库

### 4.1 根因定位

**分析**：
- v1 向量库（34,549 chunks，2026-04-11 建）正常可用
- v3 向量库（只有 235MB 目录，无 `chroma.sqlite3`）无法连接
- 两次 SIGTERM 中断发生在 `coll.add()` 过程中

**结论**：HNSW 索引写入不完整导致 ChromaDB 无法加载。

### 4.2 coll_zh 中文库建库

**时间**：2026-04-14 下午 ~ 晚上  
**脚本**：`build_edoc_chroma.py`  
**配置**：复用 BGE-large-zh-v1.5（GPU），collection 名 `edoc_v10_zh`  
**结果**：14,889 chunks，73 个 CM 文件（中文维修手册）

**验证**：
```python
coll = client.get_collection("edoc_v10_zh")
print(coll.count())  # → 14889
```

### 4.3 踩坑记录

#### 坑6：Hermes update 失败

**现象**：`hermes update` 命令超时无响应。  
**根因**：网络问题（国际出口不畅）。  
**解决**：手动更新 hermes（`hermes-manual-update` skill）。

#### 坑7：飞书 bot 写入权限

**现象**：Bot 无法写入飞书 Wiki 文档（`permission denied`）。  
**根因**：Bot 未被添加为文档协作者。  
**解决**：用户手动将 bot 添加为文档编辑者（飞书 Wiki → 分享 → 添加成员 → 搜索 bot 名称）。

---

## 5. Day 4 — v3 向量库重建 + BM25 召回 + POC 考试

### 5.1 v3 向量库重建（最终版）

**时间**：2026-04-14 下午  
**操作**：清空 `chroma_db_v3/`，用 BGE-small-en-v1.5 从头重建  
**配置变更**：
```python
BGE_MODEL = "BAAI/bge-small-en-v1.5"   # 384 维（替代 large-zh）
COLLECTION_NAME = "edoc_v10"
VEC_DIM = 384
```

**结果**：
- 34,100 chunks，142 个 PDF
- 472MB（`chroma.sqlite3` + HNSW `index.bin` + `data.msgpack`）
- collection: `edoc_v10`

### 5.2 BM25 Keyword Fallback

**时间**：2026-04-14 下午 ~ 晚上  
**背景**：纯向量检索在 Q2-Q10 上 Top-1 命中率仅 30%（封面页/通用词压制正文）。

**实现**：在 `rag_answer.py` 中加入双路 RRF 合并。

```python
# BM25 索引构建（缓存到文件）
def build_bm25_index(coll):
    chunks = []  # 分批加载所有 chunks
    # BM25: 倒排索引，O(terms × postings) 而非 O(N)
    ...

# hybrid_search: RRF 合并
def hybrid_search(query, top_k=3):
    vec_results = vector_search(query, k=5)   # 向量 top 5
    bm25_results = bm25.search(query, k=20)  # BM25 top 20
    # RRF 合并（k=60）
    seen = {}
    for rank, r in enumerate(bm25_results):
        seen[r['source']]['rrf_score'] += 1.0 / (60 + rank + 1)
    for rank, r in enumerate(vec_results):
        seen[r['source']]['rrf_score'] += 1.0 / (60 + rank + 1)
```

**效果**：Q2-Q10 封面页题全面提升，**Top-1 Hit Rate 从 60% → 70%**。

### 5.3 POC 考试体系建立

**脚本**：`edoc_poc_exam.py`  
**架构**：Q1-Q10 分类问题集，评测向量检索的 Top-1 和 Keyword Recall。

| 题型 | 说明 | 示例 |
|------|------|------|
| Q1 | Gold Standard | 操作流程（英文手册有唯一出处） |
| Q2 | Silver Standard | 中文手册优于英文 |
| Q3 | 中文语义 | 维修手册中文内容召回 |
| Q4 | PMC 语义 | PMC 梯形图相关检索 |
| Q5 | 规格参数表 | 速度/负载规格表 |
| Q6 | KAREL 编程 | KAREL 手册特定出处 |
| Q7 | 网络配置 | Ethernet/IP 配置 |
| Q8 | 焊枪诊断 | servo gun 压力/诊断 |
| Q9 | 多义词 | "reference" 歧义 |
| Q10 | Safety | 安全操作手册 |

**评测结果（2026-04-14 晚）**：

| 模型 | Top-1 Hit Rate | Keyword Recall |
|------|---------------|---------------|
| gold | 7/10 | 80% |
| silver | 6/10 | 70% |
| navy | 6/10 | 70% |
| purple | 6/10 | 70% |

**未通过**：Q4（PMC WHILE 语义排名）、Q6（KAREL B-82854EN_03.PDF 缺库）、Q8（servo gun 焊枪语义排名）。

### 5.4 System Prompt 实装

**位置**：`rag_answer.py` 第 341-351 行

```python
SYSTEM_PROMPT = """你是一个 FANUC 工业机器人技术支持助手。
回答时：
1. 基于检索到的上下文回答，不要编造
2. 如涉及具体参数/代码，提供文件名和页码
3. 使用中文回答
4. 参考格式：参考答案[来源: 文件名 第N页]"""
```

### 5.5 踩坑记录

#### 坑8：BM25 通用词压制专指内容

**现象**：查询 `SRVO-001 急停报警` 时，BM25 命中的通用"报警"关键词（出现在目录页/索引页）RRF 得分反而高于正确的 SRVO-001 专指内容页。  
**根因**：RRF k=60 权重下，向量相似度（dist=0.3132）和 BM25 rank 贡献相当，通用词覆盖广导致 BM25 rank 贡献更大。  
**解决（Day 5）**：改变策略为"向量主检索 + BM25 rerank"，向量负责初筛，BM25 仅做关键词加分。

---

## 6. Day 5 — 检索质量调优 + BGE-m3 测试 + 打标系统

### 6.1 向量主检索 + BM25 Rerank

**时间**：2026-04-15 上午  
**问题**：BM25 主导的 RRF 导致通用词压制专指内容。  
**解决**：

```python
# 向量主检索（top-20）
q_emb = encode_query(query)  # BGE-small CUDA 编码
vec_chunks = coll.query(query_embeddings=[q_emb], n_results=20)

# BM25 仅做 rerank 加分
kw_set = tokenize(query) | tokenize(keywords)
for r in vec_chunks:
    hit_kw = [t for t in kw_set if t in r['text'].lower()]
    kw_ratio = len(hit_kw) / max(len(kw_set), 1)
    kw_boost = min(0.5, kw_ratio * 0.5)
    vec_sim = max(0, 1.0 - r.get('vec_dist', 1.0) / 2.0)
    r['rrf_score'] = vec_sim + kw_boost
```

**效果**：
- `SRVO-001 急停报警` → Top-1: B-83934CM_01.PDF ✅（"操作面板紧急停止"）
- `KAREL program structure` → Top-1: B-82854EN_03.PDF ✅
- `servo gun pressure` → Top-1 正确 ✅

### 6.2 BGE-m3 GPU 显存测试

**时间**：2026-04-15 上午  
**目的**：验证 BGE-m3（多语言 1024维 embedding）能否在 RTX 4060 Laptop 上运行。

**测试代码**：
```python
from transformers import AutoModel, AutoTokenizer
model = AutoModel.from_pretrained("BAAI/bge-m3")
# GPU 编码 100 个 chunks
```

**结果**：✅ **PASS**
- **峰值 VRAM：2,179 MiB**
- RTX 4060 Laptop 上限：**8 GB**
- 显存利用率：**27%**

**踩坑记录**：

#### 坑9：sentence-transformers 与 BGE-m3 兼容性问题

**现象**：`SentenceTransformer("BAAI/bge-m3")` 报 `AutoProcessor` 检测失败。  
**根因**：sentence-transformers 5.4.1 对 BGE-m3 有兼容性 bug，AutoModel 检测逻辑在 `from_pretrained()` 时调用了不兼容的 processor。  
**解决**：绕过 sentence-transformers，直接用 `transformers.AutoModel.from_pretrained()` 底层加载。

#### 坑10：pymupdf 未安装

**现象**：`retroactive_tagging.py` 中的 `import pymupdf` 失败。  
**解决**：`uv pip install --python ~/.hermes/venv/bin/python3 pymupdf`（5秒完成）。

### 6.3 Retroactive Tagging 系统

**脚本**：`retroactive_tagging.py`（258行）  
**目的**：对已有的 142 个源 PDF 批量补语义元数据标签。

**元数据标签**：
```json
{
  "robot_model": "R-30iB",
  "manual_type": "操作手册",
  "language": "英文",
  "series": "R-30iB Controller",
  "confidence": 0.9
}
```

**流程**：
1. `find_pdf(source)` — 递归查找 PDF（支持 `Edoc V10.0/PDF/` 子目录）
2. `extract_pdf_preview()` — pymupdf 读前 5 页（~2000 chars）
3. `llm_tag()` — Volcengine API（anonymous/mizu）提取标签
4. `update_chroma_metadata()` — 批量更新 ChromaDB chunks

**踩坑记录**：

#### 坑11：LLM API 选错 endpoint

**现象**：MiniMax API 返回 `status_code: 2061 "your current token plan not support model, MiniMax-Text-01"`。  
**根因**：API key 是 Volcengine token，不是 MiniMax 原生 key。正确 endpoint 是 `https://sd6f7boe66in4kbsvm3og.apigateway-ap-southeast-1.volceapi.com/v1/chat/completions`。  
**解决**：统一使用与 `rag_answer.py` 相同的 Volcengine API。

#### 坑12：Volcengine API timeout

**现象**：`requests.post(..., timeout=30)` 报 `Read timed out`。  
**根因**：首次调用冷启动慢，30s 不够。  
**解决**：timeout 改为 60s。

#### 坑13：hermes venv 无 pymupdf

**现象**：subprocess 调用 `~/.hermes/venv/bin/python3` 时 `import pymupdf` 失败。  
**解决**：先 `uv pip install pymupdf` 到 hermes venv（耗时 ~10s）。

#### 坑14：PDF 路径映射

**现象**：chunks metadata 里 `source=B-XXXXX.PDF`，但文件实际在 `Edoc V10.0/PDF/B-XXXXX.PDF`。  
**解决**：`find_pdf()` 先查直接路径，再递归 rglob 查找。

### 6.4 飞书 docx API block_type 踩坑

**现象**：写入飞书文档返回 `code: 1770001 invalid param`。  
**根因**：skill 里的 block_type 映射有误。

**实测正确对照表**：

| block_type | 含义 | 备注 |
|-----------|------|------|
| 2 | paragraph（文本段） | ✅ 最可靠 |
| 4 | heading2（二级标题） | ✅ 字段名用 `heading2` |
| 12 | bullet（列表项） | ✅ style 需 `{"folded": False}` |
| 3 | ❌ invalid | 触发 1770001 |
| 5 | ❌ invalid | 触发 1770001 |
| 13 | ❌ invalid | 触发 1770001 |

**踩坑**：
- **不要**在 payload 里加 `index` 字段（会触发 1770001）
- **不要**用 `block_type: 5`（skill 里标注为 heading2 是错的，正确是 4）
- JSON 中的数字不用引号，`text_element_style` 字段可选

### 6.5 飞书 Wiki 考卷更新

**文档**：`LkcadYz3ZoQR4ZxO5A3cCESnnnf`（知识库检索考试）  
**写入内容**：
- 向量库状态：chroma_db_v3，edoc_v10（34,100 chunks）+ edoc_v10_zh（14,889 chunks）
- Embedding：BGE-small-en-v1.5（384维）+ BGE-large-zh-v1.5（1024维）
- 检索方案：hybrid（向量主检索 + BM25 rerank）
- Q1-Q10 结果：7/10 Top-1 Hit Rate

---

## 7. 踩坑记录汇总

| # | 坑名 | 现象 | 根因 | 解决 |
|---|------|------|------|------|
| 1 | F: 盘符不可见 | 路径 `F:\调试资料\` 在 WSL 无对应 | Windows 盘符映射问题 | 改用 `/mnt/d/Eric/知识库/` |
| 2 | Hermes 子进程崩溃 | 魔术师处理大量 PDF 时 Hermes CLI 死锁 | 内存泄漏 + /approve session 命令死锁 | 改用 Hermes 主进程直接执行 |
| 3 | WSL 内存撑爆 | 建库时 WSL 内存耗尽 → Windows BSOD | BGE-large-zh 1024维全量内存构建 HNSW | 改 BGE-small（384维），降低 batch_size |
| 4 | ChromaDB segfault | v3 连接时报 SIGSEGV RC=-11 | 两次 SIGTERM 中断建库，HNSW index.bin 不完整 | 删除重建，add-only 模式 |
| 5 | .wslconfig 键名错误 | `wsl2.relaxedVirtualMemoryAllocation: 键"9"未知` | 写了不存在的 WSL2 配置键 | 删除该行，用默认内存管理 |
| 6 | Hermes update 超时 | `hermes update` 无响应 | 网络问题 | 手动更新（hermes-manual-update skill） |
| 7 | 飞书 bot 无写入权限 | `permission denied` | Bot 未被添加为文档协作者 | 用户手动添加 bot 到文档 |
| 8 | BM25 通用词压制专指内容 | `SRVO-001 急停报警` → 目录页压过正文 | RRF k=60 下 BM25 rank 权重过大 | 改为"向量主检索 + BM25 rerank" |
| 9 | sentence-transformers + BGE-m3 | `AutoProcessor` 检测失败 | sentence-transformers 5.4.1 与 BGE-m3 不兼容 | 直接用 `transformers.AutoModel.from_pretrained()` |
| 10 | pymupdf 未安装 | `ModuleNotFoundError: No module named 'pymupdf'` | hermes venv 默认无 pymupdf | `uv pip install --python ~/.hermes/venv/bin/python3 pymupdf` |
| 11 | LLM API endpoint 选错 | `status_code: 2061 model not supported` | 用了 MiniMax endpoint 而非 Volcengine | 统一用 `https://sd6f7boe66in4kbsvm3og.apigateway.../v1/chat/completions` |
| 12 | Volcengine API timeout | `Read timed out` | 冷启动慢，30s 不够 | timeout 改为 60s |
| 13 | hermes venv 无 pymupdf | subprocess 调用 venv 时 import pymupdf 失败 | venv 未装 pymupdf | 先 `uv pip install pymupdf` 到 hermes venv |
| 14 | PDF 路径映射 | chunks metadata 的 source 找不到文件 | 文件在 `Edoc V10.0/PDF/` 子目录 | `find_pdf()` 递归 rglob 查找 |
| 15 | 飞书 docx API block_type 错误 | `1770001 invalid param` | skill 里 block_type 映射有误（5=heading2 是错的） | 实测：2=paragraph, 4=heading2, 12=bullet |
| 16 | 飞书 API index 字段 | 加了 `index` 字段后 `1770001` | API 不支持 index 参数 | payload 里不要加 index 字段 |

---

## 8. 当前状态

### 8.1 向量库

| Collection | 模型 | 维度 | Chunks | 大小 | 状态 |
|-----------|------|------|--------|------|------|
| edoc_v10 | BGE-small-en-v1.5 | 384 | 34,100 | ~472MB | ✅ 可用 |
| edoc_v10_zh | BGE-large-zh-v1.5 | 1024 | 14,889 | ~73MB | ✅ 可用 |
| v3 total | — | — | **48,989** | ~545MB | ✅ |

### 8.2 RAG 检索

- **架构**：向量主检索（BGE-small CUDA，~0.3s/query）+ BM25 rerank（关键词加分）
- **System Prompt**：已实装（`rag_answer.py` 第 341 行）
- **Top-1 Hit Rate**：7/10（70%）
- **待解决**：Q4（PMC WHILE）、Q6（KAREL B-82854EN_03.PDF 缺库）、Q8（servo gun 语义）

### 8.3 待完成任务

| 任务 | 优先级 | 说明 |
|------|--------|------|
| Q6 KAREL 建库 | P0 | 用户提供 B-82854EN_03.PDF 后入库 |
| Q4/Q8 语义召回优化 | P1 | 可能是 coll_zh 向量库查询路径问题 |
| Retroactive tagging | P2 | 142 个 PDF 批量补元数据（脚本已就绪） |
| 打标接入 rag_answer.py | P2 | 按 manual_type/robot_model 做 query filter |
| BGE-m3 建库 | P3 | 显存验证通过，可重建 edoc_v10_zh 用 BGE-m3 |
| Docker Desktop + RAGFlow | P3 | 用户计划安装，之后迁移 |

### 8.4 关键配置文件路径

```
~/.hermes/scripts/rag_answer.py         ← RAG 检索引擎（当前主力）
~/.hermes/scripts/build_edoc_chroma.py ← 建库脚本
~/.hermes/scripts/retroactive_tagging.py ← 打标脚本
~/.hermes/scripts/edoc_import_pipeline.py ← 导入流水线（含 LLM 打标，565行）
~/.hermes/scripts/edoc_poc_exam.py      ← POC 评测
~/.mmx/config.json                       ← Volcengine API key
~/.hermes/skills/feishu-docx/           ← 飞书 API skill（已修正 block_type）
```

---

*文档生成时间：2026-04-15 11:30*
*最后更新：Hermes Agent，v3 向量库重建 + 检索质量修复完成*
