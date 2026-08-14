#!/usr/bin/env python3
"""
文件打标整理迁移系统 v4（合并版）
==================================
全盘扫描 → 6维RAG打标 → 工业分类 → 三层去重 → 交互审核 → 打包ZIP → 飞书上传
用途：整理旧电脑全部资料 → 飞书上传 → 新电脑下载使用

运行（交互模式）：python doc_classifier.py
运行（自动模式）：python doc_classifier.py --auto
指定盘符：      python doc_classifier.py --drives C,D
打包ZIP：       python doc_classifier.py --package
"""

import os
import sys
import csv
import re
import json
import hashlib
import shutil
import zipfile
import string
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict, field

# ============================================================
#  6维RAG标签
# ============================================================

@dataclass
class Tags6D:
    topic: str      # 技术/办公/个人/教育/其他
    doc_type: str   # 代码/配置/文档/数据/设计/媒体/压缩包/其他
    domain: str     # 开发/前端/后端/嵌入式/运维/数据/AI/办公/其他
    priority: str   # 高/中/低
    time_tag: str   # 长期有效/不确定/可能过时
    source: str     # 个人创作/项目产出/下载资料/系统生成/未知

EXT_MAP = {
    # 代码
    '.py':Tags6D('技术','代码','开发','高','长期有效','个人创作'),'.pyw':Tags6D('技术','代码','开发','高','长期有效','个人创作'),
    '.js':Tags6D('技术','代码','前端','高','长期有效','个人创作'),'.ts':Tags6D('技术','代码','前端','高','长期有效','个人创作'),
    '.jsx':Tags6D('技术','代码','前端','高','长期有效','个人创作'),'.tsx':Tags6D('技术','代码','前端','高','长期有效','个人创作'),
    '.vue':Tags6D('技术','代码','前端','中','长期有效','个人创作'),'.svelte':Tags6D('技术','代码','前端','中','长期有效','个人创作'),
    '.java':Tags6D('技术','代码','后端','高','长期有效','个人创作'),'.kt':Tags6D('技术','代码','后端','高','长期有效','个人创作'),
    '.c':Tags6D('技术','代码','嵌入式','高','长期有效','个人创作'),'.cpp':Tags6D('技术','代码','嵌入式','高','长期有效','个人创作'),
    '.h':Tags6D('技术','代码','嵌入式','高','长期有效','个人创作'),'.hpp':Tags6D('技术','代码','嵌入式','高','长期有效','个人创作'),
    '.cs':Tags6D('技术','代码','开发','高','长期有效','个人创作'),'.go':Tags6D('技术','代码','后端','高','长期有效','个人创作'),
    '.rs':Tags6D('技术','代码','后端','高','长期有效','个人创作'),'.php':Tags6D('技术','代码','后端','高','长期有效','个人创作'),
    '.swift':Tags6D('技术','代码','开发','高','长期有效','个人创作'),'.rb':Tags6D('技术','代码','后端','高','长期有效','个人创作'),
    '.r':Tags6D('技术','代码','数据','高','长期有效','个人创作'),'.lua':Tags6D('技术','代码','开发','中','长期有效','个人创作'),
    '.m':Tags6D('技术','代码','开发','高','长期有效','个人创作'),'.dart':Tags6D('技术','代码','开发','高','长期有效','个人创作'),
    '.sh':Tags6D('技术','代码','运维','高','长期有效','个人创作'),'.bat':Tags6D('技术','代码','运维','高','长期有效','个人创作'),
    '.ps1':Tags6D('技术','代码','运维','高','长期有效','个人创作'),'.cmd':Tags6D('技术','代码','运维','中','长期有效','个人创作'),
    '.sql':Tags6D('技术','代码','数据','高','长期有效','个人创作'),
    '.html':Tags6D('技术','代码','前端','中','长期有效','个人创作'),'.css':Tags6D('技术','代码','前端','中','长期有效','个人创作'),
    # 配置
    '.json':Tags6D('技术','配置','开发','中','长期有效','个人创作'),'.yaml':Tags6D('技术','配置','开发','中','长期有效','个人创作'),
    '.yml':Tags6D('技术','配置','开发','中','长期有效','个人创作'),'.toml':Tags6D('技术','配置','开发','中','长期有效','个人创作'),
    '.ini':Tags6D('技术','配置','运维','中','长期有效','个人创作'),'.cfg':Tags6D('技术','配置','运维','中','长期有效','个人创作'),
    '.conf':Tags6D('技术','配置','运维','中','长期有效','个人创作'),'.env':Tags6D('技术','配置','运维','高','长期有效','个人创作'),
    '.xml':Tags6D('技术','配置','开发','低','不确定','系统生成'),
    '.sln':Tags6D('技术','配置','开发','高','长期有效','项目产出'),'.csproj':Tags6D('技术','配置','开发','高','长期有效','项目产出'),
    # 文档
    '.doc':Tags6D('办公','文档','办公','中','不确定','个人创作'),'.docx':Tags6D('办公','文档','办公','中','不确定','个人创作'),
    '.pdf':Tags6D('办公','文档','办公','中','不确定','下载资料'),'.txt':Tags6D('办公','文档','办公','低','不确定','个人创作'),
    '.md':Tags6D('技术','文档','开发','高','长期有效','个人创作'),'.rst':Tags6D('技术','文档','开发','中','长期有效','个人创作'),
    '.odt':Tags6D('办公','文档','办公','中','不确定','个人创作'),'.rtf':Tags6D('办公','文档','办公','低','不确定','个人创作'),
    '.tex':Tags6D('技术','文档','开发','高','长期有效','个人创作'),'.epub':Tags6D('教育','文档','其他','中','长期有效','下载资料'),
    '.ppt':Tags6D('办公','文档','办公','中','可能过时','个人创作'),'.pptx':Tags6D('办公','文档','办公','中','不确定','个人创作'),
    # 数据
    '.xlsx':Tags6D('办公','数据','办公','中','不确定','个人创作'),'.xls':Tags6D('办公','数据','办公','中','可能过时','个人创作'),
    '.csv':Tags6D('技术','数据','数据','中','不确定','项目产出'),'.ipynb':Tags6D('技术','数据','AI','高','长期有效','个人创作'),
    '.jsonl':Tags6D('技术','数据','AI','高','不确定','项目产出'),
    '.pkl':Tags6D('技术','数据','AI','高','不确定','项目产出'),'.npy':Tags6D('技术','数据','AI','高','长期有效','项目产出'),
    '.pt':Tags6D('技术','数据','AI','高','长期有效','项目产出'),'.pth':Tags6D('技术','数据','AI','高','长期有效','项目产出'),
    '.onnx':Tags6D('技术','数据','AI','高','长期有效','项目产出'),'.safetensors':Tags6D('技术','数据','AI','高','长期有效','项目产出'),
    '.db':Tags6D('技术','数据','数据','中','不确定','系统生成'),'.sqlite':Tags6D('技术','数据','数据','中','不确定','项目产出'),
    '.mdb':Tags6D('办公','数据','办公','中','可能过时','个人创作'),
    # 设计
    '.psd':Tags6D('个人','设计','其他','中','长期有效','个人创作'),'.ai':Tags6D('个人','设计','其他','中','长期有效','个人创作'),
    '.fig':Tags6D('个人','设计','其他','中','长期有效','个人创作'),'.svg':Tags6D('技术','设计','前端','中','长期有效','个人创作'),
    # 媒体
    '.jpg':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),'.jpeg':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),
    '.png':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),'.gif':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),
    '.bmp':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),'.tiff':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),
    '.heic':Tags6D('个人','媒体','其他','中','长期有效','个人创作'),'.webp':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),
    '.mp4':Tags6D('个人','媒体','其他','中','长期有效','个人创作'),'.avi':Tags6D('个人','媒体','其他','中','长期有效','个人创作'),
    '.mkv':Tags6D('个人','媒体','其他','中','长期有效','个人创作'),'.mov':Tags6D('个人','媒体','其他','中','长期有效','个人创作'),
    '.mp3':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),'.wav':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),
    '.flac':Tags6D('个人','媒体','其他','低','长期有效','个人创作'),
    # 压缩包
    '.zip':Tags6D('技术','压缩包','其他','中','不确定','下载资料'),'.rar':Tags6D('技术','压缩包','其他','中','不确定','下载资料'),
    '.7z':Tags6D('技术','压缩包','其他','中','不确定','下载资料'),'.tar':Tags6D('技术','压缩包','其他','中','不确定','下载资料'),
    '.gz':Tags6D('技术','压缩包','其他','中','不确定','下载资料'),'.iso':Tags6D('技术','压缩包','其他','中','不确定','下载资料'),
}

TYPE_TO_DIR = {
    '代码':   '01_技术/代码',
    '配置':   '01_技术/配置',
    '文档':   '02_文档/办公文档',
    '数据':   '02_文档/数据文件',
    '设计':   '03_设计',
    '媒体':   '04_媒体',
    '压缩包': '05_压缩包',
}

# ============================================================
#  工业分类（PDF/Office 专用）
# ============================================================

INDUSTRIAL_CATEGORIES = [
    '01_PLC与控制', '02_制造标准', '03_电气图纸', '04_HMI与SCADA',
    '05_驱动与传动', '06_安全与传感', '07_机器人', '08_工程工具',
    '09_项目文档', '10_其他',
]

DOC_EXTENSIONS = {'.pdf', '.doc', '.docx', '.docm', '.xls', '.xlsx', '.xlsm', '.xlsb', '.ppt', '.pptx', '.pptm'}

def classify_industrial(filepath):
    """对 PDF/Office 文件做工业领域二级分类"""
    path = filepath.replace('\\', '/').lower()
    name = os.path.basename(filepath)
    name_l = name.lower()

    if 'sicar' in path: return '01_PLC与控制'
    if any(x in path for x in ['micar', 'plc标准块', 'plc_template']):
        return '09_项目文档' if ('信号表' in name or 'interface' in name_l) else '01_PLC与控制'
    if any(x in path for x in ['tia portal', 'tia_portal', 'plcsim']): return '01_PLC与控制'
    if re.search(r'[Tt][Ss]-\d{4,}', name) or re.search(r'[Bb][Mm][Ss]-\d{4,}', name): return '02_制造标准'
    if re.search(r'==BP[12]', name) or re.search(r'==BP[12]', path): return '03_电气图纸'
    if any(x in path for x in ['wincc', 'unified']): return '04_HMI与SCADA'
    if 'scada' in path: return '04_HMI与SCADA'
    if any(x in (name_l + ' ' + path) for x in ['g120', 'cu250', 'sinamics', 'startdrive']): return '05_驱动与传动'
    if any(x in (name_l + ' ' + path) for x in ['pilz', 'euchner', 'profisafe', 'safety door']): return '06_安全与传感'
    if ('f_' in name_l[:3] and len(name_l) > 5) or any(x in path for x in ['fanuc', 'kuka', 'abb']): return '07_机器人'
    if '机器人' in path or 'robot' in path: return '07_机器人'
    if 'eplan' in path: return '08_工程工具'
    if any(x in path for x in ['cad', 'autocad', 'solidworks']): return '08_工程工具'
    if '信号表' in name or 'interface' in name_l: return '09_项目文档'
    if any(x in path for x in ['geely', 'volvo', '小米', 'xiaomi', 'xiaopeng']): return '09_项目文档'
    if any(x in path for x in ['B1现场', 'B2现场', '互传']): return '09_项目文档'
    if '供应商' in path or '验收' in path: return '09_项目文档'
    return '10_其他'

# ============================================================
#  扫描配置
# ============================================================

EXCLUDE_DIRS = {
    'Windows', 'Program Files', 'Program Files (x86)', 'ProgramData',
    'AppData', '$Recycle.Bin', 'Recovery', 'PerfLogs', 'boot',
    'WindowsApps', 'node_modules', '.git', '__pycache__',
    '.venv', 'venv', '.vscode', '.cache',
    'Temp', 'Tmp', 'CrashDumps', 'Logs',
    'Intel', 'NVIDIA', 'AMD', 'MSOCache',
    'System Volume Information', '$WinREAgent', '$WINDOWS.~BT',
}

JUNK_KEYWORDS = [
    'MsgAttach', 'Applet', 'Emoji', 'xweb_plugins',
    'Thumb', 'thumb', '~$', '~WRL', '~DF',
    'SteamApps', 'EpicGames', 'minecraft', 'Baldur',
    'site-packages', 'matplotlib', 'tkinter',
    '保险', '理赔', '聊天记录',
    'CrashDump', 'Thumbs.db', 'desktop.ini',
    'Licenses/', 'OpenSourceSoftware/', 'ThirdPartyNotices',
]

SKIP_EXTS = {
    '.tmp', '.bak', '.swp', '.lnk', '.log',
    '.exe', '.msi', '.dll', '.sys', '.ocx', '.tlb',
    '.ls', '.va', '.vr', '.dg', '.fvr', '.dt', '.stm',
    '.pc', '.sv', '.li', '.tp', '.pm', '.pac', '.pmc',
    '.al16', '.zal16', '.plf', '.idx', '.jt',
    '.frw', '.bin', '.cm', '.xvr', '.tx',
    '.ot', '.plugin', '.cyt', '.app',
}

MIN_FILE_SIZE = 512
MAX_SCAN_SIZE = 10 * 1024 * 1024 * 1024

# C: 盘只扫用户目录
USER_ROOTS = [
    r'Users\{username}\Desktop',
    r'Users\{username}\Documents',
    r'Users\{username}\Downloads',
    r'Users\{username}\OneDrive',
    r'Users\{username}\xwechat_files',
    r'Users\{username}\Documents\WeChat Files',
]

# ============================================================
#  工具函数
# ============================================================

def format_size(b):
    if b >= 1024**3: return f"{b/1024**3:.1f} GB"
    if b >= 1024**2: return f"{b/1024**2:.1f} MB"
    if b >= 1024:    return f"{b/1024:.1f} KB"
    return f"{b} B"

def detect_drives():
    """自动检测盘符（Windows + WSL）"""
    drives = []
    is_win = (os.name == 'nt')
    if is_win:
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive = f"{string.ascii_uppercase[i]}:\\"
                    if os.path.exists(drive):
                        drives.append(drive)
        except Exception:
            pass
    else:
        for letter in string.ascii_uppercase:
            mount = f"/mnt/{letter.lower()}"
            if os.path.isdir(mount) and os.access(mount, os.R_OK):
                try:
                    if any(os.listdir(mount)):
                        drives.append(mount)
                except PermissionError:
                    pass
    return drives

def detect_username():
    for var in ['USERNAME', 'USER', 'LOGNAME']:
        name = os.environ.get(var)
        if name:
            return name
    return os.path.basename(os.path.expanduser('~'))

def should_exclude(path_str):
    p = path_str.replace('\\', '/').lower()
    parts = p.split('/')
    for pat in EXCLUDE_DIRS:
        if pat.lower() in parts:
            return True
    for kw in JUNK_KEYWORDS:
        kw_l = kw.lower()
        if '/' in kw_l:
            if kw_l in p:
                return True
        else:
            for part in parts:
                if kw_l in part:
                    return True
    return False

def file_quick_hash(filepath, chunk_size=8192):
    """快速哈希（大小+首尾内容），用于去重"""
    h = hashlib.md5()
    try:
        size = os.path.getsize(filepath)
        h.update(str(size).encode())
        with open(filepath, 'rb') as f:
            h.update(f.read(min(chunk_size, size)))
        return h.hexdigest()
    except Exception:
        return ''

def get_tags_6d(ext, filepath, size):
    """获取6维RAG标签"""
    ext_l = ext.lower()
    if ext_l in EXT_MAP:
        tags = EXT_MAP[ext_l]
    else:
        tags = Tags6D('其他','其他','其他','低','不确定','未知')
        p = filepath.lower()
        if any(kw in p for kw in ['project','项目','work','工作','dev','开发','github']):
            tags = Tags6D('技术','其他','开发','中','不确定','项目产出')
        elif any(kw in p for kw in ['personal','个人','私人','照片','photo']):
            tags = Tags6D('个人','媒体','其他','中','长期有效','个人创作')
        elif any(kw in p for kw in ['download','下载','百度网盘']):
            tags = Tags6D('其他','其他','其他','低','不确定','下载资料')
    # 路径覆盖 source
    p = filepath.lower()
    if any(kw in p for kw in ['download','下载','百度网盘','baidu']):
        if tags.source in ('下载资料','未知','系统生成'):
            tags = Tags6D(tags.topic, tags.doc_type, tags.domain, tags.priority, tags.time_tag, '下载资料')
    # 大文件提升优先级
    if size > 100 * 1024 * 1024 and tags.priority != '高':
        tags.priority = '中'
    return tags

# ============================================================
#  扫描
# ============================================================

def scan_all(drives=None):
    """全盘扫描，返回文件列表"""
    if drives is None:
        drives = detect_drives()
    username = detect_username()
    is_win = (os.name == 'nt')

    # 确定扫描路径
    scan_paths = []
    for drive in drives:
        if is_win:
            drive_upper = drive[0].upper()
        else:
            drive_upper = drive[-1].upper()

        if drive_upper == 'C':
            # C盘只扫用户目录
            if is_win:
                for rel in USER_ROOTS:
                    full = os.path.join(drive, rel.format(username=username))
                    if os.path.isdir(full):
                        scan_paths.append(full)
            else:
                for rel in USER_ROOTS:
                    full = os.path.join(drive, rel.format(username=username))
                    if os.path.isdir(full):
                        scan_paths.append(full)
        else:
            scan_paths.append(drive)

    print(f"[1/5] 扫描文件...")
    print(f"  盘符: {', '.join(drives)}")
    print(f"  用户: {username}")
    print(f"  扫描路径: {len(scan_paths)} 个")
    print()

    files = []
    total_scanned = 0
    skipped = 0
    seen_hash = set()
    dupes = 0

    for scan_dir in scan_paths:
        scan_path = Path(scan_dir) if not isinstance(scan_dir, Path) else scan_dir
        if not scan_path.exists():
            continue
        display = str(scan_path)
        if len(display) > 60:
            display = '...' + display[-57:]
        print(f"  扫描: {display} ...", end='', flush=True)

        count_before = len(files)
        try:
            for entry in scan_path.rglob('*'):
                if not entry.is_file():
                    continue
                total_scanned += 1
                if total_scanned % 10000 == 0:
                    print(f"\n    已扫描 {total_scanned:,} ...", end='', flush=True)

                fp = str(entry)
                if should_exclude(fp):
                    skipped += 1
                    continue
                try:
                    size = entry.stat().st_size
                except Exception:
                    skipped += 1
                    continue
                if size < MIN_FILE_SIZE or size > MAX_SCAN_SIZE:
                    skipped += 1
                    continue
                ext = entry.suffix
                if ext.lower() in SKIP_EXTS:
                    skipped += 1
                    continue

                # 快速哈希去重
                h = file_quick_hash(fp)
                if h and h in seen_hash:
                    dupes += 1
                    skipped += 1
                    continue
                if h:
                    seen_hash.add(h)

                mtime = datetime.fromtimestamp(entry.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
                tags = get_tags_6d(ext, fp, size)

                doc = {
                    'path': fp,
                    'name': entry.name,
                    'ext': ext,
                    'size': size,
                    'mtime': mtime,
                    'tags': tags,
                    'industrial': classify_industrial(fp) if ext.lower() in DOC_EXTENSIONS else None,
                    'include': True,
                }
                files.append(doc)
        except Exception as e:
            print(f" 错误: {e}")

        added = len(files) - count_before
        print(f" +{added}")

    print(f"\n  扫描完成: 总计 {total_scanned:,}, 有效 {len(files):,}, 跳过 {skipped:,}, 去重 {dupes:,}")

    # 分类统计
    topic_stats = Counter(d['tags'].topic for d in files)
    type_stats = Counter(d['tags'].doc_type for d in files)
    prio_stats = Counter(d['tags'].priority for d in files)

    print()
    print(f"  按主题: {dict(topic_stats)}")
    print(f"  按类型: {dict(type_stats)}")
    print(f"  按优先级: {dict(prio_stats)}")

    # 工业分类统计
    ind_stats = Counter(d['industrial'] for d in files if d['industrial'])
    if ind_stats:
        print(f"  工业分类(PDF/Office): {dict(ind_stats)}")

    return files, total_scanned, dupes

# ============================================================
#  交互审核
# ============================================================

def interactive_review(files):
    """交互式审核"""
    print()
    print("=" * 60)
    print("  [2/5] 交互审核 — 检查扫描结果")
    print("=" * 60)
    print()

    while True:
        included = [d for d in files if d['include']]
        excluded = [d for d in files if not d['include']]
        total_size = sum(d['size'] for d in included)

        print(f"  当前: {len(included)} 保留, {len(excluded)} 排除, 总大小 {format_size(total_size)}")
        print()

        # 按 doc_type 显示
        type_stats = Counter(d['tags'].doc_type for d in included)
        type_sizes = defaultdict(int)
        for d in included:
            type_stats_key = d['tags'].doc_type
            type_sizes[type_stats_key] += d['size']

        print(f"  {'#':<4} {'类型':<12} {'文件数':>8} {'大小':>10}")
        print(f"  {'─'*4} {'─'*12} {'─'*8} {'─'*10}")
        types_sorted = sorted(type_stats.keys())
        for i, t in enumerate(types_sorted, 1):
            print(f"  {i:<4} {t:<12} {type_stats[t]:>8} {format_size(type_sizes[t]):>10}")

        # 工业分类
        ind_stats = Counter(d['industrial'] for d in included if d['industrial'])
        if ind_stats:
            print()
            print(f"  工业分类 (PDF/Office):")
            for cat, cnt in ind_stats.most_common():
                print(f"    {cat}: {cnt}")

        print()
        print("  操作:")
        print("    [回车]     确认继续")
        print("    l <#>      列出某类型文件详情")
        print("    e <#>      排除某类型全部文件")
        print("    r <#>      恢复某类型")
        print("    x <关键词>  排除匹配的文件")
        print("    json       导出JSON手动编辑")
        print("    q          退出")
        print()

        choice = input("  操作: ").strip()

        if choice == '' or choice.lower() in ('ok', 'y', 'yes'):
            break
        elif choice.lower() == 'q':
            print("  已取消。")
            sys.exit(0)

        elif choice.lower() == 'json':
            manifest_path = os.path.join(os.environ.get('TEMP', '/tmp'), 'file_manifest.json')
            manifest = []
            for d in files:
                manifest.append({
                    'name': d['name'], 'path': d['path'],
                    'doc_type': d['tags'].doc_type, 'topic': d['tags'].topic,
                    'domain': d['tags'].domain, 'priority': d['tags'].priority,
                    'industrial': d['industrial'],
                    'include': d['include'], 'size': d['size'],
                })
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            print(f"  已导出: {manifest_path}")
            print(f"  编辑 include (true/false) 或 industrial 字段，保存后回车重新加载")
            input("  编辑完成按回车...")
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    edited = json.load(f)
                lookup = {(d['name'], d['path']): d for d in files}
                for item in edited:
                    key = (item['name'], item['path'])
                    if key in lookup:
                        lookup[key]['include'] = item.get('include', True)
                        ind = item.get('industrial')
                        if ind in INDUSTRIAL_CATEGORIES:
                            lookup[key]['industrial'] = ind
                print(f"  已加载 {len(edited)} 条")
            except Exception as e:
                print(f"  加载失败: {e}")
            print()

        elif choice.lower().startswith('l '):
            try:
                idx = int(choice.split()[1]) - 1
                if 0 <= idx < len(types_sorted):
                    target = types_sorted[idx]
                    items = [d for d in files if d['tags'].doc_type == target and d['include']]
                    print(f"\n  {target} — {len(items)} 个文件:")
                    for j, d in enumerate(items[:50], 1):
                        prio = d['tags'].priority
                        ind = f" [{d['industrial']}]" if d['industrial'] else ""
                        print(f"    {j:>4}. [{prio}] {d['name'][:50]}{ind}  {format_size(d['size'])}")
                    if len(items) > 50:
                        print(f"    ... 还有 {len(items)-50} 个")
                    print()
            except (ValueError, IndexError):
                print("  格式: l <编号>")

        elif choice.lower().startswith('e '):
            try:
                idx = int(choice.split()[1]) - 1
                if 0 <= idx < len(types_sorted):
                    target = types_sorted[idx]
                    cnt = sum(1 for d in files if d['tags'].doc_type == target and d['include'])
                    for d in files:
                        if d['tags'].doc_type == target:
                            d['include'] = False
                    print(f"  已排除 {target} 的 {cnt} 个文件")
            except (ValueError, IndexError):
                print("  格式: e <编号>")
            print()

        elif choice.lower().startswith('r '):
            try:
                idx = int(choice.split()[1]) - 1
                if 0 <= idx < len(types_sorted):
                    target = types_sorted[idx]
                    cnt = sum(1 for d in files if d['tags'].doc_type == target and not d['include'])
                    for d in files:
                        if d['tags'].doc_type == target:
                            d['include'] = True
                    print(f"  已恢复 {target} 的 {cnt} 个文件")
            except (ValueError, IndexError):
                print("  格式: r <编号>")
            print()

        elif choice.lower().startswith('x '):
            keyword = choice[2:].strip().lower()
            cnt = 0
            for d in files:
                if d['include'] and (keyword in d['name'].lower() or keyword in d['path'].lower()):
                    d['include'] = False
                    cnt += 1
            print(f"  已排除匹配 '{keyword}' 的 {cnt} 个文件")
            print()

        else:
            print("  未知操作")
            print()

    final = [d for d in files if d['include']]
    print(f"\n  审核完成: {len(final)} 个文件将被拷贝")
    return final

# ============================================================
#  拷贝
# ============================================================

def copy_files(files, output_root):
    """拷贝文件到分类目录"""
    print()
    print(f"[3/5] 拷贝文件到 {output_root} ...")

    copied = 0
    errors = []

    for doc in files:
        tags = doc['tags']
        type_dir = TYPE_TO_DIR.get(tags.doc_type, '06_待确认')
        priority_dir = {'高':'高优先级', '中':'中优先级', '低':'低优先级'}.get(tags.priority, '待评估')
        dest_dir = os.path.join(output_root, type_dir, priority_dir)
        os.makedirs(dest_dir, exist_ok=True)

        dest_file = os.path.join(dest_dir, doc['name'])
        if os.path.exists(dest_file):
            stem, ext = os.path.splitext(doc['name'])
            counter = 1
            while os.path.exists(dest_file):
                dest_file = os.path.join(dest_dir, f"{stem}_{counter}{ext}")
                counter += 1

        try:
            shutil.copy2(doc['path'], dest_file)
            doc['dest'] = dest_file
            copied += 1
        except Exception as e:
            errors.append({'path': doc['path'], 'error': str(e)})
            doc['dest'] = None

        if copied % 500 == 0 and copied > 0:
            print(f"  已拷贝 {copied}/{len(files)} ...", flush=True)

    print(f"  成功: {copied}, 错误: {len(errors)}")
    return copied, errors

# ============================================================
#  报告
# ============================================================

def generate_reports(files, total_scanned, dupes, errors, output_root):
    """生成 Markdown + JSON + CSV 报告"""
    print()
    print(f"[4/5] 生成报告...")

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    copied_files = [d for d in files if d.get('dest')]
    total_size = sum(d['size'] for d in copied_files)

    report_dir = os.path.join(output_root, '00_目录索引')
    os.makedirs(report_dir, exist_ok=True)

    # === CSV ===
    csv_path = os.path.join(report_dir, 'file_report.csv')
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['文件名','大小','原始路径','目标路径','修改时间',
                     'topic','doc_type','domain','priority','time_tag','source','工业分类'])
        for d in copied_files:
            t = d['tags']
            w.writerow([d['name'], format_size(d['size']), d['path'],
                        d.get('dest',''), d['mtime'],
                        t.topic, t.doc_type, t.domain, t.priority, t.time_tag, t.source,
                        d.get('industrial','')])
    print(f"  CSV:  {csv_path}")

    # === JSON ===
    json_path = os.path.join(report_dir, 'file_report.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': now,
            'total_scanned': total_scanned,
            'dupes_removed': dupes,
            'total_copied': len(copied_files),
            'total_size': total_size,
            'by_topic': dict(Counter(d['tags'].topic for d in copied_files)),
            'by_type': dict(Counter(d['tags'].doc_type for d in copied_files)),
            'by_priority': dict(Counter(d['tags'].priority for d in copied_files)),
            'by_industrial': dict(Counter(d['industrial'] for d in copied_files if d['industrial'])),
            'documents': [{
                'name': d['name'], 'path': d['path'],
                'dest': d.get('dest',''), 'size': d['size'], 'mtime': d['mtime'],
                'topic': d['tags'].topic, 'doc_type': d['tags'].doc_type,
                'domain': d['tags'].domain, 'priority': d['tags'].priority,
                'time_tag': d['tags'].time_tag, 'source': d['tags'].source,
                'industrial': d.get('industrial',''),
            } for d in copied_files]
        }, f, ensure_ascii=False, indent=2)
    print(f"  JSON: {json_path}")

    # === Markdown ===
    md_path = os.path.join(report_dir, '迁移报告.md')
    lines = ['# 文件迁移整理报告', '', f'> 生成时间: {now}', '',
             '## 统计摘要', '',
             '| 指标 | 数值 |', '|------|------|',
             f'| 扫描总数 | {total_scanned} |',
             f'| 去重移除 | {dupes} |',
             f'| 保留文件 | {len(copied_files)} |',
             f'| 总大小 | {format_size(total_size)} |',
             f'| 拷贝错误 | {len(errors)} |', '']

    # 6维统计
    for dim, label in [('topic','主题'), ('doc_type','类型'), ('domain','领域'), ('priority','优先级'), ('source','来源')]:
        stats = Counter(d['tags'].__dict__[dim] for d in copied_files)
        lines.append(f'### {label}')
        lines.append('')
        lines.append('| 标签 | 文件数 |')
        lines.append('|------|--------|')
        for k, v in stats.most_common():
            lines.append(f'| {k} | {v} |')
        lines.append('')

    # 工业分类统计
    ind_stats = Counter(d['industrial'] for d in copied_files if d['industrial'])
    if ind_stats:
        lines.append('### 工业分类 (PDF/Office)')
        lines.append('')
        lines.append('| 分类 | 文件数 |')
        lines.append('|------|--------|')
        for k, v in ind_stats.most_common():
            lines.append(f'| {k} | {v} |')
        lines.append('')

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f"  MD:   {md_path}")

    return md_path

# ============================================================
#  打包
# ============================================================

def package_zip(output_root):
    """打包ZIP用于飞书上传"""
    print()
    print("[5/5] 打包 ZIP ...")

    zip_dir = os.path.dirname(output_root)
    zip_name = f"文件迁移整理_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = os.path.join(zip_dir, zip_name)

    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(output_root):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for fname in filenames:
                fpath = os.path.join(dirpath, fname)
                arcname = os.path.relpath(fpath, output_root)
                zf.write(fpath, arcname)
                count += 1

    zip_size = os.path.getsize(zip_path)
    print(f"  ZIP: {zip_path}")
    print(f"  包含: {count} 个文件, {format_size(zip_size)}")
    print(f"  ✓ 上传到飞书 → 新电脑下载解压即可")
    return zip_path

# ============================================================
#  主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='文件打标整理迁移系统 v4 — 全盘扫描 + 6维RAG打标 + 交互审核 + 打包迁移')
    parser.add_argument('--output', '-o', default=None, help='输出目录')
    parser.add_argument('--drives', '-d', default=None, help='盘符 (如: C,D,E)')
    parser.add_argument('--auto', action='store_true', help='跳过交互审核')
    parser.add_argument('--package', action='store_true', help='自动打包ZIP')
    args = parser.parse_args()

    is_win = (os.name == 'nt')
    if args.output:
        output_root = args.output
    elif is_win:
        output_root = r'D:\文件迁移整理'
    else:
        output_root = '/tmp/文件迁移整理'

    print('=' * 60)
    print('  文件打标整理迁移系统 v4')
    print('  全盘扫描 → 6维RAG打标 → 交互审核 → 打包 → 飞书上传')
    print('=' * 60)
    print()
    print(f'  环境: {"Windows" if is_win else "WSL/Linux"}')
    print(f'  输出: {output_root}')
    print(f'  模式: {"自动" if args.auto else "交互审核"}')
    print()

    # 盘符
    if args.drives:
        drives = []
        for d in args.drives.split(','):
            d = d.strip().upper()
            if is_win:
                if not d.endswith(':\\'):
                    d = d + ':\\'
            else:
                d = f'/mnt/{d[0].lower()}'
            if os.path.exists(d):
                drives.append(d)
            else:
                print(f'  警告: {d} 不存在')
    else:
        drives = None

    # === 扫描 ===
    files, total_scanned, dupes = scan_all(drives)
    if not files:
        print('  未找到文件。')
        return

    # === 审核 ===
    if args.auto:
        print("\n[2/5] 自动模式，跳过审核")
        final = files
    else:
        final = interactive_review(files)
        if not final:
            print("  审核后无文件，退出。")
            return

    # === 拷贝 ===
    copied, errors = copy_files(final, output_root)

    # === 报告 ===
    report_path = generate_reports(final, total_scanned, dupes, errors, output_root)

    # === 打包 ===
    if args.package:
        package_zip(output_root)
        print('\n完成！可上传飞书。')
    else:
        print()
        print('=' * 60)
        print('完成！')
        print(f'  报告: {report_path}')
        print(f'  目录: {output_root}')
        print()
        print(f'  打包命令: python doc_classifier.py --package')
        print('=' * 60)

if __name__ == '__main__':
    main()
