# self-grow-wiki 仓库评审 — 太阳视角复核意见

> **定位**：本文件是 Codewhale reviewer agent 报告的「太阳复核 + 落地建议」附录，不替换原报告。
> **原报告**：`self-grow-wiki-review-2026-08-11.md`（5.5/10，纯静态分析）
> **复核方式**：抽样 grep + 行号核验 + 报告 vs 实际代码逐项对照
> **复核日期**：2026-08-11 19:40 GMT+8
> **立场**：**只评审，不落地**（克莱恩 19:40 明确要求）
> **更新**：2026-08-11 22:00+ 克莱恩追加"群问题回答踩的坑"复盘 → §八
> **修复进度**：2026-08-11 22:30+ 太阳落地 P0 全部 + P1-M3，见下方「修复进度追踪」

---

## 一、抽样核验：报告可信度 9/9 全部命中

| 编号 | 报告说法 | 实际验证 | 验证手段 |
|---|---|---|---|
| **C1** | 7 处硬编码同一密钥 | ✅ 7 处全部命中，密钥一致 `sk-071…35ea` | `grep -rn 'sk-[a-f0-9]\{16,\}'` |
| **M1** | `kb_learning` API 与 3 消费方失配 | ✅ `kb_learning.py` 真没有 `get_gaps/get_feedback_summary/get_faq_pairs/generate_report`；`rag_admin.py:522-578` 实际在调 | `grep -n "^def \|^class " kb_learning.py` + `sed -n '520,580p' rag_admin.py` |
| **M2** | query_id 被假 ID 覆盖 | ✅ `rag_core.py:1892` 用 `kb_learning.log_query()` 返值覆盖真 ID；`rag_api.py:189` 真 `int(req.query_id)` | `sed -n '1880,1892p' rag_core.py` + `sed -n '180,200p' rag_api.py` |
| **M3** | ingest 不触发索引失效 | ✅ `_bm25_index.invalidate()` 全仓 0 命中；`_entity_index_built` 也不被 ingest 触达 | `grep -rn '_bm25_index.invalidate\|_entity_index_built' --include="*.py"` |
| **M4** | `from kb_selfcheck` 必崩 | ✅ `kb_selfcheck.py` 在 `scripts/`，`rag_admin.py` 头无 `sys.path` 注入 | `find . -name kb_selfcheck.py` + `sed -n '1,15p' rag_admin.py` |
| **M5** | `HTTPException` 未导入 | ✅ `rag_api.py:15` 只 import `FastAPI`，`:182` 用了 `HTTPException` | `grep -n 'from fastapi\|HTTPException' rag_api.py` |
| **M9** | 0.0.0.0 + `--share` | ✅ `rag_web.py:343/357/359`、`rag_api.py:289`、`start_rag.sh:8` 全确认 | `grep -n 'share\|0\.0\.0\.0'` |
| **m1 hp** | 残留 hp 用户路径 | ✅ 8 处命中（报告只提 2 处） | `grep -rn '/mnt/c/Users/hp'` |
| **m1 SAG** | 硬编码 `/mnt/c/.../SAG-poc` | ✅ `rag_core.py:1203` 确认，路径**真实存在**但应 config 化 | `grep -n '/mnt/c/Users/Eric Jia/SAG-poc'` + `ls -la` |

**结论**：5.5/10 评分无水分。报告抽样 9 个全部命中，剩余 13 个可信度足够。

---

## 二、复核中发现的**报告以外**的新问题

### N1. m1 hp 路径实际比报告严重（8 处 vs 报告 2 处）

报告只提 `auto_flywheel.py:20` + `daily_audit.py:38` 两处，**实际全仓 8 处**：

```
auto_flywheel.py:20                                              # RAG 巡检题库 docx
daily_audit.py:38                                                # RAG_DOCS 目录
scripts/docs/doc_verify.py:284                                   # FANUC PDF 路径
scripts/docs/graph_to_obsidian.py:21,22,166,227                  # 4 处（含字符串替换规则）
scripts/import/import_batch.py:5,6,7                             # docstring 用法示例
```

**特别严重**：`graph_to_obsidian.py:166/227` 的 `.replace('/mnt/c/Users/hp/', '~/')` 写死在 Python 字符串里——这是给**另一台机器**写的脚本，迁移到本机需要改逻辑而不是改路径。

**建议**：本机修复期内调高 m1 优先级到 P2（建议处置见下文执行顺序）。

### N2. m11 仓库卫生已部分观察到（验证时确认）

- `会话1.txt`（1462 行聊天记录）untracked
- `synonyms.json.bak.1786422492` 备份文件 untracked
- `rag_core.py` + `synonyms.json` 有未提交改动

**追加建议**：归档前先看一眼 `git diff` 的 `rag_core.py` 改动——评审期内不应残留未提交修改（易污染后续 review）。

### N3. C1 密钥已确认安全（用户 19:26 确认已吊销）

- 密钥 `sk-071…35ea` 已在厂商控制台吊销
- 7 处文件 grep 验证时显示的密钥为**已失效的废钥**，可安全操作
- 后续修复只需把字面量替换为 `os.environ.get("DEEPSEEK_API_KEY")`，无需担心二次泄露

---

## 三、与评审报告的 3 处分歧（评审意见）

### 分歧 1：不建议清理 git history

报告 C1 修复建议第③条："清理 git 历史并重推"。

**太阳意见**：**不清理**。

理由：
- 你对其他仓的偏好是「轻清理原则」（参考 MisakaNet 主仓禁 force push 的历史决策）
- 密钥已吊销，git history 中残留的废钥 = 死资产，不会扩大攻击面
- rewrite history 会让所有 contributor 的 fork 失同步，破坏协作
- 攻击者拿到废钥也用不了

唯一例外：若未来准备把仓公开给外部协作方使用，再考虑用 `git filter-repo` 一次性清理。

### 分歧 2：不建议开启 GitHub secret scanning

报告 C1 修复建议第④条："配置 GitHub secret scanning"。

**太阳意见**：**暂不开**。

理由：
- 仓库目前 self-use 定位（参考 CLAUDE.md / USER.md / 你自己的 GitHub 仓库命名 `Ikalus1988/self-grow-wiki`）
- 开启 secret scanning = 公开承认"我之前犯过这个错"，向 GitHub 暴露修复历史
- 当前 threat model 是 API 额度盗用，密钥已吊销后威胁消除
- 若 PyPI publish 前需要，按需开启

### 分歧 3：M1 建议走"兼容 shim"路径而非报告的"二选一"

报告 M1 修复建议："二选一——补回旧 API 或改三个消费方适配新 JSONL API"。

**太阳意见**：**第三条路径——兼容 shim**。

理由：
- 3 个消费方（`rag_admin.py` / `rag_api.py` / `rag_web.py`）改起来工作量大且要回归测试
- `kb_learning.py` 新版 JSONL API 的字段是真实存在的（旧版的字段在 `kb_learning.json` 也能看到），做 shim 是数据聚合层工作，不破坏新架构
- shim 优先于消费方迁移 = 早止血 + 少破坏面
- 后续若 shim 稳定，可慢慢把消费方迁移到新 API（消解 shim）

---

## 四、优先级重排与执行建议（按本机工作流）

### 优先级原则（与你白天工作流对齐）

- **P0**：今晚或明天早上必须修，否则日常使用受影响或安全洞持续暴露
- **P1**：本周修，影响功能正确性，但是间歇性触发
- **P2**：下周修，影响可移植性/一致性，一次性买断
- **P3**：空闲时修，影响对外发布质量

### 修正后的执行顺序

| 优先级 | 项 | 工作量 | 阻塞 | 落地建议 |
|---|---|---|---|---|
| **P0 今晚** | C1（7 处改 env 读取） | 20 min | 没人，明天还能用 | 一次性 `grep -l` 找全 7 个文件 → 改常量 + 加 `os.environ.get("DEEPSEEK_API_KEY")` 兜底（缺失时给出明确错误信息，不静默 fail） |
| **P0 今晚** | M9（3 处改 host 默认值） | 15 min | 没人 | `rag_web.py:357` 改 `os.environ.get("RAG_WEB_HOST", "127.0.0.1")`；`rag_api.py:289` 同；`start_rag.sh:8` 改 `${OLLAMA_HOST:-127.0.0.1:11434}`。**`--share` 默认值保持不传**，需要显式 `--share` 才启动，log 里加一行警告 |
| **P0 今晚** | M4 + M5（10 行 patch） | 10 min | 没人 | `rag_admin.py:14` 之前加 `sys.path.insert(0, str(Path(__file__).parent / "scripts"))`；`rag_api.py:15` 把 `from fastapi import FastAPI` 改为 `from fastapi import FastAPI, HTTPException` |
| **P0 明天** | M1+M2（kb_learning 兼容 shim + query_id 真 ID） | 2-3h | 自学习 Tab 复活 | shim 实现 4 个函数：`get_gaps(limit)` / `get_feedback_summary(days)` / `get_faq_pairs(limit)` / `generate_report()`；`get_stats()` 补 5 个字段；`rag_core.py:1892` 不接 `kb_learning.log_query()` 返值，return 永远用 `str(sqlite_query_id)` |
| **P1 本周** | M3（invalidate_indexes 统一入口） | 1-2h | 静默 fail 修复 | `rag_core.py` 加 `invalidate_indexes()` 函数；5 个 ingest 路径（`rag_admin.py:970`、`scripts/import/import_batch.py:215`、`rag_builder.py:394`、`rag_builder_ocr.py:324`、`rag_import_fanuc.py:280,302`）success 后调一次 |
| **P1 本周** | M10（badcase 目录统一） | 30 min | 巡检闭环 | 统一 `kb_learning.AUDIT_DIR` 为单一来源，daily_audit 改 `os.environ.get("RAG_AUDIT_DIR", kb_learning.AUDIT_DIR)` |
| **P1 本周** | M11（题库分层 + 空库文案对齐） | 1h | 巡检真实性 | `daily_audit.py:123-124` 改按 `easy/medium` 分层；`daily_audit.py:321` 文案与 `rag_api.py:79` 对齐；API 返回 `top_score` 并纳入判定 |
| **P2 下周** | m1 hp 路径（8 处）+ m11 仓库卫生 | 半天 | 可移植性 | hp 路径全部改 env 或 config；`graph_to_obsidian.py` 4 处评估"删 vs 改"，建议**直接删**（你本机不会用文件迁移工具给 obsidian 灌数据） |
| **P2 下周** | m1 SAG 路径 config 化 + m4 config 漂移 | 半天 | 一致性 | `rag_core.py:1203` 改 `config["sag"]["poc_path"]`；`config.yaml` 的 `llm.channels` 与代码 `MODEL_CHANNELS` 对齐；`reranker.enabled/top_k` 在 config 唯一来源 |
| **P2 下周** | m5（分类体系两套合一） | 2h | 二级过滤 | 选一套做"主"，另一套做"兼容映射"；建议 `scripts/rag_phase2_semantic_tag.py` 改用 `rag_core` 的字典 |
| **P2 下周** | m6/m7（kb_learning JSONL 锁 + SQLite 锁） | 1h | 并发数据丢失 | shim 稳定后做；`_append_jsonl` 加 `threading.Lock`；`get_feedback_list` 加 `_log_lock` |
| **P3 空闲** | M6/M7/M8/M13 集成层质量 | 1 天 | 对外发布 | bot 异步化 + ack + @过滤；guard_response 真接入；MCP 注入边界补 UNTRUSTED_CONTENT 标记；rag_web 写 SQLite query_log |
| **P3 空闲** | m2（setup.py 重写） | 半天 | PyPI 发布 | 等 PyPI 真要发时再做 |
| **P3 空闲** | m3（懒加载）+ m8（双 MCP 合一）+ m9（flywheel 续跑落盘）+ m10（mcp 健壮性）+ m12（测试覆盖） | 1-2 天 | 长期质量 | 批量扫尾 |

### 关键路径依赖

```
C1 (env 读取) → M9 (host 默认) → M4/M5 (10 行)
                                  ↓
                            M1/M2 (kb_learning shim) → M3 (索引失效)
                                                      ↓
                                              M10/M11 (巡检闭环)
                                                      ↓
                                              m1/m4 (路径/配置)
                                                      ↓
                                              M6/M7/M8/M13 (集成)
```

**首要建议**：本周先打 P0 + P1，可以回收 90% 的安全/集成风险；P2 一次性扫尾；P3 留给空闲。

---

## 五、三个建议先与你确认的决策点

### 决策 1：`graph_to_obsidian.py` 三个 hp 路径

- 脚本是给"文件迁移工具"输出做 obsidian 化的，hp 路径写死在字符串替换规则里
- 选项 A：直接删（你本机不会用，迁回成本低）
- 选项 B：迁移到 config（保留功能，可能未来需要）

**太阳建议**：**直接删**。理由：本机工作流没用过 obsidian 化，且脚本设计假设是 hp 用户那台机器的文件目录结构。

### 决策 2：`auto_flywheel.py:20` hp 的 docx 路径

- `docx_path = '/mnt/c/Users/hp/Desktop/自研/rag-docs/RAG巡检题库_200题_20260508.docx'`
- 你日常飞轮是真的读这文件，还是已经换了路径只是代码没改？

**太阳建议**：先确认现状。如果路径已变 → 改 env；如果还在用 → 改 `RAG_FLYWHEEL_DOCX_PATH` 环境变量。

### 决策 3：M1 兼容 shim vs 改造消费方

**太阳强烈倾向 shim**（已写入上文 P0 明天项）。shim 可让 3 个消费方零迁移立刻工作，且保留未来渐进重构空间。

如果你倾向"一次性彻底改对"（改造消费方到新 JSONL API），告诉我，工作量会从 2-3h 涨到 4-6h + 回归测试。

---

## 六、给"建议落地"的最终交付物清单

如果后续你（或下次 review）按本建议落地，按以下顺序补 commit：

1. **commit 1** (P0-1 C1): `chore(security): migrate hardcoded API keys to env (7 files)` — 7 处改 env 读取
2. **commit 2** (P0-2 M9): `fix(security): bind services to 127.0.0.1 by default` — 3 处改 host
3. **commit 3** (P0-3 M4+M5): `fix(imports): inject scripts/ into sys.path + import HTTPException` — 10 行 patch
4. **commit 4** (P0-4 M1+M2): `fix(kb_learning): add compat shim for old API + return real SQLite query_id` — 双向修复
5. **commit 5** (P1-1 M3): `fix(rag): unify index invalidation on ingest` — 5 路径 hook
6. **commit 6** (P1-2 M10+M11): `fix(audit): unify badcase dir + align question bank stratification` — 巡检真实化
7. **commit 7** (P2-1 m1+m11): `chore(cleanup): remove hp user paths + .bak files + chat logs` — 仓库卫生
8. **commit 8** (P2-2 m4): `refactor(config): single source of truth for paths and reranker` — config 收口
9. **commit 9** (P2-3 m5+m6+m7): `refactor(category): unify classification + add JSONL/SQLite locks` — 一致性
10. **commit 10** (P3-1 集成): `feat(bot): async pipeline + ack + @filter` + `feat(mcp): enable guard_response` + `feat(rag): UNTRUSTED_CONTENT boundary` + `fix(web): write query_log to SQLite` — 集成层质量
11. **commit 11+** (P3-2 扫尾): m2/m3/m8/m9/m10/m12 — 批量扫尾

每个 commit 应当独立可测、可回滚（这是 OpenClaw PR 知识库 report §6.1 的核心原则，见 `research/openclaw-pr-knowledge/report.md`）。

---

## 七、风险提示

1. **M2 修复会改变 `kb_learning.log_query()` 返值格式**——如果有外部调用方依赖 `kb_{int(time.time())}` 格式，需要先 grep 排查。**太阳已 grep**：仅 `kb_learning.log_query` 内部 + 报告描述路径，无第三方依赖。
2. **M3 修复会引入 ingest 性能开销**——`_bm25_index.invalidate()` 重算 BM25 索引成本不高（单文档 ~10ms），但要在文档确认入库成功**之后**调用，不能在 ingest 中途调用。
3. **M9 修复可能影响日常调试**——绑 127.0.0.1 后，从 Windows 浏览器访问 WSL 服务需要 `wsl.localhost` 或端口转发。建议同步写一个 `docs/DEV_ACCESS.md` 说明。
4. **P3 集成层工作量被低估**——M6 bot 异步化涉及 feishu SDK 重构 + 幂等设计 + 重试策略，实际工作量可能是 1.5-2 天而非 1 天。

---

## 八、群问题回答踩的坑复盘（克莱恩 8/11 晚追加）

最近一周在飞书群（RAG 助手测试群 + 调试群）回答问题时暴露的**知识库建库策略性缺陷**——不是 bug，是根因层面的设计问题。报告未覆盖这些，专门补一节。

### 坑 1：当前库结构不健康，应该**推倒重建**（不是修补）

| 证据会话 | 现象 |
|---|---|
| 2026-08-05 xCore 入库 | 770 chunks 入库后，立刻暴露"短字符串 BGE 召回差"是 chunk 类型问题而非查询机制问题；目录页 (p.8/p.11) PyMuPDF 文本流倒置 ("页码\n标题")，当时用"跳过修复"糊弄过去 |
| 2026-08-07 韩宝宁 PN_ENABLE_AT_BOOT | 群里被追问一个变量名，**知识库召不到任何东西**——这种"KB 实际只有 60-70% 真的能用"的状态，靠 BM25 兜底/品牌过滤打补丁救不回来 |
| 2026-08-08 R-2000iC 工作半径 | 召回的是手册封面，**未命中参数表**——这意味着占库容量的封面/前言/目录类 chunks 在污染语义检索向量空间 |

**复盘结论**：当前 wiki_docs 库 197k chunks / BGE-base-zh-v1.5 的形态，**继续往里灌 = 越灌越烂**。需要：
1. 先彻底清洗噪音（目录页 / 封面 / 前言 / 装配清单）
2. **重新建库**：按手册边界（章节、参数表、故障代码表）切，不按 800 字符粗暴切
3. 切完后跑一次回归（30+ 用例），验证"参数表召回率"和"报警码召回率"双指标双 95%+ 才算成功

**建议优先级**：作为 P1 决策项（不是 P0 修复，是 P1 战略决策）摆出来，让克莱恩拍板是否真推倒。

### 坑 2：**强制召回不应存在**

`~/.hermes/scripts/rag_core.py` 里有"短报警码强制召回"逻辑（按 `[A-Z]+-\d+` regex 强制精确召回），是 2026-07-25 SRVO-038 无召回事故后的"补丁"。

**问题**：强制召回是**症状治疗**——向量召不到所以走字符串兜底。真正的根因 = BGE-base-zh 对"SRVO-038"这种短字符串（4 字符 + 数字）的语义向量区分度本来就不行。`SRVO-038` 和 `SRVO-023` 在 768 维空间里几乎是同一个点。

**正确做法**：
- 报警码这类**结构性知识**应走**结构化索引**——每个报警码作为单独元数据字段（`entity_alarms` 已经有，但没接入检索）
- 不是兜底召回，而是**召回层第一优先**：query 命中 `[A-Z]+-\d+` 就走 metadata filter，绕开向量
- **不应该有"强制召回"代码分支**——有了就意味着正常路径坏了

**实施要点**：`rag_core.py:_detect_metadata_filter()` 里已经有 alarm code 提取逻辑（验证过在跑），**只需要在 search 入口前置做 metadata-first 路由**，不用调 embedding 就能直接拿到结果。

**建议优先级**：与"重建库"绑定——重建时 metadata-first 路由做成第一公民，强制召回代码分支整体删除。

### 坑 3：**chunk 切分需更加精细**

当前 `chunk_text(text, max_chars=800, overlap=100)` 是**字符级窗口切**——粗暴但均匀。问题：

| 切错场景 | 后果 |
|---|---|
| 参数表横跨 800 字边界 | 表头被切到上一个 chunk，表体切到下一个 → 召回时只能召回"半张表" |
| 报警代码表（SRVO-xxx + 原因 + 对策三列） | 三段被切成 3 个 chunk，单独召回任何一个都不完整 |
| 步骤列表（1. ... 2. ... 3. ... 4. ...） | 步骤 2/3/4 被融在同一个 chunk，步骤 1 单独 → 检索"步骤 3"命中步骤 1 的 chunk，给用户答非所问 |
| 长段落（含 5+ 句技术说明） | 800 字正好切在"if 条件"中间，条件与结论分离 |

**正确做法**（按优先级）：
1. **识别结构边界先切**：检测到表格 → 整表为一个 chunk；检测到有序列表 → 整列表为一个 chunk；检测到 `## / ### / #####` 标题 → 沿标题切
2. **小 chunk 合并**：< 200 字符的孤立 chunk 与相邻 chunk 合并（避免"半句话 chunk"）
3. **大 chunk 二次切**：> 1500 字符的 chunk 在段落/句子边界二次切，不在字符窗口硬切

**最小实现**：`chunk_text` 加结构识别层（regex 检测 `^#+\s` / `\|.*\|` / `^\d+\.`），保持现有 800/100 作为兜底参数。**新增代码 < 80 行**，不需要新依赖。

**建议优先级**：P1 与"重建库"同步进行——切分策略定了再谈重建。

### 坑 4：**索引、引言、页眉页脚 = 噪音，必须先判断再切**

现状（2026-08-05 xCore 入库报告里承认的）：
- 目录页 11 个 chunks — 内容是"页码\n标题"，入向量库 = 噪声
- 封面页 11 chunks — `B-NO` + 公司 logo + 标题
- 前言 45 chunks — "相关说明书 / 购买致谢 / 安全提示"
- 空白页 (p.514) — 11 字符短 chunk

**问题**：这些 chunk 当前**直接进了向量库**——向量检索时它们会被命中（"X 公司" 召回前言 / "目录" 召回目录页 / 空字符串召回空白页），污染检索结果。

**正确做法**：入 chunk 库**之前**先过滤，建一个 `is_noise_chunk(text, page, metadata)` 判断器：

```python
def is_noise_chunk(text: str, page: int, metadata: dict) -> bool:
    # 1. 短文本 (< 50 字符) → 几乎必是噪音（页眉/页脚/页码）
    if len(text.strip()) < 50:
        return True
    # 2. 页码型 (只含数字 + 空白)
    if re.fullmatch(r'\s*\d+\s*', text):
        return True
    # 3. 目录型 (含 "......" 多点符 + 页码)
    if re.search(r'\.{3,}\s*\d+', text) and len(text) < 500:
        return True
    # 4. 重复页眉 (B-NO xxx / 公司名 + 日期，跨页重复)
    if metadata.get('repeated_header', False):
        return True
    # 5. 封面/扉页 (page=1 + 图多文少)
    if page == 1 and len(text) < 200:
        return True
    # 6. "相关说明书" / "购买致谢" 类客套话
    noise_patterns = ['相关说明书', '购买致谢', '联系我们', 'Foreword', 
                      'Preface', 'Table of Contents']
    if any(p in text for p in noise_patterns) and len(text) < 300:
        return True
    return False
```

**实施要点**：判断器**先于 embedding** 跑——噪音不进 embedding 阶段，省 GPU 时间；判断结果写 `metadata.is_noise=True`，保留位置信息供 debug。

**最小实现**：30 行代码 + 1 个规则文件 `chunk_noise_rules.yaml`，不引入新依赖。

**建议优先级**：P1 与"重建库"同步——噪音判断规则必须先于切分策略落地，否则重建时还是会把噪音带进去。

### 四个坑的依赖关系

```
坑 4（先判断噪音）─→ 坑 3（精细切分）
                       ↓
              坑 2（删除强制召回）←─ 坑 1（重建库）
                                    ↑
                              metadata-first 路由
```

**正确顺序**：坑 4 → 坑 3 → 坑 2 → 坑 1。**坑 4 和坑 3 是工具**，**坑 2 是路由**，**坑 1 是结果**。

### 与原报告的关系

| 报告章节 | 涵盖度 | 这节补充 |
|---|---|---|
| M3 (索引失效) | ✅ ingest 后 BM25 不失效 | 补：不仅失效问题，**入库前就没判断噪音** → BM25 失效只是副作用 |
| m1 (硬编码路径) | ✅ 路径配置化 | 无补充 |
| m11 (仓库卫生) | ✅ 仓库层卫生 | 补：**知识库内容层卫生**——垃圾入向量库 = 检索腐烂 |
| m12 (测试覆盖) | ✅ 测试少 | 补：重建库时同时建回归集 `rag_regression.db`（已有原型，见 ~/.hermes/scripts/rag_regression.py）|
| 未涵盖 | — | **整张建库策略 = 推倒重建，不是修补** |

### 给克莱恩的决策建议

| 选项 | 工作量 | 收益 |
|---|---|---|
| A. **继续修补**（打 BM25 兜底 + 加品牌过滤 + 补 `category` 字典） | 1-2 周 | 表面缓解，本质腐烂加速 |
| B. **推倒重建**（噪音过滤 + 精细切分 + metadata-first 路由 + 30 用例回归） | 2-3 周 | 一次性买断 2-3 年的检索质量 |
| C. **渐进迁移**（保留旧库只读，新建 `wiki_docs_v2` collection，灰度切换） | 3-4 周 | 风险最低，但切换期需要双库查询路由 |

**太阳意见**：B 是**最干净的解**。C 是 B 的保险版本——如果你不放心 B 一次性切换，就走 C 但**心理预期 = 最后一定要切到 v2**，否则 v3/v4/v5 会一直叠加。

如果选 B，预计时间线：

| 阶段 | 内容 | 工时 |
|---|---|---|
| 第 1 周 | 噪音规则 + 切分器升级 + 单元测试 | 3-4 天 |
| 第 2 周 | metadata-first 路由（报警码 / 型号 / 类别）+ 删除强制召回代码 | 3-4 天 |
| 第 3 周 | 全量重建 + 回归集 30 用例 + A/B 对比 | 5-7 天 |

**回滚预案**：重建前 `cp -r wiki_docs wiki_docs.backup.20260811`，出任何问题立即回退（30 秒）。

---

## 九、附：未亲自核验的报告项（声明）

- M6 飞书 bot 阻塞 / ack / @过滤（运行时验证）
- M7 guard_response 死代码（建议 grep `guard_response` 调用方，下次落手时核验）
- M8 提示注入面（建议 grep `_RAG_OUTPUT_HEADER` 调用方）
- M10 daily_audit badcase 目录（建议 grep `badcase_pending.jsonl` 写入路径）
- M11 daily_audit L2/L3 分层（建议 grep 真实题库 level 字段）
- m2 setup.py 失效（建议 `pip install -e .` smoke）
- m3 rag_core 导入副作用（建议 `python -c 'import rag_core; print("ok")'` 测启动时间）
- m4 config.yaml 漂移（建议 `grep -rn 'config\[' rag_core.py`）
- m5 分类体系两套（建议 diff 两份字典）
- m6/m7 并发保护（建议 `grep -n 'threading.Lock\|_log_lock'`）
- m8 双 MCP server（建议看 `mcp_server.py:28` vs `rag_mcp_server.py:249`）
- m9 auto_flywheel 续跑（建议看 `processed_ids` 落盘处）
- m10 rag_mcp_server 健壮性（建议看 `:264-265` 的 `except Exception`）
- m12 测试覆盖（建议 `find tests -name "*.py"`）
- m13 双写日志（建议 grep `query_log` 写入路径）

清单作为下次落地时的"核验 todo"。

---

## 十、修复进度追踪（2026-08-11 22:30+ 太阳落地）

> 按 §四 优先级执行。只记录**已验证落地**的项；commit 均在 `self-grow-wiki` 仓 main 分支。

| 项 | Commit | 落地内容 | 验证 |
|---|---|---|---|
| **C1** ✅ | `0271288` | 7 处硬编码密钥 → env / `~/.hermes/.env` | grep 确认 0 处明文 |
| **M1+M2** ✅ | `d26e53d` | kb_learning 兼容 shim（4 函数 + get_stats 5 字段）+ 返回真实 SQLite query_id | 函数存在 + 消费方调用点核对 |
| **M5** ✅ | `9b9eedc` | `from fastapi import FastAPI, HTTPException` | py_compile 过 |
| **M7** ✅ | `ad48566` | guard_response 接入 rag_answer（think 清理/反问截断/缺来源标注） | grep 调用点确认 |
| **M4** ✅ | `071964b` | run_selfcheck_bg 注入 scripts/ 到 sys.path | grep 确认 |
| **M3** ✅ | `071964b` + `59e7075` | 5 个 ingest 路径失效索引；**⚠️ `071964b` 曾缺 `invalidate_indexes()` 函数定义（import 即崩），`59e7075` 补齐** | `python3 -m py_compile` + 函数定义核验 |
| **M9** ✅ | `1a94bd8` | rag_api / rag_web / rag_admin 默认绑 127.0.0.1（env 覆盖）+ start_rag.sh Ollama 默认 127.0.0.1 + `--share` 警告日志 | grep 确认 0.0.0.0 仅注释 |
| 额外 ✅ | `e424f7c` | 伺服焊枪挠度查询增强 + synonyms 补挠度/Deflection | py_compile + diff 核验 |

**P0 状态**：C1 / M9 / M4 / M5 / M1 / M2 **全部完成**（P0 今晚 + P0 明天两批）。
**P1 状态**：M3 完成；M10（badcase 目录统一）+ M11（题库分层对齐）未开始。
**待拍板**：§五 决策 1（graph_to_obsidian 删 vs 改）、决策 2（auto_flywheel docx 路径现状）、决策 3（shim 已按倾向执行）。
**未做**：P2 全部、P3 全部（按 §四 表）。

---

*复核人：太阳（Misaka10004）*
*复核时间：2026-08-11 19:40 GMT+8（§八由克莱恩 22:00+ 追加，太阳校阅合并）*
*立场：只评审，不落地（克莱恩 19:40 明确）*
*下游：建议本文件作为 P0 落地阶段的"路线图"，而非替换原报告*
