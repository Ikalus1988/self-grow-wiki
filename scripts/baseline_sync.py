#!/usr/bin/env python3
"""基线仓库快速同步工具 (baseline-sync)。

每次会话读取/更新基线文件后，用本工具把会话产出同步进基线仓库并提交，
保持 D:\\MD\\RAG知识库 基线始终为最新状态。

子命令:
  memory               同步项目 memory/ + MEMORY.md → 会话记忆/<project>/
  review <file...>     把评审文件复制到 评审/ (按 YYYY-MM-DD_项目_类型.md 命名)
  changelog <text...>  向 CHANGELOG.md 追加今日条目 (可多行)
  code                 镜像同步主仓库 git 跟踪内容 → code/ (评审 F4)
                       (自动跑验证门禁 scripts/verify_code_snapshot.py, 失败拒提交)
  commit [-m MSG]      git add -A + commit (默认消息: sync: 会话同步 <日期>)
  status               查看基线仓库状态

示例:
  python3 baseline_sync.py memory
  python3 baseline_sync.py review /tmp/foo-review.md --type security-review
  python3 baseline_sync.py changelog "修复 X" "新增 Y"
  python3 baseline_sync.py code
  python3 baseline_sync.py commit -m "sync: 会话产出入库"
"""
import argparse
import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path("/mnt/d/MD/RAG知识库")
DEFAULT_PROJECT = "/mnt/c/Users/Eric Jia/self-grow-wiki"

# 评审类型 → 文件名后缀
REVIEW_TYPES = {
    "code-review": "code-review",
    "security-review": "security-review",
    "design-review": "design-review",
    "architecture-review": "architecture-review",
    "review-notes": "review-notes",
}

# code 同步: 主仓库跟踪但基线 code/ 不镜像的路径前缀 (memory 归 memory 子命令)
CODE_EXCLUDE_PREFIXES = ("MEMORY.md", "memory/")
# 基线自有的工具脚本, 镜像同步时保护不删
CODE_KEEP = ("scripts/baseline_sync.py", "scripts/verify_code_snapshot.py")


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd or BASE, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"[fail] {' '.join(cmd)}: {r.stderr.strip()}")
        sys.exit(1)
    return r


def cmd_memory(project: str):
    src = Path(project)
    if not src.exists():
        print(f"[error] 项目路径不存在: {src}")
        sys.exit(1)
    name = src.name
    dst = BASE / "会话记忆" / name
    dst.mkdir(parents=True, exist_ok=True)

    # MEMORY.md
    mem = src / "MEMORY.md"
    if mem.exists():
        shutil.copy2(mem, dst / "MEMORY.md")
        print(f"[ok] {mem.name} → {dst / 'MEMORY.md'}")

    # memory/*.md
    memdir = src / "memory"
    if memdir.exists():
        count = 0
        for f in sorted(memdir.glob("*.md")):
            shutil.copy2(f, dst / f.name)
            count += 1
        print(f"[ok] memory/ {count} 个文件 → {dst}")
    else:
        print(f"[warn] {src}/memory 不存在")

    print(f"[hint] 运行 'python3 baseline_sync.py commit' 提交")


def _norm_review_name(src: Path, project: str, rtype: str) -> str:
    """按 YYYY-MM-DD_<项目>_<类型>.md 命名。"""
    date = datetime.date.today().strftime("%Y-%m-%d")
    m = re.search(r"(20\d\d-\d\d-\d\d)", src.name)
    if m:
        date = m.group(1)
    suffix = REVIEW_TYPES.get(rtype, rtype or "review")
    return f"{date}_{project}_{suffix}.md"


def cmd_review(files, project, rtype):
    dst_dir = BASE / "评审"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        src = Path(f)
        if not src.exists():
            print(f"[warn] 文件不存在: {f}")
            continue
        name = _norm_review_name(src, project, rtype)
        dst = dst_dir / name
        if dst.exists():
            same = dst.resolve() == src.resolve()
            print(f"[skip] 已存在: {dst}" + (" (同文件)" if same else ""))
            continue
        shutil.copy2(src, dst)
        print(f"[ok] {src.name} → {dst}")
    print(f"[hint] 运行 'python3 baseline_sync.py commit' 提交")


def cmd_changelog(lines):
    path = BASE / "CHANGELOG.md"
    today = datetime.date.today().strftime("%Y-%m-%d")
    block = [f"## [{today}] — {today}", ""]
    block += [f"- {ln}" for ln in lines]
    block += ["", ""]
    text = path.read_text(encoding="utf-8")
    # 插入到 "# Changelog" 标题之后
    if text.startswith("# Changelog"):
        text = "# Changelog\n\n" + "\n".join(block) + text[len("# Changelog\n"):]
    else:
        text = "# Changelog\n\n" + "\n".join(block) + text
    path.write_text(text, encoding="utf-8")
    print(f"[ok] CHANGELOG.md 追加 {len(lines)} 条 ({today})")


def cmd_code(project: str):
    """镜像同步主仓库 git 跟踪内容 → 基线 code/ (评审 F4)。"""
    src = Path(project)
    if not src.exists() or not (src / ".git").exists():
        print(f"[error] 主仓库路径无效: {src}")
        sys.exit(1)
    dst = BASE / "code"
    dst.mkdir(parents=True, exist_ok=True)

    # 1. 主仓库 git 跟踪文件清单 (排除 memory/MEMORY.md)
    r = run(["git", "-C", str(src), "ls-files"], check=True)
    tracked = [ln for ln in r.stdout.splitlines() if ln.strip()]
    wanted = [ln for ln in tracked
              if not ln.startswith(CODE_EXCLUDE_PREFIXES)]

    # 2. 复制/更新每个文件
    copied, updated = 0, 0
    for rel in wanted:
        s = src / rel
        d = dst / rel
        if not s.is_file():
            continue
        if d.exists() and d.read_bytes() == s.read_bytes():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        copied += 1
    print(f"[ok] code/ 同步: {copied} 个文件更新/新增")

    # 3. 删除基线 code/ 中不再被主仓库跟踪的旧文件 (保护基线自有工具)
    removed = 0
    for d in sorted(dst.rglob("*")):
        if not d.is_file():
            continue
        rel = d.relative_to(dst).as_posix()
        if rel in CODE_KEEP:
            continue
        if rel not in tracked:
            d.unlink()
            removed += 1
    if removed:
        print(f"[ok] 清理 {removed} 个主仓库已不跟踪的旧文件")

    # 4. 验证门禁: 失败则拒绝继续
    gate = BASE / "scripts" / "verify_code_snapshot.py"
    if gate.exists():
        r = run(["python3", str(gate), str(dst)], check=False)
        if r.returncode != 0:
            print("\n[fail] 验证门禁未通过, 拒绝提交 code/ 同步")
            print("       请修复后重新运行 'baseline_sync.py code'")
            sys.exit(1)
        print("[ok] 验证门禁通过")
    else:
        print(f"[warn] 未找到验证门禁 {gate}, 跳过")
    print(f"[hint] 运行 'python3 baseline_sync.py commit' 提交")


def cmd_commit(msg):
    today = datetime.date.today().strftime("%Y-%m-%d")
    m = msg or f"sync: 会话同步 {today}"
    run(["git", "add", "-A"])
    # 无变更则跳过
    st = run(["git", "status", "--porcelain"], check=False)
    if not st.stdout.strip():
        print("[skip] 无变更, 无需提交")
        return
    run(["git", "commit", "-m", m])
    print("[ok] 已提交")
    run(["git", "log", "--oneline", "-3"], check=False)


def cmd_status():
    run(["git", "status", "--short"], check=False)


def main():
    p = argparse.ArgumentParser(description="基线仓库快速同步工具")
    p.add_argument("--project", default=DEFAULT_PROJECT,
                   help=f"项目路径 (默认 {DEFAULT_PROJECT})")
    p.add_argument("--type", dest="rtype", default="code-review",
                   choices=sorted(REVIEW_TYPES) + ["review"],
                   help="评审类型 (默认 code-review)")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("memory", help="同步 memory → 会话记忆/<project>/")
    p_review = sub.add_parser("review", help="评审文件 → 评审/")
    p_review.add_argument("files", nargs="+", help="评审文件路径")
    # 子命令位置也接受 --type (default=SUPPRESS 避免覆盖主解析器默认值)
    p_review.add_argument("--type", dest="rtype", default=argparse.SUPPRESS,
                          choices=sorted(REVIEW_TYPES) + ["review"],
                          help="评审类型 (默认 code-review)")
    p_changelog = sub.add_parser("changelog", help="追加 CHANGELOG 条目")
    p_changelog.add_argument("lines", nargs="+", help="条目内容 (可多条)")
    sub.add_parser("code", help="镜像同步主仓库代码 → code/ (评审 F4)")
    p_commit = sub.add_parser("commit", help="git add -A + commit")
    p_commit.add_argument("-m", "--message", default=None, help="提交信息")
    sub.add_parser("status", help="git status")

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        sys.exit(1)
    if args.cmd == "memory":
        cmd_memory(args.project)
    elif args.cmd == "review":
        cmd_review(args.files, Path(args.project).name, args.rtype)
    elif args.cmd == "changelog":
        cmd_changelog(args.lines)
    elif args.cmd == "code":
        cmd_code(args.project)
    elif args.cmd == "commit":
        cmd_commit(args.message)
    elif args.cmd == "status":
        cmd_status()


if __name__ == "__main__":
    main()
