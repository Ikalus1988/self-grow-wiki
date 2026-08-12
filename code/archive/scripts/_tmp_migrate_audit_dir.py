#!/usr/bin/env python3
"""迁移仓库内 Desktop/自研/rag-docs/audit_reports 的旧 badcase/feedback 数据到统一目录 ~/audit_reports。

评审 M10 数据迁移（2026-08-11）:
- 旧目录: self-grow-wiki/Desktop/自研/rag-docs/audit_reports/  (kb_learning 旧默认路径, 仓库内垃圾目录)
- 新目录: /home/eric_jia/audit_reports                        (daily_audit 真实数据所在, 现为单一来源)
合并策略: 按 (ts, query) 去重追加; 迁移后旧目录归档为 audit_reports_legacy_20260811。
"""
import json
import shutil
import sys
from pathlib import Path

SRC = Path("/mnt/c/Users/Eric Jia/self-grow-wiki/Desktop/自研/rag-docs/audit_reports")
DST = Path("/home/eric_jia/audit_reports")

FILES = ["badcase_pending.jsonl", "feedback_log.jsonl"]

def read_lines(p: Path) -> list:
    if not p.exists():
        return []
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]

def merge(src: Path, dst: Path) -> int:
    src_lines = read_lines(src)
    if not src_lines:
        return 0
    dst_keys = set()
    for l in read_lines(dst):
        try:
            d = json.loads(l)
            dst_keys.add((d.get("ts", ""), d.get("query", "")))
        except Exception:
            dst_keys.add(l)
    added = 0
    with open(dst, "a", encoding="utf-8") as f:
        for l in src_lines:
            try:
                d = json.loads(l)
                k = (d.get("ts", ""), d.get("query", ""))
            except Exception:
                k = l
            if k not in dst_keys:
                f.write(l + "\n")
                dst_keys.add(k)
                added += 1
    return added

def main() -> int:
    if not SRC.exists():
        print(f"[skip] 旧目录不存在: {SRC}")
        return 0
    for name in FILES:
        src, dst = SRC / name, DST / name
        added = merge(src, dst)
        src_count = len(read_lines(src))
        dst_count = len(read_lines(dst))
        print(f"{name}: 旧 {src_count} 行 -> 新合并后 {dst_count} 行 (新增 {added})")
    archive = SRC.parent.parent / "audit_reports_legacy_20260811"
    shutil.move(str(SRC), str(archive))
    print(f"[moved] 旧目录已归档到 {archive}")
    for p in [SRC, SRC.parent, SRC.parent.parent, SRC.parent.parent.parent]:
        try:
            p.rmdir()
        except OSError:
            pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
