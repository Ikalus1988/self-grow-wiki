"""
横展抽检：对随机PDF源文件 vs 知识库chunk做逐页逐句比对。

策略：
1. 从wiki已入库文件中随机抽 12 份（分层：FANUC手册/PLC标准/安全/Siemens等）
2. 对每份PDF打开源文件，取 2-3 个关键页
3. 从知识库中检索同一PDF的对应chunk
4. 逐行比对：OCR误差/截断/错位/信息丢失
5. 输出结构化报告
"""

import sys, json, re, random, hashlib
sys.path.insert(0, '/mnt/c/Users/Eric Jia/self-grow-wiki')
from rag_core import get_collection, _bm25_index

random.seed(42)
coll = get_collection()

# 1. 获取所有文件名及其chunk数
from collections import Counter
if _bm25_index.metas:
    file_counts = Counter(m.get('filename', 'unknown') for m in _bm25_index.metas)
else:
    sample = coll.get(limit=5000, include=['metadatas'])
    file_counts = Counter(m.get('filename', 'unknown') for m in sample['metadatas'])

print(f"总共 {len(file_counts)} 个文件")

# 2. 按类别分层抽样
# 挑12份PDF，确保覆盖不同类别
target_files = [
    # FANUC 核心手册
    ("B-83284CM_07.PDF", None),      # FANUC 操作手册
    ("B-83264CM_05.PDF", None),      # 伺服焊枪
    ("B-83284CM-1_08.PDF", None),    # 报警代码
    ("B-83184CM_09.PDF", None),      # 安全手册
    ("B-80687CM_16.PDF", None),      # 控制装置
    # 其他类别
    ("观致汽车焊装车间FANUC Robot系统培训手册.pdf", None),
    ("FANUC_spot+说明书.pdf", None),
    ("FANUC中文手册_Jia.pdf", None),
    ("零位校正及坐标系标定.pdf", None),
    ("SICAR_Conventions.pdf", None),
    ("G120_CU250S-2_List_Manual_LH15_0414_eng.pdf", None),
    ("3HAC16590-10_revP_zh.pdf", None),
]

# 3. 对每份PDF找chunk
import fitz
import os

report = []

for fn, _ in target_files:
    print(f"\n{'='*60}")
    print(f"抽检文件: {fn}")
    
    # Find the PDF file on disk
    pdf_path = None
    for root, dirs, files in os.walk("/mnt/d/知识库wiki/"):
        if fn in files:
            pdf_path = os.path.join(root, fn)
            break
    # Also check FANUC PLUS PDF dir
    if not pdf_path:
        pdf_path = f"/mnt/d/知识库wiki/07_机器人/FANUC PLUS 最新/PDF/{fn}"
        if not os.path.exists(pdf_path):
            # Try with different extensions or names
            for root, dirs, files in os.walk("/mnt/d/知识库wiki/"):
                for f in files:
                    if fn.lower() in f.lower() or f.lower() in fn.lower():
                        pdf_path = os.path.join(root, f)
                        break
                if pdf_path:
                    break
    
    if not pdf_path or not os.path.exists(pdf_path):
        print(f"  ❌ PDF文件未找到: {fn}")
        report.append({"file": fn, "status": "not_found"})
        continue
    
    print(f"  PDF路径: {pdf_path}")
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        print(f"  总页数: {total_pages}")
        
        # 取 2 页：靠近开头和中间
        pages_to_check = [0, min(total_pages//2, total_pages-1)]
        if total_pages > 5:
            pages_to_check = [0, total_pages//3, min(total_pages*2//3, total_pages-1)]
        
        page_issues = []
        
        for pg in pages_to_check[:3]:
            text = doc[pg].get_text()
            if not text.strip():
                continue
            
            # 去除非文本页
            text_len = len(text.strip())
            if text_len < 50:
                continue
            
            # 取该页前500字作为"原文样本"
            sample_raw = text[:500].strip()
            
            # 从知识库搜索该页内容
            content_hash = hashlib.md5(sample_raw[:200].encode()).hexdigest()[:8]
            
            # 直接在知识库中搜索该PDF的chunks
            try:
                results = coll.get(
                    where={"filename": {"$eq": fn}},
                    limit=20,
                    include=["documents", "metadatas"]
                )
                chunks = results["documents"]
                metas = results["metadatas"]
            except:
                chunks, metas = [], []
            
            # 找包含该页面内容的chunk
            found = False
            for ci, (chunk, meta) in enumerate(zip(chunks, metas)):
                # 用原文长句匹配
                search_key = sample_raw[50:150].strip()  # 取中间一段
                if search_key in chunk:
                    found = True
                    # 对比
                    raw_lines = sample_raw.split('\n')
                    chunk_match = chunk[:len(sample_raw)]
                    
                    # 逐字符比较差异
                    diffs = []
                    min_len = min(len(sample_raw), len(chunk_match))
                    for ci2 in range(min_len):
                        if sample_raw[ci2] != chunk_match[ci2]:
                            # 上下文
                            start = max(0, ci2-5)
                            end = min(len(sample_raw), ci2+10)
                            diffs.append({
                                "pos": ci2,
                                "pdf_char": sample_raw[ci2],
                                "chunk_char": chunk_match[ci2],
                                "context_pdf": sample_raw[start:end],
                                "context_chunk": chunk_match[start:end],
                            })
                            if len(diffs) >= 5:
                                break
                    
                    if diffs:
                        page_issues.append({
                            "page": pg + 1,
                            "issues": len(diffs),
                            "samples": diffs[:3],
                            "chunk_len": len(chunk),
                            "pdf_len": text_len,
                        })
                    break
            
            if not found:
                page_issues.append({
                    "page": pg + 1,
                    "issues": -1,  # not found
                    "note": "该页内容在知识库chunks中未找到精确匹配"
                })
        
        doc.close()
        
        # 汇总此文件的发现
        total_issues = sum(pi.get("issues", 0) if pi.get("issues", 0) > 0 else 0 for pi in page_issues)
        not_found = sum(1 for pi in page_issues if pi.get("issues") == -1)
        
        status = "OK" if total_issues == 0 and not_found == 0 else "有差异" if total_issues > 0 else "部分未命中"
        print(f"  抽检 {len(page_issues)} 页, 字符差异: {total_issues}, 未命中: {not_found} → {status}")
        
        for pi in page_issues:
            if pi.get("issues", 0) > 0:
                print(f"    Page {pi['page']}: {pi['issues']}处差异")
                for s in pi.get("samples", []):
                    print(f"      PDF: ...{s['context_pdf']}...")
                    print(f"      Chunk: ...{s['context_chunk']}...")
            elif pi.get("issues") == -1:
                print(f"    Page {pi['page']}: 未在chunks中找到匹配")
        
        report.append({
            "file": fn,
            "pdf_path": pdf_path,
            "pages": total_pages,
            "checked_pages": len(page_issues),
            "not_found_pages": not_found,
            "diff_count": total_issues,
            "page_details": page_issues,
            "status": status
        })
        
    except Exception as e:
        print(f"  ❌ 打开失败: {e}")
        report.append({"file": fn, "status": "error", "error": str(e)})

# 汇总
print("\n" + "="*60)
print("抽检汇总")
print("="*60)
ok_count = sum(1 for r in report if r.get("status") == "OK")
diff_count = sum(1 for r in report if r.get("status") == "有差异")
miss_count = sum(1 for r in report if r.get("status") == "部分未命中")
err_count = sum(1 for r in report if r.get("status") in ("error", "not_found"))

total_diffs = sum(r.get("diff_count", 0) for r in report)
print(f"抽检文件: {len(report)}")
print(f"  完全一致(OK): {ok_count}")
print(f"  有字符差异: {diff_count}")
print(f"  部分页面未命中: {miss_count}")
print(f"  打开失败/未找到: {err_count}")
print(f"  总字符差异数: {total_diffs}")

# 差异详情
print("\n--- 差异详情 ---")
for r in report:
    if r.get("diff_count", 0) > 0:
        print(f"\n[{r['status']}] {r['file']}")
        for pd in r.get("page_details", []):
            if pd.get("issues", 0) > 0:
                print(f"  第{pd['page']}页 ({pd['issues']}处)")
                for s in pd.get("samples", []):
                    print(f"    PDF: ...{s['context_pdf']}...")
                    print(f"    Chk: ...{s['context_chunk']}...")
    elif r.get("status") == "部分未命中":
        print(f"\n[部分未命中] {r['file']}")
        for pd in r.get("page_details", []):
            if pd.get("issues") == -1:
                print(f"  第{pd['page']}页: {pd.get('note','')}")

# 保存
with open("/tmp/pdf_chunk_audit.json", "w") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print(f"\n✅ 审计结果: /tmp/pdf_chunk_audit.json")
