# MEMORY.md — self-grow-wiki 长期记忆

## 项目概要
self-grow-wiki 是一个 RAG（检索增强生成）知识库自增长系统，包含：
- 知识库管理与学习（kb_learning.py）
- 每日巡检审计（daily_audit.py）
- Badcase 评审闭环（badcase_review.py）
- RAG API 服务（rag_api.py）
- Web 管理界面（rag_web.py, rag_admin.py）
- 飞书机器人集成（feishu_rag_bot.py）

## 已完成里程碑

### M10：统一 badcase 目录（2026-08-12）✅
- 所有模块统一从 `kb_learning.py` 导入 AUDIT_DIR/PENDING_FILE/APPROVED_FILE/REJECTED_FILE
- 默认路径：~/audit_reports（RAG_AUDIT_DIR env 优先）
- commit: c21fa83

### M11：题库分层对齐 + 空库文案 + top_score 判定（2026-08-12）✅
- sample_questions 分层从硬编码改为 _BASIC_LEVELS 动态判定
- call_rag 解析 top_score 字段
- run_audit 兼容新旧空库文案，新增 score_ok 判定
- rag_api.py QueryResponse 新增 top_score
- commit: c21fa83

### 数据迁移（2026-08-12）✅
- tools/migrate_audit_data.py: Desktop 旧 audit → ~/audit_reports + 归档
- commit: c21fa83

## 待处理
- [x] Desktop/ 目录清理 → gitignore（数据已迁移 ~/audit_reports）
- [x] archive/chat-logs/ 整理 → gitignore 本地保留
- [x] scripts/_tmp_migrate_audit_dir.py → 归档 archive/scripts/
- [x] 全量验证：py_compile 全部 + pytest 20/20（新增 M11 测试 11 个）

## 测试覆盖
- tests/test_audit_and_query_strategy.py: 9 个（抽样策略 + 查询策略）
- tests/test_m11_judgment.py: 11 个（M11 判定逻辑: 分层/top_score/空库文案）commit 95adcdc
