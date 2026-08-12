# Changelog

## [2026-08-12] — 2026-08-12

- self-grow-wiki README 同步仓库状态 (布局/里程碑/开发/模块)


## [2026-08-12] — 2026-08-12

- 会话收尾: memory 记录基线外挂与评审约定


## [2026-08-12] — 2026-08-12

- 新增 baseline-sync skill (会话同步外挂, .agents/skills/baseline-sync-1.0.0)
- README 更新评审约定与同步外挂说明


## [2026-08-12] — 2026-08-12

- 新增基线同步工具 scripts/baseline_sync.py
- 评审文件统一归档至 评审/ 目录


## [baseline-2026-08-12] — 2026-08-12

### Added
- 基线文件夹 `D:\MD\RAG知识库` 首次纳入 git 版本管理
- 新增 `README.md`（目录结构 / 安全说明 / 恢复指南）
- 新增 `CHANGELOG.md`
- 新增 `.gitignore`：排除 `data/`（2.9G 运行时向量库）、`备份/`（1.6G）、
  含明文 PAT 的 `备注.txt` / `domains/reports/rag知识库演进记录.txt`、大 PDF 原文

### Changed
- `code/.git`（shallow clone, 1 commit）归档至 `归档/2026-08-12_code-git-shallow/`,
  `code/` 以普通目录纳入基线（历史完整保留于 GitHub remote 与本地
  `/mnt/c/Users/Eric Jia/self-grow-wiki`）

### Security
- 明文 GitHub PAT 文件未纳入版本库；建议撤销泄露 token
