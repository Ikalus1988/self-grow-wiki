# FANUC RAG 知识库 — 系统手册 v2

> 最后更新: 2026-07-01
> 基线: 200,835 chunks / wiki_docs / BGE-base-zh-v1.5
> 架构: RAG (ChromaDB) + SAG-Lite (SQLite entity) + OKF (Markdown Concepts)

---

## 1. 系统架构

```
飞书 / Hermes CLI
  │
  ▼
rag_mcp_server (Python MCP)
  ├── ① OKF Concepts   (Markdown, 人可读, 0.03s)
  ├── ② SAG-Lite entity (SQLite, entity-exact+hop, 0.01s)
  └── ③ ChromaDB 向量   (BGE-base-zh-v1.5, 语义兜底, 2.8s)
  │
  ▼
LLM 生成 (SYSTEM_PROMPT: "技术顾问", 三通道容灾)
  │
  ▼
飞轮自检 (200条 × 7维, 触发词: "飞轮")
```

## 2. 核心指标 (2026-07-01)

| 指标 | 值 |
|------|-----|
| 单报警精确率 | 88% (entity-exact) |
| 跨文档关联 | 83% (entity-hop) |
| 检索速度 | 26ms 平均 (SAG) / 2.8s (向量冷启动) |
| 来源引用率 | 100% |
| LLM反问率 | 0% (SYSTEM_PROMPT 已修复) |
| 知识沉淀 | 5 OKF Concepts + 飞轮自动生成 |

## 3. 文件分布

| 组件 | 路径 | 说明 |
|------|------|------|
| 向量库 | ~/rag_chromadb/ | ChromaDB, 3GB |
| SAG DB | SAG-poc/sag_lite.db | SQLite, 226MB, 63K entities |
| OKF Bundle | D:\\MD\\RAG知识库\\okf_bundle\\ | 5 Concepts |
| RAG 代码 | self-grow-wiki/ | rag_core.py, rag_mcp_server.py |
| 飞轮脚本 | D:\\MD\\RAG知识库\\rag_flywheel.py | 自检入口 |
| 同义词表 | self-grow-wiki/synonyms.json | 56条 |
| PDF源文件 | /mnt/d/知识库wiki/ | 待入库原始PDF |
| 演进报告 | D:\\MD\\RAG知识库\\RAG-SAG-OKF-演进报告.md | 完整测试数据 |

## 4. 关键修复记录

| 问题 | 根因 | 修复 | 日期 |
|------|------|------|------|
| LLM 反问用户选方向 | SYSTEM_PROMPT "透传层" 禁止归纳 | → "技术顾问", 允许归纳, 禁止反问 | 0630 |
| 变量/IO 混淆 | 纯向量检索无法区分 signal vs variable | SAG entity-exact 精确匹配 | 0630 |
| 跨文档无关联 | 向量相似度无法召回 alarm 间引用 | SAG entity-hop (173K边) | 0630 |
| Gateway ImportError | sys.modules 缓存旧模块 | 重启 gateway 进程 | 0629 |
| rag_core CHROMA_PATH 错误 | 指向 /mnt/d/Eric/... 旧路径 | → ~/rag_chromadb | 0629 |
| 嵌入维度不匹配 | BGE-m3(1024) vs DB(768) | → BGE-base-zh-v1.5 | 0629 |
| 首次检索 35s | 冷启动加载模型 | 可接受, SAG 绕过 | 0629 |

---

## 5. 迁移 SOP & 预防清单

### 5.1 迁移后必检项 (按顺序)

如果知识库从当前环境迁移到新机器, 按此顺序逐条验证 (每项通过才能继续):

```
□ 1. ChromaDB 路径: rag_core.py CHROMA_PATH 指向正确目录
□ 2. Collection 名称: 确认 COLLECTION="wiki_docs" (不是 edoc_v10_m3)
□ 3. 嵌入模型: BGE-base-zh-v1.5 (768-dim), 不是 BGE-m3(1024)
□ 4. 同义词表: synonyms.json 包含 56 条映射 (特别是变量/VR/IO)
□ 5. rag_mcp_server: 启动时 _SAG_AVAILABLE=True (SAG-Lite 路径正确)
□ 6. SAG-Lite DB: sag_lite.db 可访问, entities_v2 表有 63K 记录
□ 7. Gateway 重启: 迁移代码后必须重启 gateway (清除 sys.modules 缓存)
□ 8. MCP server 重启: rag_mcp_server 需重启加载新 SYSTEM_PROMPT
□ 9. SYSTEM_PROMPT: 确认是"技术顾问"不是"透传层"
□ 10. 飞轮验证: python3 rag_flywheel.py 通过率 >= 85%
```

### 5.2 这次出现过的陷阱 & 预防

| # | 陷阱 | 症状 | 预防 |
|---|------|------|------|
| 1 | **LLM SYSTEM_PROMPT 约束过严** | LLM 反问用户、不敢归纳 | 迁移后检查 prompt 中无"透传层"、无"禁止归纳" |
| 2 | **LLM 无 SOP 接入流程** | rag_mcp_server 启动失败/import 错误 | 迁移后跑 smoke 20 条, 逐条核对 LLM 输出质量 |
| 3 | **Gateway 进程缓旧模块** | ImportError 新函数不存在 | 代码更新后必须 SIGTERM → 等 systemd 重启 |
| 4 | **ChromaDB 路径静默错误** | 检索返回空/错误 collection | 迁移后确认 rag_core.CHROMA_PATH + COLLECTION |
| 5 | **嵌入模型维度不匹配** | ChromaDB InvalidArgumentError (768 vs 1024) | 确认 BGE-base-zh-v1.5, 不是 BGE-m3 |
| 6 | **Docker 网络不可达** | 无法 pull pgvector 镜像 | 优先用 SAG-Lite (SQLite), 不依赖 Docker |
| 7 | **WSL ntfs 文件系统** | ChromaDB 锁/性能问题 | ChromaDB 放在 Linux 文件系统 (~/rag_chromadb), 不在 /mnt/ |
| 8 | **同义词表缺失** | 变量/IO 混淆再次出现 | 迁移后确认 synonyms.json ≥ 56 条 |
| 9 | **飞轮断连** | 无法触发"飞轮" | 确认 rag_flywheel.py 路径 + Python venv 正确 |
| 10 | **LLM API 通道不可用** | 答案质量下降/超时 | 确认三通道 (mizu/qwen/minimax) 至少一个可用 |

### 5.3 迁移后验证命令

```bash
# 1. 检索验证 (5 条 smoke)
python3 -c "
from sag_hybrid import hybrid_search
tests=['SRVO-066 处理','SRVO-062 BZAL','R-30iB SRVO-050','DI425 信号','零点标定']
for q in tests:
    r=hybrid_search(q,3)
    print(f'{q}: {len(r)} results, methods={set(x["method"] for x in r)}')
"

# 2. SYSTEM_PROMPT 验证
python3 -c "
import rag_core
assert '技术顾问' in rag_core.SYSTEM_PROMPT, 'SYSTEM_PROMPT 错误!'
print('✅ SYSTEM_PROMPT OK')
"

# 3. 飞轮快速验证
python3 D:\MD\RAG知识库\rag_flywheel.py
```

---

## 6. 启动流程

```bash
# 1. 确认 gateway 运行
pgrep -f "hermes_cli.main.*gateway"

# 2. 确认 rag_mcp_server 运行
pgrep -f rag_mcp_server.py

# 3. 飞书发送测试查询

# 4. 定期飞轮
# 飞书发送 "飞轮" → 自动返回评估报告
```

---

## 7. 已知限制

| 限制 | 影响 | 缓解 |
|------|------|------|
| MHGRIPDT/MHMENU VR 未入库 | 变量查询召回弱 | OKF signals/ 已标注, 待补充 |
| 安全功能跨文档归纳弱 | C01 仅 60% | OKF safety/ 已建框架 |
| 纯语义概念 (如"焊接参数") | 依赖向量兜底 (2.8s) | SAG concepts entity 部分覆盖 |
| Docker 不可用 | 无法使用完整 SAG (pgvector) | SAG-Lite (SQLite) 替代, 够用 |
| 冷启动首次查询慢 | 35s 首查 | 后续 SAG 绕过, 仅 26ms |
