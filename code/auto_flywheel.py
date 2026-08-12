# -*- coding: utf-8 -*-
"""
Auto模式 - 自动飞轮循环系统
自动处理200题，分批次进行
"""

import requests
import json
import time
from datetime import datetime
import zipfile
import xml.etree.ElementTree as ET

OLLAMA_API = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:3b"
BATCH_SIZE = 10  # 每批处理题数

def load_questions():
    """从docx加载题目"""
    docx_path = '/mnt/c/Users/hp/Desktop/自研/rag-docs/RAG巡检题库_200题_20260508.docx'
    with zipfile.ZipFile(docx_path, 'r') as docx:
        xml_content = docx.read('word/document.xml')
        root = ET.fromstring(xml_content)

    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    tbl = root.find('.//w:tbl', ns)
    rows = tbl.findall('.//w:tr', ns)

    questions = []
    for i, row in enumerate(rows[1:], 1):
        cells = row.findall('.//w:tc', ns)
        cell_texts = []
        for cell in cells:
            texts = []
            for p in cell.findall('.//w:p', ns):
                for t in p.findall('.//w:t', ns):
                    if t.text:
                        texts.append(t.text)
            cell_texts.append(''.join(texts) if texts else '')
        if len(cell_texts) >= 7:
            questions.append({
                'id': cell_texts[0],
                'difficulty': cell_texts[1],
                'qtype': cell_texts[2],
                'query': cell_texts[3],
                'must_contain': cell_texts[4],
                'min_score': cell_texts[5],
                'feedback': cell_texts[6]
            })
    return questions

def llm_generate(prompt, max_tokens=500):
    """使用Ollama生成文本"""
    try:
        resp = requests.post(
            OLLAMA_API,
            json={"model": MODEL, "prompt": prompt, "stream": False, "max_tokens": max_tokens},
            timeout=60
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
        else:
            return f"Ollama API错误: {resp.status_code}"
    except Exception as e:
        return f"Ollama调用失败: {e}"

def process_batch(questions, batch_num):
    """处理一批题目"""
    print(f"\n{'='*70}")
    print(f"第{batch_num}批处理 - {len(questions)}题")
    print(f"{'='*70}")

    results = []
    for i, q in enumerate(questions):
        print(f"\n[{i+1}/{len(questions)}] {q['id']} - {q['query'][:40]}...")

        # 1. 纠正题目
        prompt = f"""请分析题目: {q['query']}
题目类型: {q['qtype']}
请给出: 是否准确、纠正后题目、纠正理由、难度评估"""
        q['correction'] = llm_generate(prompt, max_tokens=200)

        # 2. 查询知识库
        try:
            resp = requests.post(
                "http://localhost:8002/query",
                json={"query": q['query'], "top_k": 3, "score_threshold": 1.0},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                answer = data.get("answer", "未找到答案")
                sources = data.get("sources", [])

                # 判断知识库是否有有效答案
                if "未找到" in answer or "查询失败" in answer or "API错误" in answer or answer == "":
                    q['raw_answer'] = answer
                    q['sources'] = sources
                    q['answer_source'] = "待扩充"  # 知识库无答案，加入待扩充清单
                else:
                    q['raw_answer'] = answer
                    q['sources'] = sources
                    q['answer_source'] = "knowledge_base"  # 知识库有答案
            else:
                q['raw_answer'] = f"API错误: {resp.status_code}"
                q['sources'] = []
                q['answer_source'] = "待扩充"
        except Exception as e:
            q['raw_answer'] = f"查询失败: {e}"
            q['sources'] = []
            q['answer_source'] = "待扩充"

        # 3. 分析答案
        prompt = f"""请分析答案质量:
答案: {q['raw_answer'][:200]}
请给出: 是否完整、是否准确、需要补充、质量评分"""
        q['answer_analysis'] = llm_generate(prompt, max_tokens=200)

        results.append(q)

        # 每5题保存一次
        if (i + 1) % 5 == 0:
            save_batch_results(results, batch_num)
            print(f"  ✓ 已保存批次 {batch_num} 前{i+1}题")

    return results

def save_batch_results(results, batch_num):
    """保存批次结果"""
    filepath = f"/home/eric_jia/auto_flywheel_batch_{batch_num}.json"
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def generate_summary_report(all_results):
    """生成汇总报告"""
    report = []
    report.append("# Auto模式飞轮循环 - 汇总报告")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"模型: {MODEL}")
    report.append(f"总题数: {len(all_results)}")
    report.append("")

    # 统计
    accurate = sum(1 for q in all_results if '是否准确: 是' in q.get('correction', ''))
    complete = sum(1 for q in all_results if '是否完整: 是' in q.get('answer_analysis', ''))

    report.append("## 总体统计")
    report.append(f"- 处理题目: {len(all_results)}")
    report.append(f"- 题目准确率: {accurate}/{len(all_results)} ({accurate/len(all_results)*100:.1f}%)")
    report.append(f"- 答案完整率: {complete}/{len(all_results)} ({complete/len(all_results)*100:.1f}%)")
    report.append("")

    # 按难度统计
    report.append("## 难度分布")
    diff_count = {}
    for q in all_results:
        diff = q.get('difficulty', '未知')
        diff_count[diff] = diff_count.get(diff, 0) + 1
    for diff, count in sorted(diff_count.items()):
        report.append(f"- {diff}: {count}题")

    return "\n".join(report)

def main():
    """主函数 - Auto模式"""
    print("=" * 70)
    print("Auto模式飞轮循环启动")
    print("=" * 70)

    # 加载所有题目
    all_questions = load_questions()
    print(f"加载题目总数: {len(all_questions)}")

    # 计算批次
    total_batches = (len(all_questions) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"总批次数: {total_batches}")
    print(f"每批题数: {BATCH_SIZE}")

    # 已处理的题目ID（跳过已处理的）
    processed_ids = set()
    # 这里可以添加已处理题目的ID，避免重复处理

    all_results = []
    start_batch = 1

    for batch_num in range(start_batch, total_batches + 1):
        # 获取当前批次的题目
        start_idx = (batch_num - 1) * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(all_questions))
        batch_questions = all_questions[start_idx:end_idx]

        # 过滤已处理的题目
        batch_questions = [q for q in batch_questions if q['id'] not in processed_ids]

        if not batch_questions:
            print(f"\n第{batch_num}批已处理完成，跳过")
            continue

        # 处理批次
        try:
            batch_results = process_batch(batch_questions, batch_num)
            all_results.extend(batch_results)

            # 保存批次结果
            save_batch_results(batch_results, batch_num)

            # 生成批次报告
            report = generate_summary_report(batch_results)
            report_path = f"/home/eric_jia/auto_flywheel_batch_{batch_num}_report.md"
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"\n✓ 第{batch_num}批完成，报告: {report_path}")

            # 间隔休息（避免Ollama过载）
            if batch_num < total_batches:
                print(f"  休息30秒后继续下一批...")
                time.sleep(30)

        except Exception as e:
            print(f"\n✗ 第{batch_num}批处理失败: {e}")
            # 保存已处理的结果
            if all_results:
                save_batch_results(all_results, batch_num)
            break

    # 生成最终汇总报告
    if all_results:
        summary = generate_summary_report(all_results)
        summary_path = "/home/eric_jia/auto_flywheel_summary.md"
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write(summary)
        print(f"\n{'='*70}")
        print(f"Auto模式完成！")
        print(f"汇总报告: {summary_path}")
        print(f"{'='*70}")

if __name__ == "__main__":
    main()
