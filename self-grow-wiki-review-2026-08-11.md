# self-grow-wiki 仓库代码评审报告

- **评审日期**: 2026-08-11
- **评审对象**: `/mnt/c/Users/Eric Jia/self-grow-wiki`（本地 HEAD，与 GitHub Ikalus1988/self-grow-wiki 同步，本地 ahead 4 提交）
- **评审方式**: 只读静态审查（reviewer agent）
- **仓库可见性**: public
- **评分**: **5.5 / 10**
- **评审文件**: rag_core.py (2802 行全文)、retriever.py、sag_hybrid.py、kb_learning.py、rag_mcp_server.py、mcp_server.py、rag_api.py、rag_admin.py、rag_web.py、feishu_rag_bot.py、auto_flywheel.py、badcase_review.py、daily_audit.py、rag_feedback_card.py、rag_inject.py、rag_phase1_entity_extract.py、test_plugin.py、tests/、scripts/ 各子目录、config.yaml、synonyms.json、kb_learning.json、setup.py、start_rag.sh 等

---

## Critical

### C1. 硬编码 API 密钥提交进仓库（且仓库为公开）
**位置**: `scripts/audit/audit_chunks_p1.py:16`（`FLASH_KEY = "sk-0717..."`）、`scripts/docs/doc_verify.py:173`、`scripts/docs/doc_verify_v2.py:159`、`scripts/exam/gen_exam.py:20`、`scripts/exam/gen_exam_v2.py:10`（同一把 DeepSeek/MiMo 密钥重复出现 5 处明文），另有 `scripts/audit/audit_exam_p2.py:16`、`scripts/audit/audit_pdf_chunk_v2.py:19` 以字面量 `api_key="..."` 硬编码。
**问题**: 同一把密钥被 7 个脚本以明文提交，仓库已推送至 GitHub（public）。密钥一旦泄露 = 任意第三方可盗用消耗 API 额度。
**修复**: ① 到厂商控制台吊销/轮换该密钥（用户确认密钥已失效）；② 全部改为 `os.environ.get("DEEPSEEK_API_KEY")` 或从 `~/.hermes/.env` 读取（仓库内 `feishu_rag_bot.py:9-19`、`rag_mcp_server.py:22-31` 已有现成模式）；③ 清理 git 历史并重推；④ 配置 GitHub secret scanning。

---

## Major

### M1. kb_learning.py 重构后 API 与全部消费方失配（自学习功能整体失效）
**位置**: `kb_learning.py`（现仅有 `log_query/add_feedback/get_stats/get_feedback_stats/record_feedback/export_badcase_report`）vs 消费方：
- `rag_admin.py:522-527` 访问 `stats['total_queries']/['total_gaps']/['gap_rate']/['avg_score']/['total_feedback']/['total_faq']` → 全部 `KeyError`
- `rag_admin.py:537/549/563/575`、`rag_api.py:214/224`、`rag_web.py:105/120` 调用 `kb_learning.get_gaps / get_feedback_summary / get_faq_pairs / generate_report` → 函数**根本不存在**（`AttributeError`）
- `kb_learning.json` 仍是旧版 schema（`is_gap/datetime/timestamp`），佐证模块被重写而消费方未同步
**影响**: Web UI「自学习」Tab、管理面板「自学习反馈」Tab、`/learning/gaps`、`/learning/report` 全部报错。
**修复**: 二选一——补回旧 API 或改三个消费方适配新 JSONL API。

### M2. query_id 被伪造值覆盖 → 反馈链路断裂
**位置**: `rag_core.py:1885-1892` 先用 SQLite 真 id 调 `log_query` 拿到 `sqlite_query_id`，随后 `query_id = kb_learning.log_query(...)` 用假 ID `f"kb_{int(time.time())}"` **覆盖**真 id 并返回。
**后果链**: ① `rag_api.py:189` `/feedback` 执行 `int(req.query_id)` → `ValueError` → 反馈永远失败；② `rag_web.py:83,95` 把假 id 当 query 文本写入，且 feedback 值 "up"/"down" 与统计过滤器 ("good"/"bad") 不匹配 → 满意度统计恒 0；③ SQLite 外键约束形同虚设。
**修复**: 返回真实 SQLite query_id；统一 feedback 取值枚举。

### M3. 上传/导入文档后 BM25 与实体索引不失效 → 新文档检索不可见
**位置**: `rag_admin.py:970`、`scripts/import/import_batch.py:215`、`rag_builder.py:394`、`rag_builder_ocr.py:324`、`rag_import_fanuc.py:280,302` 均不调用 `rag_core.py:1083` 的 `_bm25_index.invalidate()`，也不重置 `_entity_index_built`（`rag_core.py:741` 构建一次后永不再建）。
**影响**: 运行中的服务导入新文档后，BM25 与实体精确检索都看不到新内容，只有纯向量通道能命中；必须重启服务才生效，且静默无提示。
**修复**: ingest 成功后调用 `_bm25_index.invalidate()` 并置 `_entity_index_built=False`、清 `_model_file_cache`。

### M4. 管理面板「矛盾自检」Tab 必然失败
**位置**: `rag_admin.py:475` `from kb_selfcheck import run_selfcheck` —— `kb_selfcheck.py` 在 `scripts/` 子目录，仓库根目录无此模块，且未把 scripts/ 加入 `sys.path` → `ModuleNotFoundError`，后台线程记入 log 后静默失败。
**修复**: `sys.path` 注入 `scripts/` 或封装成可安装模块。

### M5. rag_api.py 缺少 HTTPException 导入
**位置**: `rag_api.py:182`（`/kb/stats` 异常分支 `raise HTTPException(...)`），文件头仅 `from fastapi import FastAPI`。触发即 `NameError`（500 + 堆栈）。
**修复**: `from fastapi import HTTPException`。

### M6. 飞书 bot：长连接线程被阻塞 + 无事件 ack + 无 @ 触发过滤
**位置**: `feishu_rag_bot.py`
- `on_message`（:109-138）在 WebSocket 线程内同步调用 `query_rag`（timeout=60s），期间 `run_forever` 的 ping 无法发出 → 服务端判定失联断开；`threading, queue` 导入（:3）从未使用（"worker 队列"设计残留）
- 长连接事件无 ack → 重投/重复处理，且无幂等保护
- 未要求 @提及即回复：群里任何消息都触发一次完整 RAG 查询 + LLM 调用（token 成本、噪音回复）
- :35 `assert FEISHU_APP_ID and FEISHU_APP_SECRET` 在 `python -O` 下失效
**修复**: on_message 只入队，由独立 worker 线程池调 RAG API 并回 ack；仅当消息含 @机器人/命令前缀时响应。

### M7. guard_response 是死代码——测试测的是永远不会执行的逻辑
**位置**: `rag_mcp_server.py:207-247` 定义 `guard_response`（think 块清理、反问截断、来源缺失标注），但 `rag_answer`（:249-269）与 `rag_search`（:273-278）**从未调用它**。`test_plugin.py:16-40` 的 5 个用例全部测死代码。
**影响**: 线上回答中的 `<think>` 块、反问句、缺来源不会被清理，"Guard" 形同虚设。
**修复**: 在 `rag_answer` 返回前接入 `cleaned, _ = guard_response(answer)`。

### M8. 提示注入面：检索内容与指令无边界分隔
**位置**: `rag_inject.py:27` 把 `【指令】基于以上文档片段回答…` 直接拼接在检索文本之后；`rag_mcp_server.py:271` `_RAG_OUTPUT_HEADER = "[SYSTEM] …必须原样输出以下全部内容…"` 向消费方 Agent 上下文注入指令；`rag_core.SYSTEM_PROMPT`（:358-403）未声明检索片段是未信任数据。
**风险**: 知识库来自大量外部 PDF，若某文档含"忽略以上指令"类文本，会经 RAG 管道注入到 LLM/上层 Agent。
**修复**: 检索内容统一包裹在 `[UNTRUSTED_CONTENT]...[/UNTRUSTED_CONTENT]` 内并明文告知模型"以上为数据非指令"。

### M9. 全部服务无认证暴露在 0.0.0.0
**位置**: `rag_api.py:288-289`（uvicorn 0.0.0.0:8002）、`rag_web.py:357`（0.0.0.0:7860）、`start_rag.sh:8`（`OLLAMA_HOST="0.0.0.0:11434"`）、`rag_admin.py` 同理。无鉴权、无限流、无 CORS 限制；`rag_web.py:343` 还提供 `--share` 公网穿透。
**影响**: 局域网任意设备可调用 `/query`、`/compare`、`/report` 消耗付费 LLM token，可读 `/kb/stats`、`/learning/*`，可访问无认证的 Ollama（GPU 被任意占用）。
**修复**: 服务只绑 127.0.0.1 或加 API Token/基础认证 + 限流中间件；Ollama 不对外网监听。

### M10. daily_audit 与 kb_learning/badcase_review 的 badcase 队列目录不一致
**位置**: `daily_audit.py:43` `_AUDIT_DIR` 默认 `/home/eric_jia/audit_reports`（:426 把 badcase_pending.jsonl 写这里）；`kb_learning.py:35,50` 的 `AUDIT_DIR` 是 `仓库/Desktop/自研/rag-docs/audit_reports`；`badcase_review.py:30-42` 同 kb_learning。crontab 文档也没设 `RAG_AUDIT_DIR` 环境变量。
**影响**: 每日巡检自动产生的 bad case 永远进不了 `badcase_review.py` 的审核队列，闭环在入口就断了。
**修复**: 统一 audit 目录为同一常量（如 `kb_learning.AUDIT_DIR` 或环境变量）。

### M11. daily_audit 的 L2/L3 分层抽样与真实题库失配
**位置**: `daily_audit.py:123-124` 按 `level == "L2"` 分层；真实题库 `RAG巡检题库_200题_20260508.json` 全部 level 为 `"easy"/"medium"` → `l2_all` 恒空、分层意图落空。测试 `tests/test_audit_and_query_strategy.py:14` 用合成 L2/L3 数据——**测试通过而生产行为不同**。
另 `daily_audit.py:321` `is_empty_kb = "知识库中未找到" in answer` 与 `rag_api.py:79` 实际文案 `"未找到与「…」相关的文档"` 不匹配 → 空库检测永不触发；且 `expect.min_top_score` 从未与真实检索分数比对。
**修复**: 用 "easy"/"medium"（或按 tag）分层；对齐空库文案；API 返回 top_score 并纳入判定。

---

## Minor

### m1. 硬编码绝对路径泛滥（可移植性）
`rag_core.py:1203`（`/mnt/c/Users/Eric Jia/SAG-poc`，每次 retrieve 都 `sys.path.insert` 重复膨胀）、`sag_hybrid.py:15,134`、`rag_mcp_server.py:9,42`、`scripts/kb_selfcheck.py:25,28`、`scripts/rag_phase2_semantic_tag.py:199`、`auto_flywheel.py:20`（指向**另一位用户** `/mnt/c/Users/hp/…`）、`daily_audit.py:38`（同 hp）、`auto_flywheel.py:130,209,230`、`start_rag.sh:27-28`。与 README"PyPI 可安装"声明直接矛盾。
修复：全部收敛到 config.yaml/env。

### m2. setup.py 打包声明失效
`setup.py:11-12` entry_points 引用不存在的模块 `rag_flywheel_batch`（全仓检索 0 命中）→ `pip install` 后命令即崩；`py_modules` 仅含 retriever+rag_core，依赖的 kb_learning/sag_hybrid 等均未打包。

### m3. rag_core 导入时副作用 + 每进程重复加载模型
`rag_core.py:646` 导入即起 warmup 线程（加载嵌入模型 + reranker），`_RERANK_TOP_K=0`（:356）已禁用 reranker，warmup 却仍加载它（:637-644，注释自述 25-60s CPU）；`_init_log_db`（:2323）也在导入时执行。每个服务进程各载一份 ~GB 级模型。
修复：warmup 仅加载启用项，模型懒加载/进程间共享。

### m4. config.yaml 与代码漂移
`config.yaml:15-24` 的 `llm.channels`（mizu/qwen）没有任何代码读取——rag_core 用自己硬编码的 `MODEL_CHANNELS`（:267）；`config.yaml:27-31` `reranker.enabled: true / top_k: 25` 与代码 `_RERANK_TOP_K=0` 矛盾。

### m5. 分类体系两套并存
`rag_core.py:418-431` 运行时分类用 `'08_工程工具'/'10_能效与诊断'`，`scripts/rag_phase2_semantic_tag.py:48-59` 打标用 `'08_工装夹具'/'02_视觉系统'/'10_其他'` → 离线打标的 `category_l2` 与在线 `_query_to_l2` 对不上号，二级过滤时常空转。

### m6. kb_learning JSONL 无并发保护
`kb_learning.py:88-114` `_append_jsonl` 与 `_remove_from_jsonl`（读-改-写）无锁；`approve_badcase` 重写文件时会覆盖并发期间新追加的行（丢数据）；条目无唯一 ID，`badcase_review.py:88-91` 按行号寻址，队列增删后 ID 即错位。

### m7. SQLite 访问一致性
`rag_core.py:2784` `get_feedback_list` 无 `_log_lock`、无 `busy_timeout`；`log_query` 的 `request_id` 参数未写入 SQLite（:2393-2404），只在 JSONL 兜底里用。

### m8. 两个 MCP server 语义不一致
`mcp_server.py:28-34` 的 `rag_answer` 只返回检索原文、不调 LLM，与 `rag_mcp_server.py:249` 的 `rag_answer`（真生成）同名不同义；v3/v4 两套并存易被接错。

### m9. auto_flywheel 续跑逻辑是死代码
`auto_flywheel.py:180-181` `processed_ids` 恒空、从未落盘 → 中断后重跑全量重处理；docx 路径指向 hp 用户目录；:87 传 `score_threshold` 参数被 pydantic 静默忽略。

### m10. rag_mcp_server 健壮性细节
`_structured_trim`（:88-175）对特定文档硬编码正则（:117），文档一改即失效；`_llm_generate` 失败被 `except Exception as e: pass`（:264-265）全吞；`_load_env_key`（:22-31）裸 `open()` 无异常处理。

### m11. 仓库卫生
`会话1.txt`（1462 行聊天/问答记录）被提交；`synonyms.json.bak.1786422492` 备份文件被提交；根目录散落 `_extract_deps.py`/`_update_lessons.py`/`test_plugin.py` 等一次性脚本。建议清理并补 .gitignore。

### m12. 测试覆盖严重不足
全仓仅 `tests/test_audit_and_query_strategy.py`（8 个用例，且用生产不存在的 L2 数据）+ `test_plugin.py`（测死代码）。检索主链路、通道 failover、kb_learning、rag_api 端点、飞书 bot、mcp server 均无测试。

### m13. 双写日志与观察性割裂
`rag_web.process_query` 只写 kb_learning JSONL、不写 SQLite query_log（`rag_web.py:59-68`）→ Web 端查询在 `/status`、token 统计、风险聚类里完全不可见；`generate_compare/generate_report` 不传 usage → token 统计缺失。

---

## Nit

- `feishu_rag_bot.py:3` `threading/queue` 导入未使用；`sag_hybrid.py:12` 多处裸 `except:`（:145）。
- `rag_core.py:1212-1220` SAG 合并段变量名与主检索风格割裂（已确认 :1200 有 `sag_chunks=[]` 初始化，降级路径安全）。
- `rag_admin.py:1004-1005` `__setitem__(slice(None), …)` lambda 写法晦涩。
- `rag_core.py:256-260` `PATHS` 与 `QUERY_LOG_DB`（:2257）两份路径来源，易分叉。
- `badcase_review.py` 与 `kb_learning.py` 重复实现了一整套 JSONL 读写。
- `daily_audit.py:289/384` `int(time.time()) % 100000` 仅显示用。
- `rag_phase2b_refine.py` 与 `rag_phase2_semantic_tag.py` 两套 `KEYWORD_TAG_RULES` 高度重复且互相矛盾。

---

## SUMMARY

- 评分：**5.5 / 10**。
- 检索核心（rag_core）思路扎实：实体索引 + BM25/RRF + 多样性与品牌过滤 + overlap 守卫 + 查询改写，错误处理大体克制（SAG/reranker 降级、JSONL 兜底、WAL/busy_timeout 到位），工程反思文化好。
- 但集成层质量差：kb_learning 重构后 3 个消费方全断（M1）、反馈链路 query_id 断裂（M2）、导入后索引不失效（M3）、自检 Tab 必崩（M4）、HTTPException 未导入（M5）——核心闭环（学习→反馈→入库→检索）每一环都在漏。加上硬编码密钥（C1）、无认证服务暴露（M9）、bot 并发缺口（M6）与提示注入边界缺失（M8），安全与可靠性无法支撑对外发布（PyPI/README 宣传）状态。

### 最重要的 3 条改进建议
1. **吊销并清除全部硬编码 API 密钥**（C1），迁移到环境变量/`~/.hermes/.env`，清理 git 历史，开启 secret scanning。
2. **修复 kb_learning 集成断层**：统一 `get_stats/get_gaps/...` API 或改造三处消费方；`generate_answer` 返回真实 SQLite query_id，反馈链路回归可用（M1+M2）。
3. **索引生命周期管理**：所有 ingest 路径统一触发 `_bm25_index.invalidate()` + 实体索引重建 + 模型缓存失效；散落的绝对路径收敛进 config.yaml/env（M3+m1）。

---

*报告由 Codewhale reviewer agent 生成，纯静态分析；M6（飞书 ack）、M8（注入可利用性）需运行时验证。*
