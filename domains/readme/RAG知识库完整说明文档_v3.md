# RAG 智能问答 — FANUC 工业知识库 完整说明文档 v3

> 全生命周期复盘 | 2026-07-01
> 上一版: v2 (2026-04, 22K vectors, 企业微信)
> 当前: v3 (2026-07, 200K vectors, 飞书接入, SAG+OKF 混合检索)

---

## 目录

1. [项目概述与最终成果](#一项目概述)
2. [系统架构 (RAG+SAG+OKF)](#二系统架构)
3. [向量库构建](#三向量库构建)
4. [SAG-Lite 混合检索引擎](#四sag-lite)
5. [飞书接入方案](#五飞书接入)
6. [飞轮自检工作流](#六飞轮自检)
7. [OKF 知识沉淀](#七okf)
8. [踩坑记录 (v2→v3 新增)](#八踩坑记录)
9. [迁移 SOP & 预防清单](#九迁移sop)
10. [文件清单](#十文件清单)
11. [快速使用](#十一快速使用)
12. [后续规划](#十二后续规划)

---

## 一、项目概述

### 1.1 项目目标

为 FANUC 工业机器人领域构建 **RAG + SAG + OKF 三层知识库**:

- **L1 检索**: ChromaDB 向量检索 (200K chunks), 语义兜底
- **L2 关系**: SAG-Lite SQLite entity 引擎, 精确匹配+关联链 (0.01s)
- **L3 沉淀**: Google OKF v0.1 Markdown Concepts, 人+Agent 共同维护

### 1.2 最终成果 (v3 vs v2)

| 指标 | v2 (2026-04) | v3 (2026-07) |
|------|-------------|-------------|
| 向量数 | 22,181 | **200,835** |
| 嵌入模型 | BGE-base-zh-v1.5 | BGE-base-zh-v1.5 |
| 向量库 | ChromaDB, ~116MB | ChromaDB, ~3GB |
| LLM 通道 | 3 通道 | 3 通道 (mizu/qwen/minimax) |
| 接入平台 | 企业微信 | **飞书 (Hermes Gateway + MCP)** |
| Entity 索引 | 无 | **63K entities, 173K 关系边** |
| 检索速度 | 2.8s | **26ms** (SAG entity) |
| 知识沉淀 | 无 | **5 OKF Concepts** |
| 质量自检 | 无 | **200条飞轮, 88% 命中** |
| SYSTEM_PROMPT | 透传层 (禁止归纳) | **技术顾问 (允许归纳+标来源)** |

### 1.3 演进路线

```
2026-04  RAG v2    22K vectors, 企业微信, Gradio Web
2026-06  RAG v3    200K vectors, 飞书 MCP, SYSTEM_PROMPT v2
2026-06  +SAG      Zleap-AI/SAG 论文 → SAG-Lite SQLite 实现
2026-06  +飞轮      32条→200条自检, 7维评估
2026-06  +OKF      Google OKF v0.1, 5 Concepts 沉淀
```

---

## 二、系统架构

```
┌──────────────────────────────────────────────────┐
│              接入层                                │
│  飞书 Bot / Hermes CLI / rag_web.py (Gradio)      │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│              MCP Server (rag_mcp_server.py)        │
│  ┌──────────┬──────────────┬──────────────────┐  │
│  │ ① OKF    │ ② SAG-Lite   │ ③ ChromaDB       │  │
│  │ Concepts │ entity JOIN  │ 向量检索          │  │
│  │ (优先)   │ (精确,0.01s) │ (兜底,2.8s)      │  │
│  └──────────┴──────────────┴──────────────────┘  │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│              LLM 生成层                            │
│  SYSTEM_PROMPT: "技术顾问" (三通道容灾)            │
│  规则: 直接回答 → 标来源 → 标缺口                   │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│              飞轮自检层                             │
│  200条 × 7维, 触发词 "飞轮"                        │
│  指标: exact=88% hop=83% speed=26ms               │
└──────────────────────────────────────────────────┘
```

---

## 三、向量库构建

### 3.1 脚本: self-grow-wiki/rag_builder.py

```python
# 全流程: 文本提取 → 分块 → 向量嵌入 → 入库
python3 rag_builder.py --full

# 仅提取文本
python3 rag_builder.py --extract-only

# 仅构建向量库
python3 rag_builder.py --build-only
```

### 3.2 参数

| 参数 | 值 |
|------|-----|
| 分块大小 | 800 字符 |
| 重叠 | 100 字符 |
| 每文件最大 chunk | 100 |
| 嵌入模型 | BAAI/bge-base-zh-v1.5 |
| 向量维度 | 768 |
| 相似度 | cosine |
| 批量入库 | 256 条/批 |

### 3.3 文件格式支持

| 格式 | 提取器 |
|------|--------|
| PDF | pymupdf4llm |
| DOCX | python-docx |
| PPTX | python-pptx |
| XLSX | openpyxl |
| TXT/MD | 直接读取 |

---

## 四、SAG-Lite 混合检索引擎

### 4.1 来源

- 论文: arXiv 2606.15971 (Zleap-AI, 2026-06-14)
- 开源: Zleap-AI/SAG (⭐5,740)
- 理念: chunk→event+entities→SQL JOIN 动态构建关系

### 4.2 实现 (Docker 不可用, SQLite 替代)

| 组件 | 原 SAG | SAG-Lite |
|------|--------|---------|
| 数据库 | PostgreSQL+pgvector | SQLite |
| 后端 | TypeScript+Fastify | Python |
| Entity 提取 | LLM | 正则 (9类, 55s) |

### 4.3 Entity 覆盖

| 类型 | 唯一值 | 示例 |
|------|--------|------|
| signal | 2,704 | DI[425], DO[429] |
| manual | 231 | B-83284CM |
| alarm_code | 470 | SRVO-066 |
| model_num | 188 | R-30iB |
| safety | 21 | FENCE, DCS |
| concept | 38 | 零点标定, 碰撞检测 |
| procedure | 24 | 更换电池, KAREL |
| alarm_noprefix | 14 | BZAL, CSAL, DTERR |

关系边: 173,721 条

### 4.4 混合检索策略

```
Phase 1: entity-exact (SQL JOIN, 0.01s) → score 0.95
Phase 2: entity-hop   (entity_edges, 0.01s) → score 0.75-0.85
Phase 3: 向量兜底     (ChromaDB, 2.8s)
合并: exact > hop > vector
```

### 4.5 性能

| 场景 | 纯向量 | SAG | 加速 |
|------|--------|-----|------|
| 单报警 SRVO-066 | 2.8s | 0.008s | 350x |
| 双报警 SRVO-062+075 | 2.5s | 0.008s | 312x |
| 报警+信号 SRVO-066+DI425 | 16.9s | 0.06s | 285x |
| 200条批量 | 70s | **5.3s** | 13x |

---

## 五、飞书接入方案

### 5.1 架构

```
飞书消息 → Hermes Gateway (hermes_cli.main gateway run)
           → Feishu Plugin (hermes_plugins.feishu_platform.adapter)
           → Agent Session (run_agent.py)
           → MCP Tool: rag_search / rag_answer
           → rag_mcp_server.py (SAG + ChromaDB)
```

### 5.2 关键配置

| 组件 | 路径/命令 |
|------|----------|
| Gateway | `~/.hermes/hermes-agent/.venv/bin/python -m hermes_cli.main gateway run` |
| MCP Server | `~/mkdocs-env/bin/python3 rag_mcp_server.py` |
| Feishu Adapter | `hermes_plugins.feishu_platform.adapter` (WebSocket 模式) |

### 5.3 服务管理

```bash
# 查看状态
pgrep -f "hermes_cli.main.*gateway"
pgrep -f rag_mcp_server.py

# Gateway 重启 (代码更新后必须)
kill <gateway_pid>  # systemd Restart=on-failure 自动拉起

# MCP Server 重启 (SYSTEM_PROMPT 更新后必须)
kill <mcp_pid>      # Gateway 自动拉起新实例
```

---

## 六、飞轮自检工作流

### 6.1 触发

飞书/Hermes 发送 **"飞轮"** → 自动运行 200 条查询 → 返回评估报告

### 6.2 评估维度

| 维度 | 说明 | 当前值 |
|------|------|--------|
| speed | 检索速度 | 26ms 平均 |
| exact | entity 精确匹配率 | 88% |
| hop | 跨文档关联率 | 83% |
| sources | 来源引用率 | 100% |
| recall | 关键词召回 | 90% |
| boundary | 边界降级正确 | 100% |

### 6.3 脚本

- 入口: `D:\MD\RAG知识库\rag_flywheel.py`
- 核心: `rag_flywheel_eval.py` (200条 × 7维)
- 数据库: `SAG-poc/sag_lite.db` (226MB)

---

## 七、OKF 知识沉淀

### 7.1 Google Open Knowledge Format v0.1

- 发布: 2026-06-15, GoogleCloudPlatform/knowledge-catalog ⭐5,740
- 格式: Markdown + YAML frontmatter + 目录层级 + markdown 链接
- 定位: L3 知识沉淀层 (人+Agent 共同维护)

### 7.2 首批 Concepts

```
D:\MD\RAG知识库\okf_bundle\
├── index.md              # 知识库根
├── alarms/
│   ├── SRVO-066.md       # CSAL ROM 异常
│   └── SRVO-062.md       # BZAL 电池
├── signals/index.md      # DI/DO ↔ VR
└── safety/index.md       # 安全功能对比
```

飞轮发现缺口 → Agent 自动生成 → 人工审核 → git commit。

---

## 八、踩坑记录 (v2→v3 新增)

### 坑 1: SYSTEM_PROMPT "透传层" 导致 LLM 反问用户

**症状**: 检索碎片化时 LLM 反复问"你想往哪个方向？"
**根因**: prompt 中 `禁止跨文档归纳、对比表、推断结论`
**修复**: `透传层→技术顾问`, 允许归纳+标来源, 明确禁止反问

### 坑 2: Gateway 更新代码后 ImportError

**症状**: `cannot import name 'agent_browser_runnable' from 'hermes_constants'`
**根因**: Gateway 进程 sys.modules 缓存旧模块, 子进程无法找到新函数
**修复**: 代码更新后必须 SIGTERM → systemd 重启 Gateway。仅重启 MCP server 不够。

### 坑 3: ChromaDB 路径静默错误

**症状**: rag_core.retrieve() 返回空或错误 collection
**根因**: CHROMA_PATH 指向 `/mnt/d/Eric/知识库/chroma_db_v4` (旧路径, Windows分区)
**修复**: → `~/rag_chromadb` (Linux 文件系统), COLLECTION → `wiki_docs`

### 坑 4: 嵌入模型维度不匹配

**症状**: `InvalidArgumentError: expecting 768, got 1024`
**根因**: rag_core.py 加载 BGE-m3(1024-dim), 但向量库用 BGE-base-zh-v1.5(768-dim) 构建
**修复**: embedding model → BGE-base-zh-v1.5

### 坑 5: Docker 网络不可达

**症状**: `docker pull` 全部超时
**根因**: DOCKER_HOST=tcp://localhost:2375 (Docker Desktop 未运行), Unix socket daemon 无代理
**修复**: SAG-Lite 用 SQLite 替代 PostgreSQL, 不依赖 Docker

### 坑 6: LLM 变量/IO 混淆

**症状**: 问"变量"回答 DI[n]/DO[n] (信号), 而非 VR 文件
**根因**: 纯向量检索无法区分 concept (信号 vs 变量)
**修复**: SAG entity-exact 精确匹配 + signal entity 类型标记

### 坑 7: rag_mcp_server 重启后未加载新 SYSTEM_PROMPT

**症状**: 修改 rag_core.py 后飞书回答策略不变
**根因**: rag_mcp_server 进程 import rag_core 时缓存 SYSTEM_PROMPT
**修复**: kill rag_mcp_server → Gateway 自动拉起 → 新进程加载新 prompt

### 坑 8: 飞轮首次执行冷启动慢

**症状**: 第一条查询 35s
**根因**: 嵌入模型 (BGE) 首次加载到 GPU
**缓解**: SAG 绕过向量检索, 仅 26ms; 可考虑服务常驻预热

---

## 九、迁移 SOP & 预防清单

### 9.1 迁移后必检 (按顺序, 每项通过才能继续)

```
□ 1. ChromaDB 路径: rag_core.CHROMA_PATH = ~/rag_chromadb
□ 2. Collection 名: rag_core.COLLECTION = "wiki_docs"
□ 3. 嵌入模型: BGE-base-zh-v1.5 (768-dim), 非 BGE-m3
□ 4. 同义词表: synonyms.json ≥ 56 条
□ 5. SAG DB: sag_lite.db 可访问, entities_v2 有记录
□ 6. SYSTEM_PROMPT: "技术顾问" 非 "透传层"
□ 7. Gateway 重启: kill + 等 systemd 拉新
□ 8. MCP 重启: kill rag_mcp_server → Gateway 拉新
□ 9. 飞轮验证: python3 rag_flywheel.py, 通过率 ≥ 85%
□ 10. 飞书 E2E: 发送 SRVO-066 → 检查回答质量
```

### 9.2 10 大陷阱预防速查

| # | 陷阱 | 预防 |
|---|------|------|
| 1 | LLM prompt 过严 → 反问 | 检查 prompt 无"透传层"无"禁止归纳" |
| 2 | LLM 接入无 SOP | 迁移后跑 smoke 20 条核对 LLM 输出 |
| 3 | Gateway 缓旧模块 | 代码更新后必重启 Gateway |
| 4 | ChromaDB 路径错 | 确认 CHROMA_PATH + COLLECTION |
| 5 | 嵌入维度错 | 768-dim BGE-base-zh-v1.5 |
| 6 | Docker 不可用 | SAG-Lite SQLite 替代 |
| 7 | NTFS 文件系统 | ChromaDB 放 Linux 分区 (~/rag_chromadb) |
| 8 | 同义词缺失 | synonyms.json ≥ 56 条 |
| 9 | 飞轮断连 | 确认脚本路径 + venv 正确 |
| 10 | LLM API 通道全挂 | 至少一个通道可用 |

### 9.3 迁移后验证命令

```bash
# 1. 检索 pytest (5条)
python3 -c "
from sag_hybrid import hybrid_search
for q in ['SRVO-066','SRVO-062','R-30iB SRVO-050','DI425','零点标定']:
    r=hybrid_search(q,3)
    print(f'{q}: {len(r)} results, exact={any(x["method"]=="entity-exact" for x in r)}')
"

# 2. SYSTEM_PROMPT 断言
python3 -c "import rag_core; assert '技术顾问' in rag_core.SYSTEM_PROMPT"

# 3. 飞轮
python3 D:\\MD\\RAG知识库\\rag_flywheel.py
```

---

## 十、文件清单

| 文件 | 路径 | 用途 |
|------|------|------|
| rag_core.py | self-grow-wiki/ | RAG 核心 (检索+LLM生成+SYSTEM_PROMPT) |
| rag_mcp_server.py | self-grow-wiki/ | MCP Server (飞书接入) |
| synonyms.json | self-grow-wiki/ | 同义词表 (56条) |
| sag_hybrid.py | SAG-poc/ | SAG 混合检索引擎 |
| sag_lite.db | SAG-poc/ | Entity 索引 DB (226MB) |
| rag_flywheel.py | D:\\MD\\RAG知识库\\ | 飞轮入口 |
| rag_flywheel_eval.py | D:\\MD\\RAG知识库\\ | 飞轮评估核心 |
| RAG-SAG-OKF-演进报告.md | D:\\MD\\RAG知识库\\ | 完整测试数据 |
| okf_bundle/ | D:\\MD\\RAG知识库\\ | OKF Concepts |
| RAG知识库README_v2.md | D:\\MD\\RAG知识库\\ | 本文档 |

---

## 十一、快速使用

```bash
# 飞书查询
发送 "SRVO-066 处理方法" 到飞书机器人

# 命令行检索
python3 -c "from rag_core import retrieve; print(retrieve('SRVO-066',5))"

# 飞轮自检
飞书发送 "飞轮"

# 启动服务 (通常已运行)
pgrep -f "gateway run"   # Hermes Gateway
pgrep -f rag_mcp_server  # RAG MCP

# 停止服务
kill <gateway_pid>       # Gateway
kill <mcp_pid>           # MCP Server
```

---

## 十二、后续规划

| 优先级 | 事项 | 预期 |
|--------|------|------|
| P0 | MHGRIPDT/MHMENU VR 入库 | 解决变量查询 |
| P0 | 安全功能 OKF Concepts 填充 | 提高 C01 召回 |
| P1 | Docker 网络修复 → SAG 完整版 | pgvector 替代 SQLite |
| P1 | OKF 自动生成 Pipeline | 飞轮缺口 → LLM → OKF → git |
| P2 | 飞轮 cron 每日定时 | 持续质量监控 |
| P2 | LLM 答案质量自动评分 | 补充飞轮 LLM 维度 |
| P3 | 多语言支持 (英文手册 → 中文回答) | 扩大受众 |
