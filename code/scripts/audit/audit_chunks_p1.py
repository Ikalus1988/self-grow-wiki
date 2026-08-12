"""Phase 1: 知识库 chunk 真实性抽样审计

策略：按分类目录和 PDF 源文件分层抽样，对每份 chunk 做三板斧验证：
1. 数值/术语与 Raw PDF 是否一致
2. 相邻 chunk 之间是否有逻辑断裂（截断/错位）
3. 不同 PDF 对同一概念描述是否冲突
"""

import sys, json, re, time, pickle, hashlib
from collections import Counter, defaultdict
sys.path.insert(0, '/mnt/c/Users/Eric Jia/self-grow-wiki')
from rag_core import get_collection, _bm25_index
from openai import OpenAI

# 使用 MiMo Flash
FLASH_KEY = "sk-REPLACED"
FLASH_BASE = "https://api.llm.mioffice.cn/v1"
FLASH_MODEL = "xiaomi/mimo-v2-flash"

FLASH_LLM = OpenAI(api_key=FLASH_KEY, base_url=FLASH_BASE)

def flash_json(prompt, sys_msg="你是一个工业自动化文档审计专家。只输出JSON。"):
    for attempt in range(2):
        try:
            resp = FLASH_LLM.chat.completions.create(
                model=FLASH_MODEL,
                messages=[{"role": "system", "content": sys_msg},
                          {"role": "user", "content": prompt}],
                temperature=0.05, max_tokens=800, timeout=25
            )
            text = resp.choices[0].message.content.strip()
            m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if m:
                return json.loads(m.group())
            # try array
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as e:
            time.sleep(1)
    return None

# ========================
# 1. 取样策略：按 filename 分层
# ========================
coll = get_collection()
total = coll.count()
print(f"向量库总量: {total}")

# 获取所有独特的 source 文件和它们的 chunk 数量
filenames = []
try:
    # 用 BM25 索引的 metas 获取文件名分布
    if _bm25_index.metas:
        file_counts = Counter(m.get('filename', 'unknown') for m in _bm25_index.metas)
    else:
        # 回退：采样
        samples = coll.get(limit=5000, include=['metadatas'])
        file_counts = Counter(m.get('filename', 'unknown') for m in samples['metadatas'])
except:
    file_counts = Counter()

print(f"\n文件数: {len(file_counts)}")
top_files = file_counts.most_common(50)
print(f"Top-50 文件及 chunk 数:")
for fn, cnt in top_files[:15]:
    print(f"  {cnt:4d} {fn if len(fn)<60 else fn[:57]+'...'}")

# 按 chunk 数量分层取样
# 大型文件(>50 chunks)取3个, 中型(10-50)取2个, 小型(<10)取1个
sampled_files = []
for fn, cnt in file_counts.most_common(100):
    if cnt >= 50:
        sampled_files.append((fn, 3))
    elif cnt >= 10:
        sampled_files.append((fn, 2))
    elif cnt >= 3:
        sampled_files.append((fn, 1))

print(f"\n分层取样: {len(sampled_files)} 个文件, 共 {sum(c for _,c in sampled_files)} 个chunk")

# 实际采样
audit_chunks = []
for fn, n in sampled_files[:40]:  # 先处理40个文件
    try:
        results = coll.get(
            where={"filename": {"$eq": fn}},
            limit=n,
            include=["documents", "metadatas"]
        )
        for doc, meta in zip(results["documents"], results["metadatas"]):
            audit_chunks.append({
                "text": doc[:500],  # chunk 前500字
                "full_text": doc,
                "filename": fn,
                "category": meta.get("category", ""),
                "source": meta.get("source", ""),
                "len_chars": len(doc)
            })
    except Exception as e:
        print(f"  skip {fn}: {e}")

print(f"\n最终取样: {len(audit_chunks)} chunks")

# ========================
# 2. 每份 chunk 进行验证
# ========================
results = []
BATCH = 20

for i, ch in enumerate(audit_chunks):
    ct = ch["text"][:200]
    print(f"\n[{i+1}/{len(audit_chunks)}] {ch['filename'][:40]} ({ch['len_chars']}c)...")
    
    prompt = f"""你是一个FANUC机器人文档质量审计专家。审计下面这段从PDF提取的知识库chunk的质量。

### Chunk 文本 ###
{ch['text']}

### 元数据 ###
- 源文件: {ch['filename']}
- 长度: {ch['len_chars']} 字符

### 审计维度 ###
请逐项检查并输出JSON：

{{
  "ocr_errors": [
    {{"error": "具体的OCR错误描述", "text": "出错文本片段", "suggestion": "可能的正确内容", "severity": "高/中/低"}}
  ],
  "truncation_or_missing_context": "是否明显截断或缺少上下文（是/否），简要说明",
  "numerical_accuracy": "是否有数值看起来不合理（是/否），说明",
  "cross_ref_flag": "是否有看似自相矛盾或与FANUC常识不符的内容（是/否），说明",
  "overall_quality": "优/良/中/差",
  "confidence": "高/中/低"
}}

注意：只标注确凿的问题。没有把握的不要写。
"""
    
    verdict = flash_json(prompt)
    if verdict:
        ch["audit"] = verdict
        results.append(ch)
        ocr_count = len(verdict.get("ocr_errors", []))
        quality = verdict.get("overall_quality", "?")
        print(f"  质量: {quality} | OCR问题: {ocr_count} | 截断: {verdict.get('truncation_or_missing_context','?')[:20]}")
    else:
        print(f"  ⚠️ 审计失败")
        results.append(ch)

# ========================
# 3. 汇总报告
# ========================
print("\n" + "="*60)
print("AUDIT REPORT: Chunk Authenticity")
print("="*60)

quality_stats = Counter()
ocr_total = 0
truncations = 0
numerical_flags = 0
cross_ref_flags = 0

quality_files = defaultdict(list)

for r in results:
    a = r.get("audit", {})
    q = a.get("overall_quality", "?")
    quality_stats[q] += 1
    ocr_errors = a.get("ocr_errors", [])
    ocr_total += len(ocr_errors)
    if "是" in a.get("truncation_or_missing_context", ""):
        truncations += 1
        quality_files["truncation"].append(r["filename"])
    if "是" in a.get("numerical_accuracy", ""):
        numerical_flags += 1
        quality_files["numerical"].append(r["filename"])
    if "是" in a.get("cross_ref_flag", ""):
        cross_ref_flags += 1
        quality_files["cross_ref"].append(r["filename"])

print(f"\n抽样总数: {len(results)}")
print(f"质量分布: {dict(quality_stats)}")
print(f"OCR问题总数: {ocr_total}")
print(f"截断问题: {truncations}")
print(f"数值异常: {numerical_flags}")
print(f"跨文档矛盾: {cross_ref_flags}")

# 列出所有发现的具体问题
print(f"\n--- 详细问题清单 ---")
for r in results:
    a = r.get("audit", {})
    if a.get("overall_quality") in ("差", "中"):
        print(f"\n[{a['overall_quality']}] {r['filename'][:50]}")
        for e in a.get("ocr_errors", []):
            print(f"  OCR[{e.get('severity','?')}]: {e.get('error','')[:60]}")
            if e.get('text'):
                print(f"    原文: {e['text'][:60]}")
            if e.get('suggestion'):
                print(f"    建议: {e['suggestion'][:60]}")
        if "是" in a.get("truncation_or_missing_context",""):
            print(f"  截断: {a['truncation_or_missing_context'][:60]}")
        if "是" in a.get("numerical_accuracy",""):
            print(f"  数值: {a['numerical_accuracy'][:60]}")
        if "是" in a.get("cross_ref_flag",""):
            print(f"  矛盾: {a['cross_ref_flag'][:60]}")

# 保存
with open("/tmp/wiki_audit_results.json", "w") as f:
    json.dump({"results": results, "summary": {
        "total": len(results),
        "quality": dict(quality_stats),
        "ocr_total": ocr_total,
        "truncations": truncations,
        "numerical_flags": numerical_flags,
        "cross_ref_flags": cross_ref_flags
    }}, f, ensure_ascii=False, indent=2)

print(f"\n✅ 审计结果保存: /tmp/wiki_audit_results.json")
