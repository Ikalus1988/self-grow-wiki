"""Log DB abstraction for query_log and feedback.

Provides a simple SQLite-backed implementation with WAL and structured risk_tags (JSON).
Default behavior remains synchronous writes for compatibility, but the module is structured
so an async queue worker can be enabled later.
"""
from pathlib import Path
import os
import sqlite3
import json
import threading
import time
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Configuration
DB_PATH = Path(os.environ.get("QUERY_LOG_DB", "/home/hp/rag_query_log.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_FLUSH_LOCK = threading.Lock()

# Initialize DB (idempotent)

def _ensure_db(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            query_type TEXT NOT NULL DEFAULT 'qa',
            query TEXT NOT NULL,
            category TEXT,
            top_score REAL,
            avg_score REAL,
            num_chunks INTEGER,
            channel_id TEXT,
            channel_name TEXT,
            latency_ms INTEGER,
            tokens_prompt INTEGER,
            tokens_completion INTEGER,
            status TEXT NOT NULL DEFAULT 'success',
            error_msg TEXT,
            risk_tags TEXT,
            has_source INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_ts ON query_log(ts)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_risk_tags ON query_log(risk_tags)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            query_id INTEGER REFERENCES query_log(id),
            query TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            feedback_text TEXT,
            category TEXT,
            sender TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fb_query ON feedback(query_id)
    """)
    conn.commit()


def init_db(path: Optional[Path] = None):
    """Create DB file and tables if not exists."""
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    try:
        _ensure_db(conn)
    finally:
        conn.close()


# Synchronous helper write (keeps compatibility with existing code that expects immediate id)
def _sync_write(entry: Dict[str, Any]) -> Optional[int]:
    """Write a single log entry synchronously and return inserted id."""
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        cur = conn.execute(
            """INSERT INTO query_log
               (query_type, query, category, top_score, avg_score, num_chunks,
                channel_id, channel_name, latency_ms,
                tokens_prompt, tokens_completion, status, error_msg,
                risk_tags, has_source, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.get("query_type", "qa"),
                entry.get("query", ""),
                entry.get("category", ""),
                entry.get("top_score"),
                entry.get("avg_score"),
                entry.get("num_chunks", 0),
                entry.get("channel_id", ""),
                entry.get("channel_name", ""),
                entry.get("latency_ms", 0),
                entry.get("tokens_prompt", 0),
                entry.get("tokens_completion", 0),
                entry.get("status", "success"),
                entry.get("error_msg", ""),
                json.dumps(entry.get("risk_tags") or []),
                1 if entry.get("has_source") else 0,
                int(entry.get("source_count") or 0),
            ),
        )
        query_id = cur.lastrowid
        conn.commit()
        return query_id
    except Exception as e:
        logger.warning(f"log_db: write failed: {e}")
        return None
    finally:
        conn.close()


# Public API

def log_query(query: str, chunks: List[Dict[str, Any]], channel_id: str = "",
              channel_name: str = "", latency_ms: int = 0,
              tokens_prompt: int = 0, tokens_completion: int = 0,
              status: str = "success", error_msg: str = "",
              query_type: str = "qa", category: str = "") -> Optional[int]:
    """Compatibility wrapper: compute simple aggregates and write synchronously.

    In future this can be changed to enqueue for async write; keeping sync for now to
    preserve existing behavior in code/tests that expect an id.
    """
    scores = [c.get("score") for c in chunks] if chunks else []
    top_score = max(scores) if scores else 0.0
    avg_score = sum(scores) / len(scores) if scores else 0.0
    filenames = {c.get("filename") for c in chunks if c.get("filename") and c.get("filename") != "unknown"}
    entry = {
        "query_type": query_type,
        "query": query,
        "category": category,
        "top_score": top_score,
        "avg_score": avg_score,
        "num_chunks": len(chunks),
        "channel_id": channel_id,
        "channel_name": channel_name,
        "latency_ms": latency_ms,
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "status": status,
        "error_msg": error_msg,
        "risk_tags": getattr(chunks, "_risk_tags", None) or [],
        "has_source": 1 if filenames else 0,
        "source_count": len(filenames),
    }
    # If chunks carry risk_tags in _risk_tags attribute (internal), prefer that
    # But infer_risk_tags in rag_core populates tags separately; caller can set entries
    # For now, try to extract risk_tags from chunks meta if present
    if not entry["risk_tags"]:
        # try to detect 'risk_tags' passed via chunks meta
        rt = []
        for c in chunks:
            if isinstance(c, dict) and c.get("risk_tags"):
                rt.extend(c.get("risk_tags") or [])
        entry["risk_tags"] = list(dict.fromkeys(rt))

    return _sync_write(entry)


def log_feedback(query_id: int, query: str, feedback_type: str,
                 feedback_text: str = "", category: str = "", sender: str = ""):
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute(
            """INSERT INTO feedback
               (query_id, query, feedback_type, feedback_text, category, sender)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (query_id, query, feedback_type, feedback_text, category, sender),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"log_db.log_feedback failed: {e}")
    finally:
        conn.close()


def get_query_logs(limit: int = 200, offset: int = 0,
                   query_type: str = "", min_date: str = "",
                   max_date: str = ""):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    where, params = [], []
    if query_type:
        where.append("query_type = ?")
        params.append(query_type)
    if min_date:
        where.append("ts >= ?")
        params.append(min_date)
    if max_date:
        where.append("ts <= ?")
        params.append(max_date)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM query_log {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    out = [dict(r) for r in rows]
    # Parse JSON risk_tags
    for r in out:
        if r.get("risk_tags"):
            try:
                r["risk_tags"] = json.loads(r["risk_tags"])
            except Exception:
                pass
    return out


def get_log_stats(days: int = 7):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

    total = conn.execute(
        "SELECT COUNT(*) c FROM query_log WHERE ts >= ?", (cutoff,)
    ).fetchone()[0]

    by_day = conn.execute(
        """SELECT substr(ts,1,10) AS day, COUNT(*) c, AVG(top_score) avg_top,
                  AVG(latency_ms) avg_lat, SUM(tokens_prompt+tokens_completion) total_tok
           FROM query_log WHERE ts >= ?
           GROUP BY day ORDER BY day""",
        (cutoff,),
    ).fetchall()

    by_status = conn.execute(
        "SELECT status, COUNT(*) c FROM query_log WHERE ts >= ? GROUP BY status",
        (cutoff,),
    ).fetchall()

    low_score = conn.execute(
        """SELECT query, top_score, ts FROM query_log
           WHERE ts >= ? AND top_score < 0.4 AND top_score > 0
           ORDER BY top_score ASC LIMIT 20""",
        (cutoff,),
    ).fetchall()

    top_queries = conn.execute(
        """SELECT query, COUNT(*) c FROM query_log
           WHERE ts >= ? GROUP BY query ORDER BY c DESC LIMIT 15""",
        (cutoff,),
    ).fetchall()

    # risk tag aggregation (simple)
    risk_rows = conn.execute(
        """SELECT risk_tags FROM query_log
           WHERE ts >= ? AND COALESCE(risk_tags, '') != ''""",
        (cutoff,),
    ).fetchall()
    conn.close()

    risk_counts = {}
    for row in risk_rows:
        try:
            tags = json.loads(row[0]) if row[0] else []
        except Exception:
            tags = []
        for t in tags:
            risk_counts[t] = risk_counts.get(t, 0) + 1

    return {
        "total": total,
        "by_day": [dict(r) for r in by_day],
        "by_status": [dict(r) for r in by_status],
        "low_score_queries": [dict(r) for r in low_score],
        "top_queries": [dict(r) for r in top_queries],
        "risk_tags": [{"risk_tag": k, "c": v} for k, v in sorted(risk_counts.items(), key=lambda x: x[1], reverse=True)],
    }


def get_token_stats(days: int = 7):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

    by_day = conn.execute(
        """SELECT substr(ts,1,10) AS day,
                  SUM(tokens_prompt) total_prompt,
                  SUM(tokens_completion) total_completion,
                  SUM(tokens_prompt + tokens_completion) total,
                  COUNT(*) query_count,
                  ROUND(AVG(tokens_prompt + tokens_completion)) avg_per_query
           FROM query_log WHERE ts >= ?
           GROUP BY day ORDER BY day""",
        (cutoff,),
    ).fetchall()

    by_channel = conn.execute(
        """SELECT COALESCE(NULLIF(channel_name,''), '未知') AS channel_name,
                  COALESCE(NULLIF(channel_id,''), 'unknown') AS channel_id,
                  SUM(tokens_prompt) total_prompt,
                  SUM(tokens_completion) total_completion,
                  SUM(tokens_prompt + tokens_completion) total,
                  COUNT(*) query_count,
                  ROUND(AVG(tokens_prompt + tokens_completion)) avg_per_query
           FROM query_log WHERE ts >= ? GROUP BY channel_name ORDER BY total DESC""",
        (cutoff,),
    ).fetchall()

    overall = conn.execute(
        """SELECT SUM(tokens_prompt) total_prompt,
                  SUM(tokens_completion) total_completion,
                  SUM(tokens_prompt + tokens_completion) total,
                  COUNT(*) query_count
           FROM query_log WHERE ts >= ?""",
        (cutoff,),
    ).fetchone()

    conn.close()
    return {
        "by_day": [dict(r) for r in by_day],
        "by_channel": [dict(r) for r in by_channel],
        "overall": dict(overall) if overall else {},
    }


def get_feedback_stats(days: int = 7):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

    by_type = conn.execute(
        "SELECT feedback_type, COUNT(*) c FROM feedback WHERE ts >= ? GROUP BY feedback_type",
        (cutoff,),
    ).fetchall()

    bad_list = conn.execute(
        """SELECT fb.id, fb.ts, fb.query, fb.feedback_type, fb.feedback_text, fb.category, fb.sender
           FROM feedback fb WHERE fb.ts >= ? AND fb.feedback_type IN ('bad','wrong_category')
           ORDER BY fb.id DESC LIMIT 50""",
        (cutoff,),
    ).fetchall()

    by_day = conn.execute(
        """SELECT substr(ts,1,10) AS day,
                  SUM(CASE WHEN feedback_type IN ('good','up') THEN 1 ELSE 0 END) good,
                  SUM(CASE WHEN feedback_type IN ('bad','down') THEN 1 ELSE 0 END) bad,
                  SUM(CASE WHEN feedback_type='wrong_category' THEN 1 ELSE 0 END) wrong_cat,
                  COUNT(*) total
           FROM feedback WHERE ts >= ?
           GROUP BY day ORDER BY day""",
        (cutoff,),
    ).fetchall()

    conn.close()

    total = sum(r["c"] for r in by_type)
    stats = {r["feedback_type"]: r["c"] for r in by_type}
    good = stats.get("good", 0) + stats.get("up", 0)
    bad = stats.get("bad", 0) + stats.get("down", 0)

    return {
        "total": total,
        "good": good,
        "bad": bad,
        "wrong_category": stats.get("wrong_category", 0),
        "satisfaction_rate": round(good / (good + bad) * 100, 1) if (good + bad) > 0 else 0,
        "by_type": [dict(r) for r in by_type],
        "by_day": [dict(r) for r in by_day],
        "bad_list": [dict(r) for r in bad_list],
    }


def get_feedback_list(limit: int = 100, offset: int = 0,
                      min_date: str = "", max_date: str = "",
                      filter_type: str = ""):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    where, params = [], []
    if min_date:
        where.append("ts >= ?")
        params.append(min_date)
    if max_date:
        where.append("ts <= ?")
        params.append(max_date)
    if filter_type:
        where.append("feedback_type = ?")
        params.append(filter_type)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM feedback {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
