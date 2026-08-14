https://ikalus1988.github.io/# FANUC 机器人 RAG 知识库 — 完整项目说明文档

> 版本: v2.1 | 日期: 2026-05-07 | 模型: MiMo-V2-Flash + MiMo-V2-Pro + DeepSeek + Qwen2.5:3b | 维护: Hermes Agent (Node 1, hp WSL)

---

## 1. 项目概述

### 1.1 项目目标

给 FANUC 机器人操作/维修/编程技术文档建一个 **可检索的知识库**，让现场工程师和开发者通过**自然语言提问**快速找到答案。

**核心价值**: 不再翻 2000 页 PDF，直接问"SRVO-023 怎么处理"就能得到带出处的答案。

### 1.2 最终成果 (2026-05-07)

| 指标 | 数值 |
|------|------|
| 源 PDF | **190 个** (全部可追溯) |
| 向量数量 | **200,715** (去重清洗后) |
| 嵌入模型 | bge-base-zh-v1.5 (768维，语义搜索专用) |
| 向量数据库 | ChromaDB (cosine 距离) |
| LLM 通道 | 4通道容灾 (见下方) |
| 向量库路径 | `/home/hp/rag_chromadb/` (Linux 文件系统) |
| 知识库质量 | **95.5% 优** (4σ 达标) |
| 每日巡检 | cron 6:00 自动抽样审计 |
| 配套工具 | 微信机器人 + 试卷生成 + 知识图谱 + 专利储备 |

### 1.3 技术架构

```
┌───────────────────────────────────────────────────────────────────┐
│                    FANUC 技术文档知识库                            │
├───────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐        │
│  │  190 PDF     │    │  edoc 导出   │    │  OCR 增强    │        │
│  │  手动导入    │    │  JSON 批量   │    │  PaddleOCR   │        │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘        │
│         │ rag_builder.py    │ import_edoc.py     │ rag_builder_   │
│         │ rag_import_fanuc  │                    │ ocr.py         │
│         └───────────┬───────┴────────────────────┘                │
│                     ▼                                             │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  P2b 质检门禁 (p2b_ingest_gate.py)                         │  │
│  │  新 PDF 入库前: 污染检查 + 二进制残留 + 图片为主 + 重复检测  │  │
│  └─────────────────────────┬───────────────────────────────────┘  │
│                            ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  rag_chromadb/ (ChromaDB, cosine, 200,715 vectors)          │  │
│  │  bge-base-zh-v1.5 768维 嵌入                                │  │
│  │  质量: 95.5% 优 / 3.1% 良 / 1.4% 中 / 0.0% 差             │  │
│  └──────────────────────────┬──────────────────────────────────┘  │
│                             │ rag_core.py (检索+生成)             │
│                             ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │  LLM 四通道容灾                                          │     │
│  │  1. MiMo-V2-Flash  (主, api.llm.mioffice.cn)  ~1.5s     │     │
│  │  2. MiMo-V2-Pro    (备, api.llm.mioffice.cn)  ~0.5s     │     │
│  │  3. DeepSeek-Chat  (备, api.deepseek.com)     ~2s       │     │
│  │  4. Qwen2.5:3b     (兜底, Ollama本地)          ~50s      │     │
│  └──────┬─────────────┬──────────────┬──────────────┬───────┘     │
│         │             │              │              │              │
│         ▼             ▼              ▼              ▼              │
│  ┌───────────┐ ┌────────────┐ ┌───────────┐ ┌──────────────┐     │
│  │ rag_web   │ │ rag_admin  │ │ rag_api   │ │ wxauto_bot   │     │
│  │ Gradio    │ │ Gradio     │ │ FastAPI   │ │ 微信机器人    │     │
│  │ :7860     │ │ :7861      │ │ :8002     │ │ (wxauto v7)  │     │
│  └───────────┘ └────────────┘ └───────────┘ └──────────────┘     │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │  质量保证层 (每日自动)                                    │     │
│  │  daily_audit.py (cron 6:00) — 随机抽样50 chunks 审计     │     │
│  │  问题率 ≥10% 自动告警                                     │     │
│  └──────────────────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────────────────┘
```

### 1.4 功能清单

| 分类 | 功能 | 状态 |
|------|------|------|
| **数据导入** | PDF/Word/PPT/Excel 批量导入 (rag_builder.py) | ✅ |
| | edoc JSON 流式导入 (import_edoc.py) | ✅ |
| | FANUC 文档增量导入 + 版本替换 (rag_import_fanuc.py) | ✅ |
| | OCR 增强 PDF 导入 (rag_builder_ocr.py + PaddleOCR) | ✅ |
| | 新 PDF 入库质检门禁 (p2b_ingest_gate.py) | ✅ |
| **检索增强** | 语义搜索 + BM25 混合检索 (hybrid_search) | ✅ |
| | 报警代码自动规范化 (SRVO-023 全角/半角模糊) | ✅ |
| | 机器人型号系列文档强制召回 (M-900 等) | ✅ |
| | 品牌过滤 (查询含 FANUC 时排除非 FANUC 文档) | ✅ |
| | 关键词强制召回 (语义鸿沟桥接) | ✅ |
| | 多问题拆分 (复合查询自动拆分分别检索) | ✅ |
| | 对比检索 (/compare 端点，按 subject 独立召回) | ✅ |
| | 文件多样性 (同文件最多3个chunk) | ✅ |
| **质量保证** | P0-P2 四阶段质量审计流水线 | ✅ |
| | 4σ 质量达标 (95.5% 优) | ✅ |
| | 每日自动巡检 (cron 6:00) | ✅ |
| | 新导入门禁 (入库前自动检查) | ✅ |
| **前端** | Gradio Web UI 三通道容灾 (rag_web.py :7860) | ✅ |
| | 管理面板 (rag_admin.py :7861) | ✅ |
| | HTTP API (rag_api.py :8002) | ✅ |
| **微信集成** | wxauto_bot.py (wxauto v7 窗口自动化, 702行) | ✅ |
| | 群聊 @ 回复 + 私聊自动回复 | ✅ |
| **知识图谱** | 文件扫描 + 6维打标 + 知识图谱 | ✅ |
| **试卷生成** | 基于知识库的 FANUC 考试出题 (B卷/C卷) | ✅ (C卷打磨中) |

---

## 2. 知识库质量审计 (v2.0 核心更新)

### 2.1 审计背景

原始向量库 230,858 chunks 存在三类质量缺陷：
- **OCR 污染**: pymupdf4llm 插入 `==> picture omitted <==` 标记
- **版本冗余**: 同一内容的多个版本 (如 CM/03 vs CM/05) 被分别导入
- **来源混乱**: chunk 的 source 标注与实际 PDF 文件不一致

### 2.2 四阶段审计流水线

```
P0a 源文件完整性 ──> P0b 污染清洗 ──> P1a 版本去重 ──> P1b 来源校正 ──> P2a 质量评分
     (190/190)         (83K cleaned)    (30K removed)    (5 fixed)       (95.5% 优)
```

#### P0a: 源文件完整性检查

```bash
cd /home/hp && source /home/hp/mkdocs-env/bin/activate
CUDA_VISIBLE_DEVICES="" python3 p0_source_map.py
```

检查 DB 中所有 filename 是否能在文件系统中找到对应 PDF。
**结果**: 190/190 PDFs matched, 0 missing ✅

#### P0b: 污染清洗

```bash
CUDA_VISIBLE_DEVICES="" python3 p0_cleanup_simple.py
```

确定性替换 (无需 LLM):
- `==> picture [NxN] omitted <==` → 删除整行
- `grep: binary file matches` → 删除
- 零宽字符 strip
- 纯数字/符号噪音行 → 删除

**结果**: 83,335 chunks cleaned, 5,269 "picture omitted" markers removed ✅

#### P1a: 版本去重 (MinHash)

```bash
CUDA_VISIBLE_DEVICES="" python3 p1_dedup.py
```

每个 chunk 生成 MinHash 签名 (64-bit, 5-char shingle)。
Jaccard 相似度 > 0.85 → 视为重复。跨文件重复组中保留版本号最大的 chunk。

**结果**: 30,143 duplicates removed (230,858 → 200,715) ✅

> ⚠️ 注意: 运行前需确保 RAG API 已停止，脚本会修改 ChromaDB。

#### P1b: 来源校正

```bash
CUDA_VISIBLE_DEVICES="" python3 p1_reassign_fast.py
```

仅扫描含 B-xxxxx 编号但 filename 不匹配的 chunk，修正 source 字段。
**结果**: 5 cross-file misattributions fixed ✅

#### P2a: 质量评分

```bash
CUDA_VISIBLE_DEVICES="" python3 p2a_quality_score.py
```

给每 chunk 添加 metadata: `quality_score` (0-1), `quality_label` (优/良/中/差)。
评分规则: base=1.0，含污染标记 -0.3，噪音行 -0.2，过短 -0.1。

**结果**:

| 等级 | 占比 | chunk 数 |
|------|------|----------|
| 优 | 95.5% | ~191,681 |
| 良 | 3.1% | ~6,222 |
| 中 | 1.4% | ~2,810 |
| 差 | 0.0% | 0 |

### 2.3 四σ达标状态

| 维度 | 目标 | 当前 | 达标 |
|------|------|------|------|
| 源文件可追溯 | 100% | 100% | ✅ |
| 内容与原文一致 | ≥99.38% | ~99.5% | ✅ |
| 来源标注准确 | 100% | ~99.99% | ✅ |
| 无 OCR 污染残留 | ≥99.38% | ~99.5% | ✅ |
| 优质 chunk 占比 | ≥95% | 95.5% | ✅ |

### 2.4 新 PDF 入库门禁

```bash
python3 p2b_ingest_gate.py /path/to/new.pdf
```

入库前检查:
- picture omitted 污染
- 二进制残留
- 图片为主 (文本过少)
- 与现有文档重复

返回 0=通过，非0=失败。建议与 `rag_builder.py` 配合使用:

```bash
python3 p2b_ingest_gate.py /path/to/new.pdf && python3 rag_builder.py build
```

### 2.5 每日自动巡检

`daily_audit.py` 通过 cron 每天 06:00 自动执行:
- 随机抽样 50 chunks
- 检查 quality_label
- 问题率 ≥10% 自动告警

---

## 3. 检索增强策略 (v2.0 新增/优化)

### 3.1 混合检索

`rag_core.py` 的 `retrieve()` 函数实现多层召回:

1. **语义检索**: bge-base-zh-v1.5 嵌入 → ChromaDB cosine Top-20
2. **BM25 关键词检索**: 基于 jieba 分词的 BM25 索引，取 Top-20
3. **RRF 融合**: Reciprocal Rank Fusion 合并两路结果
4. **后处理**: 品牌过滤 → 文件多样性 → 话题补充 → 垃圾过滤

### 3.2 报警代码规范化

查询中含 FANUC 报警代码 (如 SRVO-023、SYST-012) 时，自动:
- 全角/半角转换
- 前缀标准化
- 精确匹配强制召回

### 3.3 品牌过滤 + 实体精确召回

**品牌过滤**: 查询含品牌关键词时，后置过滤排除非目标品牌文档，避免跨品牌干扰。

**实体精确召回**: 查询中提取到报警代码或机器人型号时，额外触发关键词精确匹配，覆盖全角/半角/带空格多种变体，确保低频实体不被高频实体挤出候选集。

**对比检索**: 涉及多实体对比的查询，按 subject 分别独立检索后合并，避免单一实体主导排序。

### 3.4 关键词强制召回

当语义搜索无法命中但知识库确实有对应文档时 (语义鸿沟)，通过关键词 `$contains` 强制召回:

| 查询命中 | 强制召回 |
|----------|---------|
| 上位机 / robot interface / 寄存器读/写 | `$contains`: "Robot Interface", "上位机" |

打分原则:
- 文档头部含特征词 → 0.92 (插入到 Top)
- 文档尾部含特征词 → 0.85 (进入前 10)
- 不给 1.0 满分，避免挤掉所有语义结果

### 3.5 多问题拆分 + 对比检索

**多问题拆分**: 当查询包含多个不相关子问题时，自动拆分后分别检索再合并，避免语义混合导致漏召回。

**对比检索**: 支持多实体对比场景，按 subject 独立检索后交给 LLM 做对比分析，支持指定对比维度。

### 3.6 BM25 索引构建

- `warmup()` 先加载 BGE-m3 → 立即标记 `ready=True`，向量检索 ~5s 可用
- BM25 在独立 daemon 线程构建，不阻塞首次查询
- `hybrid_search()` 首次触发时最多等待 30s
- 缓存路径: `~/.hermes/scripts/bm25_index.pkl`

### 3.7 型号文件搜索优化

`_get_model_files()` 优化历程:

| 版本 | 方法 | 性能 |
|------|------|------|
| 旧版 | ChromaDB `$contains` 全表扫描 230K docs | >40s |
| 新版 | BM25 内存索引 `_bm25_index.docs` 子串匹配 | 毫秒级 |

附加优化:
- 型号搜索上限 5 个文件/型号
- `existing_best >= 0.85` 时跳过型号遍历
- 缓存 TTL 从 5min → 1h

---

## 4. 服务清单

### 4.1 核心服务

| 服务 | 路径 | 端口 | 说明 |
|------|------|------|------|
| RAG Web UI | `rag_web.py` | :7860 | Gradio 前端，3通道容灾 |
| RAG API | `rag_api.py` | :8002 | FastAPI HTTP API (供微信 bot 调用) |
| RAG Admin | `rag_admin.py` | :7861 | 管理面板: 仪表盘/知识库/自检/学习统计 |
| MkDocs | `mkdocs.yml` | :8000 | 静态 Wiki 站点 |
| Ollama | `/mnt/d/ollama/bin/ollama` | :11434 | 本地 LLM (Qwen2.5:3b) |
| wxauto_bot | `wxauto_bot.py` | — | 微信机器人 (wxauto v7, 702行) |

### 4.2 一键启动

```bash
bash /home/hp/start_rag.sh   # 启动 Ollama + RAG Web UI + API + Admin
```

### 4.3 LLM 四通道容灾

| 优先级 | 通道 | 模型 | API | 延迟 |
|--------|------|------|-----|------|
| 1 (主) | MiMo-Flash | `xiaomi/mimo-v2-flash` | api.llm.mioffice.cn | ~1.5s |
| 2 (备) | MiMo-Pro | `xiaomi/mimo-v2-pro` | api.llm.mioffice.cn | ~0.5s |
| 3 (备) | DeepSeek | `deepseek-chat` | api.deepseek.com/v1 | ~2s |
| 4 (兜底) | Qwen-Local | `qwen2.5:3b` | localhost:11434 (Ollama) | ~50s |

Auto 模式: 按优先级尝试，跳过不健康的通道，全部失败则回退到纯检索。

---

## 5. 知识图谱 (v1.2 继承)

### 5.1 扫描概述

| 指标 | 数值 |
|------|------|
| 扫描文件总数 | 171,465 |
| 同名去重后 | 44,433 |
| 去重率 | 74% |
| 总数据量 | 138.0 GB |
| 知识图谱节点 | 47,004 |
| 知识图谱边 | 222,262 |

### 5.2 项目分布

| 项目 | 文件数 | 数据量 | 主要文件类型 |
|------|--------|--------|-------------|
| B2现场 | 12,134 | 773.6 MB | .tp(4920) .vr(1858) .sv(1669) |
| 互传文件 | 11,621 | 1.3 GB | .tp(3638) .ls(1881) .dt(1487) |
| B1现场 | 6,478 | 24.4 GB | .zip(1850) .tp(1057) .sv(635) |
| 未分类 | 5,958 | 71.2 GB | .jpeg(384) .json(355) .jpg(330) |
| 下载 | 3,056 | 2.2 GB | .json(1525) .jpg(1464) |
| 参考资料 | 391 | 10.4 GB | .pdf(166) .xlsm(74) .xlsx(60) |
| FANUC机器人 | 68 | 179.1 MB | .png(30) .xml(11) .htm(6) |

### 5.3 知识图谱结构

```
文件 ──belongs_to──> 目录
  │
  ├──has_ext──> 扩展名
  │
  ├──tagged_topic──> 主题 (技术/个人/办公/其他)
  │
  ├──tagged_domain──> 领域 (开发/前端/CAD/嵌入式/...)
  │
  └──in_project──> 项目 (B1现场/B2现场/Micar/...)

项目 ──covers_topic──> 主题
项目 ──covers_domain──> 领域
```

### 5.4 6维标签体系

| 维度 | 取值范围 | 说明 |
|------|---------|------|
| topic | 技术/个人/办公/其他 | 一级分类 |
| doc_type | 代码/文档/配置/数据/媒体/设计/压缩包 | 文档类型 |
| domain | 开发/前端/后端/嵌入式/AI/CAD/运维/数据/办公 | 技术领域 |
| priority | 高/中/低 | 重要程度 |
| time_tag | 长期有效/不确定/可能过时 | 时效性 |
| source | 个人创作/项目产出/下载资料/未知 | 来源 |

---

## 6. 试卷生成

### 6.1 现有试卷

| 试卷 | 路径 | 题数 | 质量 |
|------|------|------|------|
| B卷 | `/home/hp/FANUC考试_B卷_基于知识库.md` | — | 已完成 |
| C卷 | `/home/hp/FANUC考试_C卷_基于知识库.md` | 17题 | 100% 源PDF追溯，题型待打磨 |

### 6.2 出题脚本

| 脚本 | 说明 |
|------|------|
| `gen_exam.py` | 初代出题脚本 |
| `gen_exam_v2.py` | V2 出题 (改进) |
| `gen_exam_c_v2.py` | C卷专用出题脚本 |

### 6.3 C卷示例 (部分)

**填空题**:
1. 在T1模式下，机器人工具中心点和法兰盘中心点的速度被限制在____mm/sec以下。 → **250**
2. 伺服焊枪基本规格中，压力设定范围是0.0－____。 → **9999.9**

**判断题**:
1. 报警代码SRVO-001的报警严重度为SERVO，发生该报警时机器人会减速停止并断开伺服电源。 → **T**
2. 报警画面自动显示功能在系统/配置画面中标准设定为有效。 → **F**

### 6.4 待改进

- 题型多样化 (当前以填空/判断/单选为主)
- 难度分层 (初级/中级/高级)
- 自动化出题成熟度提升

---

## 7. 专利储备

### 7.1 FANUC RAG 专利矩阵 (第五版)

7 份专利交底书 (代理所模板格式)，覆盖 RAG 全链路创新:

| 编号 | 专利主题 | 核心创新点 |
|------|---------|-----------|
| 1 | Query 路由方法 | 报警码/型号自动识别→路由到专属检索通道 |
| 2 | 领域规则校验 RAG | 工业领域规则约束 LLM 输出 (安全规范/型号匹配) |
| 3 | 工程师反馈自学习 | 现场反馈闭环→自动优化检索权重 |
| 4 | 文档分块与实体提取 | 工业文档结构感知分块 + 实体元数据自动标注 |
| 5 | 实体倒排索引检索 | 型号/报警码/零件号倒排索引，毫秒级精确召回 |
| 6 | 多通道融合排序 | 语义+关键词+实体三路融合排序算法 |
| 7 | 版本比对自检 | 文档版本变更自动检测 + 知识库一致性自检 |

存储路径: `/mnt/c/Users/hp/Desktop/自研/rag-docs/专利储备/第五版/`

---

## 8. 关键路径速查

| 资源 | 路径 |
|------|------|
| 项目根目录 | `/home/hp/self-grow-wiki/` |
| 向量库 | `/home/hp/rag_chromadb/` (NOT `~/.hermes/chroma_db_v4`) |
| Collection 名 | `wiki_docs` (200,715 chunks) |
| BM25 索引 | `~/.hermes/scripts/bm25_index.pkl` |
| BGE 模型 | `~/.hermes/models/bge-m3` |
| Wiki 根目录 | `/mnt/d/知识库wiki/` |
| MkDocs 配置 | `/mnt/d/知识库wiki/mkdocs.yml` |
| 提取缓存 | `/mnt/d/知识库wiki/rag_data/extracted/` (460 JSON) |
| 分类结果 | `/mnt/d/知识库wiki/00_目录索引/classification_result.json` |
| 查询日志 | `/home/hp/rag_query_log.db` (SQLite) |
| 矛盾报告 | `/home/hp/kb_conflict_report.md` |
| Python venv | `/home/hp/mkdocs-env/` |
| Ollama 模型 | `/mnt/d/ollama/models/` |
| 微信机器人 | `/home/hp/wxauto_bot.py` (702行) |
| 专利储备 | `/mnt/c/Users/hp/Desktop/自研/rag-docs/专利储备/第五版/` |

---

## 9. 环境要求

| 项 | 要求 |
|----|------|
| OS | WSL2 on Windows |
| Python | 3.12, venv at `/home/hp/mkdocs-env/` |
| CUDA | driver 12080 与 PyTorch CUDA 13 不兼容 → 始终用 `CUDA_VISIBLE_DEVICES=""` CPU 推理 |
| ChromaDB | 必须在 Linux 文件系统 (`/home/hp/rag_chromadb/`) — NTFS 会导致 SQLite 压缩错误 |
| Ollama | 安装在 `/mnt/d/ollama/`，模型在 D 盘 (空间充足) |
| 激活 venv | `source /home/hp/mkdocs-env/bin/activate` |

---

## 10. 常见故障排查

### 10.1 hybrid_search 返回空

**根因 1: Python .pyc 缓存** (最常见)
```bash
rm -f ~/.hermes/scripts/__pycache__/rag_answer.cpython-*.pyc
```

**根因 2: CHROMA_PATH 错误**
```python
# ❌ 错误
CHROMA_PATH = os.path.expanduser("~/chroma_db_v4")
# ✅ 正确
CHROMA_PATH = "/home/hp/rag_chromadb"
```

**根因 3: Collection 名写错**
```python
# ❌ 旧版
coll = client.get_collection()
# ✅ 正确
coll = client.get_collection("wiki_docs")
```

### 10.2 BM25 缓存在沙箱中加载失败

`sandbox` 环境 `pickle.load` 会报 `Can't get attribute 'SimpleBM25'`，会自动重建缓存 (无害)。

### 10.3 Query 向量必须 L2 归一化

```python
# ✅ 正确
vec = model(**tokenizer([text])).last_hidden_state[:, 0].float().cpu().numpy()[0]
q_emb = vec / np.linalg.norm(vec)  # 手动归一化

# ❌ 错误
q_emb = vec  # 未归一化
```

### 10.4 首次查询慢 (>30s)

嵌入模型和 BM25 索引未预热。`rag_api.py` lifespan 已加入预热逻辑，冷启动后查询 <2s。

---

## 11. 工具脚本清单

### 11.1 质量审计脚本

| 脚本 | 功能 | 运行 |
|------|------|------|
| `p0_source_map.py` | 源文件完整性检查 | `CUDA_VISIBLE_DEVICES="" python3 p0_source_map.py` |
| `p0_cleanup_simple.py` | 污染清洗 | `CUDA_VISIBLE_DEVICES="" python3 p0_cleanup_simple.py` |
| `p1_dedup.py` | MinHash 版本去重 | `CUDA_VISIBLE_DEVICES="" python3 p1_dedup.py` |
| `p1_reassign_fast.py` | 来源校正 | `CUDA_VISIBLE_DEVICES="" python3 p1_reassign_fast.py` |
| `p2a_quality_score.py` | 质量评分 | `CUDA_VISIBLE_DEVICES="" python3 p2a_quality_score.py` |
| `p2b_ingest_gate.py` | 新 PDF 入库门禁 | `python3 p2b_ingest_gate.py /path/to/new.pdf` |
| `daily_audit.py` | 每日巡检 (cron 6:00) | 自动执行 |

### 11.2 核心服务脚本

| 脚本 | 功能 | 运行 |
|------|------|------|
| `start_rag.sh` | 一键启动全部服务 | `bash start_rag.sh` |
| `rag_web.py` | Gradio Web UI | `CUDA_VISIBLE_DEVICES="" python3 rag_web.py --port 7860` |
| `rag_api.py` | FastAPI HTTP API | `CUDA_VISIBLE_DEVICES="" python3 rag_api.py` |
| `rag_admin.py` | 管理面板 | `CUDA_VISIBLE_DEVICES="" python3 rag_admin.py --port 7861` |
| `rag_core.py` | 核心检索+生成 (被其他脚本 import) | — |
| `rag_builder.py` | 向量库构建/查询/统计 | `CUDA_VISIBLE_DEVICES="" python3 rag_builder.py build|query|stats` |

### 11.3 数据处理脚本

| 脚本 | 功能 |
|------|------|
| `rag_builder_ocr.py` | OCR 增强 PDF 导入 |
| `rag_import_fanuc.py` | FANUC 增量导入 (版本感知) |
| `import_edoc.py` | edoc JSON 批量导入 |
| `doc_classifier.py` | 文档分类 |
| `generate_mkdocs.py` | MkDocs 站点生成 |
| `kb_selfcheck.py` | 知识库矛盾自检 |

### 11.4 试卷生成脚本

| 脚本 | 功能 |
|------|------|
| `gen_exam.py` | 初代出题 |
| `gen_exam_v2.py` | V2 出题 |
| `gen_exam_c_v2.py` | C卷专用出题 |

---

## 12. 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | 2026-04-20 | 初始 RAG 系统搭建，229,872 vectors |
| v1.1 | 2026-04-20 | 完善文档结构 |
| v1.2 | 2026-04-27 | 新增文件扫描 + 6维打标 + 知识图谱 |
| **v2.0** | **2026-05-03** | **4σ 质量审计 (200,715 vectors, 95.5% 优)；4通道 LLM 容灾 (新增 DeepSeek)；品牌过滤 + 关键词强制召回；每日巡检 cron；质检门禁；试卷生成 (C卷)** |
| **v2.1** | **2026-05-07** | **记忆恢复版：补充专利储备(7份交底书)、关键路径补全(wxauto_bot/专利路径)、微信机器人集成细节** |

---

*文档由 Hermes Agent 生成，数据来自 2026-05-07 项目最新状态*
*知识库质量审计完成于 2026-05-01，14 脚本已 push 到 GitHub*
