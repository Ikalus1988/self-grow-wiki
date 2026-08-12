# eDoc RAG 知识库系统 · 完整文档 v4

> **版本**：2026-04-20 夜间版
> **模型**：MiniMax-M2 + BGE-m3
> **向量库**：`chroma_db_v4/edoc_v10_m3` — **215,037 chunks**，BGE-m3 1024维

---

## 一、背景与目标

**业务目标**：为 FANUC 工业机器人建立可检索的知识库，支持中文/英文 PDF 语义检索和 RAG 回答，POC Top-1 命中率目标 ≥90%。

**核心挑战**：
- PDF 格式为主，大量扫描件、图纸、合同保单简历等噪音
- 中英德三语文档（FANUC 手册 CN/EN/DE）
- 飞书 Bot 卡片按钮无法点击（`lark-oapi` WebSocket 模式 SDK 限制）

**Agent 分工**：

| Agent | 角色 |
|--------|------|
| 太阳（OpenClaw） | 向量库建库执行 |
| 倒吊人 | 文档分析 + 评测 |
| 魔术师 | 批量导入流水线 |
| Hermes（我） | 飞书 Bot + RAG 检索引擎 |

---

## 二、技术架构

### 2.1 整体数据流

```
PDF 文件（F:/D:）
  → PyMuPDF 文本提取（扫描件跳过 OCR）
  → 按段落拆分 chunk（~600 chars）
  → BGE-m3-small-CU12 embedding（1024 维，L2 距离）
  → ChromaDB v4 向量库（215,037 chunks）
  → rag_answer.py（向量主检索 + BM25 rerank）
  → 飞书 Bot 卡片（/查 前缀触发）
```

### 2.2 关键脚本路径

```
~/.hermes/scripts/
  rag_answer.py                  ← RAG 检索引擎（当前主力）
  edoc_poc_exam.py               ← Q1-Q10 POC 评测
  retroactive_tagging.py          ← 存量 chunks 元数据打标
  bm25_edoc_zh.pkl              ← BM25 索引缓存
  build_edoc_bge_m3_robust.py    ← 零崩溃 BGE-m3 建库脚本
  build_edoc_zh_bge_m3.py        ← 中文重编码脚本（edoc_v10_zh_m3 待续建）

/mnt/d/Eric/知识库/
  chroma_db_v4/                  ← 当前主力库（BGE-m3，215,037 chunks）
  chroma_db_v3/                  ← 历史库（BGE-small-en/BGE-large-zh，备用）
  chunks_v3/                     ← PDF 分块 JSON（每个 PDF 一个 .chunks.json）
```

---

## 三、向量库现状

### 3.1 chroma_db_v4（当前主力）

| Collection | 模型 | 维度 | Chunks | 状态 |
|------------|------|------|--------|------|
| `edoc_v10_m3` | BGE-m3-small-CU12 | 1024 | **215,037** | ✅ 主力库（2026-04-16 首次零崩溃建库） |

**历史遗留**（可忽略）：

| Collection | 模型 | 维度 | Chunks | 状态 |
|------------|------|------|--------|------|
| `chroma_db_v4/edoc_v10` | BGE-m3 | 1024 | 7,015 | ⚠️ 早期残留中断 |
| `chroma_db_v3/edoc_v10` | BGE-small-en | 384 | 34,100 | ✅ 备用 |
| `chroma_db_v3/edoc_v10_zh` | BGE-large-zh | 1024 | 14,889 | ✅ 备用 |
| `chroma_db_v3/edoc_v10_zh_m3` | BGE-m3 | 1024 | 4,608 | 🔄 待续建 |

### 3.2 建库历程（Day 1-6）

| 日期 | 事件 | 结果 |
|------|------|------|
| 2026-04-11 | Day 1 — PDF 分块（魔术师） | 142 PDF → chunks_v3，~49,000 chunks |
| 2026-04-12 | Day 2 — 首次 BGE-large-zh 建库 | WSL 内存撑爆 → Windows BSOD × 3次 |
| 2026-04-13 | Day 3 — segfault + 崩溃定位 | HNSW 索引不完整，删库重建 |
| 2026-04-14 | Day 4 — BGE-small 建库成功 + BM25 双路召回 | 34,100 chunks ✅；Top-1 Hit 60% |
| 2026-04-15 | Day 5 — 向量主检索 + BM25 rerank | 通用词压制问题修复；BGE-m3 GPU 测试通过 |
| 2026-04-16 | Day 6 — BGE-m3 零崩溃建库 | 34,100 chunks ✅ 首次零崩溃 |
| 2026-04-20 | 最新状态 | **215,037 chunks**（F: 盘批量导入后） |

**BGE-m3 全量建库关键策略**（`build_edoc_bge_m3_robust.py`）：
- 自适应 BATCH：前 2 批预热测峰值显存，动态决定 batch size（32→48）
- `coll.add()` **之后**保存 checkpoint（保证最多丢当前 batch）
- SIGINT + SIGTERM 双捕获，优雅退出
- 每 50 批 count vs checkpoint 交叉验证
- 进程锁 `fcntl.LOCK_NB` 防重复启动
- GPU 显存 >6.5GB 告警 + `gc.collect()`

---

## 四、检索策略（当前生产）

### 4.1 向量主检索 + BM25 Rerank

```python
# 向量 top20 候选（余弦相似度）
q_emb = encode_query(query)  # BGE-m3 CUDA，~0.3s
vec_chunks = coll.query(query_embeddings=[q_emb], n_results=20)

# BM25 仅做 rerank 加分（不再主导）
kw_set = tokenize(query)
for r in vec_chunks:
    hit_kw = [t for t in kw_set if t in r['text'].lower()]
    kw_ratio = len(hit_kw) / max(len(kw_set), 1)
    kw_boost = min(0.5, kw_ratio * 0.5)
    vec_sim = max(0, 1.0 - r.get('vec_dist', 1.0) / 2.0)
    r['rrf_score'] = vec_sim + kw_boost
```

**BM25 不再主导**：避免"报警"等通用词压制正确结果（之前 Q1-Q10 Top-1 Hit 仅 60% 的根因）

### 4.2 双语 Embedding 策略

**当前状态**：已被 BGE-m3 统一多语言能力取代。

**历史方案**（已废弃，仅作参考）：
- `coll_en`（BGE-small-en）→ 英文查询
- `coll_zh`（BGE-large-zh）→ 中文查询
- RRF 合并 → 因 BGE-m3 自带多语言能力而简化

---

## 五、POC 科学评测体系

### 5.1 Q1-Q10 评测集（v3 修正版）

> **核心教训**：第一轮评测 Top-1 命中率 0%——不是 RAG 差，是 **Ground Truth 标注错误**。文件名 ≠ 内容，必须先验证文档 chunk 数 >200。

| 题号 | 类型 | 难度 | 主题 | Ground Truth | Top-1 | Top-3 |
|------|------|------|------|--------------|-------|-------|
| Q1 | T1-Factual | easy | SRVO-001 急停触发条件 | B-80687EN_17, B-80687CM_16, B-82644EN_03 | B-82644EN_03 ✅ | ✅ |
| Q2 | T4-Diagnostic | medium | SRVO-050 碰撞报警根因 | B-83284EN-1_07_01, B-80687EN_17 | B-83284EN-1_07_01 ✅ | ✅ |
| Q3 | T2-Procedural | medium | 机器人 TCP 工具坐标系标定步骤 | B-83244EN_02_01, B-83264EN_02_01 | B-83244EN_02_01 ✅ | ✅ |
| Q4 | T7-Configuration | hard | PMC 宏 WHILE 循环 1000 次限制 | B-75114EN_04 | B-83284EN-1_07_01 ❌ | ✅ |
| Q5 | T5-Specification | medium | R-2000iC 最大速度规格表 | B-83644CM_06, B-83644EN_07 | B-83644EN_07 ✅ | ✅ |
| Q6 | T6-Terminology | easy | KAREL 程序结构与 I/O 控制 | B-82854EN_03 | B-83284EN-2_09_01 ❌ | ✅ |
| Q7 | T8-Safety | medium | 安全栅栏/安全门联锁配置要求 | B-80687CM_16, B-80687EN_17 | B-83304EN-3_02 ✅ | ✅ |
| Q8 | T3-MultiHop | hard | 伺服焊枪规格与诊断联动 | B-83264CM_05 | B-84064EN_04 ❌ | ✅ |
| Q9 | T9-ErrorRecovery | medium | 碰撞检测灵敏度调整与恢复 | B-83284EN-2_09_01, B-83284CM-2_05 | B-83284EN-2_09_01 ✅ | ✅ |
| Q10 | T10-Comparative | hard | T1/T2/AUTO 急停停止类别对比 | B-83284EN-5_03_01, B-80687EN_17 | B-83284EN-5_03_01 ✅ | ✅ |

**v3 修正后结果**：Top-1 命中率 **70% (7/10)**，Top-3 命中率 **90% (9/10)**

### 5.2 关键文档速查（已验证 chunk 数）

| 内容主题 | 推荐文档 | chunk 数 | 备注 |
|----------|----------|----------|------|
| SRVO 报警完整内容 | `B-83284EN-1_07_01` | 1000+ | ⚠️ B-80687EN_17 只有 88 chunks 不可靠 |
| 高灵敏度碰撞检测 | `B-83284EN-2_09_01` | — | 章节 8 |
| 伺服焊枪（含 TCP/标定） | `B-83264CM_05` | 417/446 | 中文文档 |
| PMC 宏 WHILE 循环 | `B-75114EN_04` | — | 引用 B-63983EN（需补充） |
| KAREL 编程 | `B-82854EN_03` | 31 | ⚠️ B-82854EN_01 不在库中 |
| R-2000iC 速度规格 | `B-83644EN_07` | — | EN 版更完整 |

### 5.3 脚本用法

```bash
# 预计算 query embedding（首次或修改题目后）
~/.hermes/hermes-agent/.venv/bin/python3 ~/.hermes/scripts/edoc_poc_exam.py --mode precompute

# 检索召回率考试
~/.hermes/hermes-agent/.venv/bin/python3 ~/.hermes/scripts/edoc_poc_exam.py --mode exam

# 5 模型 LLM 回答评测
~/.hermes/hermes-agent/.venv/bin/python3 ~/.hermes/scripts/edoc_poc_exam.py --mode llm-eval

# 一键连续跑
~/.hermes/hermes-agent/.venv/bin/python3 ~/.hermes/scripts/edoc_poc_exam.py --mode full
```

---

## 六、F: 盘导入流程

### 6.1 目录星级评分

| 目录 | 星级 | 数量 | 大小 | 导入耗时 | 备注 |
|------|------|------|------|----------|------|
| KUKA培训资料 | ⭐⭐⭐ | 863 | 1073 MB | ~2h | KUKA 机器人培训手册/实操/WINCC |
| CJLR | ⭐⭐⭐ | 230 | 604 MB | ~2h | 捷豹路虎 ABB/FANUC 项目，PDPS |
| Durr_Chengdu | ⭐⭐ | 672 | 362 MB | ~1.5h | 杜尔涂装线，按 MK 编号去重 |
| BMW_CHINA | ⭐⭐ | 1102 | 342 MB | ~1.5h | 宝马设备规范 |
| 吉利 | ⭐⭐ | 25 | 42 MB | ~10min | PIDS 螺柱焊/设备手册 |
| 滚边资料 | ⭐⭐ | 3 | 3 MB | ~1min | 车门滚边 KUKA 培训 |
| 法信 | ⭐⭐ | 10 | 12 MB | ~2min | Proteus WeldSaver 修磨机 |
| 上海天永 | ⭐⭐ | 1 | 3 MB | ~1min | KUKA 配置标准 |
| **总计 2 星+** | — | **2881** | **2398 MB** | **~8h（实测 7.6h ✅）** | — |
| FIBRO | ❌ | 7172 | 1342 MB | — | GM 项目，与已有 EDOC 重复 |
| Tesla2022 | ❌ | 31 | 210 MB | — | 焊装布局图纸，无文字 |
| 上海信杰 | ❌ | 6 | 41 MB | — | 焊钳图纸扫描件 |

### 6.2 差异化去重策略

| 目录类型 | 去重逻辑 | 语言优先级 |
|----------|----------|------------|
| Durr_Chengdu | **按 MK 编号**（`MK.135579`~`MK.135593`） | CN > EN > DE |
| BMW_CHINA | 按文件名，同名保留最大 | 优先大文件 |
| KUKA培训资料 | 按文件名，同名保留最大；版本不同都保留 | 优先大文件 |
| 其他目录 | 按文件名，保留最大 | CN > EN > DE |

### 6.3 导入速度估算

- 速度：实测 **~20-40 PDF/h**（大文件拖慢）
- 2881 个 2 星+目录：预估 **~8h**（实测 7.6h ✅）
- GPU 显存峰值：~2.1 GB（BGE-m3，RTX 4060 Laptop）

---

## 七、踩坑记录汇总

### 7.1 建库阶段

| # | 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|------|
| 1 | F: 盘符不可见 | `F:\调试资料\` 在 WSL 无对应 | Windows 盘符映射 | 改用 `/mnt/d/Eric/知识库/` |
| 2 | Hermes 子进程崩溃 | 魔术师处理大量 PDF 时 CLI 死锁 | 内存泄漏 + /approve session 死锁 | 改用 Hermes 主进程直接执行 |
| 3 | WSL 内存撑爆 | 建库时 WSL 内存耗尽 → Windows BSOD ×3 | BGE-large-zh 1024 维全量内存构建 HNSW | 改 BGE-small（384 维），降低 batch_size |
| 4 | ChromaDB segfault | v3 连接时报 SIGSEGV RC=-11 | SIGTERM 中断建库，HNSW index.bin 不完整 | 删除重建，add-only 模式 |
| 5 | .wslconfig 键名错误 | `wsl2.relaxedVirtualMemoryAllocation: 键"9"未知` | 无效 WSL2 配置键 | 删除该行 |
| 6 | Hermes update 超时 | `hermes update` 无响应 | 网络问题 | 手动更新 |
| 9 | sentence-transformers + BGE-m3 | `AutoProcessor` 检测失败 | sentence-transformers 5.4.1 与 BGE-m3 不兼容 | 直接用 `transformers.AutoModel.from_pretrained()` |
| 17 | stdout 未 flush | SIGTERM 打断时 log 尾部 null bytes | interrupt handler 未 flush+close | 加 `sys.stdout.flush()` |

### 7.2 检索阶段

| # | 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|------|
| 8 | BM25 通用词压制专指内容 | `SRVO-001` 目录页压过正文 | RRF k=60 下 BM25 rank 权重过大 | 改为"向量主检索 + BM25 rerank" |
| — | 命中率低（Top-1 0%） | Q1 第一轮 0% 命中 | **Ground Truth 标注错误**（文件名≠内容） | 先验证文档 chunk 数 >200 |
| — | 同内容多文档 | Q8 servo gun 中文文档英文查询 | BGE-small-en 无法匹配中文密集文档 | BGE-m3 统一多语言能力 |
| 14 | BM25 cache 首次查询命中率低 | cache.N ≠ coll.count | cache.N 变化时未重建 | 自动检测变化并重建 |

### 7.3 飞书 Bot

| # | 坑 | 现象 | 根因 | 修复 |
|----|------|------|------|------|
| 15 | 飞书 docx API `1770001` | `invalid param` | block_type 映射错误（5=heading2 是错的） | 实测：2=paragraph, 4=heading2, 12=bullet |
| 16 | 加 `index` 字段后 `1770001` | API 不支持 index 参数 | payload 构造错误 | payload 里不要加 index 字段 |
| — | 卡片按钮 `code 200340` | 按钮点击无法回调 | `lark-oapi` WebSocket 模式丢弃 `MessageType.CARD` | 需 webhook + ngrok 或切 polling |
| — | 按钮无文字 | 卡片按钮空白 | `width: 50`（整数）Feishu 拒绝 | 改 `width: "50"` 字符串 |
| — | `action_type: "card_action"` | Feishu API 不接受 | SDK 文档误导 | 改 `action_type: "request"` |
| — | `tag: "note"` | 无效 | Feishu API 不支持 | 改 `tag: "markdown"` |

### 7.4 依赖与环境

| # | 坑 | 现象 | 修复 |
|----|------|------|------|
| 10 | pymupdf 未安装 | `ModuleNotFoundError` | `uv pip install --python ~/.hermes/venv/bin/python3 pymupdf` |
| 11 | LLM API endpoint 选错 | `status_code: 2061 model not supported` | 统一用 Volcengine endpoint |
| 12 | Volcengine API timeout | `Read timed out`（30s） | timeout 改为 60s |
| 13 | hermes venv 无 pymupdf | subprocess 调用失败 | 先 `uv pip install pymupdf` 到 hermes venv |

---

## 八、元数据打标（Retroactive Tagging）

**脚本**：`~/.hermes/scripts/retroactive_tagging.py`

**目的**：对已有向量库中 142 个源 PDF 的 chunks 批量补充语义标签。

**标签格式**：
```json
{ "robot_model": "R-30iB", "manual_type": "操作手册", "language": "英文", "series": "R-30iB Controller", "confidence": 0.9 }
```

**当前状态**（2026-04-17）：
- ✅ 160 个 FANUC 源全部打标完成
- ✅ 已接入 `rag_answer.py` tag filter
- ⚠️ 21 个 PDF 文本不可提取（扫描/图像 PDF），confidence=0，跳过

**文本来源优先级**：PDF 文件 → chunks JSON → ChromaDB documents

---

## 九、飞书 Bot RAG 集成

### 9.1 触发与响应

- **触发**：`/查 <问题>` 前缀（不带前缀走正常对话）
- **卡片**：markdown 格式，`action_type: "request"`
- **按钮**：`width` 必须是字符串（`"33"` / `"50"`）
- **回调限制**：WebSocket 模式无法接收 card action 事件（`lark-oapi` SDK 限制）

### 9.2 凭证（正确值）

```
app_id=cli_a93f960281389bcd
app_secret=REPLACED
user_open_id=ou_7974c0a07d93eefc12c1eb4bb2b27fb9
```

---

## 十、交叉验证机制

**背景**：单 Agent 单次检索无法捕获 false negative（向量偏置、BM25 误判、跨语言盲区、模型局限）。

**最简方案**（用户手动协作）：
1. 对 Hermes 说：`/查 SRVO-001 刚性参数不足`
2. 对 倒吊人 说：`查 SRVO-001 刚性参数不足`
3. 对比两边 Top-1 来源：一致 → 高置信；不一致 → 双方 re-rank 合并

**自动化路线**：
- Phase 0：`/cv <query>` 命令（Hermes 执行两次 rag_answer）
- Phase 1：MCP 打通（倒吊人通过 MCP 调用 Hermes rag_answer）
- Phase 2：Task Board 队列（全自动）

---

## 十一、待办清单

- [ ] **飞书卡片回调（200340）**：需配置 ngrok 隧道 + webhook 模式，才能真正接收按钮点击事件
- [ ] **edoc_v10_zh_m3 续建**：当前仅 4,608 chunks（batch 36 中断），需再跑 `build_edoc_zh_bge_m3.py`
- [ ] **Q1-Q10 POC 重跑**：新 BGE-m3 库（215,037 chunks）质量验证
- [ ] **微信接入**：WeChatFerry / Wechaty / itchat-uos / 企业微信 webhook 四方案待选型
- [ ] **F: 盘 2星+目录确认**：2881 个文件待用户确认评分后执行导入

---

## 十二、Opus 文档改动记录（待补）

> **说明**：Opus 发来的 RAG 知识库原始文档未在会话历史中找到（会话内容为飞书/微信选型、Feishu CLI 安装等工程任务）。请重新发送 Opus 的原始文档，我将在此标注具体改动。

---

*文档生成时间：2026-04-21 00:10*
