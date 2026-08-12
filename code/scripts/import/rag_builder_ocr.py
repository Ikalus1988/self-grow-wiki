#!/usr/bin/env python3
"""RAG 知识库构建器 — OCR 增强版

与 rag_builder.py 的区别：
- 使用 PaddleOCR 对 PDF 中的图片区域进行 OCR 识别
- 保留原有的文本提取逻辑（pymupdf4llm）
- 合并 OCR 结果和原始文本
- 支持增量导入（不删除现有数据）
- 支持去重（检测已存在的文件，可选择跳过或替换）

使用:
  pip install paddlepaddle-gpu paddleocr pdf2image
  python3 rag_builder_ocr.py --source /path/to/pdfs --mode add
  python3 rag_builder_ocr.py --source /path/to/pdfs --mode replace --quality-check
"""

import os
import re
import json
import hashlib
import argparse
from pathlib import Path
from typing import List, Dict, Any

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ── 配置 ──────────────────────────────────────────────────────────────

CHROMA_DIR = Path("/home/eric_jia/rag_chromadb")
COLLECTION_NAME = "wiki_docs"
EMBEDDING_MODEL = "BAAI/bge-base-zh-v1.5"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
CHUNK_SEPARATORS = ["\n\n", "\n", "。", "；", " ", ""]

BATCH_SIZE = 256

# ── OCR 配置 ──────────────────────────────────────────────────────────

USE_OCR = True  # 是否启用 OCR
OCR_LANG = "ch"  # ch=中英文混合, en=英文
OCR_USE_GPU = True  # 是否使用 GPU 加速

# ── 工具函数 ──────────────────────────────────────────────────────────

def extract_text_with_ocr(pdf_path: str) -> str:
    """从 PDF 提取文本，包含 OCR 识别图片中的文字."""
    import fitz  # pymupdf

    # 先用 pymupdf4llm 提取文本层
    try:
        import pymupdf4llm
        text_layer = pymupdf4llm.to_markdown(pdf_path)
    except Exception as e:
        print(f"  pymupdf4llm 失败: {e}，回退到 pymupdf")
        doc = fitz.open(pdf_path)
        text_layer = "\n\n".join(page.get_text() for page in doc)
        doc.close()

    if not USE_OCR:
        return text_layer

    # OCR 识别图片区域
    try:
        from paddleocr import PaddleOCR
        from pdf2image import convert_from_path

        ocr = PaddleOCR(
            use_angle_cls=True,
            lang=OCR_LANG,
            use_gpu=OCR_USE_GPU,
            show_log=False,
        )

        # 转换 PDF 为图片（每页）
        images = convert_from_path(pdf_path, dpi=200, fmt='jpeg')

        ocr_texts = []
        for i, img in enumerate(images):
            # 保存临时图片
            tmp_img = f"/tmp/ocr_page_{i}.jpg"
            img.save(tmp_img, 'JPEG')

            # OCR 识别
            result = ocr.ocr(tmp_img, cls=True)
            if result and result[0]:
                page_text = "\n".join([line[1][0] for line in result[0]])
                ocr_texts.append(f"--- OCR Page {i+1} ---\n{page_text}")

            os.remove(tmp_img)

        ocr_layer = "\n\n".join(ocr_texts)

        # 合并文本层和 OCR 层
        combined = f"{text_layer}\n\n--- OCR 补充内容 ---\n\n{ocr_layer}"
        return combined

    except ImportError as e:
        print(f"  OCR 依赖缺失: {e}，跳过 OCR")
        return text_layer
    except Exception as e:
        print(f"  OCR 失败: {e}，返回原始文本")
        return text_layer


def chunk_text(text: str, source: str) -> List[Dict[str, Any]]:
    """将文本切分为 chunks."""
    if len(text) > 100000:
        text = text[:100000]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=CHUNK_SEPARATORS,
        length_function=len,
    )

    chunks = splitter.split_text(text)

    result = []
    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(source.encode()).hexdigest() + f"_{i}"
        result.append({
            "id": chunk_id,
            "text": chunk,
            "metadata": {
                "source": source,
                "filename": Path(source).name,
                "chunk_index": i,
                "total_chunks": len(chunks),
            }
        })

    return result


def get_existing_files(collection) -> Dict[str, List[str]]:
    """获取知识库中已存在的文件及其 chunk IDs."""
    # 分批扫描所有 metadata
    existing = {}
    offset = 0
    batch = 10000

    while True:
        try:
            result = collection.get(
                limit=batch,
                offset=offset,
                include=["metadatas"],
            )
            if not result["ids"]:
                break

            for chunk_id, meta in zip(result["ids"], result["metadatas"]):
                fn = meta.get("filename", "")
                if fn:
                    if fn not in existing:
                        existing[fn] = []
                    existing[fn].append(chunk_id)

            offset += batch

            if len(result["ids"]) < batch:
                break
        except Exception:
            break

    return existing


def quality_check_sample(old_chunks: List[str], new_chunks: List[Dict]) -> bool:
    """随机抽样对比新旧 chunks 质量.

    返回 True 表示新版本质量更好，应该替换.
    """
    import random

    if not old_chunks or not new_chunks:
        return True

    # 随机抽 3 个 chunk 对比
    sample_size = min(3, len(old_chunks), len(new_chunks))

    print(f"\n  质量对比（抽样 {sample_size} 个 chunks）:")

    for i in range(sample_size):
        old_idx = random.randint(0, len(old_chunks) - 1)
        new_idx = random.randint(0, len(new_chunks) - 1)

        old_text = old_chunks[old_idx][:200]
        new_text = new_chunks[new_idx]["text"][:200]

        print(f"\n  样本 {i+1}:")
        print(f"    旧: {old_text}...")
        print(f"    新: {new_text}...")

    answer = input("\n  新版本质量是否更好？(y/n): ").strip().lower()
    return answer == 'y'


def import_pdfs(
    source_dir: str,
    mode: str = "add",
    quality_check: bool = False,
    category: str = "FANUC机器人",
    subcategory: str = "维修手册",
):
    """导入 PDF 文件到知识库.

    Args:
        source_dir: PDF 文件目录
        mode: "add" (增量添加) 或 "replace" (替换已存在的)
        quality_check: 是否进行质量抽查（仅 mode=replace 时有效）
        category: 分类
        subcategory: 子分类
    """
    source_path = Path(source_dir)
    if not source_path.exists():
        print(f"错误: 目录不存在 {source_dir}")
        return

    pdf_files = list(source_path.glob("*.pdf")) + list(source_path.glob("*.PDF"))
    print(f"找到 {len(pdf_files)} 个 PDF 文件")

    if not pdf_files:
        return

    # 连接向量库
    print("连接向量库...")
    embedding_fn = SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device="cuda" if OCR_USE_GPU else "cpu",
    )

    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR),
        settings=Settings(anonymized_telemetry=False),
    )

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    # 获取已存在的文件
    print("扫描已存在的文件...")
    existing_files = get_existing_files(collection)
    print(f"知识库中已有 {len(existing_files)} 个文件")

    # 处理每个 PDF
    added_count = 0
    replaced_count = 0
    skipped_count = 0

    for pdf_file in pdf_files:
        filename = pdf_file.name
        print(f"\n处理: {filename}")

        # 检查是否已存在
        if filename in existing_files:
            if mode == "add":
                print(f"  跳过（已存在）")
                skipped_count += 1
                continue
            elif mode == "replace":
                print(f"  已存在，准备替换...")

                # 质量检查
                if quality_check:
                    # 读取旧 chunks
                    old_ids = existing_files[filename]
                    old_result = collection.get(ids=old_ids[:10], include=["documents"])
                    old_texts = old_result["documents"]

                    # 提取新文本并 chunk
                    print(f"  提取文本（含 OCR）...")
                    new_text = extract_text_with_ocr(str(pdf_file))
                    new_chunks = chunk_text(new_text, str(pdf_file))

                    # 质量对比
                    if not quality_check_sample(old_texts, new_chunks):
                        print(f"  用户选择保留旧版本，跳过")
                        skipped_count += 1
                        continue

                # 删除旧 chunks
                print(f"  删除旧版本 ({len(existing_files[filename])} chunks)...")
                collection.delete(ids=existing_files[filename])
                replaced_count += 1

        # 提取文本
        print(f"  提取文本（含 OCR）...")
        try:
            text = extract_text_with_ocr(str(pdf_file))
        except Exception as e:
            print(f"  提取失败: {e}")
            continue

        if not text.strip():
            print(f"  跳过（无文本）")
            continue

        # 切分 chunks
        print(f"  切分 chunks...")
        chunks = chunk_text(text, str(pdf_file))

        # 添加分类信息
        for c in chunks:
            c["metadata"]["category"] = category
            c["metadata"]["subcategory"] = subcategory
            c["metadata"]["file_type"] = "pdf"

        print(f"  生成 {len(chunks)} 个 chunks")

        # 批量插入
        print(f"  插入向量库...")
        for i in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[i:i+BATCH_SIZE]
            collection.add(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )

        if filename not in existing_files:
            added_count += 1

        print(f"  完成")

    print(f"\n导入完成:")
    print(f"  新增: {added_count}")
    print(f"  替换: {replaced_count}")
    print(f"  跳过: {skipped_count}")
    print(f"  总计: {collection.count()} vectors")


def main():
    parser = argparse.ArgumentParser(description="RAG 知识库 OCR 增强导入")
    parser.add_argument("--source", required=True, help="PDF 文件目录")
    parser.add_argument("--mode", choices=["add", "replace"], default="add",
                        help="add=增量添加, replace=替换已存在的")
    parser.add_argument("--quality-check", action="store_true",
                        help="替换前进行质量抽查（仅 mode=replace 时有效）")
    parser.add_argument("--category", default="FANUC机器人", help="分类")
    parser.add_argument("--subcategory", default="维修手册", help="子分类")

    args = parser.parse_args()

    import_pdfs(
        source_dir=args.source,
        mode=args.mode,
        quality_check=args.quality_check,
        category=args.category,
        subcategory=args.subcategory,
    )


if __name__ == "__main__":
    main()
