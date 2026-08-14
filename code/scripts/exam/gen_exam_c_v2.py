"""C卷 v2: 从已清洗的知识库出题"""
import sys, re, json
sys.path.insert(0, '/home/eric_jia/self-grow-wiki')
from rag_core import retrieve

def verify(q, expected):
    """检索知识库确认答案存在"""
    chunks = retrieve(q, top_k=5)
    for c in chunks:
        if expected.lower() in c['text'].lower()[:600]:
            return True, c.get('filename','?'), c['score'], c['text'][:100]
    return False, None, 0, ""

# 逐一搜集题目素材
topics = [
    # (topic_to_search, question_template, expected_answer, type)
    ("T1 模式 速度 限制 250mm sec",
     "在T1模式下，机器人工具中心点和法兰盘中心点的速度被限制在____mm/sec以下。",
     "250", "fill"),
    
    ("伺服焊枪 压力 设定范围 9999.9",
     "伺服焊枪基本规格中，压力设定范围是0.0－____［N, kgf, lbf］。",
     "9999.9", "fill"),
    
    ("伺服焊枪 行程 设定范围 999.9",
     "伺服焊枪基本规格中，行程设定范围是0.0－____［mm］。",
     "999.9", "fill"),
    
    ("伺服焊枪 轴速度 设定范围 2000 mm sec",
     "伺服焊枪基本规格中，焊枪轴速度设定范围是0－____［mm/sec］。",
     "2000", "fill"),
    
    ("镜像备份 恢复 F1 F2 同时按住",
     "恢复镜像备份时，需要在同时按住____和____键的状态下接通机器人电源。",
     "F1/F2", "fill"),
    
    ("自动备份 最多 设置 5个",
     "FANUC自动备份功能中，最多可以设置____个备份时间。",
     "5", "fill"),
    
    ("共享示教器 16 台 控制装置",
     "共享示教器功能中，一个共享组内最多可注册____台控制装置。",
     "16", "fill"),
    
    ("工具坐标系 序号 0 机械界面",
     "FANUC机器人中，工具坐标系序号为0时表示使用____坐标系。",
     "机械界面", "fill"),
    
    # 判断题
    ("SRVO-001 SERVO 报警 减速 停止",
     "报警代码SRVO-001的报警严重度为SERVO，发生该报警时机器人会减速停止并断开伺服电源。",
     "T", "judge"),
    
    ("报警画面自动显示 标准设定 无效",
     "报警画面自动显示功能在系统/配置画面中标准设定为有效。",
     "F", "judge"),
    
    ("冷启动 PREV NEXT Configuration menu",
     "FANUC机器人冷启动时，需在按住PREV和NEXT键的状态下接通电源，再从配置菜单中选择Cold start。",
     "T", "judge"),
    
    ("自动备份 版本 最大数目 99",
     "FANUC自动备份功能中，可保存的备份版本数目可以从1设置到99。",
     "T", "judge"),
    
    ("更换 电池 电源 保持 打开",
     "更换FANUC机器人本体电池时，设备电源应保持关闭状态。",
     "F", "judge"),
    
    ("零点复归 初始化 启动 Mastering 丢失",
     "FANUC机器人执行初始化启动后，Mastering数据不会丢失，无需重新执行零点复归。",
     "F", "judge"),
    
    # 单选题
    ("零点 标定 必须 执行 什么情况",
     "以下哪种情况必须执行零点标定？A)更换TCP工具 B)执行初始化启动导致Mastering数据丢失 C)修改了程序 D)更换了焊枪电极帽",
     "B", "single"),
    
    ("位置寄存器 PR 要素 j=5",
     "FANUC位置寄存器要素指令PR[i,j]中，使用直角坐标系时j=5代表：A)X轴 B)Y轴 C)P（回转角） D)R（旋转角）",
     "C", "single"),
    
    ("MAX GUN SPEED 693",
     "FANUC伺服焊枪轴最高速度(MAX GUN SPEED)的默认出厂设定值约为：A)250 B)400 C)693 D)2000 mm/sec",
     "C", "single"),
]

# 验证每道题
results = []
for topic, question, answer, qtype in topics:
    ok, src, score, context = verify(topic, str(answer))
    print(f"[{qtype}] {question[:40]}... => {answer} | {'✅' if ok else '❌'} {src} ({score:.3f})")
    results.append({"ok": ok, "q": question, "a": answer, "src": src, "score": score})

# 输出试卷
fill = [r for r in results if "fill" in str(r.get('type',''))]
judge = [r for r in results if "judge" in str(r.get('type',''))]
single = [r for r in results if "single" in str(r.get('type',''))]

# Actually let me redo this more carefully
fill_qs = [(r['q'], r['a']) for r in results[:8]]
judge_qs = [(r['q'], r['a']) for r in results[8:14]]
single_qs = [(r['q'], r['a']) for r in results[14:]]

lines = []
lines.append("# FANUC机器人理论考试（C卷带答案）")
lines.append("---\n")
lines.append("## 一、填空题（每空2分，共16分）\n")
for i, (q, a) in enumerate(fill_qs):
    lines.append(f"{i+1}. {q}")
lines.append("\n**答案：**")
for i, (q, a) in enumerate(fill_qs):
    lines.append(f"{i+1}. {a}")

lines.append("\n---\n## 二、判断题（每题2分，共12分，正确T/错误F）\n")
for i, (q, a) in enumerate(judge_qs):
    lines.append(f"{i+1}. {q}")
lines.append("\n**答案：**")
for i, (q, a) in enumerate(judge_qs):
    lines.append(f"{i+1}. {a}")

lines.append("\n---\n## 三、单选题（每题3分，共12分）\n")
for i, (q, a) in enumerate(single_qs):
    lines.append(f"{i+1}. {q}")
lines.append("\n**答案：**")
for i, (q, a) in enumerate(single_qs):
    lines.append(f"{i+1}. {a}")

exam = "\n".join(lines)
with open("/home/eric_jia/FANUC考试_C卷_基于知识库.md", "w") as f:
    f.write(exam)

# 纯文本版
plain = ["FANUC机器人理论考试（C卷带答案）\n"]
plain.append("填空题：")
for i, (q, a) in enumerate(fill_qs):
    plain.append(f"{i+1}. {q}  ({a})")
plain.append("")
plain.append("判断题：")
for i, (q, a) in enumerate(judge_qs):
    plain.append(f"{i+1}. {q}  {a}")
plain.append("")
plain.append("单选题：")
for i, (q, a) in enumerate(single_qs):
    plain.append(f"{i+1}. {q}  {a}")
with open("/tmp/exam_c.txt", "w") as f:
    f.write("\n".join(plain))

print(f"\n✅ 试卷: /home/eric_jia/FANUC考试_C卷_基于知识库.md")
print(f"✅ 纯文本: /tmp/exam_c.txt")
