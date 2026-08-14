#!/usr/bin/env python3
"""把仓库内 Desktop 旧 audit 数据合并到 /home/eric_jia/audit_reports/ 统一目录。"""
import json, os, shutil, sys
from datetime import datetime

WORKSPACE = "/mnt/c/Users/Eric Jia/self-grow-wiki"
OLD_DIR = os.path.join(WORKSPACE, "Desktop/自研/rag-docs/audit_reports")
DST_DIR = os.path.expanduser("~/audit_reports")
ARCHIVE_DIR = os.path.join(WORKSPACE, "Desktop/自研/rag-docs/audit_reports.archived")

def merge_jsonl(src: str, dst: str, dedup_keys=("query", "ts")):
    """把 src 的行合并到 dst — 按 dedup_keys 去重，保留 dst 已有记录。"""
    if not os.path.exists(src):
        print(f"[skip] 源文件不存在: {src}")
        return

    # 读取 dst 已有记录的去重 key
    existing = set()
    if os.path.exists(dst):
        with open(dst, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    key = tuple(rec.get(k) for k in dedup_keys)
                    existing.add(key)
                except json.JSONDecodeError:
                    continue

    added = 0
    skipped = 0
    with open(dst, "a", encoding="utf-8") as out:
        with open(src, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    key = tuple(rec.get(k) for k in dedup_keys)
                    if key in existing:
                        skipped += 1
                        continue
                    existing.add(key)
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    added += 1
                except json.JSONDecodeError:
                    print(f"[warn] 跳过非法 JSON 行: {line[:80]}")
                    continue

    print(f"  {src} → {dst}: +{added} 行, 跳过 {skipped} 行(重复)")

def main():
    os.makedirs(DST_DIR, exist_ok=True)

    print("=== 数据迁移: Desktop 旧 audit 目录 → 统一目录 ===")
    print(f"  源: {OLD_DIR}")
    print(f"  目标: {DST_DIR}")

    # 1. badcase_pending.jsonl
    merge_jsonl(
        os.path.join(OLD_DIR, "badcase_pending.jsonl"),
        os.path.join(DST_DIR, "badcase_pending.jsonl"),
    )

    # 2. feedback_log.jsonl
    merge_jsonl(
        os.path.join(OLD_DIR, "feedback_log.jsonl"),
        os.path.join(DST_DIR, "feedback_log.jsonl"),
    )

    # 3. 归档旧目录
    if os.path.exists(OLD_DIR):
        os.makedirs(os.path.dirname(ARCHIVE_DIR), exist_ok=True)
        if os.path.exists(ARCHIVE_DIR):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            real_archive = f"{ARCHIVE_DIR}.{ts}"
            print(f"\n[info] 归档目录已存在，使用: {real_archive}")
            shutil.move(OLD_DIR, real_archive)
            print(f"  已归档 → {real_archive}")
        else:
            shutil.move(OLD_DIR, ARCHIVE_DIR)
            print(f"\n  已归档 → {ARCHIVE_DIR}")

    print("\n=== 迁移完成 ===")

if __name__ == "__main__":
    main()
