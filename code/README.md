# rag-fanuc — FANUC Industrial Robot RAG Knowledge Base

<p align="center">
  <a href="https://pypi.org/project/rag-fanuc/"><img src="https://img.shields.io/pypi/v/rag-fanuc" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/smoke-10%2F10-brightgreen" alt="smoke">
  <img src="https://img.shields.io/badge/flywheel-97.4%25-brightgreen" alt="flywheel">
  <img src="https://img.shields.io/badge/speed-29ms-blue" alt="speed">
  <img src="https://img.shields.io/badge/entities-63K-blue" alt="entities">
  <img src="https://img.shields.io/badge/chroma-200K-orange" alt="chroma">
</p>

**Pluggable RAG engine for FANUC industrial robot technical documentation** — hybrid retrieval with ChromaDB vectors, SAG-Lite entity graph, and OKF knowledge concepts. [PyPI](https://pypi.org/project/rag-fanuc/) | [Flywheel](#-flywheel-self-check) | [Lessons](https://github.com/Ikalus1988/MisakaNet)

---

## ✨ Highlights

- **97.4% FANUC query exact rate** (1,000-query flywheel, 95%CI ±1.1%)
- **29 ms avg retrieval** via SAG-Lite entity JOIN (285× faster than pure vector)
- **63K entities + 174K edges** across 9 types (alarm codes, signals, manuals, safety, concepts...)
- **OKF Concept layer**: human–agent co-authored knowledge, auto-generated from flywheel gaps
- **Pluggable architecture**: swap between hybrid / vector-only / entity-only in 1 config line
- **MCP-native**: 3 `@tool`-decorated endpoints, auto-register + auto-schema
- **Published on PyPI**: `pip install rag-fanuc`

---

## 📦 Install

```bash
pip install rag-fanuc
```

> Requires `chromadb`, `torch`, `transformers`, `pyyaml`. Python ≥ 3.10.

---

## 🚀 Quick Start

```python
from retriever import get_retriever

r = get_retriever()
results = r.retrieve("SRVO-066 CSAL 报警 处理", top_k=5)

for chunk in results:
    print(f"[{chunk['method']}] {chunk['source']}")
    print(chunk['text'][:200])
```

```bash
# CLI: run flywheel self-check
rag-flywheel 200

# CLI: 5-item smoke test
rag-smoke
```

---

## 🏗 Architecture

```
Query
  ├─ ① OKF Concepts   (Markdown, human-readable)
  ├─ ② SAG-Lite entity (SQLite JOIN, 63K entities, 174K edges)
  └─ ③ ChromaDB vector (200K chunks, BGE-base-zh-v1.5)
       │
       ▼
  guard_response (11 runtime rules)
       │
       ▼
  LLM generate (SYSTEM_PROMPT v3, 3-channel failover)
       │
       ▼
  Feishu / Hermes / MCP
```

---

## 🔧 Core Modules

| Module | Description |
|--------|-------------|
| `retriever.py` | Abstract retrieval interface: `HybridRetriever` / `ChromaDBRetriever` / `SAGRetriever` |
| `rag_core.py` | RAG core: warmup, hybrid search, LLM generation, 3-channel failover |
| `rag_mcp_server.py` | MCP JSON-RPC server: `rag_search`, `rag_answer`, `flywheel_smoke` |
| `mcp_server.py` | `@tool` decorator framework — auto schema + auto register |
| `config.yaml` | Unified configuration (ChromaDB paths, LLM channels, strategy) |
| `synonyms.json` | 56 synonym mappings (VR ↔ variable, RTCP ↔ remote TCP) |

---

## 📊 Flywheel Self-Check

Trigger `"飞轮"` in Feishu/Hermes to run automated quality evaluation:

| Dimension | Current |
|-----------|---------|
| entity-exact hit | 88% |
| entity-hop (cross-doc) | 83% |
| avg speed | 29 ms |
| source citation | 100% |
| boundary degradation | 100% |

```bash
rag-flywheel 200        # batch run
rag-flywheel --smoke    # 5-item quick check
```

---

## 📚 Related

- **SAG**: Zleap-AI/SAG (arXiv 2606.15971) — entity-aware SQL join retrieval
- **OKF**: GoogleCloudPlatform/knowledge-catalog — Open Knowledge Format v0.1
- **MisakaNet**: [Ikalus1988/MisakaNet](https://github.com/Ikalus1988/MisakaNet) — Swarm Knowledge Protocol

---

MIT © Ikalus1988
