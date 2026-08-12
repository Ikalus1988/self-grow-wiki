# self-grow-wiki 第二波评审建议落地核验

- **核验日期**: 2026-08-12
- **核验对象**: GitHub `Ikalus1988/self-grow-wiki` main 分支 HEAD (`71923d3` 2026-08-12 10:38 UTC)
- **核验方式**: 远程逐文件 grep + 4 个新 commit patch diff 比对 + 第一波验证报告复查
- **核验范围**: 上次报告 4 个 follow-up + 第一波未做的 P2/P3 全量复查
- **评分**: 7.0/10 → **7.5/10**（F1/F3 已修；引入 verify_code_snapshot.py 门禁；P2/P3 仍未做）

---

## 一、第一波 4 个 follow-up 全部 ✅

| ID | 内容 | Commit | 核验手段 |
|---|---|---|---|
| **F1** | CLI 4 个 ingest 脚本加 invalidate_indexes hook | `3827020` | 4 文件均含 `invalidate_indexes` + `bm25_index.pkl.unlink()` 双保险 |
| **F2** | commit message 写评审 ID | (习俗开始养成) | `3827020` `(评审 F3 复核)`、`071964b` `(评审 M3+M4)`、`1a94bd8` `(评审 M9)` |
| **F3** | local baseline `code/` 同步 C1 修复 | `6fbbf98` | baseline `code/scripts/` 7 文件全部 `raw_sk=0` + helper 定义+调用一致 |
| **F4** | baseline `code/` 策略 | 已隐式修 | baseline README 注明 "code/ 为 2026-08-11 快照，更新请去 GitHub"（snapshot 模式） |

## 二、新增主动加固（评审未要求）✅✅

### N1. gitleaks 密钥扫描门禁（`71923d3`）

新增：
- `scripts/gitleaks.toml` —— 默认规则 + 项目自定义规则（Lark app_secret、中文"密钥/密码"声明）
- `scripts/verify_code_snapshot.py` —— **4 门禁** pre-commit-style 检查：
  1. py_compile 所有 .py
  2. gitleaks 密钥扫描（业界标准，替代手写正则）
  3. `_load_deepseek_key` 调用-定义一致性（防 `3827020` 那种"修复破坏 helper"事故）
  4. F1 hook 完整性（CLI ingest 脚本必须有 invalidate_indexes）

**评价**：**真正防御性工程**。第一波 F1 的根因 = 没有自动化门禁，所以"修复 → 新破坏"循环 4 次（`071964b` → `59e7075` 补函数 → `3827020` 又破坏）。`verify_code_snapshot.py` 直接堵这条路径。

**问题**：门禁**只查 baseline 仓库 `code/`**，**不查 GitHub remote 的 `self-grow-wiki`**——而 remote 才是 active dev 仓。建议：
- 把 verify 脚本移到 GitHub remote `self-grow-wiki` 仓库
- 加 `.git/hooks/pre-push`（baseline 仓库 GitHub 不支持 hooks，所以必须靠 CI/本地 pre-commit）

### N2. baseline README 安全段更新

旧版："⚠️ `备注.txt` 含 GitHub PAT 明文，建议撤销"——指名道姓给攻击者情报。
新版："本仓库已通过凭据扫描，不含任何密钥明文。本机目录中个别未入库的本地文件可能含历史凭据（已 .gitignore 排除），请勿入库或分享；如有泄露请及时撤销轮换。"

**评价**：**正确的安全姿态**——告诉用户"会扫 + 已扫"，但**不告诉**攻击者"在哪里 + 什么时候"。这是行业最佳实践。

---

## 三、剩余未做（13 项，分两档）

### A. 真正的 P2/P3（评审预期，未做）

| 项 | 状态 | 证据 |
|---|---|---|
| **m1** hp 用户路径 (10 处) | ❌ | auto_flywheel.py:1 / daily_audit.py:1 / doc_verify.py:1 / graph_to_obsidian.py:4 / import_batch.py:3 = **10 处**（同第一波） |
| **m1** SAG 路径 | ❌ | `config.yaml:9` `/mnt/c/Users/Eric Jia/SAG-poc/sag_lite.db` 仍是绝对路径 |
| **m2** setup.py 失效 | ❌ | `entry_points` 仍引用不存在的 `rag_flywheel_batch`，`py_modules` 只含 `retriever` + `rag_core` |
| **m3** 懒加载 | ❌ | rag_core 导入时 warmup 仍跑 |
| **m4** config.yaml 漂移 | ❌ | `config.yaml.llm.channels` 定义了 mizu/qwen，但 `rag_core.MODEL_CHANNELS` 仍硬编码——配置未被代码读取 |
| **m5** 分类两套 | ❌ | — |
| **m6** JSONL 锁 | ❌ | — |
| **m7** SQLite 锁 | ❌ | — |
| **m8** 双 MCP server | ❌ | `mcp_server.py` 与 `rag_mcp_server.py` 仍并存 |
| **m9** flywheel 续跑 | ❌ | — |
| **m10** rag_mcp_server 健壮性 | ❌ | — |
| **m11** 仓库卫生 | ❌ | `.gitignore` 不含 `*.bak` / `会话*.txt` / `test_plugin.py`（仅 `archive/chat-logs/`） |
| **m12** 测试覆盖 | 部分 | M11 判定测试已补，其他链路无 |
| **m13** 双写日志 | ❌ | `rag_web` 不写 SQLite query_log |
| **M6** bot 异步 + ack + @过滤 | ❌ | `feishu_rag_bot.py:on_message` 仍同步 `query_rag()`，无 @ 过滤，无 ack（**有改进**：`extract_question` 会 strip `@user`，但只在 strip 后还 ≥ 2 字符就触发——任意消息都触发 RAG 调用） |
| **M8** 提示注入边界 | ❌ | `rag_inject.py:27` `【指令】基于以上文档片段回答` 仍直接拼接；`rag_mcp_server.py:273` `_RAG_OUTPUT_HEADER = "[SYSTEM]…必须原样输出"` 仍注入 |
| **M13** rag_web 双写 | ❌ | rag_web:65 `query_id = kb_learning.log_query(...)` 只写 JSONL 不写 SQLite |

### B. 新发现的轻微问题（评审未提）

#### N3. `3827020` commit message 误导

消息：`fix(security): 修复 C1 修复损坏的 helper + 同步 F1 invalidate_indexes hook (评审 F3 复核)`

但 patch diff 显示：`FLASH_LLM = OpenAI(api_key=_load_deepseek_key(), ...)` **被改回** `OpenAI(api_key=FLASH_KEY, ...)`——这看起来是"破坏"。实际是：`FLASH_KEY = _load_deepseek_key()`（line 30），所以 `FLASH_KEY` 本身就是 helper 返回值。"改回"是用变量替换内联调用，**更整洁**。

**问题**：commit message 应写"改用变量替换内联调用（更整洁，行为等价）"，而不是"修复损坏的 helper"——后者**让人误以为是 bug 修复**。

**建议**：commit message 写真实意图，不写容易引起 review 误读的措辞。

#### N4. verify_code_snapshot.py 第 3 门禁"假阳性安全"

门禁 3：`_load_deepseek_key` 调用-定义一致性。文件 A 用 `from other import _load_deepseek_key; _load_deepseek_key()` —— 门禁会判 "调用无定义"。

**现状**：仓库里**没有**这种跨文件用法（每个文件自包含 helper 定义），所以不会假阳性。

**风险**：未来重构（如把 helper 移到 `rag_core.py`）时，门禁会破坏所有调用方。

**建议**：门禁改为"调用方必须有定义，或 `from` 引用"——3 行 patch。

---

## 四、Ponytail 视角的代码质量观察

### Lazy fix 候选（如果下一波评审触发）

| 文件 | 现状 | Lazy 建议 |
|---|---|---|
| `code/scripts/audit/audit_chunks_p1.py:11-22` + 6 个兄弟 | 14 行 helper 复制 7 次 | 提取到 `scripts/_secrets.py`，`from _secrets import _load_deepseek_key` —— 1 行改 7 文件（**已被门禁 #3 隐含鼓励**，但当前实现是"复制粘贴"） |
| `code/scripts/import/{import_batch,rag_builder,rag_builder_ocr,rag_import_fanuc}.py` | 17 行 `invalidate_indexes + bm25_pkl.unlink()` 复制 4 次 | 提取到 `scripts/_post_ingest.py`，4 文件各 1 行 hook |
| `code/feishu_rag_bot.py:18-43` | 26 行手写 `_load_env()` 解析 `.env` | 用 `dotenv` 或 stdlib `pathlib` + `configparser` —— 但**没装 dotenv**，手写也 OK |

### 真值得修的（如果不修下次还踩）

- **verify_code_snapshot.py** 门禁 #3 假阳性风险（N4）—— 否则下次重构 `rag_core._load_deepseek_key` 全仓库炸
- **feishu_rag_bot.py M6** —— 同步 `query_rag(timeout=60)` 在 WS ping 周期里 = 高概率断线，不是"集成层质量"问题是**生产可用性**问题

---

## 五、决策建议（按 ponytail 优先级）

| 优先级 | 决策 | 工作量 | 价值 |
|---|---|---|---|
| **A. 立即** | 把 `verify_code_snapshot.py` + `gitleaks.toml` 也部署到 GitHub remote `self-grow-wiki`（加 pre-push 或 GitHub Action） | 1-2h | 防止 active dev 仓再次出现"修复 → 新破坏"循环 |
| **B. 本周** | m1 hp 路径 → env（10 处批量改） | 1h | 一次性买断可移植性 |
| **C. 本周** | extract helper 去 7 文件重复（lazy refactor） | 30 min | 7×14 行 → 7×1 行 |
| **D. 延后** | M6/M8/M13/M2 集成层 | 1-2 天 | PyPI 发布阻塞才需要 |
| **E. 永不** | m3 懒加载 / m9 flywheel 续跑 / m10 mcp 健壮性 | — | 不影响使用，YAGNI |

**现在 = 安全可用**（P0 + F1/F3 + gitleaks 门禁），**对外发布仍不安全**（M6/M8/M9 默认值虽改但需文档配套）。

---

## 六、核验方法学声明

- 核验源：仅 GitHub remote main 分支 HEAD（`71923d3`）
- 本次未亲自跑：gitleaks 二进制是否真在 `~/.local/bin/gitleaks`（门禁脚本会告诉你）
- 本次未核验：CI 是否在 GitHub Actions 配置（远程仓库目录树未发现 `.github/workflows/` —— **确认无 CI**，门禁只在本地 baseline 仓库生效）
- 上次报告 §七 "未亲自核验" 项中 M6/M8 仍未跑，结论维持

---

*核验人：Codewhale reviewer agent*
*核验时间：2026-08-12 (GMT+8)*
*上游报告：`评审/2026-08-12_self-grow-wiki_review-verification.md`（第一波）*