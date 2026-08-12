# RAG 知识库基线 (D:\MD\RAG知识库)

> 基线日期: 2026-08-12 · 首次纳入 git 版本管理
> 用途: FANUC 工业 RAG 知识库的文档/代码/领域资产基线存档

## 目录结构

| 目录 | 说明 | 版本库 |
|------|------|--------|
| `code/` | self-grow-wiki 代码快照 (2026-08-11, remote=GitHub Ikalus1988/self-grow-wiki) | ✅ |
| `domains/` | 领域文档: readme/reports/sop/tech | ✅ |
| `graph/` | OKF 知识图谱 (alarms/safety/signals) | ✅ |
| `rag-docs/` | RAG 知识文档: concepts/entities/queries/raw (含 FANUC 手册 .PDF.md 转写) | ✅ (排除 PDF 原文) |
| `skills/` | SKILL 文档 | ✅ |
| `scripts/` | 脚本目录 (已迁出, 为空) | ✅ |
| `归档/` | 历史基线归档 (2026-07-17 baseline-move, wsl 迁移会话等) | ✅ (排除 PDF 原文) |
| 顶层 *.md | 评审报告 (self-grow-wiki / MisakaNet 2026-08-11) | ✅ |
| `data/` | ChromaDB 运行时向量库 (~2.9G) | ❌ gitignore |
| `备份/` | 向量库压缩备份 (~1.6G) | ❌ gitignore |
| `备注.txt` | ⚠️ 含 GitHub PAT 明文 | ❌ 不进库 |

## 安全说明

- **`备注.txt`** 与 **`domains/reports/rag知识库演进记录.txt`** 内含 GitHub
  Personal Access Token 明文, **未纳入版本库**。建议尽快在 GitHub Settings →
  Developer settings → Tokens 中撤销泄露的 token。
- 代码中的 API 密钥一律走环境变量 / `~/.hermes/.env` (评审 C1 修复), 不硬编码。
- 本仓库仅本地使用; 如需推送远端, 推送前请再次扫描 `git ls-files` 确认无凭据。

## 恢复指南

- **向量库恢复**: 解压 `备份/chroma_store.tar.7z` 到 `data/chroma_store/` 即可恢复
  ChromaDB (Edoc V10.0 手册 PDF + fanuc_all chunks + sqlite)。
- **代码恢复**: `code/` 为普通目录, 也可从
  `https://github.com/Ikalus1988/self-grow-wiki.git` 获取最新代码。
- **code 历史**: 原 `code/.git` (shallow clone) 已归档至 `归档/2026-08-12_code-git-shallow/`,
  完整历史在 GitHub remote。
