import os, sys, json

# 配置
os.environ.setdefault("RAG_CHROMA_DIR", os.path.expanduser("~/rag_chromadb"))
os.environ.setdefault("RAG_COLLECTION", "wiki_docs")
os.environ.setdefault("RAG_EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5")

sys.path.insert(0, "/mnt/c/Users/Eric Jia/self-grow-wiki")

def fetch_rag_context(query: str, max_chars: int = 2000) -> str:
    """调用 rag_core.retrieve()，返回纯检索结果作为 context。"""
    if len(query.strip()) < 3:
        return ""
    try:
        import rag_core
        results = rag_core.retrieve(query, top_k=3)
        if not results:
            return ""
        lines = ["[FANUC文档检索结果]"]
        for i, r in enumerate(results, 1):
            src = r.get("source", r.get("filename", "unknown"))
            text = r.get("text", "")[:250]
            lines.append(f"[{i}] {src}\n{text}")
        ctx = "\n".join(lines)
        if len(ctx) > 1200:
            ctx = ctx[:1197] + "..."
        ctx += "\n\n【指令】基于以上文档片段回答。每条事实末尾标注来源文件。不编造。"
        return ctx + "\n---\n用户: "
    except Exception as e:
        return ""
