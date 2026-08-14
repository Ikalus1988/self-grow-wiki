#!/usr/bin/env python3
"""
Phase 2+3: LLM 语义打标 + 二级分类 (合并执行)
用本地 qwen2.5:3b (Ollama) 一次调用生成 topic_tags + category_l2 + category_l3

策略:
  - 有实体的 chunks 优先处理 (40k)
  - 剩余 chunks 用关键词规则快速打标
  - 批量处理，每个 chunk 独立 prompt

用法: CUDA_VISIBLE_DEVICES="" python3 rag_phase2_semantic_tag.py [--limit N] [--batch-size N]
"""

import json
import time
import re
import argparse
import sys
import urllib.request
import urllib.error
from collections import Counter

OLLAMA_URL = 'http://127.0.0.1:11434/api/generate'
MODEL = 'qwen2.5:3b'

# ─── 二级分类体系 ────────────────────────────────────────────────

CATEGORY_L2_MAP = {
    '07_机器人': [
        '伺服与运动控制', '报警诊断与故障排除', 'IO与通信', '编程与示教',
        '系统配置与初始化', '安全与维护', '视觉与传感器', '外部轴与协调', '硬件手册',
    ],
    '01_PLC与控制': [
        'TIA Portal配置', 'SCL/STL编程', 'SICAR标准块', 'PLC报警与诊断', '通信与网络',
    ],
    '03_电气图纸': [
        '线体图纸', '供应商图纸', '标准电气符号',
    ],
    '04_HMI与SCADA': [
        'WinCC配置', '画面设计', '报警管理', '数据归档',
    ],
    '05_驱动与传动': [
        '变频器参数', '伺服驱动', '机械传动', '电机选型',
    ],
    '06_安全与传感': [
        '安全PLC', '传感器配置', '安全回路', '光栅与安全门',
    ],
    '08_工装夹具': [
        '夹具设计', '焊枪配置', '抓手工具', '工装标准',
    ],
    '09_项目文档': [
        '现场程序文档', '客户项目', '调试记录', '项目方案',
    ],
    '02_视觉系统': [
        '相机配置', '视觉引导', '标定与测量', '视觉算法',
    ],
    '10_其他': [
        '培训资料', '标准规范', '通用参考',
    ],
}

# ─── LLM 调用 ─────────────────────────────────────────────────

TAG_PROMPT_TEMPLATE = """你是工业自动化文档分类专家。对以下技术文档片段进行多维打标。

文档片段:
{text}

分类: {category_l1}

请输出JSON，包含以下字段:
{{
  "topic_tags": ["标签1", "标签2", "标签3"],
  "category_l2": "从以下选项中选一个: {l2_options}",
  "category_l3": "更细的三级分类，自行判断",
  "content_type": "从以下选项中选一个: troubleshooting/reference/manual/procedure/specification/glossary/faq/diagram"
}}

要求:
1. topic_tags: 3-5个最关键的中文技术标签
2. category_l2: 必须从给定选项中选
3. content_type: 如果之前已经是regex打的标，可以保留或修正
4. 只输出JSON，不要其他内容"""

# ─── 关键词快速打标 (不调LLM) ────────────────────────────────────

KEYWORD_TAG_RULES = [
    # (正则, topic_tags, category_l2)
    (re.compile(r'SRVO-\d|MATE-\d|报警|alarm|故障代码', re.I),
     ['伺服报警', '故障排除'], '报警诊断与故障排除'),
    (re.compile(r'伺服|servo|电机|编码器|放大器', re.I),
     ['伺服系统', '运动控制'], '伺服与运动控制'),
    (re.compile(r'PLC|SCL|STL|TIA|SICAR|FB\s*\d|FC\s*\d|DB\s*\d', re.I),
     ['PLC编程', '控制逻辑'], 'TIA Portal配置'),
    (re.compile(r'IO|数字量|模拟量|PROFINET|以太网|总线', re.I),
     ['IO通信', '信号处理'], 'IO与通信'),
    (re.compile(r'示教|TP|程序|Karel|运动指令|J\b|L\b|C\b', re.I),
     ['编程示教', '运动指令'], '编程与示教'),
    (re.compile(r'系统变量|\$\w+|配置|初始化|备份|恢复', re.I),
     ['系统配置', '参数设置'], '系统配置与初始化'),
    (re.compile(r'安全|急停|安全门|光栅|安全回路', re.I),
     ['安全功能', '安全回路'], '安全与维护'),
    (re.compile(r'视觉|iRVision|相机|标定|拍照', re.I),
     ['视觉系统', '视觉引导'], '视觉与传感器'),
    (re.compile(r'变位机|导轨|协调|外部轴|E轴', re.I),
     ['外部轴', '多机协调'], '外部轴与协调'),
    (re.compile(r'规格|payload|负载|重复精度|工作范围', re.I),
     ['技术规格', '机器人参数'], '硬件手册'),
    (re.compile(r'WinCC|HMI|SCADA|触摸屏|画面', re.I),
     ['HMI画面', 'SCADA配置'], 'WinCC配置'),
    (re.compile(r'变频|VFD|驱动器|G120|S120', re.I),
     ['变频器', '驱动控制'], '变频器参数'),
    (re.compile(r'焊枪|焊接|焊缝|弧焊|点焊', re.I),
     ['焊接工艺', '焊枪配置'], '焊枪配置'),
    (re.compile(r'夹具|抓手|工具TCP|末端执行器', re.I),
     ['夹具设计', '工具配置'], '夹具设计'),
]


def keyword_tag(text: str, category_l1: str) -> dict:
    """用关键词规则快速打标。"""
    tags = set()
    l2 = None
    for pattern, kw_tags, kw_l2 in KEYWORD_TAG_RULES:
        if pattern.search(text):
            tags.update(kw_tags)
            if l2 is None:
                l2 = kw_l2

    if not tags:
        tags = {'技术文档'}
    if l2 is None:
        l2 = '通用参考'

    return {
        'topic_tags': list(tags)[:5],
        'category_l2': l2,
        'category_l3': '',
        'content_type': None,  # 保留 Phase 1 的值
    }


def llm_tag(text: str, category_l1: str) -> dict:
    """用本地 LLM 打标。"""
    l2_options = CATEGORY_L2_MAP.get(category_l1, ['通用参考'])
    prompt = TAG_PROMPT_TEMPLATE.format(
        text=text[:500],  # 截断避免太长
        category_l1=category_l1,
        l2_options='、'.join(l2_options),
    )

    payload = json.dumps({
        'model': MODEL,
        'prompt': prompt,
        'stream': False,
        'options': {
            'temperature': 0.1,
            'num_predict': 200,
            'num_ctx': 1024,
        },
    }).encode()

    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        response = data.get('response', '')

        # 提取 JSON
        json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            # 验证字段
            return {
                'topic_tags': result.get('topic_tags', ['技术文档'])[:5],
                'category_l2': result.get('category_l2', ''),
                'category_l3': result.get('category_l3', ''),
                'content_type': result.get('content_type', None),
            }
    except Exception as e:
        pass  # fallback to keyword

    return keyword_tag(text, category_l1)


def main():
    parser = argparse.ArgumentParser(description='Phase 2+3: LLM 语义打标 + 二级分类')
    parser.add_argument('--limit', type=int, default=0, help='限制处理总数 (0=全部)')
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--keyword-only', action='store_true', help='只用关键词规则，不调LLM')
    parser.add_argument('--entity-only', action='store_true', help='只处理有实体的chunks')
    args = parser.parse_args()

    import chromadb
    client = chromadb.PersistentClient(path='/home/eric_jia/rag_chromadb')
    col = client.get_collection('wiki_docs')
    total = col.count()
    print(f'集合: wiki_docs, 总 chunks: {total}')

    stats = {
        'processed': 0,
        'llm_called': 0,
        'llm_success': 0,
        'keyword_tagged': 0,
        'l2_distribution': Counter(),
        'tag_distribution': Counter(),
    }

    start = time.time()
    offset = 0
    limit = args.limit if args.limit > 0 else total

    while offset < limit:
        batch_size = min(args.batch_size, limit - offset)
        elapsed = time.time() - start
        rate = stats['processed'] / max(elapsed, 0.1)
        remaining = (limit - offset) / max(rate, 0.1)
        print(f'\r处理中: {offset}/{limit} ({offset*100//max(limit,1)}%) | '
              f'{rate:.0f}/s | LLM:{stats["llm_success"]}/{stats["llm_called"]} | '
              f'ETA:{remaining:.0f}s', end='', flush=True)

        result = col.get(limit=batch_size, offset=offset, include=['documents', 'metadatas'])
        ids = result['ids']
        texts = result['documents']
        metas = result['metadatas']

        if not ids:
            break

        update_ids = []
        update_metas = []

        for id_, text, meta in zip(ids, texts, metas):
            cat_l1 = meta.get('category', '10_其他')
            has_entity = meta.get('has_entity', False)

            # 选择打标策略
            if args.keyword_only or not has_entity:
                tag_result = keyword_tag(text, cat_l1)
                stats['keyword_tagged'] += 1
            else:
                tag_result = llm_tag(text, cat_l1)
                stats['llm_called'] += 1
                if tag_result.get('topic_tags'):
                    stats['llm_success'] += 1

            # 构建更新元数据
            new_meta = dict(meta)
            new_meta['topic_tags'] = json.dumps(tag_result['topic_tags'], ensure_ascii=False)
            if tag_result['category_l2']:
                new_meta['category_l2'] = tag_result['category_l2']
            if tag_result.get('category_l3'):
                new_meta['category_l3'] = tag_result['category_l3']
            if tag_result.get('content_type'):
                new_meta['content_type'] = tag_result['content_type']

            # 统计
            stats['processed'] += 1
            l2 = tag_result.get('category_l2', '')
            if l2:
                stats['l2_distribution'][l2] += 1
            for t in tag_result.get('topic_tags', []):
                stats['tag_distribution'][t] += 1

            update_ids.append(id_)
            update_metas.append(new_meta)

        # 批量写入
        for i in range(0, len(update_ids), 500):
            col.update(
                ids=update_ids[i:i+500],
                metadatas=update_metas[i:i+500],
            )

        offset += len(ids)

    elapsed = time.time() - start
    print(f'\n\n=== 完成 ({elapsed:.1f}s) ===')
    print(f'处理: {stats["processed"]}')
    print(f'LLM调用: {stats["llm_called"]} (成功: {stats["llm_success"]})')
    print(f'关键词打标: {stats["keyword_tagged"]}')

    print(f'\n--- 二级分类分布 (Top 15) ---')
    for l2, cnt in stats['l2_distribution'].most_common(15):
        print(f'  {l2}: {cnt}')

    print(f'\n--- 高频标签 (Top 30) ---')
    for tag, cnt in stats['tag_distribution'].most_common(30):
        print(f'  {tag}: {cnt}')


if __name__ == '__main__':
    main()
