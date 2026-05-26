#!/usr/bin/env python3
"""
Phase 1: 正则实体抽取 — 从现有 230k chunks 提取 FANUC 专用实体，更新 ChromaDB 元数据。

提取维度:
  - entity_alarms:    FANUC 报警码 (SRVO-023, PRIO-001 等)
  - entity_models:    FANUC 机器人型号 (R-2000iC, M-20iD 等)
  - entity_manuals:   FANUC 手册编号 (B-84194EN 等)
  - entity_variables: 系统变量 ($SCR_GRP 等)
  - content_type:     内容类型

用法: CUDA_VISIBLE_DEVICES="" python3 rag_phase1_entity_extract.py [--dry-run] [--batch-size N]
"""

import re
import json
import sys
import time
import argparse
from collections import Counter

# ─── FANUC 专用正则 ──────────────────────────────────────────────

# 报警码: 只匹配已知的 FANUC 报警前缀 + 3-5位数字
FANUC_ALARM_PREFIXES = (
    'SRVO', 'MATE', 'PRIO', 'SYST', 'MENH', 'TPIF', 'MOTN', 'GRP',
    'TSTP', 'PROG', 'FILE', 'SVOF', 'UALM', 'HOST', 'SERVO', 'COMM',
    'DNBT', 'OPTI', 'MACR', 'SPOT', 'STRT', 'TCH', 'PAINT', 'ARC',
    'FCTN', 'DSQC', 'SMB', 'ENC', 'PNIO', 'DRAG', 'JPOS', 'SYS',
    'SVO2', 'SVON', 'CMND', 'MCTL', 'TUN', 'DMIO', 'GIOP',
    'ROTP', 'WELD', 'CUT', 'TOOL', 'DIST', 'MOT', 'CURR',
)
_ALARM_PATTERN = '|'.join(FANUC_ALARM_PREFIXES)
ALARM_RE = re.compile(
    rf'(?<![A-Za-z0-9])({_ALARM_PATTERN})[-－](\d{{3,5}})(?![A-Za-z0-9])',
    re.IGNORECASE
)

# FANUC 机器人型号 (严格匹配)
# R-2000iC/165F, M-20iD/25, CRX-10iA/L, LR Mate 200iD/7L, Arc Mate 120iC/10L
# S-430iC, M-710iC/50, P-250iB, F-200iB
MODEL_RE = re.compile(
    r'(?<![A-Za-z0-9])'
    r'(?:'
    r'(?:R|M|S|P|F)-\d{3,4}[a-zA-Z]{0,3}(?:/\d{1,3}[A-Z]?)?'  # R-2000iC/165F
    r'|CRX-\d{1,3}i[A-Z](?:/[A-Z])?'                            # CRX-10iA/L
    r'|(?:LR\s*Mate|Arc\s*Mate|Arc\s*Mate)\s*\d{3,4}i[A-Z](?:/\d{1,3}[A-Z]?)?'  # LR Mate 200iD
    r')'
    r'(?![A-Za-z0-9])',
    re.IGNORECASE
)

# 也匹配型号系列前缀 (更宽泛但仅用于实体补充)
MODEL_SERIES_RE = re.compile(
    r'(?<![A-Za-z0-9])'
    r'(R-2000|M-20|M-710|M-900|S-430|P-250|F-200|LR\s*Mate|Arc\s*Mate|CRX-10)'
    r'(?![A-Za-z0-9])',
    re.IGNORECASE
)
# 型号规格后缀: R-2000iC/210F -> 210F, R-2000iC/210WE -> 210WE
MODEL_VARIANT_RE = re.compile(
    r'(?:R|M|S|P|F)-\d{3,4}[a-zA-Z]{0,3}'
    r'/(\d{2,4}[A-Z]{0,2}\d*)'
)

# 独立规格后缀(仅在机器人上下文中): 210F, 210WE, 165F, 10L
STANDALONE_VARIANT_RE = re.compile(
    r'(?<![A-Za-z0-9])(\d{3,4})([A-Z]{1,2})(?![A-Za-z0-9/])'
)


# 手册编号: B-84194EN, B-83284EN, B-82574EN, M-410iB 等 FANUC 文档
MANUAL_RE = re.compile(
    r'(?<![A-Za-z0-9])(B-\d{5,6}[A-Z]{2,4})(?![A-Za-z0-9])'
)

# 系统变量: $SCR_GRP, $MNUTOOL, $PARAM_GROUP 等 (必须全大写+下划线)
VARIABLE_RE = re.compile(r'(\$[A-Z][A-Z0-9_]{2,30})')

# FANUC 关键词 (用于增强 content_type 判断)
FANUC_KW = re.compile(
    r'FANUC|发那科|法那科|机器人|robot|servo|伺服|示教器|TP|Karel',
    re.IGNORECASE
)

# ─── 内容类型推断 ────────────────────────────────────────────────

TROUBLESHOOTING_KW = [
    '报警', '故障', '解决', '排除', '原因', '处理方法', '对策', '修复', '维修',
    '异常', '失效', '损坏', '过载', '过热', '过流', '过压', '欠压',
    'alarm', 'error', 'fault', 'troubleshoot', 'solution', 'cause',
]

REFERENCE_KW = [
    '规格', '参数表', '列表', '映射', '一览', '对照表', '速查', '索引',
    'specification', 'parameter', 'table', 'mapping', 'list',
]

PROCEDURE_KW = [
    '步骤', '操作', '方法', '如何', '设置', '配置', '安装', '拆卸', '更换',
    '备份', '恢复', '校准', '标定', '初始化', '调整',
    'step', 'procedure', 'how to', 'setup', 'install', 'configure',
]

SPECIFICATION_KW = [
    '技术规格', '性能参数', '额定', '负载', '行程', '精度', '重复定位',
    'payload', 'reach', 'repeatability', 'rated', 'maximum', 'cycle time',
]


def classify_content_type(text: str, has_alarm: bool) -> str:
    scores = {
        'troubleshooting': 0,
        'reference': 0,
        'procedure': 0,
        'specification': 0,
        'manual': 0,
    }

    tl = text.lower()
    for kw in TROUBLESHOOTING_KW:
        if kw.lower() in tl:
            scores['troubleshooting'] += 1
    for kw in REFERENCE_KW:
        if kw.lower() in tl:
            scores['reference'] += 1
    for kw in PROCEDURE_KW:
        if kw.lower() in tl:
            scores['procedure'] += 1
    for kw in SPECIFICATION_KW:
        if kw.lower() in tl:
            scores['specification'] += 1

    if has_alarm:
        scores['troubleshooting'] += 5

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'manual'


def extract_entities(text: str) -> dict:
    # 报警码
    alarm_matches = ALARM_RE.findall(text)
    alarms = list(dict.fromkeys([
        f'{prefix.upper()}-{num}' for prefix, num in alarm_matches
    ]))

    # 型号 — 完整型号 + 系列
    models_full = MODEL_RE.findall(text)
    models_series = MODEL_SERIES_RE.findall(text)
    models = list(dict.fromkeys(
        [m.strip() for m in models_full] +
        [m.strip() for m in models_series]
    ))

    # 手册编号
    manuals = list(dict.fromkeys(MANUAL_RE.findall(text)))

    # 系统变量
    variables = list(dict.fromkeys(VARIABLE_RE.findall(text)))

    # 型号规格后缀
    variants = []
    for m in models_full:
        m_suffix = MODEL_VARIANT_RE.search(m)
        if m_suffix:
            variants.append(m_suffix.group(1))
    if models or FANUC_KW.search(text):
        standalone = STANDALONE_VARIANT_RE.findall(text)
        for digits, letters in standalone:
            suffix = digits + letters
            if suffix not in variants:
                variants.append(suffix)
    raw_variants = [v for v in variants if v][:15]

    return {
        'alarms': alarms[:10],
        'models': models[:10],
        'variants': raw_variants,
        'manuals': manuals[:5],
        'variables': variables[:10],
    }


def main():
    parser = argparse.ArgumentParser(description='Phase 1: FANUC 正则实体抽取')
    parser.add_argument('--dry-run', action='store_true', help='只统计不写入')
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--limit', type=int, default=0, help='限制处理总数 (0=全部)')
    args = parser.parse_args()

    import chromadb
    client = chromadb.PersistentClient(path='/home/hp/rag_chromadb')
    col = client.get_collection('wiki_docs')
    total = col.count()
    print(f'集合: wiki_docs, 总 chunks: {total}')

    if args.limit > 0:
        total = min(total, args.limit)
        print(f'限制处理: {total} chunks')

    stats = {
        'processed': 0,
        'with_alarm': 0,
        'with_model': 0,
        'with_manual': 0,
        'with_variable': 0,
        'with_any_entity': 0,
        'alarm_codes': Counter(),
        'model_codes': Counter(),
        'content_types': Counter(),
    }

    start = time.time()
    offset = 0

    while offset < total:
        batch_size = min(args.batch_size, total - offset)
        pct = offset * 100 // max(total, 1)
        elapsed = time.time() - start
        rate = offset / max(elapsed, 0.1)
        eta = (total - offset) / max(rate, 0.1)
        print(f'\r处理中: {offset}/{total} ({pct}%) | {rate:.0f}/s | ETA {eta:.0f}s', end='', flush=True)

        result = col.get(limit=batch_size, offset=offset, include=['documents', 'metadatas'])
        ids = result['ids']
        texts = result['documents']
        metas = result['metadatas']

        if not ids:
            break

        # 提取 + 统计 + 写入
        update_ids = []
        update_metas = []

        for id_, text, meta in zip(ids, texts, metas):
            entities = extract_entities(text)
            has_alarm = len(entities['alarms']) > 0
            content_type = classify_content_type(text, has_alarm)

            # 统计
            stats['processed'] += 1
            if entities['alarms']:
                stats['with_alarm'] += 1
                for a in entities['alarms']:
                    stats['alarm_codes'][a] += 1
            if entities['models']:
                stats['with_model'] += 1
                for m in entities['models']:
                    stats['model_codes'][m] += 1
            if entities['manuals']:
                stats['with_manual'] += 1
            if entities['variables']:
                stats['with_variable'] += 1
            if any(len(v) > 0 for v in entities.values()):
                stats['with_any_entity'] += 1
            stats['content_types'][content_type] += 1

            # 构建新元数据
            new_meta = dict(meta)
            new_meta['entity_alarms'] = json.dumps(entities['alarms'], ensure_ascii=False)
            new_meta['entity_models'] = json.dumps(entities['models'], ensure_ascii=False)
            new_meta['entity_model_variants'] = json.dumps(entities['variants'], ensure_ascii=False)
            new_meta['entity_manuals'] = json.dumps(entities['manuals'], ensure_ascii=False)
            new_meta['entity_variables'] = json.dumps(entities['variables'], ensure_ascii=False)
            new_meta['content_type'] = content_type
            new_meta['has_entity'] = any(len(v) > 0 for v in entities.values())
            new_meta['tag_source'] = 'regex_v1'

            update_ids.append(id_)
            update_metas.append(new_meta)

        # 批量写入
        if not args.dry_run and update_ids:
            # ChromaDB 批量更新，每500个一批
            for i in range(0, len(update_ids), 500):
                col.update(
                    ids=update_ids[i:i+500],
                    metadatas=update_metas[i:i+500],
                )

        offset += len(ids)

    elapsed = time.time() - start
    print(f'\n\n=== 完成 ({elapsed:.1f}s, {stats["processed"]/max(elapsed,0.1):.0f} chunks/s) ===')
    p = max(stats['processed'], 1)
    print(f'处理: {stats["processed"]}')
    print(f'含报警码: {stats["with_alarm"]} ({stats["with_alarm"]*100//p}%)')
    print(f'含型号: {stats["with_model"]} ({stats["with_model"]*100//p}%)')
    print(f'含手册号: {stats["with_manual"]} ({stats["with_manual"]*100//p}%)')
    print(f'含系统变量: {stats["with_variable"]} ({stats["with_variable"]*100//p}%)')
    print(f'含任意实体: {stats["with_any_entity"]} ({stats["with_any_entity"]*100//p}%)')

    print(f'\n--- 内容类型分布 ---')
    for ct, cnt in stats['content_types'].most_common():
        print(f'  {ct}: {cnt} ({cnt*100//p}%)')

    print(f'\n--- Top 30 报警码 ---')
    for code, cnt in stats['alarm_codes'].most_common(30):
        print(f'  {code}: {cnt}')

    print(f'\n--- Top 30 型号 ---')
    for model, cnt in stats['model_codes'].most_common(30):
        print(f'  {model}: {cnt}')

    if args.dry_run:
        print('\n[Dry Run] 未写入数据库')
    else:
        print(f'\n[已写入] {stats["processed"]} chunks 元数据已更新')


if __name__ == '__main__':
    main()
