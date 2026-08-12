#!/usr/bin/env python3
"""RAG 知识库增量导入工具 — FANUC 文档更新版

功能:
- 增量导入新 PDF 到知识库
- 检测已存在的同名文件，自动跳过或替换（同文件名新版本替换旧版本）
- 检测同系列不同版本（如 B-83684CM_05 vs _06），替换为更新版本
- 随机抽检质量对比

使用:
  python3 rag_import_fanuc.py                # 增量导入新文件
  python3 rag_import_fanuc.py --replace-old  # 替换旧版本为新版本
  python3 rag_import_fanuc.py --dry-run      # 只看变更不执行
"""

import os
import re
import hashlib
import random
import logging
from pathlib import Path
from typing import List, Dict, Tuple

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fanuc_import")

# ── 配置 ──────────────────────────────────────────────────────────────

CHROMA_DIR = Path("/home/eric_jia/rag_chromadb")
COLLECTION_NAME = "wiki_docs"
EMBEDDING_MODEL = "BAAI/bge-base-zh-v1.5"

SOURCE_DIR = Path("/mnt/d/知识库wiki/07_机器人/FANUC PLUS 最新/PDF")

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
CHUNK_SEPARATORS = ["\n\n", "\n", "。", "；", " ", ""]
MAX_TEXT_LEN = 100000

CATEGORY = "FANUC机器人"
SUBCATEGORY = ""
BATCH_SIZE = 256


# ── 工具函数 ──────────────────────────────────────────────────────────

def extract_text(pdf_path: str) -> str:
    """用 pymupdf4llm 提取 PDF 文本."""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(pdf_path)
    except Exception as e:
        log.warning("pymupdf4llm 失败: %s, 回退到 pymupdf", e)
        import fitz
        doc = fitz.open(pdf_path)
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text


def chunk_text(text: str, source: str, filename: str) -> List[Dict]:
    """切分文本为 chunks."""
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=CHUNK_SEPARATORS,
    )
    parts = splitter.split_text(text)

    chunks = []
    src_hash = hashlib.md5(source.encode()).hexdigest()
    for i, part in enumerate(parts):
        chunks.append({
            "id": f"{src_hash}_{i}",
            "text": part,
            "metadata": {
                "source": source,
                "filename": filename,
                "category": CATEGORY,
                "subcategory": SUBCATEGORY,
                "file_type": "pdf",
                "chunk_index": i,
                "total_chunks": len(parts),
            },
        })
    return chunks


def parse_doc_id(filename: str) -> Tuple[str, int]:
    """从文件名提取文档编号基础部分和版本号.

    B-83684CM_06.PDF → ('B-83684CM', 6)
    B-82135CM_07_01.PDF → ('B-82135CM', 7)
    """
    stem = Path(filename).stem  # B-83684CM_06
    # 匹配 B-XXXXX[XX]_NN[_NN]
    m = re.match(r'^(B-\d{4,5}[A-Z]{0,4})_(\d{2})', stem)
    if m:
        return m.group(1), int(m.group(2))
    return stem, 0


def scan_existing_files(collection) -> Dict[str, List[str]]:
    """扫描知识库中所有文件及其 chunk IDs."""
    existing = {}
    offset = 0
    batch = 10000

    while True:
        result = collection.get(limit=batch, offset=offset, include=["metadatas"])
        if not result["ids"]:
            break

        for cid, meta in zip(result["ids"], result["metadatas"]):
            fn = meta.get("filename", "")
            if fn:
                existing.setdefault(fn, []).append(cid)

        if len(result["ids"]) < batch:
            break
        offset += batch

    return existing


def quality_spot_check(collection, old_ids: List[str], new_chunks: List[Dict], filename: str):
    """随机抽检对比新旧 chunk 质量."""
    sample_n = min(3, len(old_ids), len(new_chunks))
    if sample_n == 0:
        return

    old_sample_ids = random.sample(old_ids, min(sample_n, len(old_ids)))
    old_result = collection.get(ids=old_sample_ids, include=["documents"])

    new_sample = random.sample(new_chunks, sample_n)

    log.info("质量抽检 [%s] — %d 个样本:", filename, sample_n)
    for i in range(sample_n):
        old_text = old_result["documents"][i][:200] if i < len(old_result["documents"]) else "(无)"
        new_text = new_sample[i]["text"][:200]
        log.info("  样本%d 旧: %s...", i+1, old_text[:80])
        log.info("  样本%d 新: %s...", i+1, new_text[:80])


def main():
    import argparse
    parser = argparse.ArgumentParser(description="FANUC 文档增量导入")
    parser.add_argument("--replace-old", action="store_true", help="替换旧版本文档")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划不执行")
    parser.add_argument("--spot-check", type=int, default=3, help="质量抽检数量 (0=不抽检)")
    args = parser.parse_args()

    # 扫描新文件
    pdf_files = sorted(SOURCE_DIR.glob("*.PDF")) + sorted(SOURCE_DIR.glob("*.pdf"))
    log.info("新文件目录: %s, 共 %d 个 PDF", SOURCE_DIR, len(pdf_files))

    # 连接向量库
    log.info("连接向量库...")
    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL, device="cuda",
    )
    client = chromadb.PersistentClient(str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))
    collection = client.get_or_create_collection(
        COLLECTION_NAME, embedding_function=embedding_fn, metadata={"hnsw:space": "cosine"},
    )
    log.info("当前向量库: %d vectors", collection.count())

    # 扫描已有文件
    log.info("扫描已有文件...")
    existing = scan_existing_files(collection)
    log.info("已有 %d 个文件", len(existing))

    # 建立旧版本索引: doc_base → {filename: version}
    old_versions = {}
    for fn in existing:
        base, ver = parse_doc_id(fn)
        old_versions.setdefault(base, {})[fn] = ver

    # 建立新文件版本索引: doc_base → [(pdf_path, version)]
    new_versions = {}
    for pdf in pdf_files:
        base, ver = parse_doc_id(pdf.name)
        new_versions.setdefault(base, []).append((pdf, ver))

    # 分类新文件
    to_add = []       # 全新文件
    to_replace = []   # 新版本替换旧版本 (new_file, old_filenames)
    to_skip = []      # 完全相同或非最新版，跳过

    for base, candidates in new_versions.items():
        # 同 base 多版本只保留最新
        candidates.sort(key=lambda x: x[1], reverse=True)
        best_pdf, best_ver = candidates[0]
        fn = best_pdf.name

        # 其余版本跳过
        for pdf, ver in candidates[1:]:
            to_skip.append(pdf.name)

        if fn in existing:
            to_skip.append(fn)
            continue

        if base in old_versions and args.replace_old:
            old_fns = old_versions[base]
            max_old_ver = max(old_fns.values())
            if best_ver > max_old_ver:
                to_replace.append((best_pdf, list(old_fns.keys())))
            else:
                to_skip.append(fn)
        elif base in old_versions:
            to_skip.append(fn)
        else:
            to_add.append(best_pdf)

    log.info("\n=== 导入计划 ===")
    log.info("新增: %d 个文件", len(to_add))
    log.info("替换旧版: %d 个文件", len(to_replace))
    log.info("跳过: %d 个文件", len(to_skip))

    if to_replace:
        log.info("\n替换详情:")
        for new_pdf, old_fns in to_replace:
            old_str = ", ".join(old_fns)
            log.info("  %s → 替换 %s", new_pdf.name, old_str)

    if args.dry_run:
        log.info("\n[DRY RUN] 不执行任何操作")
        return

    # 执行导入
    added = 0
    replaced = 0
    spot_checked = 0

    # 1. 替换旧版本
    for new_pdf, old_fns in to_replace:
        fn = new_pdf.name
        log.info("\n替换: %s", fn)

        # 提取新文本
        log.info("  提取文本...")
        text = extract_text(str(new_pdf))
        if not text.strip():
            log.warning("  无文本，跳过")
            continue

        new_chunks = chunk_text(text, str(new_pdf), fn)
        log.info("  生成 %d 个 chunks", len(new_chunks))

        # 质量抽检
        if args.spot_check > 0 and spot_checked < args.spot_check:
            for old_fn in old_fns:
                if old_fn in existing:
                    quality_spot_check(collection, existing[old_fn], new_chunks, fn)
                    spot_checked += 1
                    break

        # 删除旧版本
        for old_fn in old_fns:
            if old_fn in existing:
                old_ids = existing[old_fn]
                log.info("  删除旧版 %s (%d chunks)", old_fn, len(old_ids))
                # ChromaDB delete 限制每次最多 ~40000
                for i in range(0, len(old_ids), 5000):
                    collection.delete(ids=old_ids[i:i+5000])

        # 插入新版本
        log.info("  插入新版本...")
        for i in range(0, len(new_chunks), BATCH_SIZE):
            batch = new_chunks[i:i+BATCH_SIZE]
            collection.add(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )
        replaced += 1

    # 2. 新增文件
    for pdf in to_add:
        fn = pdf.name
        log.info("\n新增: %s", fn)

        text = extract_text(str(pdf))
        if not text.strip():
            log.warning("  无文本，跳过")
            continue

        new_chunks = chunk_text(text, str(pdf), fn)
        log.info("  生成 %d 个 chunks", len(new_chunks))

        for i in range(0, len(new_chunks), BATCH_SIZE):
            batch = new_chunks[i:i+BATCH_SIZE]
            collection.add(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )
        added += 1

    log.info("\n=== 导入完成 ===")
    log.info("新增: %d, 替换: %d, 跳过: %d", added, replaced, len(to_skip))
    log.info("向量库总数: %d", collection.count())


if __name__ == "__main__":
    main()
