#!/usr/bin/env python3
"""Generate MkDocs site from wiki document library."""

import json
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from urllib.parse import quote

WIKI_ROOT = Path("/mnt/d/知识库wiki")
DOCS_DIR = WIKI_ROOT / "site_docs"
RESULT_FILE = WIKI_ROOT / "00_目录索引" / "classification_result.json"

# Category display names and icons
CATEGORIES = {
    "01_PLC与控制": {"icon": "cpu", "name": "PLC与控制系统"},
    "02_制造标准": {"icon": "book", "name": "制造标准规范"},
    "03_电气图纸": {"icon": "file-text", "name": "电气图纸"},
    "04_HMI与SCADA": {"icon": "monitor", "name": "HMI与SCADA"},
    "05_驱动与传动": {"icon": "zap", "name": "驱动与传动"},
    "06_安全与传感": {"icon": "shield", "name": "安全与传感"},
    "07_机器人": {"icon": "tool", "name": "机器人"},
    "08_工程工具": {"icon": "settings", "name": "工程工具"},
    "09_项目文档": {"icon": "folder", "name": "项目文档"},
    "10_能效与诊断": {"icon": "activity", "name": "能效与诊断"},
}

EXT_ICONS = {
    '.pdf': ':material-file-pdf-box:',
    '.doc': ':material-file-word:',
    '.docx': ':material-file-word:',
    '.ppt': ':material-file-powerpoint:',
    '.pptx': ':material-file-powerpoint:',
    '.xls': ':material-file-excel:',
    '.xlsx': ':material-file-excel:',
}


def format_size(size_bytes):
    if size_bytes < 1024:
        return f'{size_bytes} B'
    elif size_bytes < 1024 * 1024:
        return f'{size_bytes / 1024:.1f} KB'
    else:
        return f'{size_bytes / 1024 / 1024:.1f} MB'


def generate():
    # Load classification result
    with open(str(RESULT_FILE), 'r', encoding='utf-8') as f:
        data = json.load(f)

    documents = data['documents']
    total_scanned = data['total_scanned']
    dedup_removed = data['dedup_removed']
    total_copied = data['total_copied']

    # Create docs directory
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # Group docs by category
    by_category = defaultdict(list)
    for doc in documents:
        if doc.get('dest_path'):
            by_category[doc['category']].append(doc)

    # Group by top-level category
    by_top = defaultdict(lambda: defaultdict(list))
    for cat, docs in by_category.items():
        parts = cat.split('/')
        top = parts[0]
        sub = parts[1] if len(parts) > 1 else ''
        by_top[top][sub] = docs

    # === Generate mkdocs.yml ===
    nav_items = []
    nav_items.append({'首页': 'index.md'})
    nav_items.append({'统计概览': 'stats.md'})

    for top_cat in sorted(by_top.keys()):
        top_info = CATEGORIES.get(top_cat, {"name": top_cat})
        sub_items = []
        subs = by_top[top_cat]

        if '' in subs and len(subs) == 1:
            # No subcategories
            page_name = f"{top_cat}.md"
            sub_items.append({top_info['name']: page_name})
        else:
            # Has subcategories
            cat_items = []
            cat_items.append({'概览': f"{top_cat}/index.md"})
            for sub in sorted(subs.keys()):
                if sub:
                    safe_sub = sub.replace('/', '_')
                    cat_items.append({sub: f"{top_cat}/{safe_sub}.md"})
            sub_items.append({top_info['name']: cat_items})

        nav_items.extend(sub_items)

    mkdocs_yml = f"""site_name: 技术文档知识库
site_description: 工业自动化技术文档分类系统
site_dir: '{str(WIKI_ROOT / "site_build")}'
docs_dir: '{str(DOCS_DIR)}'

theme:
  name: material
  language: zh
  palette:
    - scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: 切换暗色模式
    - scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: 切换亮色模式
  features:
    - navigation.instant
    - navigation.tracking
    - navigation.sections
    - navigation.expand
    - navigation.top
    - search.suggest
    - search.highlight
    - toc.follow

plugins:
  - search:
      lang:
        - zh
        - en

markdown_extensions:
  - tables
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - attr_list
  - pymdownx.emoji:
      emoji_index: !!python/name:material.extensions.emoji.twemoji
      emoji_generator: !!python/name:material.extensions.emoji.to_svg
  - toc:
      permalink: true

nav:
"""
    import yaml

    # Write mkdocs.yml
    yml_path = WIKI_ROOT / "mkdocs.yml"
    with open(str(yml_path), 'w', encoding='utf-8') as f:
        f.write(f"""site_name: 技术文档知识库
site_description: 工业自动化技术文档分类系统
site_dir: '{str(WIKI_ROOT / "site_build")}'
docs_dir: '{str(DOCS_DIR)}'

theme:
  name: material
  language: zh
  palette:
    - scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-7
        name: 切换暗色模式
    - scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/brightness-4
        name: 切换亮色模式
  features:
    - navigation.instant
    - navigation.tracking
    - navigation.sections
    - navigation.expand
    - navigation.top
    - search.suggest
    - search.highlight
    - toc.follow

plugins:
  - search:
      lang:
        - zh
        - en

markdown_extensions:
  - tables
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - attr_list
  - pymdownx.emoji:
      emoji_index: !!python/name:material.extensions.emoji.twemoji
      emoji_generator: !!python/name:material.extensions.emoji.to_svg
  - toc:
      permalink: true

""")
        # Write nav manually
        f.write("nav:\n")
        f.write("  - 首页: index.md\n")
        f.write("  - 统计概览: stats.md\n")

        for top_cat in sorted(by_top.keys()):
            top_info = CATEGORIES.get(top_cat, {"name": top_cat})
            subs = by_top[top_cat]
            f.write(f"  - {top_info['name']}:\n")
            f.write(f"    - 概览: {top_cat}/index.md\n")
            for sub in sorted(subs.keys()):
                if sub:
                    safe_sub = sub.replace('/', '_')
                    f.write(f"    - {sub}: {top_cat}/{safe_sub}.md\n")

    # === Generate index.md (home page) ===
    total_size = sum(d['size'] for d in documents if d.get('dest_path'))
    index_md = f"""# 技术文档知识库

> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} | 共 **{total_copied}** 份文档 | **{format_size(total_size)}**

本知识库收录了本机 C: 和 D: 盘上的全部工业自动化技术文档，经过智能分类和去重处理。

## 分类导航

| 分类 | 文件数 | 描述 |
|------|--------|------|
"""
    for top_cat in sorted(by_top.keys()):
        top_info = CATEGORIES.get(top_cat, {"name": top_cat})
        count = sum(len(docs) for docs in by_top[top_cat].values())
        subs = ', '.join(s for s in sorted(by_top[top_cat].keys()) if s)
        index_md += f"| [{top_info['name']}]({top_cat}/index.md) | {count} | {subs} |\n"

    index_md += f"""
## 快速统计

- 扫描文档总数: **{total_scanned}**
- 去重移除: **{dedup_removed}** ({dedup_removed*100//total_scanned}%)
- 最终入库: **{total_copied}**

!!! tip "使用方法"
    点击左侧导航栏浏览各分类，或使用顶部搜索框搜索文档名称。
    文档路径指向 `D:\\知识库wiki\\` 下的本地文件，可直接在文件管理器中打开。
"""
    write_page(DOCS_DIR / "index.md", index_md)

    # === Generate stats.md ===
    stats_md = f"""# 统计概览

## 总体统计

| 指标 | 数值 |
|------|------|
| 扫描文档总数 | {total_scanned} |
| 去重移除数 | {dedup_removed} |
| 最终入库数 | {total_copied} |
| 总大小 | {format_size(total_size)} |

## 各分类文件数

| 分类 | 子分类 | 文件数 | 大小 |
|------|--------|--------|------|
"""
    for top_cat in sorted(by_top.keys()):
        top_info = CATEGORIES.get(top_cat, {"name": top_cat})
        for sub in sorted(by_top[top_cat].keys()):
            docs = by_top[top_cat][sub]
            sub_size = sum(d['size'] for d in docs)
            display_sub = sub if sub else '(全部)'
            stats_md += f"| {top_info['name']} | {display_sub} | {len(docs)} | {format_size(sub_size)} |\n"

    stats_md += f"""
## 文件类型分布

| 类型 | 数量 |
|------|------|
"""
    ext_counts = defaultdict(int)
    for doc in documents:
        if doc.get('dest_path'):
            ext = os.path.splitext(doc['name'])[1].lower()
            ext_counts[ext] += 1
    for ext, count in sorted(ext_counts.items(), key=lambda x: -x[1]):
        stats_md += f"| {ext} | {count} |\n"

    write_page(DOCS_DIR / "stats.md", stats_md)

    # === Generate category pages ===
    for top_cat in sorted(by_top.keys()):
        top_info = CATEGORIES.get(top_cat, {"name": top_cat})
        cat_dir = DOCS_DIR / top_cat
        cat_dir.mkdir(parents=True, exist_ok=True)

        # Index page for category
        subs = by_top[top_cat]
        total_cat = sum(len(docs) for docs in subs.values())

        cat_index = f"# {top_info['name']}\n\n"
        cat_index += f"共 **{total_cat}** 份文档\n\n"

        if len(subs) > 1 or (len(subs) == 1 and '' not in subs):
            cat_index += "## 子分类\n\n"
            cat_index += "| 子分类 | 文件数 |\n|--------|--------|\n"
            for sub in sorted(subs.keys()):
                if sub:
                    safe_sub = sub.replace('/', '_')
                    cat_index += f"| [{sub}]({safe_sub}.md) | {len(subs[sub])} |\n"
            cat_index += "\n"

        # If there are docs directly in this category (no sub)
        if '' in subs:
            cat_index += doc_table(subs[''], top_cat)

        write_page(cat_dir / "index.md", cat_index)

        # Sub-category pages
        for sub in sorted(subs.keys()):
            if sub:
                safe_sub = sub.replace('/', '_')
                docs = subs[sub]
                page = f"# {sub}\n\n"
                page += f"> 属于 [{top_info['name']}](index.md) | 共 **{len(docs)}** 份文档\n\n"
                page += doc_table(docs, f"{top_cat}/{sub}")
                write_page(cat_dir / f"{safe_sub}.md", page)

    print(f"MkDocs 项目已生成:")
    print(f"  配置文件: {yml_path}")
    print(f"  文档目录: {DOCS_DIR}")
    print(f"  页面数: {count_files(DOCS_DIR, '.md')}")


def doc_table(docs, category_path):
    """Generate a markdown table for a list of documents."""
    lines = []
    lines.append("| 文件名 | 类型 | 大小 | 修改日期 | 原始路径 |")
    lines.append("|--------|------|------|----------|----------|")

    for doc in sorted(docs, key=lambda d: d['name']):
        ext = os.path.splitext(doc['name'])[1].lower()
        icon = EXT_ICONS.get(ext, ':material-file:')
        size = format_size(doc['size'])
        mdate = datetime.fromtimestamp(doc['mtime']).strftime('%Y-%m-%d')
        orig = doc['original_path'].replace('/mnt/c/', 'C:\\\\').replace('/mnt/d/', 'D:\\\\').replace('/', '\\\\')
        # Link to wiki copy
        dest = doc.get('dest_path', '')
        if dest:
            wiki_path = dest.replace('/mnt/d/知识库wiki/', '').replace('/', '\\\\')
            lines.append(f"| {icon} {doc['name']} | {ext} | {size} | {mdate} | `{orig}` |")
        else:
            lines.append(f"| {icon} {doc['name']} | {ext} | {size} | {mdate} | `{orig}` |")

    lines.append("")
    return '\n'.join(lines)


def write_page(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), 'w', encoding='utf-8') as f:
        f.write(content)


def count_files(directory, ext):
    count = 0
    for root, dirs, files in os.walk(str(directory)):
        for f in files:
            if f.endswith(ext):
                count += 1
    return count


if __name__ == '__main__':
    generate()
