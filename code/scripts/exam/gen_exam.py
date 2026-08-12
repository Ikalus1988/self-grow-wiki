#!/usr/bin/env python3
"""
根据知识库 wiki 内容生成 FANUC 机器人理论考试试卷。

流程:
1. 对每个话题从 wiki 检索具体内容
2. 根据内容生成题目 + 正确答案
3. 所有答案必须能从 wiki 内容直接验证
4. 输出标准试卷格式
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

sys.path.insert(0, '/mnt/c/Users/Eric Jia/self-grow-wiki')
from rag_core import retrieve
from openai import OpenAI
import json
import re
import time

DEEPSEEK_KEY = _load_deepseek_key()
DEEPSEEK_API = "https://api.deepseek.com/v1"

def wiki_get(topic: str, top_k: int = 8) -> list:
    """从知识库检索内容"""
    return retrieve(topic, top_k=top_k)

def gen_questions(topic: str, wiki_text: str, q_type: str, count: int = 3) -> list:
    """让 LLM 根据 wiki 内容生成题目+答案"""
    
    type_desc = {
        "填空题": "填空题（fill-in-the-blank）：用____表示填空位置，答案写在后面的括号里",
        "判断题": "判断题（True/False）：在描述末尾标注 T 或 F",
        "单选题": "单选题：给出4个选项 A)~D)，在末尾标注正确答案字母",
        "多选题": "多选题：给出4~5个选项，在末尾标注所有正确选项字母",
    }
    
    prompt = f"""你是工业自动化培训考试出题专家。根据以下知识库内容，生成 {count} 道{type_desc[q_type]}。

知识库内容（FANUC 机器人官方手册）：
{wiki_text[:3000]}

要求：
1. 每道题的答案必须能从上述知识库内容中**直接找到证据**
2. 题目要覆盖不同知识点，不要重复
3. 难度适中（中级工程师水平）
4. 答案必须是{count}选{count}中的唯一正确答案（来自知识库）
5. 使用中文出题

输出格式：每道题一行 JSON：
{{"question": "题目文本", "answer": "正确答案"}}

直接输出 JSON 数组，不要其他文字。
"""
    try:
        client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_API)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "你是工业自动化考试出题专家。只输出 JSON 数组。"},
                      {"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=1500, timeout=30
        )
        text = resp.choices[0].message.content.strip()
        # Extract JSON array
        arr_match = re.search(r'\[.*\]', text, re.DOTALL)
        if arr_match:
            return json.loads(arr_match.group())
        return []
    except Exception as e:
        print(f"  [错误] 出题失败: {e}")
        return []


def main():
    print("=" * 72)
    print("📝 FANUC 机器人理论考试试卷生成（基于知识库）")
    print("=" * 72)
    
    # 话题列表 + 各题型出题数
    topics = [
        ("FANUC 控制柜模式 T1 T2 AUTO 安全信号 IMSTP", "填空题", 4),
        ("FANUC 报警代码 SRVO 类型 处理", "判断题", 5),
        ("FANUC 坐标系 工具坐标 用户坐标 世界坐标", "填空题", 3),
        ("FANUC 零点复归 mastering 校准", "单选题", 4),
        ("FANUC 位置寄存器 PR 运算", "选择题混出", 4),
        ("FANUC 伺服焊枪 配置 参数 SPOT", "填空题", 3),
        ("FANUC 备份 还原 IMAGE 文件", "判断题", 3),
        ("FANUC 运动指令 关节 直线 圆弧", "单选题", 4),
        ("FANUC 示教器 操作 安全 编程", "多选题", 4),
        ("FANUC 伺服焊枪 Auto Tune 压力标定", "填空题", 2),
    ]
    
    all_questions = {
        "填空题": [],
        "判断题": [],
        "单选题": [],
        "多选题": [],
    }
    
    for topic, q_type, count in topics:
        print(f"\n📖 检索: {topic}...")
        chunks = wiki_get(topic, top_k=8)
        if not chunks or not chunks[0].get('text'):
            print(f"  ⚠️ 无结果，跳过")
            continue
        
        wiki_text = "\n---\n".join([
            f"[{ch.get('source','?')}] {ch['text'][:600]}"
            for ch in chunks[:6]
        ])
        
        print(f"  检索到 {len(chunks)} 个片段...")
        
        # 根据类型分配到对应题目列表
        if "填空" in q_type:
            target = "填空题"
        elif "判断" in q_type:
            target = "判断题"
        elif "单选" in q_type or "选择" in q_type:
            # 按题目类型分配
            if any(kw in topic for kw in ["零点", "运动指令"]):
                target = "单选题"
            elif any(kw in topic for kw in ["位置寄存器"]):
                target = "单选题"
            else:
                target = "多选题"
        else:
            print(f"  ⚠️ 未知题型: {q_type}")
            continue
        
        mapped_type = "填空题" if "填空" in q_type else ("判断题" if "判断" in q_type else 
                     ("单选题" if "单选" in q_type or target == "单选题" else "多选题"))
        
        questions = gen_questions(topic, wiki_text, mapped_type, count)
        if questions:
            all_questions[mapped_type].extend(questions)
            print(f"  ✅ 生成 {len(questions)} 道{mapped_type}")
            for q in questions:
                print(f"    {q['question'][:60]} => {q['answer'][:30]}")
    
    # ============ 输出试卷 ============
    print("\n" + "=" * 72)
    print("📋 FANUC机器人理论考试（B卷 — 基于知识库）")
    print("=" * 72)
    
    total = sum(len(v) for v in all_questions.values())
    
    lines = []
    lines.append("# FANUC机器人理论考试（B卷）")
    lines.append("")
    lines.append("---")
    lines.append(f"生成来源: 知识库 wiki（230858向量，FANUC官方手册）")
    lines.append(f"题目总数: {total}")
    lines.append("---\n")
    
    # 填空题
    fill_questions = all_questions["填空题"]
    if fill_questions:
        lines.append("## 一、填空题（每空1分）")
        for i, q in enumerate(fill_questions):
            lines.append(f"{i+1}. {q['question']}")
        lines.append("")
        lines.append("**答案：**")
        for i, q in enumerate(fill_questions):
            lines.append(f"{i+1}. {q['answer']}")
        lines.append("")
    
    # 判断题
    judge_questions = all_questions["判断题"]
    if judge_questions:
        lines.append("---")
        lines.append("## 二、判断题（每题1分，正确T，错误F）")
        for i, q in enumerate(judge_questions):
            lines.append(f"{i+1}. {q['question']}")
        lines.append("")
        lines.append("**答案：**")
        for i, q in enumerate(judge_questions):
            lines.append(f"{i+1}. {q['answer']}")
        lines.append("")
    
    # 单选题
    single_questions = all_questions["单选题"]
    if single_questions:
        lines.append("---")
        lines.append("## 三、单选题（每题1分）")
        for i, q in enumerate(single_questions):
            lines.append(f"{i+1}. {q['question']}")
        lines.append("")
        lines.append("**答案：**")
        for i, q in enumerate(single_questions):
            lines.append(f"{i+1}. {q['answer']}")
        lines.append("")
    
    # 多选题
    multi_questions = all_questions["多选题"]
    if multi_questions:
        lines.append("---")
        lines.append("## 四、多选题（每题2分，多选或少选不得分）")
        for i, q in enumerate(multi_questions):
            lines.append(f"{i+1}. {q['question']}")
        lines.append("")
        lines.append("**答案：**")
        for i, q in enumerate(multi_questions):
            lines.append(f"{i+1}. {q['answer']}")
        lines.append("")
    
    # 五、问答题（用单独检索）
    print("\n📖 检索问答题话题...")
    essay_topics = [
        ("FANUC 零点复归 步骤 为什么 需要做", "简述FANUC机器人为什么需要进行零点复归（Mastering）？什么情况下需要重新做零点复归？"),
        ("FANUC IMAGE 备份 还原 步骤", "简述FANUC机器人控制柜IMAGE备份的步骤。"),
    ]
    
    lines.append("---")
    lines.append("## 五、问答题（每题10分）")
    
    for i, (topic, question) in enumerate(essay_topics):
        chunks = wiki_get(topic, top_k=6)
        wiki_ctx = "\n".join([c['text'][:300] for c in chunks[:4]])
        
        prompt = f"""根据以下知识库内容，生成一道问答题的标准答案（80-150字）。

问题：{question}

知识库内容：
{wiki_ctx[:2000]}

输出 JSON：{{"answer": "标准答案内容"}}
"""
        try:
            client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_API)
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "只输出 JSON。"},
                          {"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=500, timeout=20
            )
            text = resp.choices[0].message.content.strip()
            jm = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            answer = json.loads(jm.group())["answer"] if jm else "（基于知识库编写）"
        except Exception as e:
            answer = f"（基于知识库编写）"
        
        lines.append(f"\n**{i+1}. {question}**")
        lines.append("")
        lines.append("**答案：**")
        lines.append(answer)
    
    # 保存试卷
    exam_text = "\n".join(lines)
    with open("/home/eric_jia/FANUC考试_B卷_基于知识库.md", "w", encoding="utf-8") as f:
        f.write(exam_text)
    
    # 同时生成纯文本版（给 doc_verify 用）
    plain_lines = []
    plain_lines.append("FANUC机器人理论考试（B卷带答案）")
    plain_lines.append("")
    
    for q_type, label, ans_label in [
        ("填空题", "填空题：", None),
        ("判断题", "判断题：", None),
        ("单选题", "单选题：", None),
        ("多选题", "多选题：", None),
    ]:
        qs = all_questions[q_type]
        if qs:
            plain_lines.append(label)
            for i, q in enumerate(qs):
                plain_lines.append(f"{i+1}. {q['question']}  {q['answer']}")
            plain_lines.append("")
    
    # 问答题
    plain_lines.append("问答题：")
    for i, (topic, question) in enumerate(essay_topics):
        plain_lines.append(f"{i+1}. {question}")
    plain_lines.append("")
    
    plain_text = "\n".join(plain_lines)
    with open("/tmp/exam_b.txt", "w", encoding="utf-8") as f:
        f.write(plain_text)
    
    print("\n" + "=" * 72)
    print(f"✅ 试卷已生成!")
    print(f"   Markdown版: /home/eric_jia/FANUC考试_B卷_基于知识库.md")
    print(f"   纯文本版: /tmp/exam_b.txt")
    print(f"   题目总数: {total}")
    for k, v in all_questions.items():
        print(f"   {k}: {len(v)}题")
    print(f"   问答题: {len(essay_topics)}题")
    print("=" * 72)


if __name__ == "__main__":
    main()
