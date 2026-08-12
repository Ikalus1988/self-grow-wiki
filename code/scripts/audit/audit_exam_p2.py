"""
Phase 2: 试卷生成复盘审计

对B卷每道题追溯源chunk，逐项检验：
- 溯源：找到LLM生成时参考的源chunk
- 验真：chunk内容与题目答案是否一致
- 分类：准确 / 幻觉 / 遗漏 / 张冠李戴
"""

import sys, json, re, time
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
from rag_core import retrieve, _normalize_query, get_collection
from openai import OpenAI

LLM = OpenAI(
    api_key=_load_deepseek_key(),
    base_url="https://api.deepseek.com/v1"
)

# B卷全部题目及答案
exam_qs = {
    "填空题": [
        ("使用示教器模式切换功能时，切换模式需要输入密码，初始密码为____。", "1111"),
        ("在T1模式下，机器人工具中心点和手腕法兰盘中心点的速度限制为低于____mm/s。", "250"),
        ("共享示教器功能中，共享组内最多可注册____台控制装置。", "16"),
        ("*IMSTP信号是通过____控制的信号，不宜用于以安全为目的的处理。", "软件"),
        ("SRVO-206报警中，示教器有效时，虽然松开了或者用力按下了安全开关，但未切断____线路。", "急停"),
        ("FANUC机器人位置数据中，标准的位置数据使用____坐标。", "笛卡尔"),
        ("在FANUC机器人工具坐标系序号中，使用机械界面坐标系时，序号应设为____。", "0"),
        ("在伺服焊枪输出配置中，需要针对每把焊枪进行____。", "输出配置"),
        ("伺服焊枪基本规格中，焊枪轴速度设定范围是0－____［mm/sec］。", "2000"),
        ("在点焊配置移植实用工具画面中，将光标指向'配置输出'的行，按下____键。", "ENTER"),
    ],
    "判断题": [
        ("报警代码SRVO-001的报警严重度为SERVO，发生该报警时机器人会减速停止并断开伺服电源。", "T"),
        ("报警画面自动显示功能在系统/配置画面中默认设定为有效。", "F"),
        ("报警ID'SRVO'对应的数值为11，在错误代码输出功能中通过DO[1]至DO[8]的二进制组合输出。", "T"),
        ("执行冷启动时，需要在按住示教操作盘的PREV键和NEXT键的状态下接通控制装置的电源断路器。", "T"),
        ("自动备份功能最多可以设置10个备份时间。", "F"),
        ("恢复图像备份时，在同时按住F1和F2键的状态下接通机器人电源，可以选择从存储卡或以太网恢复。", "T"),
    ],
    "单选题": [
        ("根据FANUC机器人零点标定相关知识，以下哪个选项是必须执行零点标定的情况？A)机器人正常关机后重新开机 B)机器人执行初始化启动导致Mastering数据丢失 C)机器人更换了工具 D)机器人程序被删除", "B"),
        ("关于FANUC机器人零点标定，以下哪个说法是正确的？A)零点标定数据由脉冲编码器电池单独保持 B)正常情况下也需要定期执行零点标定 C)机械部分撞击后脉冲计数可能无法指示轴角度，需执行零点标定 D)零点标定数据出厂时未设置", "C"),
        ("在FANUC机器人系统中，当出现报警代码FXTL-160时，可能的原因是什么？A)步骤号无效 B)程序没有运动步骤 C)需要执行零点标定 D)托盘中没有单元", "C"),
    ],
    "多选题": [
        ("根据FANUC安全手册，以下哪些人员被允许在安全栅栏内进行作业？A.操作者 B.程序员/示教作业者 C.维护技术人员 D.维修工程师", "BCD"),
        ("根据FANUC安全手册，操作者的职责包括以下哪些？A.进行机器人电源ON/OFF操作 B.从操作面板启动机器人程序 C.在安全栅栏内进行示教 D.进行机器人维修作业", "AB"),
    ]
}

def search_chunks(query, k=8):
    """搜索知识库，返回所有chunk"""
    return retrieve(query, top_k=k)

def llm_classify(prompt):
    for attempt in range(2):
        try:
            resp = LLM.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": "你是一个严格的知识审计专家。只输出JSON。"},
                          {"role": "user", "content": prompt}],
                temperature=0.05, max_tokens=1000, timeout=25
            )
            text = resp.choices[0].message.content.strip()
            m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if m: return json.loads(m.group())
        except:
            time.sleep(1)
    return None

audit_log = []

# 对每道题做追溯审计
for qtype, qlist in exam_qs.items():
    for q_text, expected in qlist:
        print(f"\n--- [{qtype}] {q_text[:50]} => {expected} ---")
        
        # 1. 搜索知识库，看哪些 chunk 可能被用来出这道题
        chunks = search_chunks(q_text, k=8)
        
        # 2. 用 LLM 分析：答案是否能在chunks中找到证据
        ctx = "\n---\n".join([
            f"[#{i+1} 文件:{c.get('filename','?')} score:{c['score']:.3f}] {c['text'][:400]}"
            for i, c in enumerate(chunks[:6])
        ])
        
        prompt = f"""审计一道FANUC机器人考题的答案来源。

### 题目 ###
{q_text}

### 预期答案 ###
{expected}

### 知识库检索结果（前6个chunk） ###
{ctx}

### 任务 ###
判断预期答案是否能从上述知识库chunks中找到直接证据。输出JSON：

{{
  "has_evidence": true/false,
  "evidence_chunk_index": "数字编号（能找到的chunk序号，多个用逗号分隔）",
  "evidence_text": "chunk中支撑答案的关键原文片段（限80字）",
  "verdict": "准确|幻觉|遗漏前提|张冠李戴|数值偏差",
  "detail": "具体说明（限80字）",
  "severity": "严重|中等|轻微"
}}

判断标准：
- 准确：答案与知识库完全一致，上下文完整
- 幻觉：答案有数值或事实在知识库中不存在/不同
- 遗漏前提：答案本身对但缺少关键约束条件（如"仅DCS模式"）
- 张冠李戴：答案引用了错误的知识来源
- 数值偏差：答案数值与知识库不同（如693.33 vs 2000）
"""
        
        result = llm_classify(prompt)
        audit_log.append({
            "type": qtype,
            "question": q_text,
            "expected": expected,
            "sources": [c.get('filename','?') for c in chunks[:3]],
            "audit": result or {"verdict": "审计失败", "detail": "LLM未返回有效结果"}
        })
        
        v = result.get("verdict", "?") if result else "?"
        d = result.get("detail", "") if result else ""
        print(f"  => {v}: {d[:60]}")

# 汇总
print("\n\n" + "="*60)
print("AUDIT SUMMARY: 试卷错误分布")
print("="*60)

errors_by_type = {}
for item in audit_log:
    v = item["audit"].get("verdict", "?")
    if v != "准确":
        t = item["type"]
        if t not in errors_by_type: errors_by_type[t] = []
        errors_by_type[t].append(item)

if errors_by_type:
    for t, items in errors_by_type.items():
        print(f"\n[{t}] {len(items)} 个问题:")
        for item in items:
            print(f"  {item['audit']['verdict']}: {item['question'][:50]}")
            print(f"    预期: {item['expected']} | {item['audit'].get('detail','')[:60]}")
            print(f"    来源: {item['sources']}")
else:
    print("所有题目答案均准确")

# 按检举分类
verdicts = {}
for item in audit_log:
    v = item["audit"].get("verdict", "?")
    verdicts[v] = verdicts.get(v, 0) + 1
print(f"\n分布: {verdicts}")
total = len(audit_log)
correct = verdicts.get("准确", 0)
print(f"总题数: {total}, 准确: {correct} ({correct/total*100:.0f}%), 有问题: {total-correct}")

# 保存
with open("/tmp/exam_audit.json", "w") as f:
    json.dump({"summary": verdicts, "details": audit_log}, f, ensure_ascii=False, indent=2)
print(f"\n✅ 审计结果: /tmp/exam_audit.json")
