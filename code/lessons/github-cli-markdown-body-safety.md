# GitHub CLI 创建 Markdown Issue/PR 正文的安全模式

## 背景

使用 `gh issue create`、`gh pr create` 等命令时，经常需要传入包含 Markdown 的正文。正文里如果包含反引号、命令示例、路径、参数名或 `$()` 等 shell 特殊字符，直接写在命令行参数中容易被 shell 提前解释，导致：

- 反引号中的内容被当作命令执行。
- 正文中的代码片段被替换为空或报错。
- Issue/PR 创建成功但正文损坏。
- 终端出现与正文示例相关的误报错。

这类问题和具体仓库、账号、业务无关，是 CLI 自动化创建协作内容时的通用风险。

## 经验结论

**凡是 Markdown 正文包含代码、命令、路径、参数或反引号时，优先使用正文文件，而不是把正文直接塞进命令参数。**

推荐模式：

```bash
cat > /tmp/issue-body.md <<'BODY_EOF'
## Background
Use `some_function()` to generate the report.

## Scope
- Support `--days`
- Support `--output reports/example.md`
BODY_EOF

gh issue create --title "feat: add report exporter" --body-file /tmp/issue-body.md
```

关键点：

- heredoc 使用单引号分隔符，例如 `<<'BODY_EOF'`，避免 shell 展开正文内容。
- 外层脚本和内层示例不要复用同一个 heredoc 分隔符，否则外层会提前结束。
- 使用 `--body-file` 或同类参数传递正文。
- 创建后立即读取远端内容确认。

## 反模式

避免这样写：

```bash
gh issue create --title "..." --body "支持 `--days` 和 `scripts/export.py`"
```

风险：

- 反引号内容可能被 shell 当作命令执行。
- 路径可能触发 “no such file or directory”。
- 参数名可能触发 “command not found”。
- Issue 已创建但正文丢失代码片段。

## 推荐流程

1. 将正文写入临时 Markdown 文件。
2. 使用 `gh issue create --body-file` 或 `gh pr create --body-file`。
3. 创建后用 `gh issue view` 或 `gh pr view` 拉取远端正文。
4. 如果正文损坏，立刻用 `gh issue edit --body-file` 或 `gh pr edit --body-file` 修复。
5. 最后把链接和确认结果反馈给用户。

示例：

```bash
cat > /tmp/body.md <<'BODY_EOF'
## Summary
- Add `build_report()`.
- Support `--output reports/weekly.md`.
BODY_EOF

gh issue create --title "feat: add weekly report" --body-file /tmp/body.md

gh issue view 123 --json title,body,url
```

## 校验清单

创建 Issue/PR 后至少检查：

- 标题是否正确。
- 正文中的代码、路径、参数是否保留。
- Markdown 列表和代码块是否完整。
- 关联的 PR/Issue 编号是否正确。
- 是否意外暴露本地路径、账号、token、公司内链或敏感文档名。

## 修复方式

如果已经创建了正文损坏的 Issue/PR，不需要关闭重建，直接编辑正文：

```bash
gh issue edit 123 --body-file /tmp/body.md
gh pr edit 456 --body-file /tmp/body.md
```

修复后再次读取远端内容确认。

## 适用场景

- 自动创建 GitHub Issue。
- 自动创建 GitHub PR。
- 自动评论包含代码块的内容。
- 自动生成 release notes。
- 自动同步任务说明到远端协作系统。

## 泛化原则

当 CLI 参数需要承载富文本时，应默认认为 shell 会干扰内容。把富文本写入文件，再通过 `--*-file` 传递，是更稳妥的自动化模式。
