#!/usr/bin/env python3
"""RAG HTTP API — 供 Windows 侧 wxauto 机器人调用.

端点:
  POST /query   {"query": "...", "top_k": 8, "temperature": 0.3}
  GET  /status   通道和向量库状态
  GET  /health   健康检查
"""

import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from rag_core import (
    get_collection, retrieve, generate_answer, generate_compare,
    generate_report, channel_mgr, MODEL_CHANNELS, DEFAULT_TOP_K, DEFAULT_TEMPERATURE,
    log_feedback, PATHS, _bm25_index,
)

REPORT_PATH = Path(PATHS["conflict_report"])


class QueryRequest(BaseModel):
    query: str
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=20)
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=1.0)
    channel: str = "auto"


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]
    status: str
    elapsed: float
    query_id: str = ""
    top_score: float = 0.0  # 评审 M11: 检索最高分, 供 daily_audit 判定


class FeedbackRequest(BaseModel):
    query_id: str
    query: str = ""
    rating: str  # "up" or "down"
    comment: str = ""


class ReportRequest(BaseModel):
    topic: str
    report_type: str = "theme"  # theme | compare | category
    compare_target: str = ""
    top_k: int = Field(default=30, ge=5, le=50)
    channel: str = "auto"


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("预加载向量库...")
    get_collection()
    print("预加载 BM25 索引...")
    _bm25_index._ensure_index()
    print("通道健康检查...")
    channel_mgr.check_all()
    yield


app = FastAPI(title="RAG API", lifespan=lifespan)


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    t0 = time.time()

    chunks = retrieve(req.query, top_k=req.top_k)
    if not chunks:
        return QueryResponse(
            answer=f"未找到与「{req.query}」相关的文档，建议换个关键词试试。",
            sources=[],
            status="no_results",
            elapsed=time.time() - t0,
            top_score=0.0,
        )

    # 检查相关度：如果最高分都很低，提示用户细化问题
    best_score = chunks[0].get("score", 0)
    if best_score < 0.35:
        hint = (
            f"当前检索结果与「{req.query}」的相关度较低（最高 {best_score:.0%}），回答可能不够准确。"
            "建议换个关键词或补充更具体的信息再试。\n\n以下是基于现有检索结果的回答：\n\n"
        )
    else:
        hint = ""

    answer, status, query_id = generate_answer(req.query, chunks, req.channel, req.temperature)
    answer = hint + answer

    seen = set()
    sources = []
    for c in chunks:
        if c["filename"] not in seen:
            seen.add(c["filename"])
            sources.append(c["filename"])
        if len(sources) >= 5:
            break

    return QueryResponse(
        answer=answer,
        sources=sources,
        status=status,
        elapsed=time.time() - t0,
        query_id=query_id,
        top_score=best_score,
    )


@app.get("/status")
def status():
    # 用缓存的健康状态，不做实时探测（避免 Ollama 挂掉时卡 30s）
    results = []
    for ch in MODEL_CHANNELS:
        h = channel_mgr.health.get(ch["id"], {})
        alive = h.get("alive")
        results.append({
            "id": ch["id"],
            "name": ch["name"],
            "model": ch["model_id"],
            "alive": alive,
            "latency": h.get("latency", 0) if alive else None,
            "error": h.get("error", "") if not alive else "",
        })

    try:
        coll = get_collection()
        vec_count = coll.count()
    except Exception:
        vec_count = -1

    return {
        "channels": results,
        "vectors": vec_count,
    }


class CompareRequest(BaseModel):
    subjects: list[str] = Field(min_length=2, max_length=4)
    aspect: str = ""
    top_k: int = Field(default=10, ge=1, le=20)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)


@app.post("/compare")
def compare(req: CompareRequest):
    t0 = time.time()

    answer, sources, status = generate_compare(
        subjects=req.subjects,
        aspect=req.aspect,
        top_k=req.top_k,
        temperature=req.temperature,
    )

    return {
        "answer": answer,
        "sources": sources,
        "status": status,
        "elapsed": time.time() - t0,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/kb/stats")
async def kb_stats():
    """知识库统计."""
    try:
        from rag_core import get_kb_stats
        return get_kb_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/feedback")
def submit_feedback(req: FeedbackRequest):
    """用户反馈 — 走 SQLite 统一数据源"""
    try:
        qid = int(req.query_id) if req.query_id else 0
        if not qid:
            return {"status": "error", "message": "query_id is required"}
        fb_type = "good" if req.rating in ("up", "good") else "bad"
        log_feedback(qid, req.query, fb_type, req.comment)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}


@app.get("/learning/stats")
def learning_stats():
    """自学习统计"""
    try:
        import kb_learning
        return kb_learning.get_stats()
    except ImportError:
        return {"status": "error", "message": "kb_learning module not available"}


@app.get("/learning/gaps")
def learning_gaps(limit: int = 50):
    """知识缺口列表"""
    try:
        import kb_learning
        return kb_learning.get_gaps(limit)
    except ImportError:
        return {"status": "error", "message": "kb_learning module not available"}


@app.get("/learning/report")
def learning_report():
    """自检报告"""
    try:
        import kb_learning
        return {"report": kb_learning.generate_report()}
    except ImportError:
        return {"status": "error", "message": "kb_learning module not available"}


@app.get("/selfcheck/report")
def selfcheck_report(limit: int = 5):
    if not REPORT_PATH.exists():
        return {
            "status": "no_report",
            "message": "尚未运行自检，请先执行: python3 ~/kb_selfcheck.py",
        }

    content = REPORT_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    generated_at = ""
    total_groups = 0
    total_conflicts = 0
    for line in lines[:6]:
        if line.startswith("生成时间:"):
            generated_at = line.replace("生成时间:", "").strip()
        elif line.startswith("扫描文档组:"):
            m = re.search(r"(\d+)", line)
            if m:
                total_groups = int(m.group(1))
        elif line.startswith("发现矛盾"):
            m = re.search(r"需处理:\s*(\d+)", line)
            if m:
                total_conflicts = int(m.group(1))

    needs = [l[len("## [需处理] "):] for l in lines if l.startswith("## [需处理]")]
    uncertain = [l[len("## [待核实] "):] for l in lines if l.startswith("## [待核实]")]

    return {
        "status": "ok",
        "generated_at": generated_at,
        "total_groups_scanned": total_groups,
        "needs_action_count": len(needs),
        "uncertain_count": len(uncertain),
        "needs_action": needs[:limit],
        "uncertain": uncertain[:limit],
    }


@app.post("/report", response_model=QueryResponse)
def report(req: ReportRequest):
    t0 = time.time()
    answer, sources, status, query_id = generate_report(
        topic=req.topic,
        report_type=req.report_type,
        compare_target=req.compare_target,
        top_k=req.top_k,
        preferred=req.channel,
    )
    return QueryResponse(
        answer=answer,
        sources=sources,
        status=status,
        elapsed=round(time.time() - t0, 2),
        query_id=query_id or "",
    )


if __name__ == "__main__":
    # 评审 M9: 默认只绑 127.0.0.1; 需要局域网访问时显式设 RAG_API_HOST=0.0.0.0
    uvicorn.run(app, host=os.environ.get("RAG_API_HOST", "127.0.0.1"), port=8002)
