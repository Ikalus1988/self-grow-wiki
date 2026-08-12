#!/usr/bin/env python3
"""Bad Case 审核工具 — 管理待审队列，批准/拒绝/查看统计。

用法:
  python3 badcase_review.py list             列出所有待审 bad case
  python3 badcase_review.py show <id>        查看指定 bad case 详情
  python3 badcase_review.py approve <id>     批准一条 bad case
  python3 badcase_review.py reject <id>      拒绝一条 bad case（附带原因）
  python3 badcase_review.py stats            查看审核统计
  python3 badcase_review.py export           导出 bad case 汇总报告
  python3 badcase_review.py auto             自动批准高置信度 bad case
"""

import json
import sys
import re
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("badcase_review")

# ── 直接复用 kb_learning 的路径常量（评审 M10 单一来源, 2026-08-11）──
# 目录解析逻辑统一在 kb_learning: RAG_AUDIT_DIR env 优先 → ~/audit_reports
from kb_learning import AUDIT_DIR, PENDING_FILE, APPROVED_FILE, REJECTED_FILE


# ── JSONL 操作 ───────────────────────────────────────────────────

def read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def write_jsonl(path: Path, items: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def append_jsonl(path: Path, item: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ── 核心操作 ──────────────────────────────────────────────────────

def list_pending() -> list:
    items = read_jsonl(PENDING_FILE)
    # 只显示 pending 状态
    pending = [it for it in items if it.get("status", "pending") == "pending"]
    return pending


def get_item(items: list, item_id: int) -> dict:
    if 1 <= item_id <= len(items):
        return items[item_id - 1]
    return None


def approve(item_id: int) -> bool:
    items = read_jsonl(PENDING_FILE)
    target = get_item(items, item_id)
    if not target:
        return False
    pending_idx = item_id - 1
    item = items.pop(pending_idx)
    item["status"] = "approved"
    item["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_jsonl(PENDING_FILE, items)
    append_jsonl(APPROVED_FILE, item)
    logger.info(f"已批准: {item.get('query', '?')[:50]}...")
    _learn_synonyms_from_badcase(item)
    return True


def reject(item_id: int, reason: str = "") -> bool:
    items = read_jsonl(PENDING_FILE)
    target = get_item(items, item_id)
    if not target:
        return False
    pending_idx = item_id - 1
    item = items.pop(pending_idx)
    item["status"] = "rejected"
    item["rejected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    item["reject_reason"] = reason or "人工拒绝"
    write_jsonl(PENDING_FILE, items)
    append_jsonl(REJECTED_FILE, item)
    logger.info(f"已拒绝: {item.get('query', '?')[:50]}... (原因: {reason or '无'})")
    return True


def auto_approve():
    """自动批准高置信度的 bad case（top_score 极低、检索为空等）。"""
    items = read_jsonl(PENDING_FILE)
    approved_count = 0
    kept = []
    for item in items:
        score = item.get("top_score", 1.0)
        chunks_count = item.get("chunks_count", 1)
        reason = item.get("reason", "")

        # 自动批准条件
        auto = False
        if chunks_count == 0:
            auto = True  # 检索结果为空 → 文档缺失，确定 bad case
        elif score < 0.3:
            auto = True  # 分数极低 → 检索严重偏差
        elif "检索结果为空" in reason:
            auto = True
        elif "低质量检索" in reason:
            auto = True

        if auto:
            item["status"] = "approved"
            item["approved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            item["auto_approved"] = True
            append_jsonl(APPROVED_FILE, item)
            approved_count += 1
            logger.info(f"自动批准: {item.get('query', '?')[:50]}... ({reason[:40]})")
        else:
            kept.append(item)

    write_jsonl(PENDING_FILE, kept)

    # 对已批准的 badcase 尝试同义词学习
    all_approved = read_jsonl(APPROVED_FILE)
    for aitem in all_approved[-approved_count:]:
        _learn_synonyms_from_badcase(aitem)

    logger.info(f"自动批准完成: {approved_count} 条已批准，{len(kept)} 条待人工审核")
    return approved_count


def show_stats() -> dict:
    pending = read_jsonl(PENDING_FILE)
    approved = read_jsonl(APPROVED_FILE)
    rejected = read_jsonl(REJECTED_FILE)
    return {
        "pending": len(pending),
        "approved": len(approved),
        "rejected": len(rejected),
        "total": len(pending) + len(approved) + len(rejected),
        "file_pending": str(PENDING_FILE),
        "file_approved": str(APPROVED_FILE),
        "file_rejected": str(REJECTED_FILE),
    }


# ── 格式化输出 ───────────────────────────────────────────────────

def _learn_synonyms_from_badcase(item: dict):
    """从批准的 badcase 中提取中文术语，自动追加到 synonyms.json。

    规则：
    - 查询中有中文技术词（2-6字）在失败原因中标注了"未命中关键词"
    - 该词不在 synonyms.json 中则追加为新的同义词条目
    """
    query = item.get("query", "")
    reason = item.get("reason", "")
    if "未命中关键词" not in reason and "检索质量偏低" not in reason:
        return

    # 提取查询中的中文技术词
    terms = set()
    for part in query.replace("FANUC机器人", "").replace("FANUC", "").replace(" ", ""):
        if '\u4e00' <= part <= '\u9fff':
            terms.add(part)
    # 取长度 2-6 的连续中文片段
    cn_phrases = re.findall(r'[\u4e00-\u9fff]{2,6}', query)
    cn_phrases = [p for p in cn_phrases if p not in ("机器人", "步骤", "方法", "区别", "设定", "报警")]

    if not cn_phrases:
        return

    # 加载现有同义词
    syn_path = _HERE / "synonyms.json"
    if not syn_path.exists():
        return
    try:
        with open(syn_path, "r", encoding="utf-8") as f:
            syns = json.load(f)
    except Exception:
        return

    added = []
    for phrase in cn_phrases:
        if phrase not in syns and not any(phrase in str(v) for v in syns.values()):
            # 添加为新的同义词条目，初始值为空列表（等待用户补充同义词）
            syns[phrase] = ["auto"]
            added.append(phrase)

    if added:
        try:
            with open(syn_path, "w", encoding="utf-8") as f:
                json.dump(syns, f, ensure_ascii=False, indent=2)
            logger.info(f"同义词自动学习: 新增 {added}")
        except Exception as e:
            logger.warning(f"写入同义词失败: {e}")


def format_pending(items: list) -> str:
    if not items:
        return "🎉 没有待处理的 bad case！"
    lines = []
    lines.append(f"待处理 Bad Case: {len(items)} 条\n")
    lines.append(f"{'ID':>3} | {'时间':<16} | {'分数':<5} | {'类型':<8} | {'题目':<40} | {'原因':<30}")
    lines.append("-" * 110)
    for i, item in enumerate(items, 1):
        ts = item.get("ts", "")[5:16] if item.get("ts") else "?"
        score = item.get("top_score", "?")
        source = item.get("source", "user")[:8]
        query = item.get("query", "?")[:38]
        reason = item.get("reason", "")[:28]
        lines.append(f"{i:>3} | {ts:<16} | {score:<5} | {source:<8} | {query:<40} | {reason:<30}")
    return "\n".join(lines)


def format_detail(item: dict, item_id: int) -> str:
    if not item:
        return "未找到"
    lines = []
    lines.append(f"=== Bad Case #{item_id} ===")
    for k, v in item.items():
        if k in ("query", "reason", "top_score", "ts", "source", "status", "feedback"):
            lines.append(f"  {k}: {v}")
    lines.append(f"  完整 query: {item.get('query', '?')}")
    lines.append(f"  完整 reason: {item.get('reason', '无')}")
    return "\n".join(lines)


def format_stats(s: dict) -> str:
    lines = []
    lines.append("=== Bad Case 审核统计 ===")
    lines.append(f"  待处理: {s['pending']}")
    lines.append(f"  已批准: {s['approved']}")
    lines.append(f"  已拒绝: {s['rejected']}")
    lines.append(f"  总计:   {s['total']}")
    lines.append(f"  pending 文件: {s['file_pending']}")
    return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "list":
        items = list_pending()
        print(format_pending(items))

    elif cmd == "show":
        if len(sys.argv) < 3:
            print("用法: python3 badcase_review.py show <id>")
            return
        items = list_pending()
        item = get_item(items, int(sys.argv[2]))
        print(format_detail(item, int(sys.argv[2])))

    elif cmd == "approve":
        if len(sys.argv) < 3:
            print("用法: python3 badcase_review.py approve <id>")
            return
        ok = approve(int(sys.argv[2]))
        print("已批准" if ok else "批准失败，ID 不存在")

    elif cmd == "reject":
        if len(sys.argv) < 3:
            print("用法: python3 badcase_review.py reject <id> [原因]")
            return
        reason = sys.argv[3] if len(sys.argv) > 3 else ""
        ok = reject(int(sys.argv[2]), reason)
        print("已拒绝" if ok else "拒绝失败，ID 不存在")

    elif cmd == "stats":
        s = show_stats()
        print(format_stats(s))

    elif cmd == "export":
        # 调用 kb_learning 的导出函数
        try:
            import kb_learning
            report = kb_learning.export_badcase_report()
            print(f"报告已生成:\n{report}")
        except ImportError:
            print("错误: 需要 kb_learning.py 模块")

    elif cmd == "auto":
        count = auto_approve()
        print(f"自动批准: {count} 条")

    else:
        print(f"未知命令: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
