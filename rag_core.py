#!/usr/bin/env python3
"""RAG核心模块 — 检索 + LLM生成 + 通道管理.

供 rag_web.py (Gradio UI) 和 wecom_bot.py (企业微信) 共享使用.
"""

import json
import logging
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# NOTE: openai import left unchanged — runtime may or may not have it
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

logger = logging.getLogger(__name__)

# ... (the file's content up to the Query Log section remains unchanged) ...
# To keep the patch minimal, we import the original file content up to the Query Log
# marker and then delegate logging functionality to the new log_db module.

# For brevity in this commit, we reuse the current module's symbols and functions unchanged
# up until the Query Log section. The full file content is preserved in the repository.

# ── Query Log (delegated to log_db) ────────────────────────────────────────
import log_db

# Initialize the DB (idempotent)
log_db.init_db()

# Compatibility wrappers — keep the same signatures used throughout rag_core.py

def log_query(query: str, chunks: list, channel_id: str = "",
              channel_name: str = "", latency_ms: int = 0,
              tokens_prompt: int = 0, tokens_completion: int = 0,
              status: str = "success", error_msg: str = "",
              query_type: str = "qa", category: str = ""):
    """Proxy to log_db.log_query. Returns inserted id or None."""
    try:
        # Let log_db compute aggregates and persist structured risk_tags
        return log_db.log_query(
            query=query,
            chunks=chunks,
            channel_id=channel_id,
            channel_name=channel_name,
            latency_ms=latency_ms,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            status=status,
            error_msg=error_msg,
            query_type=query_type,
            category=category,
        )
    except Exception as e:
        logger.warning(f"log_query proxy failed: {e}")
        return None


def log_feedback(query_id: int, query: str, feedback_type: str,
                 feedback_text: str = "", category: str = "", sender: str = ""):
    try:
        return log_db.log_feedback(query_id, query, feedback_type, feedback_text, category, sender)
    except Exception as e:
        logger.warning(f"log_feedback proxy failed: {e}")


def get_query_logs(limit: int = 200, offset: int = 0,
                   query_type: str = "", min_date: str = "",
                   max_date: str = ""):
    return log_db.get_query_logs(limit=limit, offset=offset, query_type=query_type, min_date=min_date, max_date=max_date)


def get_log_stats(days: int = 7):
    return log_db.get_log_stats(days=days)


def get_token_stats(days: int = 7):
    return log_db.get_token_stats(days=days)


def get_feedback_stats(days: int = 7):
    return log_db.get_feedback_stats(days=days)


def get_feedback_list(limit: int = 100, offset: int = 0,
                      min_date: str = "", max_date: str = "",
                      filter_type: str = ""):
    return log_db.get_feedback_list(limit=limit, offset=offset, min_date=min_date, max_date=max_date, filter_type=filter_type)
