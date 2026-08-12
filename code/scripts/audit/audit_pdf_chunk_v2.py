"""
横展抽检 v2：语义级内容比对

对每份PDF随机取3段有实质内容的段落，
用段落文本搜索知识库（语义检索），
对比"这段话在PDF里"和"在chunk里"是否一致。

聚焦实质性差异：数值偏差、关键信息丢失、OCR导致语义变化。
"""

import sys, json, re, random, os
sys.path.insert(0, '/mnt/c/Users/Eric Jia/self-grow-wiki')
from rag_core import retrieve
from openai import OpenAI

random.seed(20260430)

LLM = OpenAI(
    api_key="sk-REPLACED",
    base_url="https://api.deepseek.com/v1"
)

def llm_audit(text):
    for attempt in range(2):
        try:
            resp = LLM.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "你是一个严谨的文档质量审计员。只输出JSON。"},
                          {"role": "user", "content": text}],
                temperature=0.05, max_tokens=600, timeout=20
            )
            import re, json
            m = re.search(r'\{[^{}]*\}', resp.choices[0].message.content, re.DOTALL)
            if m: return json.loads(m.group())
        except: pass
    return None

# 能找到的PDF
import fitz
found_pdfs = []
for subdir in ["07_机器人/FANUC PLUS 最新/PDF", "07_机器人", "01_PLC与控制/SICAR标准块文档", "05_驱动与传动/G120变频器", "02_制造标准"]:
    base = f"/mnt/d/知识库wiki/{subdir}"
    if os.path.isdir(base):
        for f in os.listdir(base):
            if f.endswith('.pdf') or f.endswith('.PDF'):
                found_pdfs.append(os.path.join(base, f))

print(f"找到 {len(found_pdfs)} 份PDF")
sample_pdfs = random.sample(found_pdfs, min(15, len(found_pdfs)))

audit_results = []

for pdf_path in sample_pdfs:
    fn = os.path.basename(pdf_path)
    print(f"\n{'='*60}")
    print(f"📄 {fn}")
    
    try:
        doc = fitz.open(pdf_path)
        total = len(doc)
        
        # 挑3个随机页，取实质性段落
        pages = random.sample(range(min(total, 300)), min(3, total))
        
        page_findings = []
        
        for pg in pages:
            text = doc[pg].get_text().strip()
            if len(text) < 100:
                continue
            
            # 取1-2个实质性段落（不含页码、页眉页脚）
            paragraphs = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 60]
            if not paragraphs:
                paragraphs = [text[:300]]
            
            for para in paragraphs[:2]:
                para_sample = para[:300]
                
                # 语义搜索知识库
                chunks = retrieve(para_sample, top_k=5)
                
                # 找到最匹配的chunk
                best_chunk = None
                best_score = 0
                for c in chunks:
                    # 计算简单匹配分
                    words_in_para = set(para_sample[:100])
                    words_in_chunk = set(c['text'][:500])
                    overlap = len(words_in_para & words_in_chunk)
                    score = overlap / max(len(words_in_para), 1)
                    if score > best_score:
                        best_score = score
                        best_chunk = c
                
                if best_chunk and best_score > 0.3:
                    # LLM对比
                    prompt = f"""对比"PDF原文"和"知识库Chunk"，判断知识库是否完整、准确地保留了原文信息。

PDF原文（{fn} 第{pg+1}页）：
{para_sample[:500]}

知识库Chunk（来源：{best_chunk.get('filename','?')}）：
{best_chunk['text'][:500]}

输出JSON：
{{
  "match": true/false,
  "issue_type": "无问题|数值偏差|OCR错误|上下文丢失|截断",
  "pdf_key_info": "PDF中的关键信息摘要（30字）",
  "chunk_missed": "chunk缺失或错误的关键信息（30字，无则空）",
  "severity": "无/轻微/中等/严重",
  "note": "具体说明（40字）"
}}
"""
                    verdict = llm_audit(prompt)
                    if verdict:
                        page_findings.append({
                            "page": pg+1,
                            **verdict
                        })
                        v = verdict.get("match", "?")
                        t = verdict.get("issue_type", "?")
                        if v != True or t != "无问题":
                            print(f"  Page {pg+1}: [{t}] {verdict.get('note','')[:60]}")
        
        doc.close()
        
        # 汇总
        issues = [f for f in page_findings if f.get("match") != True or f.get("issue_type") != "无问题"]
        status = "OK" if len(issues) == 0 else f"{len(issues)}个问题"
        print(f"  抽检 {len(page_findings)} 段, 状态: {status}")
        
        audit_results.append({
            "file": fn,
            "path": pdf_path,
            "pages": total,
            "checked_segments": len(page_findings),
            "issues": len(issues),
            "status": status,
            "details": page_findings
        })
        
    except Exception as e:
        print(f"  ❌ {e}")
        audit_results.append({"file": fn, "status": f"error: {e}"})

# 汇总
print("\n\n" + "="*60)
print("横展审计汇总")
print("="*60)

total_pdfs = len(audit_results)
total_segments = sum(r.get("checked_segments", 0) for r in audit_results)
total_issues = sum(r.get("issues", 0) for r in audit_results)
ok_pdfs = sum(1 for r in audit_results if r.get("status") == "OK")
issue_pdfs = sum(1 for r in audit_results if r.get("issues", 0) > 0)

print(f"抽检PDF: {total_pdfs}")
print(f"抽检段落: {total_segments}")
print(f"完全一致: {ok_pdfs}")
print(f"有问题: {issue_pdfs}")
print(f"总问题数: {total_issues}")
print(f"出问题率: {total_issues/max(total_segments,1)*100:.0f}%")

if issue_pdfs > 0:
    print(f"\n--- 问题清单 ---")
    severity_count = {}
    for r in audit_results:
        for d in r.get("details", []):
            t = d.get("issue_type", "?")
            s = d.get("severity", "?")
            key = f"{s}-{t}"
            severity_count[key] = severity_count.get(key, 0) + 1
            if d.get("match") != True:
                print(f"  [{s}/{t}] {r['file']} p{d['page']}")
                print(f"    PDF关键信息: {d.get('pdf_key_info','')[:50]}")
                if d.get('chunk_missed'):
                    print(f"    Chunk缺失: {d['chunk_missed'][:50]}")
    print(f"\n问题分布: {severity_count}")

with open("/tmp/pdf_chunk_audit_v2.json", "w") as f:
    json.dump(audit_results, f, ensure_ascii=False, indent=2)
print(f"\n✅ /tmp/pdf_chunk_audit_v2.json")
