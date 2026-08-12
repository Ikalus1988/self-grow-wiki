#!/usr/bin/env python3
"""
Phase 2 修复版: 更精准的关键词打标规则
修复: IO/运动指令 过度匹配问题
"""

import json
import time
import re
import argparse
from collections import Counter
import chromadb

# ─── 更精准的关键词规则 ─────────────────────────────────────────
# 规则: 只在高置信度匹配时才打标，避免过度匹配

KEYWORD_TAG_RULES = [
    # === 报警诊断 (最优先，高置信度) ===
    {
        'pattern': re.compile(r'SRVO-\d|MATE-\d|PRIO-\d|SYST-\d|MENH-\d|报警代码|alarm\s*code', re.I),
        'tags': ['伺服报警', '故障排除'],
        'l2': '报警诊断与故障排除',
        'priority': 10,
    },
    {
        'pattern': re.compile(r'报警原因|故障原因|解决方法|处理方法|排除方法|对策|修复方案', re.I),
        'tags': ['故障排除', '报警诊断'],
        'l2': '报警诊断与故障排除',
        'priority': 9,
    },

    # === 伺服与运动控制 ===
    {
        'pattern': re.compile(r'伺服放大器|伺服电机|编码器|servo\s*amp|servo\s*motor|脉冲编码', re.I),
        'tags': ['伺服系统', '伺服硬件'],
        'l2': '伺服与运动控制',
        'priority': 8,
    },
    {
        'pattern': re.compile(r'运动指令|MOVEJ|MOVEL|MOVEC|J\s*\d+|L\s*\d+.*mm/s|关节运动|直线运动|圆弧运动', re.I),
        'tags': ['运动指令', '编程示教'],
        'l2': '编程与示教',
        'priority': 8,
    },

    # === 编程与示教 ===
    {
        'pattern': re.compile(r'Karel|TP程序|示教器|teach\s*pendant|程序编辑|PROGRAM\s+\w+', re.I),
        'tags': ['编程示教', 'TP操作'],
        'l2': '编程与示教',
        'priority': 8,
    },
    {
        'pattern': re.compile(r'寄存器|位置寄存器|PR\[\d|R\[\d|数值寄存器|DI\[\d|DO\[\d|AI\[\d|AO\[\d', re.I),
        'tags': ['寄存器', '编程示教'],
        'l2': '编程与示教',
        'priority': 7,
    },

    # === PLC ===
    {
        'pattern': re.compile(r'TIA\s*Portal|STEP\s*7|SCL程序|STL程序|PLC程序|功能块FB|功能FC|数据块DB', re.I),
        'tags': ['PLC编程', 'TIA配置'],
        'l2': 'TIA Portal配置',
        'priority': 8,
    },
    {
        'pattern': re.compile(r'SICAR|标准块|SICAR\s*Library|接口定义', re.I),
        'tags': ['SICAR', '标准功能块'],
        'l2': 'SICAR标准块',
        'priority': 8,
    },

    # === IO与通信 (更严格的匹配) ===
    {
        'pattern': re.compile(r'PROFINET|OPC\s*UA|以太网通信|现场总线|DeviceNet|CC-Link', re.I),
        'tags': ['工业通信', '总线协议'],
        'l2': 'IO与通信',
        'priority': 8,
    },
    {
        'pattern': re.compile(r'数字IO|模拟IO|I/O映射|信号分配|IO分配|输入输出模块', re.I),
        'tags': ['IO配置', '信号映射'],
        'l2': 'IO与通信',
        'priority': 7,
    },

    # === 系统配置 ===
    {
        'pattern': re.compile(r'系统变量\$|SYSSERVO|STARTUP|冷启动|热启动|镜像备份|RESTORE', re.I),
        'tags': ['系统配置', '备份恢复'],
        'l2': '系统配置与初始化',
        'priority': 8,
    },
    {
        'pattern': re.compile(r'零点标定|零位校准|MASTERING|参考点|编码器校准', re.I),
        'tags': ['零点标定', '校准'],
        'l2': '系统配置与初始化',
        'priority': 8,
    },

    # === 安全 ===
    {
        'pattern': re.compile(r'安全门|安全回路|急停回路|安全PLC|安全等级|SIL|PLd', re.I),
        'tags': ['安全功能', '安全回路'],
        'l2': '安全与维护',
        'priority': 7,
    },
    {
        'pattern': re.compile(r'定期维护|润滑脂|电池更换|密封圈|减速机|保养周期', re.I),
        'tags': ['定期维护', '保养'],
        'l2': '安全与维护',
        'priority': 7,
    },

    # === 视觉 ===
    {
        'pattern': re.compile(r'iRVision|视觉引导|相机标定|视觉定位|Blob|图案匹配|视觉检测', re.I),
        'tags': ['视觉系统', 'iRVision'],
        'l2': '视觉与传感器',
        'priority': 8,
    },

    # === 外部轴 ===
    {
        'pattern': re.compile(r'变位机|导轨|协调运动|外部轴|E轴组|附加轴', re.I),
        'tags': ['外部轴', '多机协调'],
        'l2': '外部轴与协调',
        'priority': 7,
    },

    # === HMI ===
    {
        'pattern': re.compile(r'WinCC|Unified|SCADA|触摸屏|HMI画面|界面设计', re.I),
        'tags': ['HMI', 'SCADA'],
        'l2': 'WinCC配置',
        'priority': 7,
    },

    # === 焊接 ===
    {
        'pattern': re.compile(r'焊枪|焊接参数|弧焊|点焊|焊缝跟踪|焊接工艺', re.I),
        'tags': ['焊接工艺', '焊枪'],
        'l2': '焊枪配置',
        'priority': 7,
    },

    # === 驱动 ===
    {
        'pattern': re.compile(r'变频器|VFD|G120|S120|伺服驱动器|电机参数', re.I),
        'tags': ['变频器', '驱动控制'],
        'l2': '变频器参数',
        'priority': 7,
    },

    # === 硬件规格 ===
    {
        'pattern': re.compile(r'payload|负载能力|重复定位精度|工作范围|最大行程|cycle\s*time', re.I),
        'tags': ['技术规格', '硬件参数'],
        'l2': '硬件手册',
        'priority': 6,
    },

    # === 夹具 ===
    {
        'pattern': re.compile(r'夹具设计|抓手|末端执行器|工具TCP|换枪盘', re.I),
        'tags': ['夹具', '工具'],
        'l2': '夹具设计',
        'priority': 7,
    },
]

# 按优先级排序
KEYWORD_TAG_RULES.sort(key=lambda r: r['priority'], reverse=True)


def keyword_tag_v2(text: str, category_l1: str) -> dict:
    """更精准的关键词打标。"""
    tags = []
    l2 = None
    matched_priority = -1

    for rule in KEYWORD_TAG_RULES:
        if rule['pattern'].search(text):
            # 只取最高优先级的 category_l2
            if l2 is None or rule['priority'] > matched_priority:
                l2 = rule['l2']
                matched_priority = rule['priority']
            # 合并所有匹配的 tags
            for t in rule['tags']:
                if t not in tags:
                    tags.append(t)
            if len(tags) >= 5:
                break

    if not tags:
        # 默认: 用 category_l1 推断
        default_map = {
            '07_机器人': ('技术文档', '硬件手册'),
            '01_PLC与控制': ('PLC文档', 'TIA Portal配置'),
            '03_电气图纸': ('电气图纸', '线体图纸'),
            '09_项目文档': ('项目文档', '现场程序文档'),
            '05_驱动与传动': ('驱动技术', '变频器参数'),
            '06_安全与传感': ('安全技术', '安全与维护'),
            '04_HMI与SCADA': ('HMI文档', 'WinCC配置'),
            '08_工装夹具': ('工装文档', '夹具设计'),
            '02_视觉系统': ('视觉技术', '视觉与传感器'),
            '10_其他': ('通用文档', '通用参考'),
        }
        default_tag, default_l2 = default_map.get(category_l1, ('通用文档', '通用参考'))
        tags = [default_tag]
        l2 = default_l2

    return {
        'topic_tags': tags[:5],
        'category_l2': l2,
    }


def main():
    parser = argparse.ArgumentParser(description='Phase 2 修复: 精准关键词打标')
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()

    client = chromadb.PersistentClient(path='/home/eric_jia/rag_chromadb')
    col = client.get_collection('wiki_docs')
    total = col.count() if args.limit == 0 else min(args.limit, col.count())
    print(f'处理: {total} chunks')

    stats = {
        'processed': 0,
        'l2': Counter(),
        'tags': Counter(),
    }

    start = time.time()
    offset = 0

    while offset < total:
        batch_size = min(500, total - offset)
        elapsed = time.time() - start
        rate = stats['processed'] / max(elapsed, 0.1)
        print(f'\r{offset}/{total} ({offset*100//max(total,1)}%) | {rate:.0f}/s', end='', flush=True)

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
            tag_result = keyword_tag_v2(text, cat_l1)

            new_meta = dict(meta)
            new_meta['topic_tags'] = json.dumps(tag_result['topic_tags'], ensure_ascii=False)
            new_meta['category_l2'] = tag_result['category_l2']

            stats['processed'] += 1
            stats['l2'][tag_result['category_l2']] += 1
            for t in tag_result['topic_tags']:
                stats['tags'][t] += 1

            update_ids.append(id_)
            update_metas.append(new_meta)

        for i in range(0, len(update_ids), 500):
            col.update(ids=update_ids[i:i+500], metadatas=update_metas[i:i+500])

        offset += len(ids)

    elapsed = time.time() - start
    print(f'\n\n=== 完成 ({elapsed:.1f}s) ===')
    print(f'\n--- 二级分类分布 ---')
    for l2, cnt in stats['l2'].most_common():
        print(f'  {l2}: {cnt} ({cnt*100//max(stats["processed"],1)}%)')

    print(f'\n--- 高频标签 Top 25 ---')
    for tag, cnt in stats['tags'].most_common(25):
        print(f'  {tag}: {cnt}')


if __name__ == '__main__':
    main()
