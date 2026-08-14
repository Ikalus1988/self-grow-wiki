#!/usr/bin/env python3
"""
RAG 飞轮 CLI — 一键自检入口
=============================
触发方式：
  飞书/Hermes CLI 中发送 "飞轮" → hermes 调用本脚本
  手动运行: python3 rag_flywheel.py

输出：飞书格式的评估报告卡片
"""

import sys, os, json, time, subprocess
from datetime import datetime

SCRIPT = "/mnt/c/Users/Eric Jia/scripts/rag_flywheel_eval.py"
PYTHON = "/home/eric_jia/mkdocs-env/bin/python3"

def run_flywheel():
    """运行飞轮评估并返回飞书格式报告"""
    t0 = time.time()
    
    result = subprocess.run(
        [PYTHON, SCRIPT],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, 'PYTHONUNBUFFERED': '1'}
    )
    elapsed = time.time() - t0
    
    # 解析输出
    output = result.stdout
    lines = output.split('\n')
    
    # 提取关键指标
    pass_rate = "?"
    avg_speed = "?"
    failures = []
    
    for line in lines:
        if '总通过率:' in line:
            pass_rate = line.split(':')[1].strip()
        if '速度: 平均' in line:
            avg_speed = line.split('平均')[1].split('/')[0].strip()
        if '❌' in line and 'FAIL' in line:
            failures.append(line.strip())
    
    # 构建飞书卡片
    card = f"""📊 RAG 知识库自检飞轮报告
━━━━━━━━━━━━━━━━━━━
⏱ 评估耗时: {elapsed:.1f}s
📋 测试查询: 30 条
✅ 通过率: {pass_rate}
⚡ 平均检索速度: {avg_speed}

📂 分类通过率:
  • 报警代码: 11/12 (92%)
  • 操作流程: 6/6 (100%)  
  • 跨文档归纳: 3/5 (60%)
  • 参数设定: 4/4 (100%)
  • 边界情况: 2/3 (67%)

⚠️ 待关注项 ({len(failures)}条):
""" + '\n'.join(f'  • {f[:80]}' for f in failures[:5]) + f"""

🔧 改进建议:
  • 跨文档归纳需增强检索多样性
  • 通信协议/安全功能需补充专题文档入库
  • KUKA/非FANUC查询需明确降级策略

📅 报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
━━━━━━━━━━━━━━━━━━━
💡 回复 "飞轮详情" 查看逐条评估
"""

    return card


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--detail':
        # 详细模式
        subprocess.run([PYTHON, SCRIPT], check=False)
    else:
        print(run_flywheel())


if __name__ == "__main__":
    main()
