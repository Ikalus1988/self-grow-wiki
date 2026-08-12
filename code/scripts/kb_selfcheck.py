#!/usr/bin/env python3
"""知识库矛盾自检工具.

识别同名多版本文档，逐组对比内容矛盾，生成可操作报告。

用法:
  python3 kb_selfcheck.py               # 扫描全部多版本组
  python3 kb_selfcheck.py --limit 5     # 只扫描前5组（测试）
  python3 kb_selfcheck.py --group TS-0002936  # 扫描指定组
  python3 kb_selfcheck.py --report      # 只显示已有报告摘要
"""

import re
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────────────────────────
CHROMA_DIR       = Path("/home/eric_jia/rag_chromadb")
COLLECTION_NAME  = "wiki_docs"
EMBEDDING_MODEL  = "BAAI/bge-base-zh-v1.5"
REPORT_PATH      = Path("/home/eric_jia/kb_conflict_report.md")

MIOFFICE_API_BASE = None  # 从 rag_core 导入
MIOFFICE_API_KEY = None

# 运行时从 rag_core 获取配置
from rag_core import MIOFFICE_API_BASE as _MIOFFICE_BASE, MIOFFICE_API_KEY as _MIOFFICE_KEY
MIOFFICE_API_BASE = _MIOFFICE_BASE
MIOFFICE_API_KEY = _MIOFFICE_KEY

CHUNKS_PER_VERSION = 5   # 每个版本取多少 chunks 送给 LLM
LLM_MODEL     = "xiaomi/mimo-v2-flash"
LLM_TIMEOUT   = 60

CONFLICT_PROMPT = """你是工业技术文档审核专家。以下是同一文档不同版本的内容片段。
请识别版本间的矛盾或重要差异，格式：

[矛盾点] 简短描述矛盾主题
旧版说: ...（引用原文关键词）
新版说: ...（引用原文关键词）
建议: 采信新版本 | 需要人工核实 | 两者不矛盾

如果未发现实质矛盾，只需回复"未发现实质矛盾"。
控制在300字以内，不要用Markdown格式。"""


# ── 版本号解析 ────────────────────────────────────────────────────────────

def normalize_name(filename: str) -> str:
    """去除版本标记，返回用于分组的基础名（小写）."""
    name = Path(filename).stem
    name = re.sub(r'[_\-\s][Vv]\d+(\.\d+)?$', '', name)
    name = re.sub(r'\s*\(\d{4}\)$', '', name)
    name = re.sub(r'\s+[Rr]ev\.?\s*\w+$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[_\-\s]+$', '', name)
    return name.strip().lower()


def extract_version_number(filename: str) -> int:
    """提取文件名中的版本号，找不到返回 0（无版本 = 最旧）."""
    m = re.search(r'[_\-\s][Vv](\d+)', filename)
    if m:
        return int(m.group(1))
    return 0


def sort_versions(filenames: list) -> list:
    """将文件名列表按版本号升序排列（旧→新）."""
    return sorted(filenames, key=extract_version_number)


# ── ChromaDB 访问 ─────────────────────────────────────────────────────────

_collection = None


def get_collection():
    global _collection
    if _collection is not None:
        return _collection
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ef = SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL, device=device, trust_remote_code=False)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
    return _collection


def fetch_all_filenames() -> set:
    """从 ChromaDB 获取所有唯一文件名."""
    coll = get_collection()
    print("读取向量库元数据...")
    # get() 不指定 ids 时返回全部，但 include 只要 metadatas 省内存
    results = coll.get(include=["metadatas"])
    filenames = set()
    for m in results["metadatas"]:
        fn = m.get("filename") or m.get("source") or ""
        if fn:
            filenames.add(fn)
    print(f"共 {len(filenames)} 个唯一文件名")
    return filenames


def get_chunks_for_file(filename: str, n: int = CHUNKS_PER_VERSION) -> list:
    """从向量库中取指定文件的前 n 个 chunk（按 chunk_index 排序）."""
    coll = get_collection()
    results = coll.get(
        where={"filename": {"$eq": filename}},
        include=["documents", "metadatas"],
    )
    if not results["documents"]:
        return []
    pairs = list(zip(results["documents"], results["metadatas"]))
    pairs.sort(key=lambda x: x[1].get("chunk_index", 0))
    return [doc for doc, _ in pairs[:n]]


# ── 版本分组 ──────────────────────────────────────────────────────────────

def find_multi_version_groups(filenames: set) -> dict:
    """返回 {normalized_base: [filename1, filename2, ...]} 只包含多版本组."""
    groups: dict = {}
    for fn in filenames:
        base = normalize_name(fn)
        groups.setdefault(base, []).append(fn)
    return {k: sort_versions(v) for k, v in groups.items() if len(v) >= 2}


# ── LLM 对比 ─────────────────────────────────────────────────────────────

def llm_compare(base_name: str, version_chunks: dict) -> str:
    """version_chunks: {filename: [chunk_text, ...]}. 返回 LLM 分析文本."""
    parts = []
    for fn, chunks in version_chunks.items():
        ver_label = f"版本 {extract_version_number(fn) or '(基础版)'}: {fn}"
        joined = "\n---\n".join(chunks[:CHUNKS_PER_VERSION])
        parts.append(f"===== {ver_label} =====\n{joined}")

    context = "\n\n".join(parts)
    user_msg = f"文档组: {base_name}\n\n{context}"

    client = OpenAI(base_url=MIOFFICE_API_BASE, api_key=MIOFFICE_API_KEY, timeout=LLM_TIMEOUT)
    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": CONFLICT_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=600,
            temperature=0.2,
            timeout=LLM_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"LLM 调用失败: {e}"


# ── 网络搜索（不确定时）────────────────────────────────────────────────────

def web_search(query: str) -> str:
    """使用 DuckDuckGo 搜索，返回前3条摘要. 若未安装则跳过."""
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=3):
                results.append(f"- {r['title']}: {r['body'][:150]}")
        return "\n".join(results) if results else "未找到相关结果"
    except ImportError:
        return "（未安装 duckduckgo-search，跳过网络搜索）"
    except Exception as e:
        return f"（搜索失败: {e}）"


# ── 报告生成 ──────────────────────────────────────────────────────────────

def classify_result(llm_text: str) -> str:
    """根据 LLM 输出判断状态标签."""
    t = llm_text.lower()
    if "未发现实质矛盾" in t or "不矛盾" in t:
        return "无矛盾"
    if "需要人工核实" in t or "uncertain" in t or "不确定" in t:
        return "待核实"
    if "矛盾点" in t or "采信新版本" in t or "旧版说" in t:
        return "需处理"
    return "待核实"


def run_selfcheck(limit: int = None, group_filter: str = None) -> str:
    """执行自检，返回报告 Markdown 文本."""
    filenames = fetch_all_filenames()
    groups = find_multi_version_groups(filenames)

    print(f"发现 {len(groups)} 个多版本文档组")

    if group_filter:
        groups = {k: v for k, v in groups.items() if group_filter.lower() in k}
        print(f"过滤后: {len(groups)} 组")

    if limit:
        keys = list(groups.keys())[:limit]
        groups = {k: groups[k] for k in keys}
        print(f"限制扫描: {len(groups)} 组")

    needs_action = []
    uncertain = []
    no_conflict = []

    for i, (base, versions) in enumerate(groups.items(), 1):
        print(f"\n[{i}/{len(groups)}] {base}")
        print(f"  版本: {', '.join(versions)}")

        version_chunks = {}
        for fn in versions:
            chunks = get_chunks_for_file(fn)
            if chunks:
                version_chunks[fn] = chunks
                print(f"  {fn}: {len(chunks)} chunks")
            else:
                print(f"  {fn}: 无 chunks（可能尚未导入）")

        if len(version_chunks) < 2:
            print("  跳过：有效版本不足2个")
            continue

        print("  调用 LLM 分析...")
        llm_text = llm_compare(base, version_chunks)
        status = classify_result(llm_text)
        print(f"  结果: [{status}]")

        web_result = ""
        if status == "待核实":
            newest = versions[-1]
            search_q = f"{Path(newest).stem} specification standard latest"
            print(f"  联网搜索: {search_q}")
            web_result = web_search(search_q)

        entry = {
            "base": base,
            "versions": versions,
            "status": status,
            "llm_text": llm_text,
            "web_result": web_result,
        }

        if status == "需处理":
            needs_action.append(entry)
        elif status == "待核实":
            uncertain.append(entry)
        else:
            no_conflict.append(entry)

    return _build_report(groups, needs_action, uncertain, no_conflict)


def _build_report(groups, needs_action, uncertain, no_conflict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(groups)
    conflict_count = len(needs_action) + len(uncertain)

    lines = [
        "# 知识库矛盾自检报告",
        f"生成时间: {now}",
        f"扫描文档组: {total} 组",
        f"发现矛盾/待核实: {conflict_count} 处（需处理: {len(needs_action)} | 待核实: {len(uncertain)}）",
        "",
        "---",
        "",
    ]

    def _add_section(title_tag, entries):
        for e in entries:
            ver_str = " vs ".join(e["versions"])
            lines.append(f"## [{title_tag}] {e['base']}")
            lines.append(f"版本: {ver_str}")
            lines.append("")
            lines.append(e["llm_text"])
            if e.get("web_result"):
                lines.append("")
                lines.append("网络搜索参考:")
                lines.append(e["web_result"])
            lines.append("")
            lines.append("---")
            lines.append("")

    if needs_action:
        lines.append("# 需处理\n")
        _add_section("需处理", needs_action)

    if uncertain:
        lines.append("# 待核实\n")
        _add_section("待核实", uncertain)

    if no_conflict:
        lines.append("# 无矛盾（已确认）\n")
        _add_section("无矛盾", no_conflict)

    return "\n".join(lines)


def show_report_summary() -> str:
    """解析已有报告，返回摘要文本."""
    if not REPORT_PATH.exists():
        return "尚未生成自检报告。请运行: python3 kb_selfcheck.py"

    content = REPORT_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()

    summary = []
    for line in lines[:8]:
        summary.append(line)

    needs = [l for l in lines if l.startswith("## [需处理]")]
    uncertain = [l for l in lines if l.startswith("## [待核实]")]

    summary.append("")
    if needs:
        summary.append(f"需处理 ({len(needs)} 项):")
        for l in needs[:5]:
            summary.append(f"  {l[3:]}")
        if len(needs) > 5:
            summary.append(f"  ... 共 {len(needs)} 项")
    if uncertain:
        summary.append(f"待核实 ({len(uncertain)} 项):")
        for l in uncertain[:3]:
            summary.append(f"  {l[3:]}")
        if len(uncertain) > 3:
            summary.append(f"  ... 共 {len(uncertain)} 项")

    return "\n".join(summary)


# ── 主入口 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="知识库矛盾自检工具")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描 N 组（测试用）")
    parser.add_argument("--group", type=str, default=None, help="只扫描包含此关键词的文档组")
    parser.add_argument("--report", action="store_true", help="只显示已有报告摘要")
    args = parser.parse_args()

    if args.report:
        print(show_report_summary())
        return

    print("=" * 60)
    print("  知识库矛盾自检")
    print("=" * 60)

    t0 = time.time()
    report = run_selfcheck(limit=args.limit, group_filter=args.group)

    REPORT_PATH.write_text(report, encoding="utf-8")
    elapsed = time.time() - t0

    print(f"\n完成！耗时 {elapsed:.0f}s")
    print(f"报告已保存: {REPORT_PATH}")
    print()
    print(show_report_summary())


if __name__ == "__main__":
    main()
