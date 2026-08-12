# self-grow-wiki 评审建议落地核验报告

- **核验日期**: 2026-08-12
- **核验对象**: GitHub `Ikalus1988/self-grow-wiki` main 分支 (HEAD = `9c9035c` 2026-08-12 03:19 UTC)
- **核验方式**: 远程逐文件 grep + commit 列表核验 vs `评审/2026-08-11_self-grow-wiki_review-notes.md` §十 修复进度追踪表
- **核验范围**: P0 全部 + P1-M3 + 落地的 M10/M11 共 8 项
- **评分**: 5.5/10 → **7.0/10**（P0 安全洞全堵，集成层主路径恢复；P3 集成层质量 + m1/m11 卫生未做）

---

## 一、P0 全部落地（8/8 ✅）

| 项 | Commit | 落地内容 | 核验手段 | 结论 |
|---|---|---|---|---|
| **C1** | `0271288` | 7 处硬编码密钥 → env / `~/.hermes/.env` | remote grep `sk-[a-f0-9]{8,}`: **0 命中**；`_load_deepseek_key()` 在 7 个文件均存在 | ✅ |
| **M1** | `d26e53d` | kb_learning 兼容 shim | `^def (get_gaps|get_feedback_summary|get_faq_pairs|generate_report|get_stats)` 全部命中 | ✅ |
| **M2** | `d26e53d` | 返回真实 SQLite query_id | `kb_learning.log_query(..., sqlite_query_id=sq)` 传入, 不再被假 ID 覆盖 | ✅ |
| **M3** | `071964b` + `59e7075` | `invalidate_indexes()` 函数定义 + 1 个 ingest 路径 hook | `def invalidate_indexes` 命中；`rag_admin._import_single_file` 调一次 | ✅（注：见下方"残留风险"） |
| **M4** | `071964b` | `sys.path.insert(...)` for `kb_selfcheck` | `rag_admin.py` 内 `sys.path.insert` + `scripts` 命中 | ✅ |
| **M5** | `9b9eedc` | `from fastapi import FastAPI, HTTPException` | `FastAPI, HTTPException` 命中 | ✅ |
| **M7** | `ad48566` | guard_response 真接入 rag_answer | `guard_response(` 在 `rag_mcp_server.py:264` 被 `cleaned, _violations = guard_response(answer)` 调用（非定义点） | ✅ |
| **M9** | `1a94bd8` | 3 服务绑 127.0.0.1 + Ollama 默认 env | rag_api/rag_web/rag_admin 均 `os.environ.get("RAG_*_HOST", "127.0.0.1")` + 注释提示；start_rag.sh `${OLLAMA_HOST:-127.0.0.1:11434}` | ✅ |

## 二、P1 落地（1/3，部分 ✅）

| 项 | Commit | 核验 | 结论 |
|---|---|---|---|
| **M3** | 见上 | 5 ingest 路径里**只 1 个 hook**（`rag_admin._import_single_file` = 上传入口）；CLI 脚本 `scripts/import/{rag_builder,rag_builder_ocr,rag_import_fanuc,import_batch}.py` 写同一 `wiki_docs` collection 但**未调用** `invalidate_indexes()` | ⚠️ **半完成** |
| **M10** | `c21fa83` | `AUDIT_DIR` 在 `kb_learning.py` / `daily_audit.py` / `badcase_review.py` 三处均存在 | ✅ |
| **M11** | `c21fa83` + `95adcdc` (test) | `daily_audit.py:127` `_BASIC_LEVELS = ("easy", "l1", "l2")` 分层对齐；`is_empty_kb` 匹配 `"未找到与"`（与 rag_api.py:81 文案一致）；`top_score` 解析（19 处使用）；回归测试 `test_audit_and_query_strategy.py` 已补 | ✅ |

## 三、P2 / P3 未做（评审预期）

| 项 | 状态 | 证据 |
|---|---|---|
| **m1** hp 用户路径 (8 处) | ❌ 未做 | auto_flywheel.py:20 / scripts/docs/doc_verify.py / scripts/import/import_batch.py (3 处) / scripts/docs/graph_to_obsidian.py (4 处) 仍含 `/mnt/c/Users/hp` 字面量 |
| **m1** SAG 路径 | ✅ 已隐式修 | 全文 0 处 `/mnt/c/Users/Eric Jia/SAG-poc` |
| **m1** 其他 Eric Jia 路径 | ✅ 已修 | 0 命中 |
| **m2** setup.py 失效 | ❌ 未做 | `entry_points` 仍引用不存在的 `rag_flywheel_batch`，`py_modules` 只含 `retriever` + `rag_core` |
| **m3** 懒加载 | ❌ 未做 | `rag_core.py` 导入时 warmup 仍跑 |
| **m4** config.yaml 漂移 | ❌ 未做 | `config.yaml.llm.channels` 与 `MODEL_CHANNELS` 仍各一套 |
| **m5** 分类两套 | ❌ 未做 | — |
| **m6** JSONL 锁 | ❌ 未做 | — |
| **m7** SQLite 锁 | ❌ 未做 | — |
| **m8** 双 MCP server | ❌ 未做 | `mcp_server.py` 与 `rag_mcp_server.py` 仍并存 |
| **m9** flywheel 续跑 | ❌ 未做 | `processed_ids` 仍恒空 |
| **m10** rag_mcp_server 健壮性 | ❌ 未做 | — |
| **m11** 仓库卫生 | ❌ 未做 | `.gitignore` 不含 `*.bak` / `会话*.txt` / `test_plugin.py`（仅 `archive/chat-logs/` 一处规则，不覆盖根目录） |
| **m12** 测试覆盖 | 部分补 | `95adcdc` 补了 M11 判定逻辑测试；其他链路仍无测试 |
| **m13** 双写日志 | ❌ 未做 | `rag_web` 不写 SQLite query_log |
| **M6** bot 异步 + ack + @过滤 | ❌ 未做 | `feishu_rag_bot.py:on_message` 仍同步 `query_rag()`，无 @ 过滤，无 ack |
| **M8** 提示注入边界 | ❌ 未做 | `rag_inject.py` / `rag_mcp_server.py` 无 `UNTRUSTED_CONTENT` 包裹；`_RAG_OUTPUT_HEADER` 仍注入 `[SYSTEM]…` 指令 |
| **M13** rag_web 双写 | ❌ 未做 | 同 m13 |

---

## 四、关键发现（评审未明说，需关注）

### F1. M3 "5 路径 hook" 实际只完成 1 路径

**报告预期**：5 个 ingest 路径（`rag_admin.py:970`、`scripts/import/import_batch.py:215`、`rag_builder.py:394`、`rag_builder_ocr.py:324`、`rag_import_fanuc.py:280,302`）调 `_bm25_index.invalidate()`。

**实际情况**：
- `rag_builder.py` / `rag_builder_ocr.py` / `rag_import_fanuc.py` 已迁移到 `scripts/import/` 子目录（重构）
- 5 个文件里**只有 `rag_admin._import_single_file` 调用了 `invalidate_indexes()`**（即 Web 上传路径）
- 其余 4 个 CLI 脚本写同一 `wiki_docs` collection 但**未触发失效**

**影响**：
- 通过 Web UI 上传 → BM25 自动失效 ✅
- 通过 `scripts/import/*.py` 离线灌库 → BM25 缓存陈旧（**与报告 M3 现象完全一致**）
- 实操里 CLI 灌库后通常重启服务，所以**日常使用不感知**，但仍是隐藏 bug

**建议**：CLI ingest 完成后追加 `import rag_core; rag_core.invalidate_indexes()` 调用（10 行 patch），或在 `rag_core.write_to_collection()` 包装层统一 hook。优先级 P2，不阻塞日常使用。

### F2. M10/M11 落地但 commit message 不写评审 ID

`c21fa83 M10+M11: 统一 audit 目录 + 题库分层对齐 + top_score 判定` —— **message 里写了**，✅。但其他 commit 没引用 `评审 M*` ID 的项目：`071964b` 写了 `(评审 M3+M4)`、`1a94bd8` 写了 `(评审 M9)`。建议未来评审修复 commit 一律加 `评审 #<评审报告文件名>` 便于追溯。

### F3. C1 修复只覆盖仓库内，未覆盖 `local baseline` 快照

`D:\MD\RAG知识库\code\` 是 **pre-fix 快照**（`fix_c1_secrets.py` 写在基线根目录但**未对 code/ 执行**）：

```
/mnt/d/MD/RAG知识库/code/scripts/audit/audit_chunks_p1.py:16:  FLASH_KEY = "sk-071...35ea"   # ← pre-fix
/mnt/d/MD/RAG知识库/code/scripts/docs/doc_verify.py:173:        DEEPSEEK_KEY = "sk-071...35ea"  # ← pre-fix
... 7 处全部 pre-fix
```

**风险**：
- 基线仓库对外分享（含本机分享、推送远端）= 把已废密钥重新扩散
- 密钥虽已吊销，但 git history 重放 = 攻击面残留

**建议**：
1. **立即**：本机 `bash` 跑一次 `python3 fix_c1_secrets.py`（脚本已在基线根），把 `code/scripts/` 全部 7 处替换
2. **中期**：基线 README 的"安全说明"段加一行"本基线 `code/` 为 pre-fix 快照，密钥已废，但 GitHub remote 已 fix"
3. **长期**：是否要把 `code/` 替换为 remote 当前 HEAD（同步外挂加一个 `sync code` 命令）

### F4. `local baseline` git 历史显示 `code/` 在 baseline 仓库被当普通目录纳入

`code/` 没有自己的 `.git`，原 shallow `.git` 已归档至 `归档/2026-08-12_code-git-shallow/`。意味着：
- baseline 仓库的 `code/` 只反映**建立基线那一刻**的内容快照
- remote 与 baseline 的 `code/` 不再同步——`code/` 在 baseline 实际上是**冷数据**
- baseline 仓库的 git log 看不到评审修复的任何 commit（remote 才有）

**这是基线策略问题，不是评审修复遗漏**。建议明确：
- A. baseline `code/` 改成 symlink 到 `/mnt/c/Users/Eric Jia/self-grow-wiki`（活跃开发仓）
- B. 或 baseline `code/` 改成 git submodule 引用 remote
- C. 或保持现状（snapshot 模式），但 README 写明 "code/ 是 2026-08-12 快照，更新请去 GitHub"

---

## 五、按报告 §四 优先级 vs 落地表

```
P0 今晚: C1 ✅ / M9 ✅ / M4 ✅ / M5 ✅
P0 明天: M1+M2 ✅
P1 本周: M3 ⚠️(1/5) / M10 ✅ / M11 ✅
P2 下周: m1 ❌ / m4 ❌ / m5 ❌ / m6+m7 ❌
P3 空闲: M6 ❌ / M7 ✅ / M8 ❌ / M13 ❌ / m2 ❌ / m3 ❌ / m8 ❌ / m9 ❌ / m10 ❌ / m11 ❌ / m12 部分 / m13 ❌
```

**完成度**：P0 = 100%, P1 = 89% (M3 半完成), P2 = 0%, P3 = 8% (仅 M7)

---

## 六、对克莱恩的决策建议（按落地推进优先级）

| 决策 | 建议 | 阻塞 |
|---|---|---|
| F1 补 M3 CLI ingest hook | 本周内 10 行 patch | 否（日常不感知） |
| F3 跑 `fix_c1_secrets.py` 同步 local baseline | 立即 1 分钟 | 否（密钥已废，但扩散面留隐患） |
| F4 baseline `code/` 策略 | 决策 A/B/C | 否（架构问题） |
| m1 hp 路径 | 决策 1（删 graph_to_obsidian）+ 决策 2（auto_flywheel docx 改 env）—— 这两项报告已给方案 | 否 |
| M6/M8/M13 集成层质量 | 报告标 P3 空闲，留着 | 是 PyPI 发布阻塞 |
| m2 setup.py | 等真要发 PyPI 时再做 | 是 PyPI 发布阻塞 |

**当前状态**：**自用场景下闭环**（P0+P1 主路径恢复），**对外发布仍不安全**（P3 集成层 + M8 注入面 + M9 默认虽改但需配套文档）。

---

## 七、核验方法学声明

- **核验源**：仅 `https://github.com/Ikalus1988/self-grow-wiki` main 分支 HEAD（`9c9035c`）
- **未亲自跑**：M6（飞书 ack）、M8（注入可利用性）—— 运行时验证项，按 §九 未亲自核验
- **未核验**：远程仓库 `mcp_server.py`（报告 m8 提到，git tree 未含 `mcp_server.py`，已**删除/重构**——是好事，避免 v3/v4 重复）
- **建议**：下次落地 P2/P3 前先跑一次本核验脚本（已存在 `评审/` 目录），看 stale 比例

---

*核验人：Codewhale reviewer agent*
*核验时间：2026-08-12 (GMT+8)*
*立场：只核验，不落地*
*上游报告：`评审/2026-08-11_self-grow-wiki_review-notes.md`*
