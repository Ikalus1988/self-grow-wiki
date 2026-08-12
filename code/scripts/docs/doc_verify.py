#!/usr/bin/env python3
"""
文档鉴定工具 — 用知识库 wiki 内容核对文档的每个知识点。

用法:
  python3 doc_verify.py <文档文本文件路径>
  
对文档逐条提取知识点，检索知识库，LLM 判断一致性，生成鉴定报告。
"""

import sys
import re
import json
import time
import requests
from typing import List, Tuple, Dict

RAG_API = "http://localhost:8002/query"

# ============================================================
# 第一步：解析考试文档中的知识点声明
# ============================================================

def parse_claims(text: str) -> List[Dict]:
    """将考试文档解析为结构化声明列表"""
    claims = []
    
    lines = text.strip().split('\n')
    
    # 按题目类型分段
    sections = {
        "填空题": [],
        "判断题": [],
        "单选题": [],
        "多选题": [],
        "问答题": [],
        "选答题": []
    }
    
    current_section = None
    section_markers = {
        "填空题", "判断题", "单选题", "多选题", "问答题", "选答题"
    }
    
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        # Detect section header
        for marker in section_markers:
            if marker in line_stripped and len(line_stripped) < 30:
                current_section = marker
                break
        if current_section and line_stripped not in section_markers:
            sections[current_section].append(line_stripped)
    
    # 解析填空题
    for line in sections["填空题"]:
        # Lines like: "在复制程序时，写保护状态是否能被复制过来？（能）。"
        m = re.match(r'^[^.。]*[。.]?([^。]+[。.]?)$', line)
        if len(line) > 10 and ('（' in line or '(' in line):
            # Extract question and answer
            q = re.sub(r'[（(][^）)]*[）)]', '____', line)
            a_match = re.search(r'[（(]([^）)]+)[）)]', line)
            answer = a_match.group(1) if a_match else ""
            if answer:
                claims.append({
                    "type": "填空题",
                    "claim": q,
                    "doc_answer": answer,
                    "raw": line
                })
    
    # 解析判断题
    for line in sections["判断题"]:
        m = re.match(r'(\d+[.、])\s*(.+?)(?:[TtFf]|正确|错误|对|错)', line)
        if m:
            statement = m.group(2).strip()
            # Determine answer
            is_true = bool(re.search(r'[Tt]|正确|对', line[-10:]))
            claims.append({
                "type": "判断题",
                "claim": statement,
                "doc_answer": "正确" if is_true else "错误",
                "raw": line
            })
    
    # 解析单选题
    q_no = None
    for line in sections["单选题"]:
        m = re.match(r'(\d+)[.、]?\s*(.+)', line)
        if m:
            q_no = m.group(1)
            question_text = m.group(2).strip()
            # Check if answer is at end
            ans_match = re.search(r'[A-Ea-e]$', question_text)
            answer = ans_match.group(0).upper() if ans_match else ""
            if answer:
                q_clean = re.sub(r'\s*[A-Ea-e]$', '', question_text)
                claims.append({
                    "type": "单选题",
                    "claim": f"第{q_no}题: {q_clean}",
                    "doc_answer": f"选项{answer}",
                    "raw": line
                })
    
    # 解析多选题
    current_multi = None
    for line in sections["多选题"]:
        m = re.match(r'(\d+)[.、]?\s*(.+?)([A-D]+)$', line)
        if m:
            q_no = m.group(1)
            question_text = m.group(2).strip()
            answer = m.group(3)
            if len(answer) >= 2:
                claims.append({
                    "type": "多选题",
                    "claim": f"第{q_no}题: {question_text}",
                    "doc_answer": f"选项{'/'.join(answer)}",
                    "raw": line
                })
    
    # 问答题和选答题 - 作为整段描述处理
    for qa_type in ["问答题", "选答题"]:
        q_text = ""
        for line in sections[qa_type]:
            q_text += line + "\n"
        if q_text.strip():
            claims.append({
                "type": qa_type,
                "claim": q_text[:200],
                "doc_answer": q_text,
                "raw": q_text
            })
    
    return claims


# ============================================================
# 第二步：检索知识库
# ============================================================

def wiki_search(claim: str, top_k: int = 5) -> Dict:
    """通过 RAG API 检索知识库"""
    try:
        resp = requests.post(
            RAG_API,
            json={"query": claim, "top_k": top_k, "temperature": 0.1},
            timeout=30
        )
        data = resp.json()
        return data
    except Exception as e:
        return {"error": str(e), "answer": "", "sources": []}


def wiki_search_raw(claim: str, top_k: int = 10) -> list:
    """直接调用 rag_core.retrieve() 获取原始 chunks"""
    try:
        import sys as _sys
        _sys.path.insert(0, "/mnt/c/Users/Eric Jia/self-grow-wiki")
        from rag_core import retrieve
        chunks = retrieve(claim, top_k=top_k)
        return chunks
    except Exception as e:
        return [{"text": f"检索失败: {e}", "score": 0, "source": "error"}]


# ============================================================
# 第三步：LLM 判断一致性
# ============================================================

DEEPSEEK_KEY = _load_deepseek_key()
DEEPSEEK_API = "https://api.deepseek.com/v1"

def llm_verify(claim: str, doc_answer: str, wiki_context: str) -> Dict:
    """用 LLM 判断文档声明与知识库的一致性"""
    
    prompt = f"""你是一个工业自动化文档鉴定专家。你的任务是用知识库 wiki 内容核对文档中的声明。

【文档中的声明】
{claim}

【文档给出的答案】
{doc_answer}

【知识库相关上下文】
{wiki_context[:3000]}

请严格按以下格式输出鉴定结果（只输出 JSON 块，不要其他文字）：
{{
  "judgment": "一致|矛盾|存疑|信息不全",
  "reason": "简要说明判断理由（50字以内）",
  "wiki_evidence": "知识库中支持或矛盾的关键引文（不超过200字）",
  "confidence": "高|中|低"
}}

判断标准：
- 一致：文档答案与知识库内容完全吻合
- 矛盾：文档答案与知识库内容明显冲突
- 存疑：知识库中没有相关信息可用于验证
- 信息不全：知识库覆盖了部分内容，但文档缺少细节或知识库有补充信息
"""

    from openai import OpenAI
    client = OpenAI(api_key=_load_deepseek_key(), base_url=DEEPSEEK_API)
    
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是工业自动化文档鉴定专家。只输出 JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500,
            timeout=20
        )
        text = resp.choices[0].message.content.strip()
        # Extract JSON from response
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"judgment": "解析失败", "reason": "LLM返回格式异常", "wiki_evidence": text[:200], "confidence": "低"}
    except Exception as e:
        return {"judgment": "错误", "reason": str(e), "wiki_evidence": "", "confidence": "低"}


# ============================================================
# 第四步：生成鉴定报告
# ============================================================

def generate_report(verification_results: List[Dict], exam_text: str) -> str:
    """生成格式化鉴定报告"""
    
    lines = []
    lines.append("=" * 72)
    lines.append("📋 知识库鉴定报告")
    lines.append(f"文档: FANUC机器人理论考试（A卷带答案）")
    lines.append(f"鉴定时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"总知识点数: {len(verification_results)}")
    lines.append("=" * 72)
    
    # 统计
    stats = {"一致": 0, "矛盾": 0, "存疑": 0, "信息不全": 0, "错误": 0, "解析失败": 0}
    for r in verification_results:
        j = r.get("judgment", "未知")
        if j in stats:
            stats[j] += 1
        else:
            stats["存疑"] += 1
    
    lines.append(f"\n📊 鉴定统计")
    lines.append(f"  ✅ 一致: {stats['一致']}  ❌ 矛盾: {stats['矛盾']}  ⚠️ 存疑: {stats['存疑']}  ℹ️ 信息不全: {stats['信息不全']}")
    lines.append(f"  知识库覆盖率: {stats['一致'] + stats['信息不全']}/{len(verification_results)} ({(stats['一致']+stats['信息不全'])/max(len(verification_results),1)*100:.0f}%)")
    lines.append(f"  问题发现: {stats['矛盾'] + stats['存疑']}/{len(verification_results)}")
    
    # 按类型分组显示
    for r in verification_results:
        j = r.get("judgment", "存疑")
        icon = {"一致": "✅", "矛盾": "❌", "存疑": "⚠️", "信息不全": "ℹ️"}.get(j, "❓")
        
        lines.append(f"\n{icon} [{j}] {r.get('type', '?')}")
        lines.append(f"   声明: {r['claim'][:100]}")
        lines.append(f"   文档答案: {r['doc_answer'][:100]}")
        if r.get("wiki_sources"):
            lines.append(f"   知识库来源: {', '.join(r['wiki_sources'][:3])}")
        if r.get("reason"):
            lines.append(f"   判断: {r['reason'][:150]}")
    
    return "\n".join(lines)


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 72)
    print("📋 FANUC 考试文档知识库鉴定")
    print("=" * 72)
    
    # 读取文档
    pdf_path = "/mnt/c/Users/hp/Downloads/FANUC机器人理论考试（A卷带答案）.pdf"
    print(f"\n📄 读取文档: {pdf_path}")
    
    # 已预提取文本（WSL 下 fitz 针对此 PDF 挂起，已单独处理）
    with open("/tmp/exam_text.txt", "r", encoding="utf-8") as f:
        full_text = f.read()
    print(f"   读取预提取文本: {len(full_text)} 字符")
    
    # 解析声明
    print(f"\n🔍 解析知识点声明...")
    claims = parse_claims(full_text)
    print(f"   提取到 {len(claims)} 条声明")
    for c in claims:
        print(f"   [{c['type']}] {c['claim'][:60]} => {c['doc_answer'][:40]}")
    
    # 逐条验证
    print(f"\n🔎 逐条检索知识库验证...")
    results = []
    
    for i, c in enumerate(claims):
        print(f"\n   [{i+1}/{len(claims)}] {c['type']}: {c['claim'][:50]}...")
        
        # Step 1: 检索知识库
        try:
            chunks = wiki_search_raw(c['claim'], top_k=10)
        except Exception as e:
            print(f"     检索失败: {e}")
            results.append({**c, "judgment": "存疑", "reason": f"检索失败: {e}", 
                          "wiki_sources": [], "wiki_evidence": ""})
            continue
        
        # Format wiki context
        wiki_context = "\n---\n".join([
            f"[来源: {ch.get('source','?')}] {ch['text'][:500]}" 
            for ch in chunks[:5] if ch.get('text')
        ])
        
        wiki_sources = list(set(
            ch.get('source', ch.get('filename', '?')) 
            for ch in chunks[:5]
        ))
        
        # Step 2: LLM 鉴定
        try:
            verdict = llm_verify(c['claim'], c['doc_answer'], wiki_context)
        except Exception as e:
            print(f"     LLM鉴定失败: {e}")
            results.append({**c, "judgment": "存疑", "reason": f"LLM鉴定失败: {e}",
                          "wiki_sources": wiki_sources, "wiki_evidence": ""})
            continue
        
        print(f"     → {verdict.get('judgment', '?')}: {verdict.get('reason', '')[:80]}")
        
        results.append({
            **c,
            "judgment": verdict.get("judgment", "存疑"),
            "reason": verdict.get("reason", ""),
            "wiki_sources": wiki_sources,
            "wiki_evidence": verdict.get("wiki_evidence", ""),
            "confidence": verdict.get("confidence", "中")
        })
    
    # 生成报告
    print(f"\n{'=' * 72}")
    print(f"📊 生成鉴定报告...")
    
    report = generate_report(results, full_text)
    print("\n" + report[:2000])
    
    # 保存报告
    report_path = "/home/eric_jia/FANUC考试_知识库鉴定报告.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
        f.write("\n\n---\n\n## 详细鉴定记录\n\n")
        for r in results:
            f.write(f"### {r.get('judgment', '?')}: {r['claim'][:100]}\n")
            f.write(f"- 类型: {r['type']}\n")
            f.write(f"- 文档答案: {r['doc_answer'][:200]}\n")
            f.write(f"- 判断: {r.get('reason', '')}\n")
            if r.get("wiki_evidence"):
                f.write(f"- 知识库证据: {r['wiki_evidence'][:300]}\n")
            if r.get("wiki_sources"):
                f.write(f"- 来源: {', '.join(r['wiki_sources'][:5])}\n")
            f.write("\n")
    
    print(f"\n✅ 报告已保存: {report_path}")
    print(f"   总知识点: {len(results)}")
    print(f"   ✅ 一致: {sum(1 for r in results if r['judgment']=='一致')}")
    print(f"   ❌ 矛盾: {sum(1 for r in results if r['judgment']=='矛盾')}")
    print(f"   ⚠️ 存疑: {sum(1 for r in results if r['judgment']=='存疑')}")
    print(f"   ℹ️ 信息不全: {sum(1 for r in results if r['judgment']=='信息不全')}")


if __name__ == "__main__":
    main()
