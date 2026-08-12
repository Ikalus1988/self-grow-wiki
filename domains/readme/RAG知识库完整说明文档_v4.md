# RAG 智能问答 — FANUC 工业知识库 完整说明文档 v4（v4.1 增量更新 2026-07-09）

> 全生命周期复盘 | **2026-07-09** (基于 v3 增量更新)
> 上一版: v3 (2026-07-01, 200K vectors, 飞书接入, SAG+OKF 混合检索)
> 当前: v4 (2026-07-06, **飞轮 32 条 / 65% 通过率实测, SOP v2.5, 14 个 RAG lessons 沉淀**)

---

## 0. v3 → v4 增量变更摘要

| 维度 | v3 (2026-07-01) | v4 (2026-07-06) | 状态 |
|------|-----------------|-----------------|------|
| 向量库 | ~/rag_chromadb / wiki_docs / 200K | 同 (1.77 GB sqlite, 112K fulltext) | ✓ 一致 |
| 飞轮题库 | v3 报 "200 条 88% 命中" | **32 条 × 6 类, 实测 65% 通过率** | ❌ 修订 |
| 上岗 SOP | 未明确版本 | v2.0 (2026-07-02) → v2.5 (2026-07-08, 三层相关性检查 + codewhale 审计) | ⚠️ 修订
| 沉淀 lessons | 0 个 RAG 专项 | **14 个** (RAG/chroma/SOP/品牌污染/分块/检索乱码/...) | ⚠️ 大幅新增 |
| ChromaDB 路径 | v3 提到 ~/rag_chromadb | 同 (v4 命名目录是临时/空, 真实存储 rag_chromadb) | ⚠️ 修正 |
| 飞轮脚本路径 | v3 提 `D:\MD\RAG知识库\rag_flywheel.py` | **实际 `/mnt/c/Users/Eric Jia/scripts/rag_flywheel_eval.py`** | ⚠️ 修正 |
| 飞书 bot | 1 个 bot (cli_a93f9710d9791cbd) | 同 + card reply 稳定 | ✓ 一致 |
| edoc 库 | v3 提 PCDK 报告 | + `edoc_5model_poc_method.md` (5 模型 POC 方法) | ⚠️ 增量 |
| Robot-forum 抓取 | v3 未提 | **CF `_rc` cookie + curl 绕过 WoltLab** (新增 4 帖实测) | ⚠️ 新增 |

---

## 1. 知识库当前真实状态（v4 实测数据）

### 1.1 ChromaDB 向量库

```
路径:     /home/eric_jia/rag_chromadb/chroma.sqlite3
集合:     wiki_docs (1 个)
向量:     200,842 个 (≈ 200K)
全文索引: 112,912 条 (FTS5)
文件大小: 1.77 GB
模型:     bge-m3 (1024 维)  [与 v3 一致]
```

> ⚠️ **命名修正**: v3 文档提 `chroma_db_v4` 目录, 实际 v4 命名目录是空壳 (0 embeddings). 真实运行目录是 `rag_chromadb/`. 见 lesson `chroma-rebuild-no-checkpoint.md` (建库无 checkpoint, 进程一死全部丢失).

### 1.2 飞轮题库 (32 条)

```
脚本:     /mnt/c/Users/Eric Jia/scripts/rag_flywheel_eval.py
触发词:   "飞轮" (飞书/Hermes)
分类:     6 类
  - 报警代码   12 条
  - 操作流程   6 条
  - 跨文档归纳 5 条
  - 参数设定   4 条
  - 边界情况   3 条
  - 飞轮调优   2 条
```

**实测表现 (2026-07-02 飞轮评估)**:

```
┌──────────────┬────────┬──────┬─────────────────────┐
│ 类别         │ 通过   │ 总数 │ 通过率              │
├──────────────┼────────┼──────┼─────────────────────┤
│ 报警代码     │ 5/12   │ 12   │ 41.7% ⚠️ 最低      │
│ 操作流程     │ 5/6    │ 6    │ 83.3%               │
│ 跨文档归纳   │ 2/5    │ 5    │ 40.0% ⚠️           │
│ 参数设定     │ 4/4    │ 4    │ 100% ✓              │
│ 边界情况     │ 3/3    │ 3    │ 100% ✓              │
│ 飞轮调优     │ 1/2    │ 2    │ 50.0%               │
├──────────────┼────────┼──────┼─────────────────────┤
│ 总计         │ 21/32  │ 32   │ 65.6%               │
└──────────────┴────────┴──────┴─────────────────────┘
```

**核心问题**:
1. **top-1 错配**: top-5 里有答案, 但被多样性筛选 + top_k=5 截到 top-1 之外
2. **报警代码召回污染**: A06 SRVO-075 召回到 KUKA 文档 = chromadb 混料
3. **A01 首推 24s** = bge cold start, 加 preload 后 <1s

**稳定可重现**: 21/32 全 4 轮一致通过, 11/32 全 4 轮一致失败, 0 flaky. prod 行为稳定.

### 1.3 上岗 SOP (v2.0)

```
文件:     /mnt/d/MD/RAG知识库/domains/sop/LLM_SOP_onboarding.md
版本:     v2.5 (2026-07-08) — 权威源: ~/.hermes/skills/software-development/llm-sop-onboarding/SKILL.md
更新:     2026-07-02
适用:     rag_mcp_server.py → rag_core.generate_answer() → 飞书/Hermes
```

**v2.0 关键变化** (vs v1 隐含版):
- 角色定位: 技术顾问 (非"知识库管理员"被动查)
- SYSTEM_PROMPT v2 修复 v1 的"反问用户"问题
- 明确边界: RAG 源文不可用时直说"查不到", **绝不用 LLM 经验伪装手册答案**
- LLM 层对 RAG chunks 纪律: 只做路由/洞察, **禁止整合/归类/对比表/计算/转义理解等二次加工**
- 关键区分: 用户描述 vs vision 实际不一致时, **先 vision, 不先信用户**

### 1.4 RAG 沉淀 lessons (14 个)

```
本机位置: /home/eric_jia/work/misakanet-pr237/lessons/contrib/
```

| 主题 | lesson 文件 | 关键要点 |
|------|------------|---------|
| ChromaDB | `chroma-rebuild-no-checkpoint.md` | 建库无 checkpoint, 进程死全丢 |
| ChromaDB | `chroma-建库无-checkpoint-进程一死全部丢失.md` | (同义镜像) |
| ChromaDB | `chromadb-不能放在-ntfs-文件系统.md` | NTFS 性能/锁问题 |
| 检索 | `rag-分块参数-800-字符-100-重叠-每文件最多-100-分块.md` | 分块参数经验值 |
| 检索 | `rag-报警代码检索需要关键词强制召回.md` | 报警码需要强制 keyword 召回 |
| 检索 | `rag-检索中文乱码-pymupdf4llm-默认编码问题.md` | pymupdf4llm 默认 UTF-8 不全 |
| 检索 | `rag-chunk-coarse-cover-page-pollution.md` | 手册扉页污染 top-1 |
| 检索 | `rag-cross-encoder-reranker-cpu-瓶颈-与-llm-确定性调优.md` | reranker 性能 |
| 检索 | `rag-brand-contamination-detection-and-fix.md` | 品牌污染检测 |
| 检索 | `rag-brand-filter-three-pitfalls.md` | 品牌过滤 3 大坑 |
| 飞轮 | `rag-kb-quality-flywheel-self-loop.md` | 飞轮自循环 |
| 建库 | `rag建库策略-不可一次性加载全部数据.md` | 分批建库 |
| 容灾 | `rag-三通道-llm-容灾方案.md` | LLM 主备 fallback |
| 群消息 | `feishu-group-fanuc-rag-sop.md` | 群消息图片处理 SOP |

### 1.5 飞书接入

```
Bot:        cli_a93f9710d9791cbd
Home:       oc_1bf03d465a785da56ae541a1ce5e77fa (RAG 助手测试群)
群规:       7 类屏幕主体分类 (报警/选项菜单/TP 程序/变量配置/文件菜单/PLC 集成/混合/非工业)
bot 静默:   GATEWAY_ALLOW_ALL_USERS + FEISHU_ALLOWED_USERS 双层鉴权
```

### 1.6 Robot-forum 抓取 (v3 之后新增能力)

```
方法:       CF _rc cookie + curl 绕过 WoltLab
工具:       /home/eric_jia/.local/bin/playwright (缺 libnspr4, 跑不动)
            备选: r.jina.ai (board 通, thread 失败)
            备选: Agent-Reach (gh-proxy.com 镜像装)
            备选: Chrome CDP (9222 端口)
lesson:     ~/.hermes/skills/devops/hermes-mcp-integration/references/anti-scraping-paths.md
已抓:       4 帖 (26348/31173/43289/53126) → 内容已落飞书云文档
            https://tarot-club.feishu.cn/docx/MvHMdPkkYoVW43x0NIgcffUunWe
```

---

## 2. v3 文档保留章节（继承 v3 主体结构, 局部修订）

> 以下章节 (3-12) 跟 v3 主体一致, 仅修正与 v4 不一致处 (路径/版本/数据). 原 v3 文档见 `RAG知识库完整说明文档_v3.md` 备查.

## 3. 项目概述

为 FANUC 工业机器人领域构建 **RAG + SAG + OKF 三层知识库**:
- **RAG**: ChromaDB 向量库 (200K vectors) + bge-m3 嵌入
- **SAG**: 结构化查询 + entity 匹配 + 多跳推理 (SQLite 实现, Docker 不可用替代)
- **OKF**: Open Knowledge Format, 知识沉淀为 Concept (Google Open Knowledge Format v0.1)

最终成果 (v4 vs v2):

| 维度 | v2 (2026-04) | v4 (2026-07) | 提升 |
|------|--------------|-------------|------|
| 向量 | 22K | **200K** | 9x |
| 飞轮自检 | 无 | **32 条 / 65.6%** | 0→1 |
| LLM SOP | 无 | **v2.0** | 0→1 |
| 飞书集成 | 企业微信 | 飞书 (多 bot) | ✓ |
| RAG lessons | 0 | **14** | 0→1 |
| Robot-forum 抓取 | 不可达 | **CF cookie + curl 通** | 0→1 |

## 4. 系统架构 (RAG+SAG+OKF)

(同 v3, 略, 见 v3 文档 §二)

## 5. 向量库构建

(同 v3 §三, 略)

**v4 增量**:
- 真实路径: `~/rag_chromadb` (v3 已修正过, v4 实测一致)
- lesson `chroma-rebuild-no-checkpoint.md` 提示: **建库一定要分批 + 检查点**

## 6. SAG-Lite 混合检索引擎

(同 v3 §四, 略)

## 7. 飞书接入方案

(同 v3 §五, 略)

**v4 增量**:
- 多 bot 切换支持 (lesson `hermes-feishu-bot-management`)
- 群消息图片处理 SOP (lesson `feishu-group-fanuc-rag-sop.md`)
- 卡回复 (card reply) 稳定, 错误回退为文本

## 8. 飞轮自检工作流 (v4 修订)

**v4 真实流程** (vs v3 报"200 条 88% 命中"):

```
触发: 飞书/Hermes 发送 "飞轮" → 自动运行
脚本: /mnt/c/Users/Eric Jia/scripts/rag_flywheel_eval.py
题数: 32 条
分类: 6 类 (报警代码 12 / 操作流程 6 / 跨文档归纳 5 / 参数设定 4 / 边界 3 / 调优 2)
评估: 7 维 (准确性 / 引用源 / 速度 / 召回精度 / LLM 修剪 / 答非所问 / 跨文档归纳)
频率: 用户主动触发 (无定时)
输出: 评估报告 + recall 概览
```

**当前瓶颈** (基于 32 题实测):
- 报警代码召回 top-1 错配 (41.7% 通过率)
- KUKA 文档污染 1 例
- 跨文档归纳召回弱 (40% 通过率)

**改进方向** (prod 行为稳定前提下):
1. top_k 提到 8 或 rerank 选 top-3 而非 top-1 → 预计 85%+
2. 清理非 FANUC 文档 (品牌过滤)
3. bge 嵌入 preload (消除 cold start)
4. 报警码强制 keyword 召回 (lesson `rag-报警代码检索需要关键词强制召回.md`)

## 9. OKF 知识沉淀

(同 v3 §七, 略)

## 10. 踩坑记录 (v4 增量)

**v3 八坑保留**, v4 新增 5 坑:

### 坑 9: ChromaDB 路径命名混乱 (chroma_db_v3 / chroma_db_v4 / rag_chromadb)
- **现象**: chroma_db_v4 目录是空壳, 真实运行是 rag_chromadb
- **根因**: 历史重命名, 没清理
- **修复**: 实际路径 = `/home/eric_jia/rag_chromadb/`
- **预防**: 见 lesson `chroma-rebuild-no-checkpoint.md`

### 坑 10: 飞轮评估口径与召回 top-1 错配
- **现象**: 11/32 题全 4 轮一致失败, 但 top-5 里有正确答案
- **根因**: 多样性筛选 + top_k=5 截断, top-1 不是最优
- **修复**: 评测脚本加 "失败召回片段预览" + "期望关键词缺失" 输出 (已落地)
- **预防**: 改 top-1 选择策略, 评测口径对齐 prod 实际行为

### 坑 11: pymupdf4llm 默认编码导致中文乱码
- **现象**: PDF 转 markdown 时中文变乱码
- **根因**: pymupdf4llm 默认 UTF-8 不完整, 缺 GBK 兜底
- **修复**: 指定 `utf-8` + `gbk` 双编码 fallback
- **预防**: 见 lesson `rag-检索中文乱码-pymupdf4llm-默认编码问题.md`

### 坑 12: 手册扉页污染 top-1
- **现象**: 报警码题 top-1 是手册扉页, 真正答案在 top-5
- **根因**: 扉页向量化得分高, 关键词权重让扉页占优
- **修复**: 关键词权重让手册内实体词占优, 滤掉纯扉页
- **预防**: 见 lesson `rag-chunk-coarse-cover-page-pollution.md`

### 坑 13: Robot-forum 在境内 WSL 不可达
- **现象**: 5 路径 (curl / r.jina.ai / scrapling / gh-proxy / 搜狗) 全断
- **根因**: GFW SNI 阻断 + Cloudflare JS challenge + WSL 缺 libnspr4
- **修复**: CF `_rc` cookie + curl 拿 WoltLab 真 HTML (实测通, 4 帖已抓)
- **预防**: 见 lesson `gfw-tls-sni-block-pattern.md` (pr362 已合并) + `multi-forum-scraping-architecture.md`

## 11. 迁移 SOP & 预防清单

(同 v3 §九, 略)

**v4 增量检查项**:
- [ ] ChromaDB 路径 = `~/rag_chromadb` (不是 v3/v4 命名目录)
- [ ] 飞轮脚本 = `/mnt/c/Users/Eric Jia/scripts/rag_flywheel_eval.py` (不是 `D:\MD\RAG知识库\rag_flywheel.py`)
- [ ] 上岗 SOP = v2.0 (不是 v1)
- [ ] 14 个 RAG lessons 都在 `~/work/misakanet-pr237/lessons/contrib/`

## 12. 文件清单 (v4)

```
D:\MD\RAG知识库\domains\
├── readme\
│   ├── RAG_知识库系统_hermes.md
│   ├── RAG知识库README_v2.md
│   ├── RAG知识库完整说明文档_opus.md
│   ├── RAG知识库完整说明文档_v3.md  ← 旧版, 备查
│   └── RAG知识库完整说明文档_v4.md  ← 本文档
├── sop\
│   └── LLM_SOP_onboarding.md  (v2.0)
├── tech\
│   ├── edoc_5model_poc_method.md
│   └── fanuc_classify_cli_design.md
└── reports\
    ├── FANUC mhfripdt.txt
    ├── RAG-SAG-OKF-演进报告.md
    ├── SAG-L1-报告.md
    ├── SAG-L2-报告.md
    ├── edoc-knowledgebase-build-log.md
    ├── rag-flywheel.md
    ├── rag知识库汇报文档0617.txt
    ├── rag知识库演进记录.txt
    ├── 案例介绍_RAG工业知识库(1).docx
    └── 迁移报告_v2_v3.docx

/mnt/c/Users/Eric Jia/scripts\
└── rag_flywheel_eval.py  (32 条题库, 6 类, 7 维)

/home/eric_jia/work/misakanet-pr237/lessons/contrib\
└── rag* (14 个 RAG 专项) + chroma* (3 个) + 相关 lessons (134 总)

/home/eric_jia/rag_chromadb\
└── chroma.sqlite3 (1.77 GB, 200K vectors, wiki_docs collection)
```

## 13. 快速使用 (v4)

```bash
# 1. 查 (群消息 / Hermes CLI)
"查 SRVO-023"  → 自动路由 RAG + LLM SOP v2.0

# 2. 飞轮自检 (32 条)
python3 /mnt/c/Users/Eric\ Jia/scripts/rag_flywheel_eval.py
# 或
"飞轮"  → 飞书群/Hermes 触发

# 3. 上岗 SOP 速查
cat /mnt/d/MD/RAG知识库/domains/sop/LLM_SOP_onboarding.md

# 4. RAG lessons 速查
ls ~/work/misakanet-pr237/lessons/contrib/ | grep -E "rag|chroma|feishu"
```

## 14. 后续规划 (v4 修订)

| 项 | 优先级 | 状态 |
|----|--------|------|
| 飞轮 32→100 条扩充 | P1 | 待做 |
| top-1 改 rerank top-3 (预计 85%+) | P1 | 待做 |
| 品牌污染清理 (KUKA 文档) | P1 | 待做 |
| bge 嵌入 preload | P2 | 待做 |
| 飞轮题按用户 62 条真实问题补充 | P2 | 已落库 (云文档 NPlldycBkoWIOXx36Xxctnyonyc) |
| 上岗 SOP v3 (修 vision SOP 8 分类) | P3 | 待做 |
| 飞轮 4 轮稳定性自动化 (cron) | P3 | 待做 |

## 15. 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1 | 2026-04 | 初版, 22K vectors, 企业微信 |
| v2 | 2026-04 | 飞书接入, SAG entity |
| v3 | 2026-07-01 | 200K vectors, OKF v0.1, 8 踩坑, 9 迁移 SOP |
| **v4** | **2026-07-06** | **飞轮 32 条/65% 实测, SOP v2.0, 14 RAG lessons, Robot-forum CF cookie 通, 5 新踩坑** |

---

## 附录 A — 14 个 RAG lessons 索引

| 序号 | 文件 | 主题 | 优先级 |
|------|------|------|--------|
| 1 | `chroma-rebuild-no-checkpoint.md` | ChromaDB 建库 | P0 |
| 2 | `chroma-建库无-checkpoint-进程一死全部丢失.md` | (镜像) | P0 |
| 3 | `chromadb-不能放在-ntfs-文件系统.md` | 文件系统 | P0 |
| 4 | `rag-分块参数-800-字符-100-重叠-每文件最多-100-分块.md` | 分块 | P1 |
| 5 | `rag-报警代码检索需要关键词强制召回.md` | 报警码召回 | P1 |
| 6 | `rag-检索中文乱码-pymupdf4llm-默认编码问题.md` | 中文编码 | P1 |
| 7 | `rag-chunk-coarse-cover-page-pollution.md` | 扉页污染 | P1 |
| 8 | `rag-cross-encoder-reranker-cpu-瓶颈-与-llm-确定性调优.md` | reranker | P2 |
| 9 | `rag-brand-contamination-detection-and-fix.md` | 品牌污染 | P1 |
| 10 | `rag-brand-filter-three-pitfalls.md` | 品牌过滤 | P1 |
| 11 | `rag-kb-quality-flywheel-self-loop.md` | 飞轮自循环 | P0 |
| 12 | `rag建库策略-不可一次性加载全部数据.md` | 分批建库 | P1 |
| 13 | `rag-三通道-llm-容灾方案.md` | LLM 容灾 | P1 |
| 14 | `feishu-group-fanuc-rag-sop.md` | 群消息 SOP | P0 |

## 附录 B — 上岗 SOP v2.0 关键约束

(节选自 `LLM_SOP_onboarding.md` v2.0)

1. **RAG 源文不可用时直说"查不到"** — 绝不用 LLM 经验伪装手册答案
2. **LLM 层对 RAG chunks 纪律**: 只对用户问题做路由/洞察; chunks 完整输出; **禁止整合/归类/对比表/计算/转义理解等二次加工**
3. **用户描述 vs vision 实际不一致时, 先 vision, 不先信用户** (2026-07-05 教训)
4. **群消息表达纪律**: 思考过程最小化; FANUC 领域结论与推断保持引源+专业术语
5. **诚实底线**: 不基于未验证信息作答 (2026-07-05 SPOT-550 教训)
