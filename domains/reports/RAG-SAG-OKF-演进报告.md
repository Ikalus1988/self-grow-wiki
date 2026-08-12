# RAG → SAG → OKF 知识库演进报告

> 生成: 2026-06-30 | 环境: WSL2 + Hermes Gateway + ChromaDB 200K docs

---

## 概述

本报告记录了 FANUC 工业机器人知识库从纯 RAG 到 SAG 混合检索再到 OKF 知识沉淀的三阶段演进。

---

## 1. 基线: 纯 RAG (ChromaDB + BGE)

### 架构
```
用户查询 → rag_core.retrieve() → ChromaDB 向量检索 → LLM → 回答
```
- 向量库: wiki_docs, 200,835 chunks
- 嵌入模型: BGE-base-zh-v1.5 (768-dim)
- LLM: 三通道 (mizu → qwen → gemma)

### 飞轮自检基线 (32条, 8维)

| 维度 | 通过率 | 说明 |
|------|--------|------|
| 检索速度 <20s | 97% | 平均 2.8s |
| 来源引用 | 100% | |
| 召回精度 | 90% | |
| 相关性 | 100% | |
| 报警代码 | 92% | |
| 操作流程 | 100% | |
| 跨文档归纳 | **60%** | 核心缺陷 |

### 发现的系统性问题

| 问题 | 影响 |
|------|------|
| 变量/IO混淆 | DI信号 vs VR变量不分 |
| SYSTEM_PROMPT"透传层"陷阱 | 反问用户而非直接回答 |
| 跨文档无法关联 | SRVO-066↔SRVO-088无法召回 |
| 短代码语义弱 | SRVO-066被相似代码挤占top-K |

---

## 2. SAG 混合检索

### 来源
- 论文: arXiv 2606.15971 (Zleap-AI, 2026-06-14)
- 开源: Zleap-AI/SAG (⭐5,740)
- 微信文章: SAG+LLM WIKI — 最强知识库

### 核心理念
```
传统: chunk → embedding → 相似 → top-K
SAG:  chunk → event+entities → SQL JOIN → 精确关联
```
不预建全局图, 查询时SQL动态构建局部关系。

### SAG-Lite 实现 (Docker不可用, SQLite替代)

| 组件 | 原SAG | SAG-Lite |
|------|-------|---------|
| 数据库 | PostgreSQL+pgvector | SQLite |
| Entity提取 | LLM | 正则9类 55s |

### Entity覆盖 (63K条, 9类型)

| 类型 | 唯一值 | 记录 | 示例 |
|------|--------|------|------|
| signal | 2,704 | 20,390 | DI[425] |
| manual | 231 | 33,338 | B-83284CM |
| alarm_code | 470 | 4,379 | SRVO-066 |
| model_num | 188 | 4,745 | R-30iB |
| safety | 21 | 8,583 | FENCE,DCS |
| concept | 38 | 7,478 | 零点标定 |
| procedure | 24 | 4,758 | 更换电池 |

关系边: 173,721条

### 性能对比

| 查询 | 纯向量 | SAG | 加速比 |
|------|--------|-----|--------|
| SRVO-066+DI425 | 16.9s | 0.06s | 285x |
| SRVO-062+SRVO-075 | 2.5s | 0.008s | 312x |
| R-30iB+SRVO-050 | 2.0s | 0.002s | 1000x |

### Smoke测试 (20条)

| | 扩展前 | 扩展后 |
|---|--------|--------|
| entity-exact | 45% | 80% |
| entity-hop | 45% | 80% |
| 平均速度 | 20ms | 24ms |

---

## 3. SYSTEM_PROMPT修复

原: `你是"透传层"...禁止归纳` → LLM反问用户
修: `你是"技术顾问"...允许归纳,标来源,禁止反问`

| | 修复前(TCP/IP) | 修复后(高惯量模式) |
|---|--------|--------|
| 回答轮次 | 3轮反问 | 1轮直接 |
| 结构 | 碎片dump | 4段分层+表格 |
| 跨文档归纳 | ❌ | ✅ 7PDF→1表 |
| 量化数据 | ❌ | ✅ 260→460 kg/m² |

---

## 4. OKF集成

- Google Cloud 2026-06-15 v0.1 (GoogleCloudPlatform/knowledge-catalog ⭐5,740)
- Markdown+YAML+目录+交叉链接

```
L1检索(事实): RAG — ChromaDB
L2关系(链条): SAG — SQLite entity JOIN
L3沉淀(理解): OKF — Markdown Concepts
```

首批5个Concept: SRVO-066, SRVO-062, 信号变量区分, 安全功能对比

---

## 5. 终态架构

```
飞书/Hermes
  rag_mcp_server
    ├ OKF Concepts (优先, 0.03s)
    ├ SAG entity (精确, 0.01s)
    └ ChromaDB向量 (兜底, 2.8s)
  飞轮自检 (32条×8维, "飞轮"触发)
```

---

## 6. 关键指标演进

| 指标 | RAG | +SAG | +PROMPT | +OKF |
|------|-----|------|---------|------|
| 单报警精确率 | 60% | 100% | — | — |
| 跨文档关联 | ❌ | ✅ | — | — |
| 检索速度 | 2.8s | 0.02s | — | — |
| 反问用户 | ✅ | — | ❌ | — |
| 跨文档归纳 | 60% | — | 100% | — |
| 人可读引用 | ❌ | — | — | okf:// |
| 知识沉淀 | ❌ | — | — | ✅ |

---

## 7. 交付清单

| 交付物 | 位置 |
|--------|------|
| 飞轮脚本 | D:\\MD\\RAG知识库\\rag_flywheel.py |
| SAG引擎 | SAG-poc/sag_hybrid.py |
| SAG DB | SAG-poc/sag_lite.db (226MB) |
| OKF Bundle | D:\\MD\\RAG知识库\\okf_bundle\\ |
| SYSTEM_PROMPT | self-grow-wiki/rag_core.py |
| 同义词表 | self-grow-wiki/synonyms.json |
| Lessons | MisakaNet/lessons/contrib/ |
| GitHub | Ikalus1988/self-grow-wiki (main) |
