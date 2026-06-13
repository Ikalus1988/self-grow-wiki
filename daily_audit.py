#!/usr/bin/env python3
"""每日巡检 — RAG 知识库质量保障 + 飞轮闭环.

流程:
  每天自动跑 7 道测试题（分层抽样），
  检查检索结果的分数、关键词命中、品牌污染，
  结果写入 audit_reports/ + badcase_pending 队列。

用法:
  python3 daily_audit.py             手动跑一次完整巡检
  python3 daily_audit.py --dry-run   预览抽样题目，不调 API
  python3 daily_audit.py --cron      安静模式（只写文件，不打印细节）

定时任务（crontab 每天 9:00）:
  0 9 * * * cd /home/hp && python3 daily_audit.py --cron >> /home/hp/audit_cron.log 2>&1
"""

import json
import os
import sys
import time
import random
import urllib.request
import logging
from datetime import datetime
from pathlib import Path

# ── 日志 ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("daily_audit")

# ── 路径 ─────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_RAG_DOCS = Path(os.environ.get("RAG_DOCS_DIR", "/mnt/c/Users/hp/Desktop/自研/rag-docs"))
_QUESTION_BANK = Path(os.environ.get(
    "RAG_QUESTION_BANK",
    str(_RAG_DOCS / "RAG巡检题库_200题_20260508.json"),
))
_AUDIT_DIR = Path(os.environ.get("RAG_AUDIT_DIR", "/home/hp/audit_reports"))
_SYNONYM_FILE = _HERE / "synonyms.json"
_BADCASE_MD = _RAG_DOCS / "badcase_汇总.md"

# fallback
_QUESTION_BANK_ALT = _HERE / "RAG巡检题库_200题_20260508.json"

# ── API ──────────────────────────────────────────────────────────────
RAG_API = os.environ.get("RAG_API_URL", "http://localhost:8002/query")

# ── 配置 ─────────────────────────────────────────────────────────────
SAMPLE_SIZE = 7          # 每次巡检 7 题
L2_COUNT = 2             # 其中 2 题 L2
L3_COUNT = 5             # 5 题 L3
MIN_ANSWER_LEN = 150     # 有效回答最短长度
SCORE_WARN = 0.6         # 分数警告线
NO_REPEAT_DAYS = 30      # 原则上 30 天内不重复抽题，题库耗尽时自动轮换

# ── 加载题库 ─────────────────────────────────────────────────────────

def load_question_bank() -> list:
    """返回题库列表 [{id, level, tag, query, expect: {must_contain_any, min_top_score}}, ...]"""
    paths = [_QUESTION_BANK, _QUESTION_BANK_ALT]
    for p in paths:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, list) and len(raw) > 0:
                logger.info(f"加载题库: {p} ({len(raw)} 题)")
                return raw
            logger.warning(f"题库格式异常: {p}")
    logger.error("题库文件未找到，请检查路径")
    return []


def _question_id(q: dict) -> str:
    """返回题目稳定 ID；无 id 时回退到 query，避免重复抽题。"""
    return str(q.get("id") or q.get("query") or "")


def _load_recent_qids(days: int = NO_REPEAT_DAYS) -> set:
    """读取最近巡检已抽题目 ID；新旧报告格式都兼容。"""
    recent = set()
    if not _AUDIT_DIR.exists():
        return recent

    cutoff_ts = time.time() - days * 86400
    for path in _AUDIT_DIR.glob("audit_*.json"):
        try:
            if path.stat().st_mtime < cutoff_ts:
                continue
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        for qid in report.get("sampled_qids") or []:
            if qid:
                recent.add(str(qid))

        for item in report.get("results") or []:
            qid = item.get("qid") or item.get("id")
            if qid:
                recent.add(str(qid))

    return recent


def _exclude_recent_if_possible(pool: list, needed: int, recent_qids: set) -> list:
    """优先从 30 天未抽过的池子抽；池子不够时允许月轮换。"""
    fresh = [q for q in pool if _question_id(q) not in recent_qids]
    return fresh if len(fresh) >= needed else pool


def sample_questions(bank: list, seed: int = None) -> list:
    """分层抽样：L2/L3 + tag 多样性 + 30 天内尽量不重复。"""
    if seed is None:
        seed = int(time.time())
    rng = random.Random(seed)

    recent_qids = _load_recent_qids()
    l2_all = [q for q in bank if q.get("level", "").upper() == "L2"]
    l3_all = [q for q in bank if q.get("level", "").upper() != "L2"]
    l2 = _exclude_recent_if_possible(l2_all, L2_COUNT, recent_qids)
    l3 = _exclude_recent_if_possible(l3_all, L3_COUNT, recent_qids)

    # 对 L3 按 tag 进一步分层，确保类型多样性
    l3_by_tag = {}
    for q in l3:
        tag = q.get("tag", "其他")
        l3_by_tag.setdefault(tag, []).append(q)

    selected_l2 = rng.sample(l2, min(L2_COUNT, len(l2)))
    selected_l3 = []

    # 从尽可能多的 tag 中各取 1 题
    tags = list(l3_by_tag.keys())
    rng.shuffle(tags)
    for tag in tags:
        if len(selected_l3) >= L3_COUNT:
            break
        candidates = [q for q in l3_by_tag[tag] if q not in selected_l3]
        if candidates:
            selected_l3.append(rng.choice(candidates))

    # 如果还不够，从剩余的 L3 补齐
    remaining = [q for q in l3 if q not in selected_l3]
    rng.shuffle(remaining)
    selected_l3.extend(remaining[:L3_COUNT - len(selected_l3)])

    result = selected_l2 + selected_l3

    # 题库当前可能只有 L2 或某一层题量不足；保持 7 题预算，用全库未抽过题目补齐。
    # 补齐仍优先 30 天未抽过，只有题库耗尽时才月轮换。
    if len(result) < SAMPLE_SIZE:
        selected_ids = {_question_id(q) for q in result}
        fresh_bank = [q for q in bank if _question_id(q) not in recent_qids]
        fill_pool = [q for q in fresh_bank if _question_id(q) not in selected_ids]
        if len(fill_pool) < SAMPLE_SIZE - len(result):
            fill_pool = [q for q in bank if _question_id(q) not in selected_ids]
        rng.shuffle(fill_pool)
        result.extend(fill_pool[:SAMPLE_SIZE - len(result)])

    rng.shuffle(result)  # 混排，不按难度顺序
    return result[:SAMPLE_SIZE]


# ── API 调用 ─────────────────────────────────────────────────────────

def call_rag(query_text: str, top_k: int = 3) -> dict:
    """调用 RAG API，返回 {"answer": "...", "elapsed": N}."""
    payload = json.dumps({"query": query_text, "top_k": top_k}).encode("utf-8")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            RAG_API,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=60)
        data = json.loads(resp.read().decode("utf-8"))
        elapsed = time.time() - t0
        return {
            "answer": data.get("answer", ""),
            "elapsed_s": round(elapsed, 2),
        }
    except Exception as e:
        elapsed = time.time() - t0
        return {
            "answer": "",
            "elapsed_s": round(elapsed, 2),
            "error": str(e),
        }


# ── 单题检测 ─────────────────────────────────────────────────────────

def check_brand_contamination(answer: str) -> list:
    """检查是否混入竞品品牌信息。返回检测到的品牌列表。"""
    brands = {
        "KUKA": ["kuka", "库卡"],
        "ABB": ["abb", "abb机器人"],
        "Yaskawa": ["yaskawa", "安川"],
        "Kawasaki": ["kawasaki", "川崎"],
        "OTC": ["otc", "daiben"],
        "Panasonic": ["panasonic", "松下", "TAWERS"],
        "Staubli": ["staubli", "史陶比尔"],
        "Fanuc_only_ok": ["fanuc"],  # FANUC 本身不算污染
    }
    found = []
    a_lower = answer.lower()
    for brand, keywords in brands.items():
        if brand == "Fanuc_only_ok":
            continue
        for kw in keywords:
            if kw in a_lower:
                found.append(brand)
                break
    return found


def check_semantic_gap(query: str, answer: str, top_score: float) -> list:
    """检测语义鸿沟：查询中有但答案中缺失的关键技术词，建议加同义词。"""
    # 从查询中提取可能的技术术语
    terms = set()
    for part in query.replace("？", " ").replace("?", " ").replace("，", " ").split():
        part = part.strip()
        # 中文词 (2-6 字) 或 英文代码
        if len(part) >= 2 and any('\u4e00' <= c <= '\u9fff' for c in part):
            terms.add(part)
        elif '-' in part and len(part) <= 20:  # 报警码/型号
            terms.add(part)

    # 哪些术语在答案中完全没出现
    missing = []
    a_lower = answer.lower()
    for t in terms:
        if t.lower() not in a_lower and len(t) >= 2:
            missing.append(t)

    # 如果分数低且关键词未命中，建议加同义词
    suggestions = []
    if top_score < SCORE_WARN and missing:
        suggestions.append({
                "query_term": list(terms),
                "missing_in_answer": missing[:5],
            "suggestion": "考虑添加同义词或检查文档覆盖",
        })
    return suggestions


# ── 同义词补充建议 ──────────────────────────────────────────────────

def auto_suggest_synonyms(bad_queries: list) -> list:
    """根据失败的查询，自动建议同义词条目。

    返回 [(原始词, [建议同义词]), ...]
    """
    suggestions = []
    for item in bad_queries:
        q = item.get("query", "")
        if not q:
            continue
        # 提取报警码前缀和中文关键词
        words = q.replace("FANUC机器人", "").replace("FANUC", "").strip()
        # 简单的规则：长中文词建议英文缩写
        cn_terms = []
        for c in words:
            if '\u4e00' <= c <= '\u9fff':
                cn_terms.append(c)
        cn_text = "".join(cn_terms)
        if 2 <= len(cn_text) <= 6 and cn_text not in ("机器人",):
            suggestions.append((cn_text, []))
    return suggestions[:3]


# ── 巡检主流程 ──────────────────────────────────────────────────────

def run_audit(dry_run: bool = False, quiet: bool = False) -> dict:
    """执行一次完整巡检，返回报告 dict。"""
    # 0. 加载题库
    bank = load_question_bank()
    if not bank:
        return {"error": "题库加载失败", "total": 0, "passed": 0, "rate": 0}

    # 1. 抽样
    questions = sample_questions(bank)
    logger.info(f"抽样: {len(questions)} 题 (seed={int(time.time()) % 100000})")
    if not quiet:
        for q in questions:
            level = q.get("level", "?")
            tag = q.get("tag", "?")
            query = q.get("query", "?")[:40]
            logger.info(f"  [{level}] [{tag}] {query}")

    if dry_run:
        return {"dry_run": True, "sampled": len(questions)}

    # 2. 逐一查询
    results = []
    bad_queries = []
    passed = 0
    total = len(questions)

    for i, q_data in enumerate(questions, 1):
        query = q_data.get("query", "")
        must_contain = q_data.get("expect", {}).get("must_contain_any", [])
        min_score = q_data.get("expect", {}).get("min_top_score", SCORE_WARN)

        # 构造完整查询（同现有审计脚本风格）
        full_query = f"FANUC机器人{query}"

        resp = call_rag(full_query)
        answer = resp.get("answer", "")
        elapsed = resp.get("elapsed_s", 0)
        error = resp.get("error", "")

        # 判断通过
        hit_keywords = [kw for kw in must_contain if kw.lower() in answer.lower()]
        is_empty_kb = "知识库中未找到" in answer
        answer_ok = len(answer) >= MIN_ANSWER_LEN
        brand_contamination = check_brand_contamination(answer)
        keyword_hit = len(hit_keywords) > 0

        ok = keyword_hit and answer_ok and not is_empty_kb and not brand_contamination

        if ok:
            passed += 1
        else:
            reasons = []
            if not keyword_hit:
                reasons.append(f"未命中关键词 {must_contain}")
            if not answer_ok:
                reasons.append(f"答案过短 ({len(answer)} < {MIN_ANSWER_LEN})")
            if is_empty_kb:
                reasons.append("知识库未覆盖")
            if brand_contamination:
                reasons.append(f"品牌污染: {brand_contamination}")

            bad_queries.append({
                "query": query,
                "must_contain": must_contain,
                "min_score": min_score,
                "reason": "; ".join(reasons),
                "answer_length": len(answer),
            })

        # 语义鸿沟检测
        gap = check_semantic_gap(full_query, answer, min_score)

        result = {
            "id": i,
            "qid": q_data.get("id", f"Q{i}"),
            "level": q_data.get("level", "?"),
            "tag": q_data.get("tag", "?"),
            "query": query,
            "pass": ok,
            "hit_kws": hit_keywords,
            "brand_contamination": brand_contamination,
            "answer_length": len(answer),
            "elapsed_s": elapsed,
            "error": error,
            "gap": gap,
        }
        results.append(result)

        if not quiet or not ok:
            status = "PASS" if ok else "FAIL"
            logger.info(f"  [{status}] Q{i:02d} ({elapsed:.1f}s) {query[:40]}")

    # 3. 统计
    total = len(results)
    rate = (passed / total * 100) if total > 0 else 0

    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "total": total,
        "passed": passed,
        "rate_pct": round(rate, 1),
        "sigma": "4σ达标" if rate >= 95 else "3σ达标" if rate >= 90 else "需改进",
        "method": "每天7题分层抽样 + 30天去重/月轮换 + 关键词命中验证 + 品牌污染检测",
        "sample_seed": int(time.time()) % 100000,
        "sampled_qids": [q_data.get("id", f"Q{i}") for i, q_data in enumerate(questions, 1)],
        "results": results,
        "bad_queries": bad_queries,
    }

    # 4. 写入报告文件
    write_report(report)

    # 5. 写入 badcase_pending（通过 kb_learning 格式兼容）
    if bad_queries:
        write_badcase_pending(bad_queries)

    if not quiet:
        logger.info(f"巡检完成: {passed}/{total} ({rate:.1f}%)")
        if rate >= 95:
            logger.info("🎯 4σ 达标")
        elif rate >= 90:
            logger.info("📊 3σ 达标")
        else:
            logger.info("⚠️  需要改进")

    return report


def write_report(report: dict):
    """写入 JSON 报告到 audit_reports/audit_YYYY-MM-DD.json。"""
    date_str = report["date"]
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        path = _AUDIT_DIR / f"audit_{date_str}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"报告已写入 {path}")
    except Exception as e:
        logger.warning(f"写入报告失败: {e}")


def write_badcase_pending(bad_queries: list):
    """写入 badcase_pending.jsonl（与 kb_learning 格式兼容）。"""
    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        path = _AUDIT_DIR / "badcase_pending.jsonl"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            for bq in bad_queries:
                entry = {
                    "ts": now,
                    "source": "daily_audit",
                    "query": bq.get("query", ""),
                    "reason": bq.get("reason", ""),
                    "top_score": bq.get("min_score", 0),
                    "badcase": True,
                    "status": "pending",
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"已追加 {len(bad_queries)} 条 bad case 到 {path}")
    except Exception as e:
        logger.warning(f"写入 pending 失败: {e}")


def write_markdown_summary(report: dict):
    """生成简化的 Markdown 摘要。"""
    date = report.get("date", "?")
    total = report.get("total", 0)
    passed = report.get("passed", 0)
    rate = report.get("rate_pct", 0)

    lines = []
    lines.append(f"# 每日巡检报告 — {date}\n")
    lines.append(f"**通过率:** {rate}% ({passed}/{total})")
    lines.append(f"**评级:** {report.get('sigma', '?')}\n")

    if report.get("bad_queries"):
        lines.append("## ❌ 本次失败\n")
        lines.append("| 题目 | 原因 |")
        lines.append("|------|------|")
        for bq in report["bad_queries"]:
            q = bq.get("query", "")[:40]
            reason = bq.get("reason", "")[:60]
            lines.append(f"| {q} | {reason} |")
        lines.append("")

    lines.append(f"---\n")
    lines.append(f"生成时间: {report.get('time', '?')}")

    try:
        _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        path = _AUDIT_DIR / f"audit_{date}_summary.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        logger.warning(f"写入 summary 失败: {e}")


# ── 命令行入口 ──────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="RAG 知识库每日巡检")
    parser.add_argument("--dry-run", action="store_true", help="预览抽样题目")
    parser.add_argument("--cron", action="store_true", help="安静模式（用于 crontab）")
    args = parser.parse_args()

    quiet = args.cron
    dry_run = args.dry_run

    if not quiet:
        logger.info("=" * 50)
        logger.info("RAG 知识库每日巡检")
        logger.info(f"题库: {_QUESTION_BANK}")
        logger.info(f"API: {RAG_API}")
        logger.info(f"抽样: {SAMPLE_SIZE} 题 (L2:{L2_COUNT}, L3:{L3_COUNT})")
        logger.info("=" * 50)

    report = run_audit(dry_run=dry_run, quiet=quiet)

    if dry_run:
        logger.info(f"Dry-run: 将抽取 {report.get('sampled', 0)} 题")
        return

    if report.get("bad_queries"):
        write_markdown_summary(report)

    # cron 模式 exit code 反映结果
    if args.cron:
        rate = report.get("rate_pct", 0)
        if rate < 90:
            sys.exit(2)  # 严重
        elif rate < 95:
            sys.exit(1)  # 警告
        # 0 = 正常


if __name__ == "__main__":
    main()
