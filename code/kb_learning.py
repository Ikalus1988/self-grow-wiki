#!/usr/bin/env python3
"""自学习模块 — 知识库质量闭环引擎.

供 rag_core.py 在 generate_answer() 末尾调用 kb_learning.log_query()。
功能:
  1. 自动检测低质量检索 → 写入 badcase_pending 队列
  2. 用户反馈 → 写入 badcase_pending 队列
  3. 队列管理 → 供 badcase_review.py 审核
  4. 统计 → 巡检进度、未处理量

依赖:
  - 上级模块 rag_core.py（提供 QUERY_LOG_DB、log_feedback 等）
  - 引用 rag_core 路径的同时，badcase 队列写在 Windows 可访问的目录

文件结构:
  Desktop/自研/rag-docs/audit_reports/
    badcase_pending.jsonl    待审核失败用例（自动追加）
    badcase_approved.jsonl   已批准的 bad case（下次巡检自动加载）
    badcase_rejected.jsonl   已拒绝的 bad case
    audit_YYYY-MM-DD.json    每日巡检报告
"""

import json
import os
import logging
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────────────────────────
# 统一 audit 目录（评审 M10, 2026-08-11）:
#   RAG_AUDIT_DIR env 优先 → 默认 ~/audit_reports（daily_audit 真实数据所在）
# 旧默认 _HERE/Desktop/自研/rag-docs/audit_reports 已废弃（仓库内垃圾目录）
_HERE = Path(__file__).resolve().parent
_AUDIT_DIR = Path(os.environ.get("RAG_AUDIT_DIR", str(Path.home() / "audit_reports")))

def _ensure_audit_dir() -> Path:
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        return _AUDIT_DIR
    except (OSError, PermissionError) as e:
        logger.warning("audit dir 创建失败 %s, 回退仓库内 audit_reports: %s", _AUDIT_DIR, e)
        alt = _HERE / "audit_reports"
        alt.mkdir(parents=True, exist_ok=True)
        return alt

AUDIT_DIR = _ensure_audit_dir()

PENDING_FILE = AUDIT_DIR / "badcase_pending.jsonl"
APPROVED_FILE = AUDIT_DIR / "badcase_approved.jsonl"
REJECTED_FILE = AUDIT_DIR / "badcase_rejected.jsonl"

# ── 阈值 ──────────────────────────────────────────────────────────────
# 低于这些分数判定为潜在 bad case
SCORE_WARN = 0.6       # 警告线
SCORE_FAIL = 0.45      # 失败线（低质量检索）
MIN_CHUNKS = 1          # 最少命中chunk数

# ── 辅助函数 ─────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_jsonl(path: Path) -> list:
    """读取 JSONL 文件，每行一个 dict，跳过空行/坏行."""
    if not path.exists():
        return []
    items = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(f"坏行跳过: {path} ({line[:60]})")
    except Exception as e:
        logger.warning(f"读取 {path} 失败: {e}")
    return items


def _append_jsonl(path: Path, item: dict):
    """追加一条记录到 JSONL 文件."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"写入 {path} 失败: {e}")


def _remove_from_jsonl(path: Path, pred_fn) -> list:
    """过滤掉满足 pred_fn 的行，重写文件，返回被移除的条目."""
    items = _read_jsonl(path)
    kept = []
    removed = []
    for item in items:
        if pred_fn(item):
            removed.append(item)
        else:
            kept.append(item)
    try:
        with open(path, "w", encoding="utf-8") as f:
            for item in kept:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"重写 {path} 失败: {e}")
    return removed


# ── 公共 API ──────────────────────────────────────────────────────────

def log_query(query: str, top_score: float = 0.0, chunks_count: int = 0,
              channel: str = "", answer_length: int = 0, model: str = "",
              sqlite_query_id=None):
    """记录一条查询，自动检测是否需要进入 badcase 队列。

    由 rag_core.py generate_answer() 在每次 LLM 生成后调用。
    返回 query_id（字符串），与 SQLite 的 query_log.id 对应。

    参数:
      query: 用户查询原文
      top_score: 检索到的最高 chunk score
      chunks_count: 检索到的 chunk 数量
      channel: 使用的 LLM 通道名
      answer_length: 生成答案的字符数
      model: 模型 ID
      sqlite_query_id: SQLite query_log 中的真实 id；传入后 entry 保留回指字段，
                       返回值优先用它（保证反馈链路 query_id 真实可 int()）
    """
    now = _now()
    entry = {
        "ts": now,
        "query": query,
        "top_score": round(top_score, 4),
        "chunks_count": chunks_count,
        "channel": channel,
        "answer_length": answer_length,
        "model": model,
    }
    if sqlite_query_id is not None:
        entry["sqlite_query_id"] = sqlite_query_id

    # ── Bad Case 自动判定 ──
    reasons = []
    if top_score < SCORE_FAIL and chunks_count > 0:
        reasons.append(f"top_score={top_score:.3f} < {SCORE_FAIL}（低质量检索）")
    elif top_score < SCORE_WARN and chunks_count > 0:
        reasons.append(f"top_score={top_score:.3f} < {SCORE_WARN}（检索质量偏低）")
    if chunks_count == 0:
        reasons.append("检索结果为空（知识库未覆盖）")
    if answer_length < 50 and chunks_count > 0:
        reasons.append(f"生成答案过短 ({answer_length} 字符)")

    # ── 语义鸿沟检测 ──
    # 分数不低但查询含明确技术词 → 可能向量检索混淆相似概念（如 PC Interface ↔ DeviceNet）
    _semantic_gap_terms = [
        "PC Interface", "DeviceNet", "RTCP", "远程TCP", "高惯量",
        "物料搬运", "Robot Interface", "上位机", "寄存器读写",
        "PCIF", "TCPC", "BODY", "MOTN", "CNT", "ACC",
    ]
    _gap_hits = [t for t in _semantic_gap_terms if t.lower() in query.lower()]
    if _gap_hits and 0.4 < top_score < 0.75 and chunks_count > 0:
        reasons.append(f"语义鸿沟风险: 查询含关键词{_gap_hits[:3]}但检索分数偏低({top_score:.2f})，可能向量混淆相似概念")

    if reasons:
        entry["badcase"] = True
        entry["reason"] = "; ".join(reasons)
        entry["status"] = "pending"
        _append_jsonl(PENDING_FILE, entry)
        logger.info(f"Bad case 自动记录: {query[:50]}... → {reasons[0]}")
    else:
        entry["badcase"] = False

    # 返回标识符：有真实 SQLite id 时优先返回它，反馈链路才能 int(query_id)
    if sqlite_query_id is not None:
        return str(sqlite_query_id)
    return f"kb_{int(time.time())}"


def add_feedback(query_text: str, feedback: str, top_score: float = 0.0,
                 sender: str = "", note: str = ""):
    """用户反馈入口（👍/👎），写入 pending 队列。

    参数:
      query_text: 触发反馈的查询原文
      feedback: 'good' | 'bad'
      top_score: 检索分数（如有）
      sender: 反馈者（微信昵称等）
      note: 补充说明
    """
    now = _now()
    entry = {
        "ts": now,
        "query": query_text,
        "top_score": round(top_score, 4),
        "feedback": feedback,
        "sender": sender or "unknown",
        "note": note,
        "badcase": (feedback == "bad"),
        "reason": "用户反馈 👎" if feedback == "bad" else "",
        "status": "pending" if feedback == "bad" else "user_good",
    }
    _append_jsonl(PENDING_FILE if feedback == "bad" else APPROVED_FILE, entry)
    logger.info(f"用户反馈 {feedback}: {query_text[:50]}...")
    return entry


def get_pending_badcases() -> list:
    """返回待审核的 bad case 列表。"""
    return _read_jsonl(PENDING_FILE)


def get_approved_badcases() -> list:
    """返回已批准的 bad case。"""
    return _read_jsonl(APPROVED_FILE)


def get_rejected_badcases() -> list:
    """返回已拒绝的 bad case。"""
    return _read_jsonl(REJECTED_FILE)


def approve_badcase(pred_fn) -> int:
    """批准满足 pred_fn 的 pending bad case，移入 approved 队列。

    返回批准的数量。
    """
    removed = _remove_from_jsonl(PENDING_FILE, pred_fn)
    for item in removed:
        item["status"] = "approved"
        item["approved_at"] = _now()
        _append_jsonl(APPROVED_FILE, item)
    return len(removed)


def reject_badcase(pred_fn, reason: str = "") -> int:
    """拒绝满足 pred_fn 的 pending bad case，移入 rejected 队列。

    返回拒绝的数量。
    """
    removed = _remove_from_jsonl(PENDING_FILE, pred_fn)
    for item in removed:
        item["status"] = "rejected"
        item["rejected_at"] = _now()
        item["reject_reason"] = reason
        _append_jsonl(REJECTED_FILE, item)
    return len(removed)


def get_stats() -> dict:
    """返回学习统计（兼容旧版消费方字段 + 新字段）。

    旧版消费方（rag_admin._sl_overview / rag_api / rag_web）依赖:
      total_queries / total_gaps / gap_rate / avg_score /
      total_feedback / total_faq / top_gaps
    """
    pending = get_pending_badcases()
    approved = get_approved_badcases()
    rejected = get_rejected_badcases()
    total_queries, avg_score = _sqlite_query_stats()
    fb_items = _read_jsonl(_FEEDBACK_LOG)

    # Top 知识缺口：pending 队列中的重复查询
    qcount: dict = {}
    for it in pending:
        q = (it.get("query") or "").strip()
        if q:
            qcount[q] = qcount.get(q, 0) + 1
    top_gaps = sorted(qcount.items(), key=lambda kv: kv[1], reverse=True)[:10]
    total_gaps = len(pending)
    total_faq = len(get_faq_pairs(limit=100))

    return {
        "pending_count": len(pending),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "pending_items": pending[-20:] if pending else [],
        "last_updated": _now(),
        # ── 兼容旧版消费方字段 ──
        "total_queries": total_queries,
        "total_gaps": total_gaps,
        "gap_rate": round(total_gaps / total_queries * 100, 1) if total_queries else 0,
        "avg_score": avg_score,
        "total_feedback": len(fb_items),
        "total_faq": total_faq,
        "top_gaps": top_gaps,
    }


def _sqlite_query_stats() -> tuple:
    """从 SQLite query_log 读统计（函数内延迟导入，避免循环依赖）。

    返回 (total_queries, avg_top_score)；读取失败时返回 (0, 0.0)。
    """
    try:
        from rag_core import QUERY_LOG_DB
        import sqlite3
        conn = sqlite3.connect(str(QUERY_LOG_DB), timeout=5)
        try:
            total = conn.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
            row = conn.execute(
                "SELECT AVG(top_score) FROM query_log WHERE top_score IS NOT NULL"
            ).fetchone()
            avg = float(row[0]) if row and row[0] is not None else 0.0
        finally:
            conn.close()
        return int(total), round(avg, 4)
    except Exception:
        return 0, 0.0


def get_gaps(limit: int = 50) -> list:
    """知识缺口列表：badcase 队列中未处理的低质量检索。

    兼容旧版消费方：rag_admin._sl_gaps / rag_api.learning_gaps / rag_web.show_gaps。
    每项: {'datetime', 'query', 'top_score', 'chunks_count'}
    """
    items = get_pending_badcases()
    items.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return [
        {
            "datetime": it.get("ts", ""),
            "query": it.get("query", ""),
            "top_score": it.get("top_score", 0.0),
            "chunks_count": it.get("chunks_count", 0),
        }
        for it in items[:limit]
    ]


def get_feedback_summary(days: int = 7) -> dict:
    """反馈汇总（兼容旧版消费方 up/down 语义）。

    返回: {'period_days', 'up', 'down', 'satisfaction_rate', 'down_queries'}
    """
    cutoff = (datetime.now().timestamp() - days * 86400)
    items = []
    for it in _read_jsonl(_FEEDBACK_LOG):
        try:
            ts = datetime.strptime(it.get("ts", ""), "%Y-%m-%d %H:%M:%S")
            if ts.timestamp() >= cutoff:
                items.append(it)
        except (ValueError, TypeError):
            continue
    up = sum(1 for r in items if r.get("feedback") in ("good", "up"))
    down = sum(1 for r in items if r.get("feedback") in ("bad", "down"))
    total = up + down
    return {
        "period_days": days,
        "up": up,
        "down": down,
        "satisfaction_rate": round(up / total * 100, 1) if total else 0,
        "down_queries": [
            {
                "query": r.get("query", ""),
                "comment": r.get("note", ""),
                "datetime": r.get("ts", ""),
            }
            for r in items if r.get("feedback") in ("bad", "down")
        ][-20:],
    }


def get_faq_pairs(limit: int = 50) -> list:
    """自动沉淀 FAQ：聚合用户 👍 反馈中出现过的高频查询。

    每项: {'query', 'hit_count', 'datetime'}
    """
    counts: dict = {}
    last_ts: dict = {}
    for it in _read_jsonl(_FEEDBACK_LOG):
        if it.get("feedback") not in ("good", "up"):
            continue
        q = (it.get("query") or "").strip()
        if not q:
            continue
        counts[q] = counts.get(q, 0) + 1
        last_ts[q] = it.get("ts", "")
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"query": q, "hit_count": c, "datetime": last_ts.get(q, "")}
        for q, c in ranked[:limit]
    ]


def generate_report() -> str:
    """自学习自检报告（文本）。"""
    stats = get_stats()
    lines = [
        "# 自学习自检报告",
        f"- 生成时间: {_now()}",
        f"- 总查询数: {stats.get('total_queries', 0)}",
        f"- 知识缺口: {stats.get('total_gaps', 0)}（待审 {stats.get('pending_count', 0)}）",
        f"- 平均检索分: {stats.get('avg_score', 0)}",
        f"- 用户反馈: {stats.get('total_feedback', 0)}",
        f"- 沉淀FAQ: {stats.get('total_faq', 0)}",
    ]
    gaps = get_gaps(limit=10)
    if gaps:
        lines.append("\n## Top 知识缺口")
        for g in gaps:
            lines.append(f"- [{g['datetime']}] {g['query'][:60]} (score={g['top_score']})")
    else:
        lines.append("\n## 知识缺口\n无")
    return "\n".join(lines)


def export_badcase_report(output_path: str = "") -> str:
    """生成 Bad Case 汇总 Markdown 报告。

    输出路径默认为 AUDIT_DIR / badcase_汇总.md
    """
    pending = get_pending_badcases()
    approved = get_approved_badcases()
    rejected = get_rejected_badcases()

    # 合并所有待处理（按时间排序）
    pending_sorted = sorted(
        [p for p in pending if p.get("badcase") and p.get("status") == "pending"],
        key=lambda x: x.get("ts", ""),
        reverse=True,
    )

    lines = []
    lines.append(f"# Bad Case 汇总 — {datetime.now().strftime('%Y-%m-%d')}\n")
    lines.append(f"**生成时间:** {_now()}")
    lines.append(f"**待处理:** {len(pending_sorted)} | "
                 f"**已批准:** {len(approved)} | "
                 f"**已拒绝:** {len(rejected)}\n")
    lines.append("---\n")
    lines.append("## 待处理 Bad Case 清单\n")

    if pending_sorted:
        lines.append("| # | 时间 | 题目 | 失败原因 | top_score |")
        lines.append("|---|------|------|---------|-----------|")
        for i, bc in enumerate(pending_sorted, 1):
            q = bc.get("query", "")[:50]
            reason = bc.get("reason", "")[:60]
            score = bc.get("top_score", 0)
            ts = bc.get("ts", "")[5:16]  # MM-DD HH:MM
            lines.append(f"| {i} | {ts} | {q} | {reason} | {score} |")
    else:
        lines.append("*暂无待处理 bad case* ✅\n")

    lines.append(f"\n**共 {len(pending_sorted)} 条待处理 bad case**\n")
    lines.append("---\n")
    lines.append("> 处理方式: 运行 `python3 badcase_review.py` 审核")
    lines.append(f"> 报告路径: {AUDIT_DIR / 'badcase_汇总.md'}")

    report_text = "\n".join(lines)

    if output_path:
        out = Path(output_path)
    else:
        out = AUDIT_DIR / "badcase_汇总.md"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write(report_text)
        logger.info(f"Bad case 报告已写入 {out}")
    except Exception as e:
        logger.warning(f"写入报告失败: {e}")

    return report_text


# ── 反馈日志（独立于 badcase 队列，用于趋势分析） ──────────────────
_FEEDBACK_LOG = AUDIT_DIR / "feedback_log.jsonl"

def record_feedback(query: str, feedback: str, source: str = "", note: str = ""):
    """记录用户 👍/👎 反馈（独立于 badcase 队列）。
    
    source 区分来源: 'flywheel' | 'hermes_feishu' | 'manual_review'
    """
    now = _now()
    entry = {
        "ts": now,
        "query": query[:100],
        "feedback": feedback,    # "good" | "bad" | "neutral"
        "source": source,
        "note": note,
    }
    _append_jsonl(_FEEDBACK_LOG, entry)
    return entry

def get_feedback_stats(days: int = 7) -> dict:
    """返回最近 N 天的 👍/👎 统计。"""
    items = _read_jsonl(_FEEDBACK_LOG)
    cutoff = (datetime.now().timestamp() - days * 86400)
    recent = []
    for it in items:
        try:
            ts = datetime.strptime(it.get("ts",""), "%Y-%m-%d %H:%M:%S")
            if ts.timestamp() >= cutoff:
                recent.append(it)
        except (ValueError, TypeError):
            continue
    good = sum(1 for r in recent if r.get("feedback") == "good")
    bad = sum(1 for r in recent if r.get("feedback") == "bad")
    total = good + bad
    return {
        "period_days": days,
        "total": total,
        "good": good,
        "bad": bad,
        "pass_rate": round(good / total, 3) if total > 0 else 0,
        "items": recent[-20:],
    }

def compare_flywheel_feedback(flywheel_pass_rate: float, feedback_pass_rate: float) -> str:
    """对比飞轮通过率和用户满意度，发现漏检问题。
    
    Returns: 'match' | 'flywheel_overestimates' | 'feedback_overestimates' | 'insufficient_data'
    """
    if feedback_pass_rate == 0:
        return "insufficient_data"
    gap = flywheel_pass_rate - feedback_pass_rate
    if abs(gap) < 0.1:
        return "match"
    return "flywheel_overestimates" if gap > 0 else "feedback_overestimates"

# ── 命令行入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "export":
        print(export_badcase_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = get_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "record_feedback":
        q = sys.argv[2] if len(sys.argv) > 2 else ""
        fb = sys.argv[3] if len(sys.argv) > 3 else "good"
        r = record_feedback(q, fb, source="cli")
        print(json.dumps(r, ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "feedback_stats":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        stats = get_feedback_stats(days)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "compare":
        fw = float(sys.argv[2]) if len(sys.argv) > 2 else 0.93
        fb = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
        fb_stats = get_feedback_stats(7)
        fb_rate = fb_stats["pass_rate"]
        result = compare_flywheel_feedback(fw, fb_rate or fb)
        print(f"飞轮通过率: {fw:.2%}")
        print(f"用户满意度: {fb_rate:.2%} ({fb_stats['good']}/{fb_stats['total']} 👍)")
        print(f"对比结论: {result}")
    else:
        print(f"kb_learning.py — 自学习模块")
        print(f"  AUDIT_DIR: {AUDIT_DIR}")
        print(f"  pending: {len(get_pending_badcases())}")
        print(f"  approved: {len(get_approved_badcases())}")
        print(f"  rejected: {len(get_rejected_badcases())}")
        print(f"  feedback_log: {len(_read_jsonl(_FEEDBACK_LOG))} 条")
        print()
        print("用法:")
        print("  python3 kb_learning.py export              生成 bad case 汇总报告")
        print("  python3 kb_learning.py stats               查看学习统计")
        print("  python3 kb_learning.py record_feedback <q> <good|bad>  记录反馈")
        print("  python3 kb_learning.py feedback_stats [days]           查看反馈统计")
        print("  python3 kb_learning.py compare [fw_rate] [fb_rate]     对比飞轮vs满意度")
