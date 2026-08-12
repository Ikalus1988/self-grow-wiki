---
name: baseline-sync
description: >
  基线仓库快速同步外挂：每次会话读取/更新基线文件（D:\MD\RAG知识库 的 README/CHANGELOG/会话记忆/评审）时，
  用 scripts/baseline_sync.py 一键同步会话产出（memory、评审、changelog）并提交，保持基线始终为最新状态。
  触发场景：会话启动读取基线状态、会话结束收尾、需要归档评审报告、需要把项目 memory 同步到基线仓库、
  提到"同步基线/归档评审/更新 changelog/会话记忆"等。
version: 1.0.0
license: MIT
metadata:
  author: Codewhale
  hermes_tags: [baseline, sync, review, memory, changelog]
  related_skills: [agentic-context-engineering]
---

# Baseline Sync — 基线仓库快速同步外挂

## Overview

用户的工作区有一个**基线仓库** `D:\MD\RAG知识库`（WSL 路径 `/mnt/d/MD/RAG知识库`），
用于存档 RAG 知识库的文档、代码快照、评审报告与会话记忆。

本 skill 定义"会话 ↔ 基线"的同步约定：**会话产出（记忆/评审/changelog）由 agent
在会话收尾时通过同步脚本自动写入基线仓库并提交**，避免手工维护。

## 基线仓库结构（约定）

| 路径 | 内容 |
|------|------|
| `评审/` | 评审报告，命名 `YYYY-MM-DD_<项目>_<类型>.md`（类型: code-review / security-review / design-review / architecture-review / review-notes） |
| `会话记忆/<project>/` | 项目 memory 快照（`MEMORY.md` + `memory/YYYY-MM-DD.md`） |
| `scripts/baseline_sync.py` | 同步工具（本 skill 的核心外挂） |
| `CHANGELOG.md` | 基线变更日志，按日期倒序 |
| `README.md` | 基线说明（目录/安全/恢复） |
| `code/` | self-grow-wiki 代码快照（普通目录，内层 .git 已归档） |

## 同步脚本用法

脚本位置：`/mnt/d/MD/RAG知识库/scripts/baseline_sync.py`

```bash
# 1. 同步项目 memory → 会话记忆/<project>/（默认项目 self-grow-wiki）
python3 /mnt/d/MD/RAG知识库/scripts/baseline_sync.py memory

# 2. 归档评审文件 → 评审/（自动按命名规范重命名）
python3 /mnt/d/MD/RAG知识库/scripts/baseline_sync.py review <文件路径> --type security-review

# 3. 追加 CHANGELOG 条目（可多条）
python3 /mnt/d/MD/RAG知识库/scripts/baseline_sync.py changelog "修复 X" "新增 Y"

# 4. 提交全部变更
python3 /mnt/d/MD/RAG知识库/scripts/baseline_sync.py commit -m "sync: 会话产出入库"

# 5. 查看基线状态
python3 /mnt/d/MD/RAG知识库/scripts/baseline_sync.py status
```

其他项目同步：`--project /path/to/other/project`（会按项目名建 `会话记忆/<name>/` 子目录）。

## 标准工作流

### 会话启动（读取基线状态）
1. `git -C /mnt/d/MD/RAG知识库 log --oneline -5` — 看最近基线变更
2. 读 `会话记忆/<project>/MEMORY.md`（若存在）— 了解跨会话长期记忆
3. 读 `CHANGELOG.md` 头部 — 了解最近变更

### 会话收尾（同步产出，必做）
1. 若本次会话有 memory/MEMORY 更新 → `baseline_sync.py memory`
2. 若有评审/复盘产出 → `baseline_sync.py review <文件> --type <类型>`
3. 若有关键变更 → `baseline_sync.py changelog "<一行摘要>"`
4. → `baseline_sync.py commit -m "sync: <摘要>"`

### 评审约定（其他 agent 参与评审时）
- 评审产出统一放基线 `评审/` 目录，由同步脚本重命名归档
- 命名规范：`YYYY-MM-DD_<项目>_<类型>.md`（日期优先取文件名内日期，缺省用今天）
- 评审报告开头建议带元信息块：评审日期 / 对象 / 方式 / 仓库可见性 / 评分（参照现有评审文件风格）

## 安全红线

- **含明文凭据的文件绝不入库**：`备注.txt`、`domains/reports/rag知识库演进记录.txt`
  含 GitHub PAT（历史遗留），已被 .gitignore 排除。若新发现含 token/密钥的文件，
  先加 .gitignore 再提交，并提醒用户撤销凭据。
- 密钥读取一律走环境变量 / `~/.hermes/.env`，不硬编码。
- 推送远端前先 `git ls-files | grep -E "备注|演进记录|token|key|secret"` 复查。

## 注意事项

- 基线仓库在 drvfs（/mnt/d）上，`core.filemode false` 已配置，提交不受权限影响。
- `code/` 是普通目录；获取最新代码应从 GitHub remote 或本地 self-grow-wiki 仓库，而非基线快照。
- 大文件（PDF 原文、向量库、备份 7z）不在版本库中，恢复方式见基线 README.md。
