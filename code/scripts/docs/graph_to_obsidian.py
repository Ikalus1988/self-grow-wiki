#!/usr/bin/env python3
"""
知识图谱 JSON → Obsidian Vault 转换器

输入: knowledge_graph.json
输出: Obsidian vault 目录结构，含 wikilink 互链

策略:
  - 项目页 (14): 主 hub，链接到目录/扩展名/主题
  - 扩展名页: 按项目统计分布
  - 主题/领域页: 链接到相关项目
  - 重要目录页 (50+文件): 列出文件
  - 主索引页 (MOC): 全局导航
"""
import json
import os
import re
from pathlib import Path
from collections import defaultdict, Counter

INPUT = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output/knowledge_graph.json')
VAULT = Path('/mnt/c/Users/hp/Desktop/文件迁移工具/output/obsidian_vault')

def safe_name(s: str) -> str:
    """Obsidian 文件名安全化"""
    return re.sub(r'[<>:"/\\|?*]', '_', s).strip('. ')

def format_size(b):
    if b >= 1024**3: return f'{b/1024**3:.1f} GB'
    if b >= 1024**2: return f'{b/1024**2:.1f} MB'
    if b >= 1024: return f'{b/1024:.1f} KB'
    return f'{b} B'

def main():
    print('=' * 60)
    print('  知识图谱 → Obsidian Vault 转换器')
    print('=' * 60)

    with open(INPUT, 'r', encoding='utf-8') as f:
        g = json.load(f)

    nodes_by_id = {n['id']: n for n in g['nodes']}

    # ── 索引构建 ──
    files = [n for n in g['nodes'] if n['type'] == 'file']
    edges_from = defaultdict(list)  # source → [edges]
    edges_to = defaultdict(list)    # target → [edges]
    for e in g['edges']:
        edges_from[e['source']].append(e)
        edges_to[e['target']].append(e)

    # 从边推导 ext / domain
    file_ext = {}    # file_id → ext
    file_domain = {} # file_id → domain
    for e in g['edges']:
        if e['relation'] == 'has_ext' and e['source'].startswith('file:'):
            ext_node = nodes_by_id.get(e['target'], {})
            file_ext[e['source']] = ext_node.get('name', '(无)')
        elif e['relation'] == 'tagged_domain' and e['source'].startswith('file:'):
            dom_node = nodes_by_id.get(e['target'], {})
            file_domain[e['source']] = dom_node.get('name', '其他')

    # 文件按项目/目录/扩展名分组
    files_by_project = defaultdict(list)
    files_by_dir = defaultdict(list)
    ext_by_project = defaultdict(lambda: Counter())
    dirs_by_project = defaultdict(lambda: Counter())  # project → {dir_id: count}

    for f_node in files:
        fid = f_node['id']
        proj = f_node.get('project', '未分类')
        ext = file_ext.get(fid, '(无)')
        domain = file_domain.get(fid, '其他')
        f_node['_ext'] = ext       # 缓存到节点上
        f_node['_domain'] = domain
        files_by_project[proj].append(f_node)
        ext_by_project[proj][ext] += 1

        for e in edges_from.get(fid, []):
            if e['relation'] == 'belongs_to':
                files_by_dir[e['target']].append(f_node)
                dirs_by_project[proj][e['target']] += 1

    # 清理旧输出
    if VAULT.exists():
        import shutil
        shutil.rmtree(VAULT)

    # 创建子目录
    for sub in ['项目', '目录', '扩展名', '主题', '领域', '索引']:
        (VAULT / sub).mkdir(parents=True, exist_ok=True)

    written = 0

    # ══════════════════════════════════════════════
    # 1. 主索引页 (MOC)
    # ══════════════════════════════════════════════
    total_files = len(files)
    total_size = sum(f['size'] for f in files)
    projects_sorted = sorted(files_by_project.items(), key=lambda x: -len(x[1]))

    moc = f"""# 📊 文件知识图谱 — 总览

> 共 **{total_files:,}** 个文件，**{format_size(total_size)}**
> 生成时间: {g.get('generated', 'N/A')}

---

## 🏗️ 项目分布

| 项目 | 文件数 | 数据量 | 主要格式 |
|------|--------|--------|---------|
"""
    for proj, pfiles in projects_sorted:
        sz = format_size(sum(f['size'] for f in pfiles))
        top_exts = Counter(f.get('_ext', '') for f in pfiles).most_common(3)
        ext_str = ', '.join(f"`{e}`({c})" for e, c in top_exts)
        moc += f"| [[{proj}]] | {len(pfiles):,} | {sz} | {ext_str} |\n"

    moc += f"""
---

## 📁 按类型浏览

- [[索引/按扩展名|按扩展名]] — {len(ext_by_project)} 种文件格式
- [[索引/按主题|按主题]] — 技术/个人/办公/其他
- [[索引/按领域|按领域]] — 开发/前端/CAD/嵌入式...

---

## 🔗 快速入口

"""
    for proj, pfiles in projects_sorted[:5]:
        moc += f"- [[{proj}]] — {len(pfiles):,} 文件\n"

    (VAULT / '索引' / '00_总览.md').write_text(moc, encoding='utf-8')
    written += 1

    # ══════════════════════════════════════════════
    # 2. 项目页 (14 个 hub)
    # ══════════════════════════════════════════════
    for proj, pfiles in projects_sorted:
        sz = format_size(sum(f['size'] for f in pfiles))
        ext_counter = Counter(f.get('_ext', '') for f in pfiles)
        topic_counter = Counter(f.get('topic', '其他') for f in pfiles)
        domain_counter = Counter(f.get('_domain', '其他') for f in pfiles)

        # 该项目下的目录 (按文件数排序)
        proj_dirs = dirs_by_project[proj].most_common(30)

        md = f"""# 🏗️ {proj}

> {len(pfiles):,} 文件 | {sz}

---

## 📂 目录结构 (Top 30)

| 目录 | 文件数 |
|------|--------|
"""
        for dir_id, cnt in proj_dirs:
            dir_name = dir_id.replace('dir:', '')
            # 简化路径显示
            short = dir_name.replace('/mnt/c/Users/hp/', '~/').replace('/mnt/d/', 'D:/')
            # 只取最后两级
            parts = short.replace('\\', '/').split('/')
            display = '/'.join(parts[-2:]) if len(parts) > 2 else short
            safe = safe_name(dir_name)
            if cnt >= 50:
                md += f"| [[{safe}\\|{display}]] | {cnt} |\n"
            else:
                md += f"| {display} | {cnt} |\n"

        md += f"""
---

## 📊 扩展名分布

| 格式 | 数量 | 占比 |
|------|------|------|
"""
        for ext, cnt in ext_counter.most_common(15):
            pct = cnt / len(pfiles) * 100
            md += f"| `{ext or '(无)'}` | {cnt} | {pct:.1f}% |\n"

        md += f"""
---

## 🏷️ 标签

"""
        for topic, cnt in topic_counter.most_common():
            md += f"- [[{topic}]] ({cnt})\n"

        md += "\n"
        for domain, cnt in domain_counter.most_common():
            md += f"- [[{domain}]] ({cnt})\n"

        md += f"""
---

## 📋 文件列表 (前 50)

"""
        for f_node in sorted(pfiles, key=lambda x: -x['size'])[:50]:
            fname = f_node['name']
            fsize = format_size(f_node['size'])
            fext = f_node.get('_ext', '')
            md += f"- `{fname}` ({fsize}) `{fext}`\n"

        if len(pfiles) > 50:
            md += f"\n> ...还有 {len(pfiles) - 50} 个文件\n"

        (VAULT / '项目' / f'{safe_name(proj)}.md').write_text(md, encoding='utf-8')
        written += 1

    # ══════════════════════════════════════════════
    # 3. 重要目录页 (50+ 文件)
    # ══════════════════════════════════════════════
    notable_dirs = [(did, flist) for did, flist in files_by_dir.items() if len(flist) >= 50]
    notable_dirs.sort(key=lambda x: -len(x[1]))

    for dir_id, dir_files in notable_dirs:
        dir_name = dir_id.replace('dir:', '')
        short = dir_name.replace('/mnt/c/Users/hp/', '~/').replace('/mnt/d/', 'D:/')
        proj = dir_files[0].get('project', '未分类')
        sz = format_size(sum(f['size'] for f in dir_files))
        ext_counter = Counter(f.get('_ext', '') for f in dir_files)

        md = f"""# 📂 {short}

> [[{proj}]] | {len(dir_files):,} 文件 | {sz}

---

## 扩展名

"""
        for ext, cnt in ext_counter.most_common(10):
            md += f"- `{ext or '(无)'}`: {cnt}\n"

        md += f"""
---

## 文件 (前 30)

"""
        for f_node in sorted(dir_files, key=lambda x: -x['size'])[:30]:
            md += f"- `{f_node['name']}` ({format_size(f_node['size'])})\n"

        if len(dir_files) > 30:
            md += f"\n> ...还有 {len(dir_files) - 30} 个文件\n"

        (VAULT / '目录' / f'{safe_name(dir_name)}.md').write_text(md, encoding='utf-8')
        written += 1

    # ══════════════════════════════════════════════
    # 4. 扩展名汇总页
    # ══════════════════════════════════════════════
    all_exts = Counter()
    for f_node in files:
        all_exts[f_node.get('_ext', '(无)')] += 1

    ext_page = "# 📎 按扩展名浏览\n\n"
    ext_page += f"> 共 {len(all_exts)} 种文件格式\n\n---\n\n"

    for ext, cnt in all_exts.most_common():
        bar = '█' * min(int(cnt / max(len(files), 1) * 40), 40)
        ext_page += f"- `{ext or '(无)'}`: **{cnt:,}** {bar}\n"

    (VAULT / '索引' / '按扩展名.md').write_text(ext_page, encoding='utf-8')
    written += 1

    # ══════════════════════════════════════════════
    # 5. 主题页 + 领域页
    # ══════════════════════════════════════════════
    topic_files = defaultdict(list)
    domain_files = defaultdict(list)
    for f_node in files:
        topic_files[f_node.get('topic', '其他')].append(f_node)
        domain_files[f_node.get('_domain', '其他')].append(f_node)

    topic_page = "# 🏷️ 按主题浏览\n\n"
    for topic, tfiles in sorted(topic_files.items(), key=lambda x: -len(x[1])):
        proj_counter = Counter(f.get('project', '未分类') for f in tfiles)
        topic_page += f"\n## [[{topic}]] ({len(tfiles):,} 文件)\n\n"
        for proj, cnt in proj_counter.most_common(5):
            topic_page += f"- [[{proj}]]: {cnt}\n"

    (VAULT / '索引' / '按主题.md').write_text(topic_page, encoding='utf-8')
    written += 1

    domain_page = "# 🔧 按领域浏览\n\n"
    for domain, dfiles in sorted(domain_files.items(), key=lambda x: -len(x[1])):
        proj_counter = Counter(f.get('project', '未分类') for f in dfiles)
        domain_page += f"\n## [[{domain}]] ({len(dfiles):,} 文件)\n\n"
        for proj, cnt in proj_counter.most_common(5):
            domain_page += f"- [[{proj}]]: {cnt}\n"

    (VAULT / '索引' / '按领域.md').write_text(domain_page, encoding='utf-8')
    written += 1

    # 主题独立页
    for topic, tfiles in topic_files.items():
        proj_counter = Counter(f.get('project', '未分类') for f in tfiles)
        md = f"# 🏷️ {topic}\n\n> {len(tfiles):,} 文件\n\n---\n\n"
        for proj, cnt in proj_counter.most_common():
            md += f"- [[{proj}]]: {cnt} 文件\n"
        (VAULT / '主题' / f'{safe_name(topic)}.md').write_text(md, encoding='utf-8')
        written += 1

    # 领域独立页
    for domain, dfiles in domain_files.items():
        proj_counter = Counter(f.get('project', '未分类') for f in dfiles)
        md = f"# 🔧 {domain}\n\n> {len(dfiles):,} 文件\n\n---\n\n"
        for proj, cnt in proj_counter.most_common():
            md += f"- [[{proj}]]: {cnt} 文件\n"
        (VAULT / '领域' / f'{safe_name(domain)}.md').write_text(md, encoding='utf-8')
        written += 1

    # ══════════════════════════════════════════════
    # 完成
    # ══════════════════════════════════════════════
    print(f'\n  ✅ 转换完成!')
    print(f'  Vault 路径: {VAULT}')
    print(f'  生成文件数: {written}')
    print(f'  目录结构:')
    for sub in sorted((VAULT / sub) for sub in ['项目', '目录', '扩展名', '主题', '领域', '索引']):
        count = len(list(sub.glob('*.md')))
        print(f'    {sub.name:8} {count:>4} 个 .md')

    print(f'\n  打开方式:')
    print(f'    1. 安装 Obsidian: https://obsidian.md')
    print(f'    2. 打开 Obsidian → Open folder as vault')
    print(f'    3. 选择: {VAULT}')
    print(f'    4. 打开 索引/00_总览.md 开始浏览')
    print(f'    5. Ctrl+G 打开 Graph View 查看关系图')

if __name__ == '__main__':
    main()
