#!/usr/bin/env python3
"""
生成完整试卷 v2 — 确保所有选择题有完整选项文本，格式供 doc_verify 解析。
"""
import sys, json, re
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

sys.path.insert(0, '/home/eric_jia/self-grow-wiki')
from rag_core import retrieve
from openai import OpenAI

KEY = _load_deepseek_key()
API = "https://api.deepseek.com/v1"

def wiki(topic, k=8):
    return [(c['text'][:500], c.get('source','?')) for c in retrieve(topic, top_k=k)]

def llm(prompt, sys_msg="只输出 JSON。"):
    try:
        client = OpenAI(api_key=KEY, base_url=API)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": sys_msg},
                      {"role": "user", "content": prompt}],
            temperature=0.2, max_tokens=2000, timeout=30
        )
        text = resp.choices[0].message.content.strip()
        m = re.search(r'\[.*\]|\{.*\}', text, re.DOTALL)
        return json.loads(m.group()) if m else None
    except Exception as e:
        print(f"  LLM error: {e}")
        return None

# 预置话题和对齐的检索
topics_fill = [
    ("FANUC 控制柜模式 操作 T1 T2 AUTO", 3),
    ("FANUC 安全信号 IMSTP 急停", 2),
    ("FANUC 坐标系 工具坐标", 2),
    ("FANUC 伺服焊枪 参数 配置", 3),
]
topics_judge = [
    ("FANUC 报警代码 SRVO 严重度", 3),
    ("FANUC 备份 还原 IMAGE 冷启动", 3),
]
topics_single = [
    ("FANUC 零点复归 mastering 原因 时机", 3),
    ("FANUC 位置寄存器 PR 要素", 2),
    ("FANUC 运动指令 关节 直线 圆弧", 2),
]
topics_multi = [
    ("FANUC 示教器 安全 编程 操作", 2),
]

results = {"填空题": [], "判断题": [], "单选题": [], "多选题": []}

for tlist, qtype in [
    (topics_fill, "填空题"),
    (topics_judge, "判断题"),
    (topics_single, "单选题"),
    (topics_multi, "多选题"),
]:
    for topic, count in tlist:
        chunks = wiki(topic)
        ctx = "\n---\n".join([f"[{s}]\n{t}" for t, s in chunks[:6]])
        
        if qtype == "填空题":
            prompt = f"""根据以下知识库，生成{count}道FANUC机器人填空题（每题1空）。
要求：答案必须是知识库中的确切术语或数值。

知识库：
{ctx[:2500]}

输出格式：JSON数组
[{{"question":"题目文本，用____表示填空","answer":"正确答案文本"}}]
"""
        elif qtype == "判断题":
            prompt = f"""根据以下知识库，生成{count}道FANUC机器人判断题。
要求：用知识库内容判断对错，答案只能是 T 或 F。

知识库：
{ctx[:2500]}

输出格式：
[{{"question":"题目陈述文本","answer":"T或F"}}]
"""
        elif qtype == "单选题":
            prompt = f"""根据以下知识库，生成{count}道FANUC机器人单选题。
要求：
1. 每道题4个选项 A/B/C/D
2. 题目文本中**必须包含完整的选项内容**，例如"以下哪个选项正确的是？A)xxx B)xxx C)xxx D)xxx"
3. 答案必须是选项字母

知识库：
{ctx[:2500]}

输出格式：
[{{"question":"完整题目文本（含A/B/C/D选项）","answer":"A或B或C或D"}}]
"""
        elif qtype == "多选题":
            prompt = f"""根据以下知识库，生成{count}道FANUC机器人多选题。
要求：
1. 每道题4个选项 A/B/C/D，需选择2个以上正确答案
2. 题目文本中必须包含完整选项内容
3. 答案是字母组合

知识库：
{ctx[:2500]}

输出格式：
[{{"question":"完整题目文本（含A/B/C/D选项）","answer":"ABC或ABD等"}}]
"""
        
        print(f"\n[{qtype}] {topic}...")
        qs = llm(prompt)
        if qs:
            results[qtype].extend(qs)
            for q in qs:
                print(f"  {q['question'][:70]} => {q.get('answer','?')[:20]}")
        else:
            print(f"  ⚠️ 生成失败")

# 问答题 - 直接用
faq_chunks = wiki("FANUC 零点复归 mastering 原因", 6)
faq_ctx = "\n".join([t for t, s in faq_chunks[:4]])
faq_prompt = f"""根据以下知识库，生成1道简答题的标准答案（80-120字）。
问题：简述FANUC机器人零点复归（Mastering）的作用和必须重新执行的几种情况。

知识库：
{faq_ctx[:2000]}

输出：{{"answer":"标准答案"}}
"""
faq_res = llm(faq_prompt)

backup_chunks = wiki("FANUC IMAGE 备份 控制启动", 6)
backup_ctx = "\n".join([t for t, s in backup_chunks[:4]])
backup_prompt = f"""根据以下知识库，生成1道简答题的标准答案（80-120字）。
问题：简述FANUC机器人控制柜IMAGE备份的正确步骤。

知识库：
{backup_ctx[:2000]}

输出：{{"answer":"标准答案"}}
"""
backup_res = llm(backup_prompt)

# ============ 输出试卷 ============
lines = []
lines.append("# FANUC机器人理论考试（B卷带答案）")
lines.append("---")
lines.append(f"来源: FANUC官方手册知识库（230858向量）")
lines.append("---\n")

# 填空题
if results["填空题"]:
    lines.append("## 一、填空题（每空2分，共20分）")
    for i, q in enumerate(results["填空题"]):
        lines.append(f"{i+1}. {q['question']}")
    lines.append("")
    lines.append("答案：")
    for i, q in enumerate(results["填空题"]):
        lines.append(f"{i+1}. {q['answer']}")
    lines.append("")

# 判断题
if results["判断题"]:
    lines.append("---")
    lines.append("## 二、判断题（每题1分，共10分，正确T/错误F）")
    for i, q in enumerate(results["判断题"]):
        lines.append(f"{i+1}. {q['question']}")
    lines.append("")
    lines.append("答案：")
    for i, q in enumerate(results["判断题"]):
        lines.append(f"{i+1}. {q['answer']}")
    lines.append("")

# 单选题
if results["单选题"]:
    lines.append("---")
    lines.append("## 三、单选题（每题2分，共14分）")
    for i, q in enumerate(results["单选题"]):
        lines.append(f"{i+1}. {q['question']}")
    lines.append("")
    lines.append("答案：")
    for i, q in enumerate(results["单选题"]):
        lines.append(f"{i+1}. {q['answer']}")
    lines.append("")

# 多选题
if results["多选题"]:
    lines.append("---")
    lines.append("## 四、多选题（每题3分，共6分，多选少选不得分）")
    for i, q in enumerate(results["多选题"]):
        lines.append(f"{i+1}. {q['question']}")
    lines.append("")
    lines.append("答案：")
    for i, q in enumerate(results["多选题"]):
        lines.append(f"{i+1}. {q['answer']}")
    lines.append("")

# 问答题
lines.append("---")
lines.append("## 五、简答题（每题10分，共20分）")
if faq_res:
    lines.append(f"\n1. 简述FANUC机器人零点复归（Mastering）的作用和必须重新执行的几种情况。")
    lines.append(f"\n答案：{faq_res['answer']}")
if backup_res:
    lines.append(f"\n2. 简述FANUC机器人控制柜IMAGE备份的正确步骤。")
    lines.append(f"\n答案：{backup_res['answer']}")

# 保存 markdown
exam_md = "\n".join(lines)
with open("/home/eric_jia/FANUC考试_B卷_基于知识库.md", "w", encoding="utf-8") as f:
    f.write(exam_md)

# 也生成纯文本版（给 doc_verify 用）
plain = []
plain.append("FANUC机器人理论考试（B卷带答案）")
plain.append("")
# 填空题
if results["填空题"]:
    plain.append("填空题：")
    for i, q in enumerate(results["填空题"]):
        plain.append(f"{i+1}. {q['question']}  ({q['answer']})")
    plain.append("")
# 判断题
if results["判断题"]:
    plain.append("判断题：")
    for i, q in enumerate(results["判断题"]):
        plain.append(f"{i+1}. {q['question']}  {q['answer']}")
    plain.append("")
# 单选题
if results["单选题"]:
    plain.append("单选题：")
    for i, q in enumerate(results["单选题"]):
        plain.append(f"{i+1}. {q['question']}  {q['answer']}")
    plain.append("")
# 多选题
if results["多选题"]:
    plain.append("多选题：")
    for i, q in enumerate(results["多选题"]):
        plain.append(f"{i+1}. {q['question']}  {q['answer']}")
    plain.append("")
# 问答题
plain.append("问答题：")
if faq_res:
    plain.append(f"1. 简述FANUC机器人零点复归（Mastering）的作用和必须重新执行的几种情况。  答案：{faq_res['answer'][:100]}")
if backup_res:
    plain.append(f"2. 简述FANUC机器人控制柜IMAGE备份的正确步骤。  答案：{backup_res['answer'][:100]}")

plain_text = "\n".join(plain)
with open("/tmp/exam_b.txt", "w", encoding="utf-8") as f:
    f.write(plain_text)

print("\n" + "=" * 72)
print("✅ 试卷已生成!")
print(f"   Markdown: /home/eric_jia/FANUC考试_B卷_基于知识库.md")
print(f"   纯文本: /tmp/exam_b.txt")
total = sum(len(v) for v in results.values())
for k, v in results.items():
    print(f"   {k}: {len(v)}题")
print(f"   问答题: 2题")
print(f"   总分: {len(results['填空题'])*2 + len(results['判断题'])*1 + len(results['单选题'])*2 + len(results['多选题'])*3 + 20}")
