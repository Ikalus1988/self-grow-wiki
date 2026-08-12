# MisakaNet 仓库代码评审报告

- **评审日期**: 2026-08-11
- **评审对象**: `/mnt/c/Users/Eric Jia/MisakaNet`（Ikalus1988/MisakaNet，main，v2.16.0；当日已 pull 合并远端 538 提交，比远端最新落后约 1-2 个提交）
- **评审方式**: 只读静态审查（reviewer agent）
- **仓库可见性**: public
- **评分**: **5.5 / 10**

---

## Critical

### C1. 未鉴权的 GitHub Token 代理（信息泄露/越权读）
`workers/register-proxy.js:317-331`（及 `register-proxy-sw.js` 同款）
`/api/github/*` 将任意 GET 路径原样转发到 `api.github.com`，并带上 `REGISTER_TOKEN`（README 声明该 token 有 contents+issues 写权限）。任何匿名访客可 `GET /api/github/user`、枚举仓库私有内容、探测 token 权限范围。worker 部署在公网（misakanet.org）。
修复：删除通用代理，只保留白名单端点（counter/lessons/helpful）；或改用只读专用 token 并对 path 做前缀白名单校验。

### C2. 邮件 intake 内容未脱敏即发布到公开 GitHub Issue
`workers/email-register/src/index.js:231-267`（`createAuditIssue`）
邮件正文（最长 12000 字符）直接写入公开 Issue body，只做了 `<!--` 转义，没有应用 `scripts/intake_redact.py` 的脱敏逻辑。用户把含 token/私钥的报错日志发到 bot 邮箱 → 凭据公开泄露。
修复：worker 中移植 `REDACT_PATTERNS`，创建 Issue 前先脱敏；对 `[REDACTED]` 计数并拒绝未脱敏内容。

### C3. MCP 服务器路径穿越（任意文件读取）
`scripts/mcp_server.py:208-231`、`scripts/mcp_http_server.py:78-94`
`lesson_path = REPO_ROOT / path_or_id`：传绝对路径（`Path.joinpath` 遇绝对路径直接替换）或 `../../...` 即可读取任意文件，前 5000 字符经 `misakanet_get_lesson` 返回给 MCP 客户端。`mcp_http_server.py` 是 streamable-http 公网可达。
修复：`resolved = lesson_path.resolve()` 后校验 `resolved.is_relative_to(REPO_ROOT.resolve())`，拒绝越界；补回归测试。

---

## Major

### M1. `misakanet_get_lesson` / `handle_get_lesson` 路径穿越（与 C3 同源，按端分开计）
`scripts/mcp_http_server.py:78` 同上，另加 `REPO_ROOT / path_or_id` 拼接后 `exists()` 判断，未解析规范化。

### M2. 注册成功页反射型/存储型 XSS
`workers/email-register/src/index.js:308-324`（`renderPage('success')`）
`${data.email}`、`${data.name}`、`${data.nodeId}` 未做 HTML 转义。`email` 校验只要求 `includes('@')`，`<script>…</script>@x.com` 可通过并原样反射。邮箱/名称还会写入 KV。
修复：所有插值做 `escapeHtml`；服务端对 email 做正则格式校验。

### M3. `submit_lesson.py` 把 PAT 写进 .git/config 且经 shell 执行
`scripts/submit_lesson.py:228,255-258`
`remote_url = f"https://ikalus:{pat}@github.com/..."` → `git remote set-url origin <url> && git push`（`shell=True`）。后果：(a) PAT 明文持久化在 `.git/config`；(b) `shell=True` + 拼接 URL 注入模式危险；(c) 自带 lesson 还把这个当推荐做法传播。
修复：改用 `GIT_ASKPASS`/credential helper 或 `gh auth`；禁止 token 入 remote URL 与 argv。

### M4. 搜索结果与 lesson 落盘位置不一致（新 lesson 永远搜不到）
`scripts/queue_lesson.py:155,274` 写入 `lessons/` 根；`misakanet/search/engine.py:174-176` 只扫描 `lessons/core` 和 `lessons/contrib`；`scripts/update_lessons_json.py:16` 也只索引 core/contrib。当前 `lessons/` 根下已有 3 个真实 lesson 搜不到（索引是旧文件位置残留）。
修复：queue_lesson 写入 `lessons/contrib/`；引擎/索引/写入三方统一目录契约；重新生成 lessons.json；`skill_cron.py:24` 同样改写入 contrib。

### M5. worker `/api/lessons` 端点必然 404
`workers/register-proxy.js:285-289` 与 `register-proxy-sw.js:757`：`fetchFromGitHub(token, "lessons.json", "data")` —— 仓库根目录没有 `lessons.json`（实际在 `data/lessons.json`），且 ref 传了 `"data"`（非分支名）。GitHub API 返回 404 → `/api/lessons` 永远报错。
修复：`fetchFromGitHub(token, "data/lessons.json", "main")`，补 worker 单元测试。

### M6. HTTP MCP 服务器 BM25 分支是死代码
`scripts/mcp_http_server.py:41,63`：`from misakanet.search.engine import MisakaNetSearchEngine` —— 全仓库不存在该类。`ImportError` 被吞 → `HAS_BM25` 恒为 False，HTTP 服务器在无 SAG 时直接返回 "No search engine available"。
修复：与 mcp_server.py 一致导入 `_load_docs_cached`/`_search_cached`。

### M7. guard.py 在 Windows 负退出码下崩溃，墓碑生成失败
`misakanet/guard.py:113-116`：`signal.Signals(signal_num).name` —— Windows 上被强杀时 `proc.wait()` 返回 `-1073741510`（0xC000013A）等大负数，`signal.Signals()` 抛 `ValueError`，guard 自身崩溃、墓碑写不出来（本项目含 .bat/.ps1 hook，Windows 是目标平台）。
修复：`try: name = signal.Signals(n).name except ValueError: name = str(n)`。

### M8. intake_redact 先截断后脱敏，跨边界 secret 存活
`scripts/intake_redact.py:58`：`result = str(text)[:max_length]` 在正则脱敏之前执行。PEM 私钥等多行 secret 若横跨截断点，`BEGIN…END` 无法完整匹配 → 私钥前缀原样进入持久化 payload。
修复：先应用全部 `REDACT_PATTERNS`，再截断；`redact_payload` 对嵌套 dict/list 递归处理。

---

## Minor（选列）

1. `scripts/mcp_server.py:713-726` main 循环无 try/except，异常直接杀死服务器；`top` 无类型/范围校验。
2. 状态词表不一致：`lesson_gate.py:31` `VALID_STATUS = {published, draft, archived}` vs `data/lessons.json` 多数为 `"active"` vs `engine.py:24` 给 `"active"` 加分。三处词表互不相同。
3. `lessons/index.md` Markdown 表格损坏（表头声明表格、条目是列表项，tags 带字面引号）。
4. `data/lessons.json` 含伪条目（`id="README"`、confidence 恒 0.5 等模板填充）。
5. `queue_lesson.py` `_get_token()` 解析 `~/.git-credentials` 但结果从未使用（死代码 + 无谓读取凭据）。
6. `queue_lesson.py:159-181` slug 碰撞即"合并"两条不同 lesson，破坏原 lesson 元数据且无提示。
7. `guard.py:161-171` `/tmp/misakanet-tombstone-<pid>.json` 可预测路径（本地 symlink 竞争，低危）。
8. `langchain_tool.py:315-352` `_audit_sliding_window` 死代码 + `_check_blacklist` 无限增长。
9. `misakanet/profile.py:120-126` f-string 里 `\\n` 输出字面 `\n`；`_save` 非原子，并发丢计数。
10. `scripts/push_via_api.py:6` 硬编码他机路径 `/mnt/c/Users/hp/MisakaNet`；66-70 行参数自相矛盾。
11. worker 双实现漂移：`register-proxy.js` 与 `register-proxy-sw.js` 两份独立实现，bug 需修两遍。
12. `/api/health` 返回 `hasToken: !!env.REGISTER_TOKEN`，公网泄露配置状态；注册计数器无 409 冲突重试。
13. `email-register` `parseInt(lastReg)` 遇脏 KV 值 NaN → 限频绕过（低概率）；Turnstile sitekey 硬编码。
14. `hub/master/master_api.py:53-54` 无运行 loop 时 `asyncio.create_task` 抛 RuntimeError；`token_manager.py:130` secret 比较非恒定时间。
15. `skill_cron.py:13-15` `subprocess.run(f"git {cmd}", shell=True)` 模式脆弱。
16. 邮件 intake 的 `lessonContent` 原文存 KV（30 天 TTL）并 forward 给维护者邮箱 —— 存储侧脱敏缺失。

---

## Nit

- 重复红名单实现：`guard.py` `_SECRET_PATTERNS` 与 `intake_redact.py` `REDACT_PATTERNS` 两套，规则已不一致（guard 缺 PEM 块、信用卡等）。
- `retrieval_noisebench.py` 与 `retrieval_noise_bench.py`、`score_lessons.py` 与 `check_lesson_quality.py`、`validate_lessons.py` 与 `lesson_gate.py` 功能重叠。
- `web/package.json:5` description 塞 HTML；`server.mcpb`/`server.json` 等根目录产物无说明。
- `workers/wrangler.toml:7` 与 `web/wrangler.jsonc:17` KV id 仍是 `YOUR_KV_NAMESPACE_ID` 占位符。
- `engine.py:534,546` 单字符 CJK token 高亮刷屏（装饰性）。
- `intake_classify.py:34-36` `BUG_SIGNALS` 含 "misakanet"/"worker"/"endpoint"，正面反馈会被误分类为 bug。

---

## SUMMARY

- 评分：**5.5 / 10**。
- 核心本地库（`misakanet/`、search engine、telemetry、lesson_gate、evidence）质量尚可、测试覆盖在同类个人项目中属中上（tests/ 40+ 文件，含路径穿越/限流/脱敏用例）。
- **公网暴露面存在多处真实可利用漏洞**：未鉴权 GitHub Token 代理（C1）、邮件内容未脱敏发公开 Issue（C2）、MCP 路径穿越（C3）、注册页 XSS（M2）、`/api/lessons` 必 404（M5）、HTTP MCP BM25 死分支（M6）、搜索与落盘目录契约分裂（M4）。

### 最重要的 3 条改进建议
1. **先封公网面**：删除/白名单化 `/api/github/*` 代理，worker 侧引入与 Python 一致的脱敏后再写 GitHub Issue，MCP 服务器对 lesson path 做 `resolve().is_relative_to(REPO_ROOT)` 校验并补回归测试。
2. **统一 lesson 目录契约**：写入统一走 `lessons/contrib/`，`engine.py`/`update_lessons_json.py`/`lesson_gate.py` 共用一份配置，重生成 `data/lessons.json`，修复 `/api/lessons` 路径。
3. **消灭双实现漂移**：合并两个 register-proxy、统一两个 MCP server 的搜索后端（消除 `MisakaNetSearchEngine` 死代码）、统一 guard/intake 两套脱敏规则，为两个 worker 补端点级测试。

---

*报告由 Codewhale reviewer agent 生成；C1/C2/C3/M2 基于静态路径分析，未做运行时验证（未部署/请求 worker）。*
