# PROGRESS — self-grow-wiki RAG 知识库

> 进度记忆单一真相源，由 **progress-memory 外挂**（`.agents/skills/progress-memory-1.0.0/`）维护。
> 约定：**会话启动读本文件恢复进度；会话收尾用 `scripts/progress_memory.py checkpoint` 追加时间线。**

## 当前任务

- **任务**: RAG 架构手术（评审《2026-08-15_self-grow-wiki_review-forced-recall.md》落地）
- **进度**: 69% — #1-#9 ✅ 完成；**#10-#13 待办**
- **下一步**: #10 手术 C-1 — rag_core.py 各 chunk 构建处加 `exact_type` 标签（排序一行不动）
- **上次更新**: 2026-08-20（健康检查确认知识库可用）
- **交接文档**: `memory/2026-08-16-handoff-rag-surgery.md`（工作区根 memory/，本仓库 memory/ 下无副本）

## 里程碑

### 已完成（#1-#9）✅

- [x] #1-#7 手术 A（建库+实体集成）: 新版手册重建知识库（FANUC Manual 13.0 CM，218 PDF），200702 chunks 合入替换；实体元数据 Phase 1 全库重跑完成（200702/200702 有 entity_* 字段）；import_batch.py 已改造（文件级 checkpoint + 实体集成 + 离线模型）
- [x] #8-#9 手术 B（强制召回收敛）: 结论 = 报警 `$contains`、PCIF/RTCP/上位机强制召回为**必要兜底**（探针实证，勿删）；回归 14/14 全绿
- [x] 独立 badcase 修复（2026-08-20）: M-900iB 换油周期静默退化 — 分类标签等价 `$in` + BM25 `$in` 支持 + 润滑 synonyms + 回归用例 16/16 绿（详见时间线）

### 待办（#10-#13）

- [ ] **#10 手术 C-1: exact_type 标签**（排序不动）— 先跑飞轮基线（32 条查询，记通过率）；在 rag_core.py 各 chunk 构建处加 `exact_type` 标签（variant/alarm/feature/entity/rrf/语义；已有部分标签 `_variant_kw`/`_entity_match`/`_feature_match`/`_rrf`/`_topic`）；**排序逻辑一行不动**，回归 + 探针零回归；目的：暴露分数真相，为渐进置顶铺路
- [ ] **#11 手术 C-2: 渐进置顶**（每步独立验证）— 顺序 variant → alarm → feature；每步改码 → 回归 + 探针对比（vs probe_baseline_v2.json）→ 飞轮通过率不降才走下一步；失败即 `git checkout rag_core.py` 回滚
- [ ] **#12 手术 D: 规则文件化**（低风险纯迁移）— `_CATEGORY_RULES`(419) / `_L2_RULES`(444) / `_NON_FANUC_KW`(≈1700) 迁到 config.yaml 或独立 rules 文件；加分类断言测试
- [ ] **#13 收尾** — 全程回归（回归集 14 + 探针 + 飞轮）；双仓库分步 commit：
  - `self-grow-wiki`（生产，HEAD 077f8d8；含未提交 import_batch.py 改造 + 建库相关）
  - `/mnt/d/MD/RAG知识库`（基线，HEAD d096015；含 code/ 同步 + 评审 + SOP lesson）

## 关键状态快照（2026-08-20 健康检查）

- **ChromaDB**: `/home/eric_jia/rag_chromadb`（3.1G），collection `wiki_docs` = **200702 chunks**，连接正常
- **BM25 缓存**: `bm25_index.pkl` 535MB 就绪，加载 8.4s（若删除，首次查询全量重建 ≈3 分钟 + 高内存，勿与 pytest/torch 叠加）
- **检索冒烟**: `retrieve("SRVO-066 CSAL 报警 处理")` → 6 条，链路正常
- **服务**: 2× `rag_mcp_server.py` + `rag_web.py` 运行中（Aug18 启动；重启后重新加载代码）
- **git**: `self-grow-wiki` HEAD `077f8d8`（chromadb 首调竞态加锁）；工作区未提交 = `scripts/import/import_batch.py`(M) + 未跟踪 `tests/test_retrieval_regression.py` / `scripts/retrieval_probe.py` / `.gitleaks.toml`
- **测试**: `tests/test_retrieval_regression.py` 14/14（37.4s）；pytest 全量 20+ 用例

## 关键文件与备份

- `/tmp/entity_snapshot.jsonl` — 200702 条实体元数据快照（42MB）⚠️ /tmp 重启即失
- `/tmp/rag_core_before_surgeryB.py` — 手术 B 前 rag_core.py ⚠️ /tmp 重启即失
- `/tmp/probe_baseline_v2.json` — 新库探针基线（手术 C-2 对比基准）⚠️ /tmp 重启即失
- `/tmp/probe_nofeature.json` — 手术 B 验证（无强制召回版）⚠️ /tmp 重启即失
- ~~`/tmp/rag_backup_20260815_190855/`~~ — **已不存在**（/tmp 清理），勿再引用
- 代码级备份靠 git（`git log` / `git show 55fa24a` 等）

## 恢复指引（快速回到工作状态）

```bash
# 1. 回归集确认基线绿
cd /mnt/c/Users/Eric Jia/self-grow-wiki && /usr/bin/python3 -m pytest tests/test_retrieval_regression.py -q

# 2. BM25 预重建（pytest/BM25/torch 叠加会 segfault，先跑这个再跑别的）
/usr/bin/python3 /mnt/c/Users/Eric Jia/.rag_bm25_rebuild.py

# 3. 探针基线（如 /tmp/probe_baseline_v2.json 仍在可跳过）
/usr/bin/python3 scripts/retrieval_probe.py --out /tmp/probe_baseline_v2.json

# 4. 飞轮基线（手术 C-1 开工前必跑）
/usr/bin/python3 /mnt/c/Users/Eric Jia/scripts/rag_flywheel_eval.py

# 5. 健康检查（快速确认知识库活着）
/usr/bin/python3 /mnt/c/Users/Eric Jia/.rag_health_check.py
```

## 环境与坑（踩过的，必读）

1. 系统 `/usr/bin/python3` 跑 rag_core/测试/探针；`/home/eric_jia/mkdocs-env/bin/python3` 跑 import_batch（有 langchain_text_splitters）；pymupdf4llm/openpyxl 两环境都缺（PDF 用 fitz 回退）
2. **chromadb 首调 bug**（RustBindingsAPI AttributeError）：连接脚本带 3 次重试
3. `where $contains` 是分词匹配，对下划线/中文/空格不可靠 —— 验证 metadata 用 Python 侧遍历或 `$eq`，别信 `$contains` 的 0
4. 误报教训：遇反常先验证工具本身，再怀疑数据（2026-08-20 M-900iB 换油周期案例：AI 断言"知识库未覆盖"，实测数据在库，是检索静默退化）
5. 后台长任务：用 Bash `background=true`，输出重定向到文件（如 /tmp/kb_build.log）
6. Phase 1 全库重跑 ≈8.3h（ChromaDB update 瓶颈），跑前必须快照
7. **分类标签漂移（2026-08-20 修复）**: 新版手册(34324 chunks)统一标 `FANUC机器人`，历史库(132815)用 `07_机器人` 等细分标签，分类器只认老标签 → where_filter 精确 $eq 误杀新版 chunk。已修: `_CATEGORY_EQUIV` 等价组 + where_filter $in + BM25Index.search 支持 $in。**注意**: 新版手册未做细分分类（全塞 FANUC机器人），其他分类的 $in 等价组待手术 #12 补齐
8. **BM25Index.search 对未知 where 静默退回全库**（2026-08-20 修复）: `$in` 此前被忽略，候选集漂移叠加 overlap-guard 可能把结果全杀；现在 $eq/$in 都显式处理

## 进度时间线
- 2026-08-20 23:56: M-900iB 换油周期静默退化修复: 分类标签等价 $in(07_机器人↔FANUC机器人) + BM25 $in 支持 + BM25 fallback + 润滑 synonyms + M-900iB 保养锚点 + 回归用例 16/16 绿（修复前 0 召回 → 修复后答案第 2 位）
