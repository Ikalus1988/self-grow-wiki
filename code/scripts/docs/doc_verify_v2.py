#!/usr/bin/env python3
"""
文档鉴定工具 v2 — 用知识库 wiki 内容核对文档的每个知识点。

v2 修复：
- 判断题：不直接问"声明是否匹配知识库"，而是问"知识库认为声明真伪"，再对比文档答案
- 填空题：合并多行属于同一题的声明
- LLM prompt：明确区分 T/F 判断逻辑
"""

import sys
# C1: 密钥改从环境变量 / ~/.hermes/.env 读取 (评审修复)
import os as _os
def _load_deepseek_key():
    k = _os.environ.get('DEEPSEEK_API_KEY', '')
    if k:
        return k
    p = _os.path.expanduser('~/.hermes/.env')
    if _os.path.exists(p):
        for l in open(p):
            l = l.strip()
            if l.startswith('DEEPSEEK_API_KEY='):
                return l.split('=', 1)[1].strip().strip('"').strip("'")
    return ''

import re
import json
import time
from typing import List, Dict

# ============================================================
# 第一步：解析考试文档中的知识点声明
# ============================================================

def parse_claims(text: str) -> List[Dict]:
    """将考试文档解析为结构化声明列表"""
    claims = []
    
    lines = text.strip().split('\n')
    
    sections = {
        "填空题": [], "判断题": [], "单选题": [],
        "多选题": [], "问答题": [], "选答题": []
    }
    
    current_section = None
    section_markers = {"填空题", "判断题", "单选题", "多选题", "问答题", "选答题"}
    
    for line in lines:
        ls = line.strip()
        if not ls:
            continue
        for marker in section_markers:
            if marker in ls and len(ls) < 30:
                current_section = marker
                break
        if current_section and ls not in section_markers:
            sections[current_section].append(line)
    
    # ── 填空题：合并跨行 ──
    merged_fill = []
    buf = ""
    for line in sections["填空题"]:
        if buf and re.match(r'^\s*[（(]', line):
            buf += line
        else:
            if buf:
                merged_fill.append(buf)
            buf = line
    if buf:
        merged_fill.append(buf)
    
    # 提取填空：每个完整行作为一个知识点
    for line in merged_fill:
        if len(line) < 10:
            continue
        # 提取所有括号中的答案
        bracket_answers = re.findall(r'[（(]([^）)]+)[）)]', line)
        # 提取所有括号前的空白占位
        question = re.sub(r'[（(][^）)]*[）)]', '____', line).strip()
        if bracket_answers:
            claims.append({
                "type": "填空题",
                "claim": question,
                "doc_answer": " / ".join(a.strip() for a in bracket_answers),
                "raw": line
            })
    
    # ── 判断题：提取声明 + T/F 答案 ──
    for line in sections["判断题"]:
        # 匹配: "序号. 声明 T/F"
        m = re.match(r'(\d+[.、]?)\s*(.+?)\s*([TFtf]|正确|错误|对|错)\s*$', line.strip())
        if not m:
            continue
        statement = m.group(2).strip()
        answer_raw = m.group(3).strip()
        is_true = answer_raw.upper() == 'T' or answer_raw in ('正确', '对')
        
        claims.append({
            "type": "判断题",
            "claim": statement,
            "doc_answer": "T" if is_true else "F",
            "doc_answer_cn": "正确" if is_true else "错误",
            "raw": line
        })
    
    # ── 单选题 ──
    for line in sections["单选题"]:
        m = re.match(r'(\d+)[.、]?\s*(.+)', line)
        if not m:
            continue
        q_no = m.group(1)
        text = m.group(2).strip()
        ans_match = re.search(r'\s([A-Ea-e])\s*$', text)
        if not ans_match:
            continue
        answer = ans_match.group(1).upper()
        q_clean = re.sub(r'\s*[A-Ea-e]\s*$', '', text)
        claims.append({
            "type": "单选题",
            "claim": f"第{q_no}题: {q_clean}",
            "doc_answer": f"选项{answer}",
            "raw": line
        })
    
    # ── 多选题 ──
    for line in sections["多选题"]:
        m = re.match(r'(\d+)[.、]?\s*(.+?)\s*([A-Da-d]{2,})\s*$', line)
        if not m:
            continue
        q_no = m.group(1)
        text = m.group(2).strip()
        answer = m.group(3).upper()
        claims.append({
            "type": "多选题",
            "claim": f"第{q_no}题: {text}",
            "doc_answer": f"选项{'/'.join(answer)}",
            "raw": line
        })
    
    # ── 问答题和选答题 ──
    for qa_type in ["问答题", "选答题"]:
        q_text = "\n".join(sections[qa_type]).strip()
        if q_text:
            claims.append({
                "type": qa_type,
                "claim": q_text[:150],
                "doc_answer": q_text[:500],
                "raw": q_text
            })
    
    return claims


# ============================================================
# 第二步：检索知识库
# ============================================================

def wiki_search_raw(claim: str, top_k: int = 10) -> list:
    try:
        import sys as _sys
        _sys.path.insert(0, "/mnt/c/Users/Eric Jia/self-grow-wiki")
        from rag_core import retrieve
        return retrieve(claim, top_k=top_k)
    except Exception as e:
        return [{"text": f"检索失败: {e}", "score": 0, "source": "error"}]


# ============================================================
# 第三步：LLM 判断一致性（分题型）
# ============================================================

DEEPSEEK_KEY = _load_deepseek_key()
DEEPSEEK_API = "https://api.deepseek.com/v1"


def llm_verify(claim: dict, wiki_context: str) -> Dict:
    """根据题型用不同的验证策略"""
    
    ctype = claim["type"]
    
    if ctype == "判断题":
        return _llm_verify_judgment(claim, wiki_context)
    elif ctype == "填空题":
        return _llm_verify_fill(claim, wiki_context)
    else:
        return _llm_verify_generic(claim, wiki_context)


def _llm_verify_judgment(c: dict, wiki_context: str) -> Dict:
    """判断题验证：先查知识库判断声明真伪，再比对文档答案"""
    
    prompt = f"""你是工业自动化文档鉴定专家。你的任务是：先根据知识库判断声明的真伪，再与文档答案比对。

### 题目声明 ###
{c['claim']}

### 文档答案 ###
文档说这道题的答案是: {c['doc_answer_cn']}（{'T=True=正确' if c['doc_answer']=='T' else 'F=False=错误'}）

### 知识库相关上下文（从 FANUC 官方手册/技术资料中检索） ###
{wiki_context[:2500]}

### 你的任务 ###
1. 先凭你的工业自动化知识，结合知识库上下文，判断这个声明本身是 True（正确）还是 False（错误）
2. 然后对比：文档答案和你的判断是否一致

### 输出格式（严格 JSON，不要其他文字） ###
{{
  "statement_is_true": true 或 false,
  "wiki_evidence": "知识库中支撑判断的关键引文（80字以内）",
  "match": true 或 false,
  "judgment": "一致" 或 "矛盾",
  "reason": "判断理由（40字以内）"
}}

判断标准：
- statement_is_true=true & 文档答案是 T → match=true → judgment="一致"
- statement_is_true=false & 文档答案是 F → match=true → judgment="一致" 
- statement_is_true=true & 文档答案是 F → match=false → judgment="矛盾"
- statement_is_true=false & 文档答案是 T → match=false → judgment="矛盾"
"""
    
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_API)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是工业自动化文档鉴定专家。只输出 JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1, max_tokens=500, timeout=20
        )
        text = resp.choices[0].message.content.strip()
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            # 标准化 judgment 字段
            j = result.get("judgment", "存疑")
            if j not in ("一致", "矛盾", "存疑", "信息不全"):
                j = "存疑"
            return {
                "judgment": j,
                "reason": result.get("reason", ""),
                "wiki_evidence": result.get("wiki_evidence", ""),
                "confidence": "高" if result.get("match") is not None else "中"
            }
        return {"judgment": "存疑", "reason": "LLM返回格式异常", "wiki_evidence": text[:200], "confidence": "低"}
    except Exception as e:
        return {"judgment": "存疑", "reason": str(e), "wiki_evidence": "", "confidence": "低"}


def _llm_verify_fill(c: dict, wiki_context: str) -> Dict:
    """填空题验证"""
    prompt = f"""你是工业自动化文档鉴定专家。对比文档答案和知识库内容。

### 题目 ###
{c['claim']}

### 文档答案 ###
{c['doc_answer']}

### 知识库相关上下文 ###
{wiki_context[:2500]}

### 输出 ###
{{
  "judgment": "一致|矛盾|存疑|信息不全",
  "reason": "简要说明（40字以内）",
  "wiki_evidence": "知识库中支撑判断的关键引文（80字以内）"
}}

- 一致：答案和知识库完全吻合
- 矛盾：答案和知识库明显冲突
- 存疑：知识库无相关信息
- 信息不全：知识库有但不精确，或答案不完整
"""
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_API)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是工业自动化文档鉴定专家。只输出 JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1, max_tokens=500, timeout=20
        )
        text = resp.choices[0].message.content.strip()
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"judgment": "存疑", "reason": "LLM返回格式异常", "wiki_evidence": "", "confidence": "低"}
    except Exception as e:
        return {"judgment": "存疑", "reason": str(e), "wiki_evidence": "", "confidence": "低"}


def _llm_verify_generic(c: dict, wiki_context: str) -> Dict:
    """选/问答题和其他题型验证"""
    prompt = f"""你是工业自动化文档鉴定专家。核对文档内容与知识库是否一致。

### 文档问题 ###
{c['claim'][:200]}

### 文档答案 ###
{c['doc_answer'][:300]}

### 知识库相关上下文 ###
{wiki_context[:2000]}

### 输出 ###
{{
  "judgment": "一致|矛盾|存疑|信息不全",
  "reason": "简要说明（40字以内）",
  "wiki_evidence": "关键引文（80字以内）"
}}
"""
    from openai import OpenAI
    client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_API)
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是工业自动化文档鉴定专家。只输出 JSON。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1, max_tokens=500, timeout=20
        )
        text = resp.choices[0].message.content.strip()
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return {"judgment": "存疑", "reason": "LLM返回格式异常", "wiki_evidence": "", "confidence": "低"}
    except Exception as e:
        return {"judgment": "存疑", "reason": str(e), "wiki_evidence": "", "confidence": "低"}


# ============================================================
# 第四步：报告生成
# ============================================================

def generate_report(results: List[Dict]) -> str:
    lines = []
    lines.append("=" * 72)
    lines.append("📋 知识库鉴定报告 v2")
    lines.append("文档: FANUC机器人理论考试（A卷带答案）")
    lines.append(f"鉴定时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"总知识点数: {len(results)}")
    lines.append("=" * 72)
    
    stats = {"一致": 0, "矛盾": 0, "存疑": 0, "信息不全": 0}
    for r in results:
        j = r.get("judgment", "存疑")
        if j in stats:
            stats[j] += 1
    
    covered = stats["一致"] + stats["信息不全"]
    pct = covered / max(len(results), 1) * 100
    
    lines.append(f"\n📊 鉴定统计")
    lines.append(f"  ✅ 一致: {stats['一致']}  ❌ 矛盾: {stats['矛盾']}  ⚠️ 存疑: {stats['存疑']}  ℹ️ 信息不全: {stats['信息不全']}")
    lines.append(f"  知识库覆盖率: {covered}/{len(results)} ({pct:.0f}%)")
    lines.append(f"  问题发现: {stats['矛盾'] + stats['存疑']}/{len(results)}")
    
    for r in results:
        j = r.get("judgment", "存疑")
        icon = {"一致": "✅", "矛盾": "❌", "存疑": "⚠️", "信息不全": "ℹ️"}.get(j, "❓")
        lines.append(f"\n{icon} [{j}] {r.get('type', '?')}")
        lines.append(f"   声明: {r['claim'][:100]}")
        lines.append(f"   文档答案: {r['doc_answer'][:100]}")
        if r.get("wiki_sources"):
            lines.append(f"   来源: {', '.join(r['wiki_sources'][:3])}")
        if r.get("reason"):
            lines.append(f"   判断: {r['reason'][:150]}")
    
    return "\n".join(lines)


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 72)
    print("📋 FANUC 考试文档知识库鉴定 v2")
    print("=" * 72)
    
    with open("/tmp/exam_text.txt", "r", encoding="utf-8") as f:
        full_text = f.read()
    print(f"\n📄 读取文档: {len(full_text)} 字符")
    
    print(f"\n🔍 解析知识点...")
    claims = parse_claims(full_text)
    print(f"   提取到 {len(claims)} 条声明")
    for c in claims:
        ans = c['doc_answer'][:35]
        print(f"   [{c['type']}] {c['claim'][:55]} => {ans}")
    
    print(f"\n🔎 逐条检索知识库验证...")
    results = []
    
    for i, c in enumerate(claims):
        print(f"\n   [{i+1}/{len(claims)}] {c['type']}: {c['claim'][:45]}...")
        
        try:
            chunks = wiki_search_raw(c['claim'], top_k=8)
        except Exception as e:
            print(f"     检索失败: {e}")
            results.append({**c, "judgment": "存疑", "reason": f"检索失败: {e}",
                          "wiki_sources": [], "wiki_evidence": ""})
            continue
        
        wiki_context = "\n---\n".join([
            f"[来源: {ch.get('source','?')}] {ch['text'][:400]}"
            for ch in chunks[:5] if ch.get('text')
        ])
        
        wiki_sources = list(set(
            ch.get('source', ch.get('filename', '?'))
            for ch in chunks[:5]
        ))
        
        try:
            verdict = llm_verify(c, wiki_context)
        except Exception as e:
            print(f"     LLM鉴定失败: {e}")
            results.append({**c, "judgment": "存疑", "reason": f"LLM鉴定失败: {e}",
                          "wiki_sources": wiki_sources, "wiki_evidence": ""})
            continue
        
        print(f"     → {verdict.get('judgment', '?')}: {verdict.get('reason', '')[:60]}")
        
        results.append({
            **c,
            "judgment": verdict.get("judgment", "存疑"),
            "reason": verdict.get("reason", ""),
            "wiki_sources": wiki_sources,
            "wiki_evidence": verdict.get("wiki_evidence", ""),
            "confidence": verdict.get("confidence", "中")
        })
    
    # 报告
    print(f"\n{'=' * 72}")
    report = generate_report(results)
    print("\n" + report[:1500])
    
    report_path = "/home/eric_jia/FANUC考试_知识库鉴定报告_v2.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
        f.write("\n\n---\n\n## 详细鉴定记录\n\n")
        for r in results:
            j = r.get("judgment", "?")
            icon = {"一致": "✅", "矛盾": "❌", "存疑": "⚠️", "信息不全": "ℹ️"}.get(j, "❓")
            f.write(f"### {icon} [{j}] {r['claim'][:100]}\n")
            f.write(f"- 类型: {r['type']}\n")
            f.write(f"- 文档答案: {r['doc_answer'][:200]}\n")
            f.write(f"- 判断: {r.get('reason', '')}\n")
            if r.get("wiki_evidence"):
                f.write(f"- 知识库证据: {r['wiki_evidence'][:300]}\n")
            if r.get("wiki_sources"):
                f.write(f"- 来源: {', '.join(r['wiki_sources'][:5])}\n")
            if r.get("confidence"):
                f.write(f"- 置信度: {r['confidence']}\n")
            f.write("\n")
    
    print(f"\n✅ 报告已保存: {report_path}")
    print(f"   总知识点: {len(results)}")
    print(f"   ✅ 一致: {sum(1 for r in results if r['judgment']=='一致')}")
    print(f"   ❌ 矛盾: {sum(1 for r in results if r['judgment']=='矛盾')}")
    print(f"   ⚠️ 存疑: {sum(1 for r in results if r['judgment']=='存疑')}")
    print(f"   ℹ️ 信息不全: {sum(1 for r in results if r['judgment']=='信息不全')}")


if __name__ == "__main__":
    main()
