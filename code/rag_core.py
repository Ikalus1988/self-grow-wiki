#!/usr/bin/env python3
"""RAG核心模块 — 检索 + LLM生成 + 通道管理.

供 rag_web.py (Gradio UI) 和 wecom_bot.py (企业微信) 共享使用.
"""

import json
import logging
import os
import re
import time
import sqlite3
import threading
import pickle as _pickle
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)

def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文约2 token/字，英文/数字约0.25 token/字"""
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other = len(text) - chinese
    return chinese * 2 + max(1, other // 4)

# BM25 混合检索
try:
    from rank_bm25 import BM25Okapi
    import jieba
    jieba.setLogLevel(20)  # suppress jieba init logs
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False

# 自学习模块
try:
    import kb_learning
    _KB_LEARNING = True
except ImportError:
    _KB_LEARNING = False

# 报警代码模式：SRVO-023, PRIO-001, SYST-037 等
_ALARM_CODE_RE = re.compile(r'(?<![A-Za-z])([A-Z]{2,6}-\d{3,6})(?![A-Za-z0-9])', re.I)

# 机器人型号系列模式：M-900, R-2000 等（_normalize_query 先把 M900→M-900）
_MODEL_SERIES_RE = re.compile(r'(?<![A-Za-z0-9])([A-Z]{1,2}-\d{2,4})(?!\d)')

# 2026-08-23: 部件/型号类查询信号——查询含这些词时，实体型号检索的参考组
# （相邻代际）按主题相关性排序：查询的部件词（电机/减速机等）映射到文本词族
# （MOTOR/A06B、GEAR/A97L），让更换部件表/备件表（真正的“型号”答案）
# 排在规格页/夹具页前面（B-82135 电机表 A06B 案例）。
_PART_KW_RE = re.compile(r'型号|部件|电机|减速机|编号|备件|更换|规格')
_PART_TERM_GROUPS = [
    (r'电机|马达|伺服|motor', ('电机', '马达', 'MOTOR', 'SERVO', 'A06B')),
    (r'减速机|齿轮|reducer|gear', ('减速机', '齿轮', 'GEAR', 'REDUCER', 'A97L')),
    (r'控制器|control', ('控制器', 'CONTROL')),
    (r'电池|battery', ('电池', 'BATTERY')),
]


# ── 中文别名 → FANUC 标准术语 ──────────────────────────────────────────
_CHINESE_ALIASES = {
    "法那科": "FANUC",
    "法兰克": "FANUC",
    "发那科": "FANUC",
    "发那克": "FANUC",
    "法纳科": "FANUC",
    "fanuc机器人": "FANUC机器人",
}
_CHINESE_ALIAS_RE = re.compile("|".join(re.escape(k) for k in _CHINESE_ALIASES), re.I)


def _normalize_query(query: str) -> str:
    """将查询中的无连字符型号/报警代码规范化为带连字符形式."""
    q = query
    # 中文别名标准化：法那科/发那科/法兰克 → FANUC（中文与英文间补空格）
    q = _CHINESE_ALIAS_RE.sub(lambda m: _CHINESE_ALIASES[m.group().lower()], q)
    q = re.sub(r'(FANUC)([A-Z0-9])', r'\1 \2', q)  # FANUCM-900 → FANUC M-900
    # CR 系列协作机器人：CR35iA → CR-35iA, CR7iA → CR-7iA
    q = re.sub(r'(?<![A-Za-z0-9])CR(\d{1,2})(i[A-Z]?)(?![A-Za-z0-9])', r'CR-\1\2', q, flags=re.I)
    # 常见现场写法标准化：CCLink/CC Link → CC-Link，R30iB → R-30iB
    q = re.sub(r'(?i)CC\s*-?\s*Link', 'CC-Link', q)
    q = re.sub(r'(?i)(?<![A-Za-z0-9])R\s*30i([AB])(?![A-Za-z0-9])', r'R-30i\1', q)
    q = re.sub(r'(?i)([A-Z]{2,6}-\d{3,6})(CC-Link)', r'\1 \2', q)
    q = re.sub(r'(?i)(CC-Link)([A-Z]{2,6})', r'\1 \2', q)
    q = re.sub(r'(?i)(CRC)([\u4e00-\u9fff])', r'\1 \2', q)
    q = re.sub(r'(?i)(R-30i[AB])([\u4e00-\u9fff])', r'\1 \2', q)
    # M900 → M-900, R2000 → R-2000
    q = re.sub(r'(?<![A-Za-z0-9])([A-Z]{1,2})(\d{2,4})(?!\d)', r'\1-\2', q)
    # SRVO-228RIOfuseblown → SRVO-228 RI/O fuse blown（历史 badcase 中常见粘连写法）
    q = re.sub(
        r'(?<![A-Za-z])([A-Z]{2,6}-\d{3,6})(RIO)(fuse)(blown)',
        lambda m: f'{m.group(1).upper()} RI/O fuse blown',
        q,
        flags=re.I,
    )
    # 英文报警码/缩写和中文后缀粘连时补空格："blown排查" → "blown 排查"
    q = re.sub(r'([A-Za-z/]{4,})([\u4e00-\u9fff])', r'\1 \2', q)
    # 保持常见品牌+中文名词的紧凑写法，避免把 FANUC机器人 拆成两个弱 token
    q = re.sub(r'(?i)\b(FANUC)\s+(机器人)', r'\1\2', q)
    # SRVO023 → SRVO-023, svgn381 → SVGN-381
    q = re.sub(r'(?<![A-Za-z])([a-zA-Z]{2,6})(\d{3,6})(?![A-Za-z0-9])',
               lambda m: f'{m.group(1).upper()}-{m.group(2)}', q)
    # svgn-381 → SVGN-381 (已有横杠的小写报警码)
    q = re.sub(r'(?<![A-Za-z])([a-zA-Z]{2,6})-(\d{3,6})(?![A-Za-z0-9])',
               lambda m: f'{m.group(1).upper()}-{m.group(2)}', q)
    # 负载数字→型号映射：纯数字负载查询补齐为完整型号
    q = _expand_load_to_model(q)
    return q


# ── 负载数字→型号映射 ──────────────────────────────────────────────────
# FANUC 常见负载数字对应的主流型号，用于"搜360→找到M-900iB/360L"
_FANUC_LOAD_MODELS = {
    # 格式: "负载数字": ["型号1", "型号2", ...]
    "700": ["M-900iB/700", "M-410iB/700"],
    "450": ["M-410iB/450"],
    "400": ["M-900iB/400L", "M-900iB/400"],
    "360": ["M-900iB/360L", "M-900iB/360"],
    "350": ["M-900iA/350"],
    "330": ["M-900iB/330L"],
    "300": ["M-900iB/300L", "M-900iB/300", "M-410iB/300"],
    "280": ["M-900iB/280L", "M-900iB/280"],
    "270": ["M-900iB/270L", "M-900iB/270", "R-2000iC/270F"],
    "260": ["M-900iA/260L"],
    "210": ["R-2000iC/210F", "R-2000iC/210L", "R-2000iC/210WE"],
    "200": ["R-2000iC/200E", "M-900iA/200P"],
    "180": ["R-2000iC/180F"],
    "165": ["R-2000iC/165F", "R-2000iB/165F", "M-20iD/165F"],
    "160": ["M-410iB/160"],
    "150": ["M-900iA/150P"],
    "125": ["R-2000iC/125L"],
    "120": ["Arc Mate 120iC", "R-1000iA/120F"],
    "100": ["M-710iC/100", "R-1000iA/100F"],
    "70": ["M-710iC/70"],
    "50": ["M-710iC/50", "M-710iC/50T", "M-20iD/50"],
    "35": ["M-20iD/35"],
    "25": ["M-20iD/25", "LR Mate 200iD/25"],
    "20": ["M-710iC/20L", "M-20iD/20"],
    "12": ["LR Mate 200iD/12", "Arc Mate 120iC/12L"],
    "7": ["LR Mate 200iD/7L", "LR Mate 200iD/7C"],
    "4": ["LR Mate 200iD/4S"],
}


def _expand_load_to_model(query: str) -> str:
    """如果查询包含纯负载数字，追加对应型号名。

    "360" → "360 M-900iB/360L"
    "360机器人" → "360机器人 M-900iB/360L"
    """
    # 匹配独立的数字（2-4位，前后非字母数字）
    m = re.search(r'(?<![A-Za-z0-9])(\d{2,4})(?![A-Za-z0-9/])', query)
    if not m:
        return query
    load_num = m.group(1)
    # 排除年份、版本号、角度 360°
    if load_num in ("2024", "2025", "2026", "180", "360"):
        # 360° 要排除：检查上下文是否含 "°"、"度"、"轴"
        # 只处理"360"单独出现，且不是在角度语境
        ctx_start = max(0, m.start() - 10)
        ctx_end = min(len(query), m.end() + 10)
        ctx = query[ctx_start:ctx_end]
        # 如果是角度/范围上下文，跳过
        if "°" in ctx or "度" in ctx or "轴" in ctx or "-" in ctx:
            return query
    models = _FANUC_LOAD_MODELS.get(load_num, [])
    if not models:
        return query
    return f"{query} {models[0]}"


# ── 同义词扩展 ──────────────────────────────────────────────────────────
_SYNONYM_FILE = Path(__file__).parent / "synonyms.json"
_synonym_cache = None
_synonym_mtime = 0


def _load_synonyms() -> dict:
    global _synonym_cache, _synonym_mtime
    try:
        mtime = _SYNONYM_FILE.stat().st_mtime
        if _synonym_cache is None or mtime > _synonym_mtime:
            with open(_SYNONYM_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            _synonym_cache = {k: v for k, v in raw.items() if not k.startswith("_")}
            _synonym_mtime = mtime
        return _synonym_cache
    except Exception:
        return {}


def expand_query(query: str) -> str:
    """用同义词扩展查询词，提升语义鸿沟场景的召回率。"""
    syns = _load_synonyms()
    if not syns:
        return query
    expanded = [query]
    for orig, aliases in syns.items():
        if orig in query:
            expanded.extend(aliases)
    return " ".join(expanded)


def _augment_query(query: str) -> str:
    """基于提取到的实体类型增强检索查询，提升 FANUC 领域匹配精度。

    在 _normalize_query（格式标准化）之后、expand_query（同义词扩展）之前调用。
    纯规则实现，零延迟零依赖，不会引入检索失败风险。
    """
    alarm_codes = _extract_alarm_codes(query)
    model_numbers = _extract_model_numbers(query)
    chinese_chars = sum(1 for c in query if '\u4e00' <= c <= '\u9fff')

    aug_parts = []

    # 报警码查询：锚定"报警"语义域
    if alarm_codes:
        aug_parts.append("报警")

    # 型号查询：锚定技术文档上下文
    if model_numbers:
        aug_parts.append("规格 参数")

    # badcase 高频语义域：补领域锚点，不改变用户原意
    if re.search(r'(?i)RI/O|RIO|FUSE|保险丝|SRVO-228|SRVO-229', query):
        aug_parts.append("RI/O FUSE 保险丝 I/O板")
    if re.search(r'(?i)CC-?Link|PRIO-323|CRC|终端电阻', query):
        aug_parts.append("CC-Link CRC 终端电阻 通信")
    if re.search(r'伺服放大器|电源模块|主电源模块|直流母线|servo\s*amp', query, re.I):
        aug_parts.append("伺服放大器 主电源模块 直流母线")
    if re.search(r'圆弧跟踪|焊缝跟踪|电弧跟踪|through[-\s]*arc|TAST', query, re.I):
        aug_parts.append("Through-Arc Tracking TAST 焊缝跟踪 电弧跟踪 弧焊")
    # ponytail: 伺服焊枪 + 挠度/deflection → B-83264CM 手册术语锚点
    if re.search(r'伺服焊枪|servo\s*gun', query, re.I):
        aug_parts.append("B-83264CM 伺服焊枪 加压条件画面")
    if re.search(r'(?i)(伺服焊枪|焊枪|servo\s*gun).*挠度|deflection', query):
        aug_parts.append("焊枪挠曲补偿 加压条件画面 三维挠曲补偿 补偿值的设置方法")

    # ── 机型保养锚点（已移除 2026-08-23）──
    # 用户决策: 不考虑强制召回（含机型锚点），因用户问题不可预测。
    # 此前 M-900iB→B-83444/B-83684、R-2000iC→B-83644 的保养锚点是针对已知问题的
    # 查询注入，问题不可预测则锚点列表永远追不上 → 移除，靠数据质量（补蒸馏/实体标注）
    # + synonyms 通用扩展 + 排序公平性自然命中。

    # 查询不含 FANUC/brand 关键词时，自动追加以锚定语义域
    if not re.search(r'(?i)fanuc|kuka|abb|yaskawa|kawasaki|发那科', query):
        if not re.search(r'(?i)CNC|ROBODRILL|ROBOCUT|加工中心|数控', query):
            aug_parts.append("FANUC 工业机器人")
    # 短中文查询额外加强
    if 2 <= chinese_chars <= 15 and not alarm_codes and not model_numbers:
        if any(kw in query for kw in ['机器人', '伺服', '报警', '故障', '参数',
                                       '规格', '操作', '维护', '安装', '调试']):
            aug_parts.append("FANUC 工业机器人")

    # 功能询问/型号覆盖类问题：追加实体锚定
    if re.search(r'哪些(型号|机型|机器人)|什么(型号|机器人).*(带|有|支持)|适用(哪些|什么).*型号', query):
        aug_parts.append("可选购项 适用型号 出厂标准 高惯量")
    if not aug_parts:
        return query
    return f"{query} {' '.join(aug_parts)}"


# ── Config ──────────────────────────────────────────────────────────────
CHROMA_DIR = Path(os.environ.get("RAG_CHROMA_DIR", os.path.expanduser("~/rag_chromadb")))
COLLECTION_NAME = os.environ.get("RAG_COLLECTION", "wiki_docs")
EMBEDDING_MODEL = os.environ.get("RAG_EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5")

PATHS = {
    "chromadb": str(CHROMA_DIR),
    "query_log_db": os.environ.get("RAG_QUERY_LOG", os.path.expanduser("~/rag_query_log.db")),
    "conflict_report": os.environ.get("RAG_CONFLICT_REPORT", os.path.expanduser("~/kb_conflict_report.md")),
}

MIOFFICE_API_BASE = "https://api.llm.mioffice.cn/v1"
MIOFFICE_API_KEY = os.environ.get("MIOFFICE_API_KEY", "")

OLLAMA_BASE = "http://localhost:11434/v1"

MODEL_CHANNELS = [
    {
        "id": "mimo-flash",
        "name": "MiMo-V2-Flash",
        "label": "MiMo-Flash (快速)",
        "model_id": "xiaomi/mimo-v2-flash",
        "api_base": MIOFFICE_API_BASE,
        "api_key": MIOFFICE_API_KEY,
        "timeout": 60,
    },
    {
        "id": "mimo-pro",
        "name": "MiMo-V2-Pro",
        "label": "MiMo-Pro (高质量)",
        "model_id": "xiaomi/mimo-v2-pro",
        "api_base": MIOFFICE_API_BASE,
        "api_key": MIOFFICE_API_KEY,
        "timeout": 60,
    },
]

DEFAULT_TOP_K = 8
MIN_SCORE = 0.50          # 语义分数低于此阈值的 chunk 直接丢弃（0.50=噪声基线）
MIN_TEXT_LEN = 30         # chunk 文本少于该字符数视为垃圾
DEFAULT_TEMPERATURE = 0
HEALTH_CHECK_INTERVAL = 120
RISK_LOW_CONFIDENCE = 0.65
RISK_VERY_LOW_CONFIDENCE = 0.4
RISK_SLOW_QUERY_MS = 30000

# BM25 混合检索配置
BM25_INDEX_PATH = CHROMA_DIR / "bm25_index.pkl"
BM25_TOP_K = 20           # BM25 候选数量
BM25_ALPHA = 0.4          # 向量分数权重 (1-alpha = BM25 权重)
BM25_RRF_K = 60           # RRF 常数 (越小 BM25 影响越大)

# ── 配置加载（延迟导入，避免循环依赖） ──────────────────────────────
_CONFIG = None

def _load_config():
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    try:
        from retriever import load_config
        _CONFIG = load_config()
    except Exception:
        _CONFIG = {}
    return _CONFIG

def _get_feature_name_kw() -> dict:
    """从 config.yaml 加载功能名称关键词清单，回退到硬编码兜底。"""
    cfg = _load_config()
    configured = cfg.get("feature_name_kw", {})
    if configured:
        result = {}
        for pattern_str, variants in configured.items():
            try:
                result[re.compile(pattern_str, re.I)] = [
                    {"$contains": v} for v in variants
                ]
            except re.error:
                logger.warning(f"无效功能名正则: {pattern_str}")
        if result:
            return result
    # 硬编码兜底
    return {
        re.compile(r'pc\s*interface|PCIF|pcif', re.I): [
            {"$contains": "PC Interface"}, {"$contains": "PCIF"},
            {"$contains": "pc interface"}, {"$contains": "pcif"},
        ],
        re.compile(r'device\s*net|devicenet', re.I): [
            {"$contains": "DeviceNet"}, {"$contains": "devicenet"},
            {"$contains": "Device Net"},
        ],
        re.compile(r'RTCP|remote\s*tcp|远程\s*TCP', re.I): [
            {"$contains": "远程 TCP"}, {"$contains": "Remote TCP"},
            {"$contains": "RTCP"},
        ],
        re.compile(r'高惯量|High\s*Inertia', re.I): [
            {"$contains": "高惯量"}, {"$contains": "High Inertia"},
        ],
        re.compile(r'物料搬运|Material\s*Handling', re.I): [
            {"$contains": "物料搬运"}, {"$contains": "Material Handling"},
        ],
    }

# Cross-encoder rerank（可选，依赖 sentence-transformers）
_RERANKER_MODEL = "BAAI/bge-reranker-base"
_RERANK_TOP_K = 0        # ponytail: lesson rag-cross-encoder-cpu-bottleneck — reranker 在 CPU 上 25-60s, 关掉走 RRF+entity, 速度 25s→29ms

SYSTEM_PROMPT = """你是 FANUC 工业机器人知识库的"技术顾问"。任务是直接回答技术问题，禁止反问用户。

# 回答格式: 直接答案 → 分点(标注[来源:文件名]) → 未覆盖项

# 好回答 (必须)
Q:"SRVO-066怎么处理"
A:"更换电机或脉冲编码器，执行mastering。需重新上电[来源:B-83284EN]。若同时出现SRVO-068/069/070，优先处理伴随报警[来源:fanuc_system_r-j2.pdf]。以下未覆盖:更换步骤图解。"

# 坏回答 (绝对禁止)
Q:"TCP/IP怎么配置"
A:"你想往哪个方向深入？" ← 禁止反问!
A:"建议你查阅B-8xxxx手册" ← 禁止建议查手册!
A:"<think>...</think>" ← 禁止think块!

# 规则
1. 直接回答，禁止:"你想往哪个方向" "要继续查哪种" "建议下一步" "建议查阅"
2. 每个事实附带[来源:文件名]
3. ★相关性检查★：输出前判断每条检索片段是否与问题真正相关。不相关的内容（如 DeviceNet ≠ PC Interface、其他功能名撞词）跳过不引用，标注"以下来源与问题不相关已省略:xxx"
4. 允许跨文档归纳，标注每个结论的来源
5. 检索不全:先给有的，再说"以下未覆盖:xxx"，不编造
5a. ★严禁用训练知识补检索缺口★：当所有检索片段与问题不相关时，禁止用预训练知识"补"出答案。必须明确写出"以下未覆盖:xxx"并停笔。
5b. ★章节缺失禁写：未带章节/页码的事实不得写入正文（如"PROFINET IRT 延迟<1ms"）。若推理无源，立即停笔。ponytail: 防 LLM 用预训练知识补 RAG 缺口(2026-07-27 62 题复盘 C03 实例)。
5c. ★禁否定存在性：当用户询问某型号/规格/参数而检索片段缺失或低相关时，禁止写"XX 不存在/没有/未推出"。必须写"知识库未覆盖 XX 的 [属性]"，并列出已检索到的相关片段标题供用户人工核实(2026-08-12 M-900iB/330L 实例: RAG 召回 0 ≠ 型号不存在)。
5d. ★近似参考允许（2026-08-23）：目标机型数据未覆盖、但检索到相邻/前代机型（如 M-900iA↔iB、同系列不同后缀）数据时，**允许提供显式标注的近似参考**：先写"未查到 [目标机型] 的 [属性]"，再给"相邻机型 [如 M-900iA] 的数据为 [型号/数值]（来源），仅供参考，请确认参考性"。禁止未标注地套用（仍是红线），但**不得因跨代纪律而完全不提可参考数据**。
6. 多手册描述不一致:列出差异+各自来源
7. DI[n]/DO[n]=I/O信号 ≠ 系统变量(VR文件)，概念不同，禁止混淆

# 回答结构（强制）
先给结论(1-2句) → 按要点分点展开 → 最后列限制/注意事项

# ★三签名溯源（每个来源必须包含以下三要素）
每个 [来源] 标注必须包含: 手册编号 | 章节 | 页码
格式: [来源: B-83284CM §7 远程TCP功能 p.12]
严禁只写文件名不写章节。当某片段没有章节信息时标注"章节未知"。
来源汇总段: 末尾单独列一张来源表，三签名各一列。

# ★结构化卡片（800 字硬限制）
回答按以下顺序组织，超过 800 字强制截断：
  1. 结论（1-2 句）——用户最需要知道的那句话
  2. 操作步骤（最多 3 条）——每一步 1-2 句 + 来源
  3. 参数/规格（最多 3 条）——每个参数 1-2 句 + 来源
  4. 警告/限制（最多 3 条）——没有则跳过
  5. 来源汇总（三签名表）

禁止行为：
- 禁止输出完整chunk原文（用户不需要看碎片，需要看归纳后的知识）
- 禁止在"如下所示""如下"后粘贴大段原文
- 禁止跨chunk无衔接地堆砌多个[来源]块"""

COMPARE_PROMPT = """你是工业自动化技术文档助手。根据检索到的多组文档片段，对用户指定的对象进行结构化对比。
要求：
1. 按维度逐项对比（如：控制器、编程语言、性能参数、适用场景等）
2. 每个维度分别列出各对象的要点
3. 直接给出要点，不用表格，不用Markdown格式
4. 回答控制在500字以内
5. 最后给出简要总结"""


# ── 查询大类分类器 ─────────────────────────────────────────────────────
# 根据查询关键词判断大类，用于 retrieve() 前置过滤
# 大类 = wiki 目录主章节 (01_PLC与控制, 02_制造标准, ...)

_CATEGORY_RULES = [
    # (正则, category) — 按优先级排序
    (re.compile(r'SRVO-?\d|MATE-?\d|SVGN-?\d|SYST-?\d|MCTL-?\d|PRIO-?\d|报警|故障代码|error\s*code', re.I), '07_机器人'),
    (re.compile(r'FANUC|M-\d{3}|R-\d{4}|LR\s*Mate|伺服|servo|焊枪|焊机|机器人|robot', re.I), '07_机器人'),
    (re.compile(r'PLC|SCL|STL|STEP\s*7|TIA|PLCSIM|SICAR|SIMATIC|程序块|功能块|FB\s*\d|FC\s*\d|DB\s*\d', re.I), '01_PLC与控制'),
    (re.compile(r'WinCC|HMI|SCADA|Unified|触摸屏|界面', re.I), '04_HMI与SCADA'),
    (re.compile(r'G120|CU250|SINAMICS|Startdrive|变频器|驱动器|电机', re.I), '05_驱动与传动'),
    (re.compile(r'PILZ|Euchner|MGB|PROFIsafe|安全门|安全扫描|安全继电器|安全PLC', re.I), '06_安全与传感'),
    (re.compile(r'EPLAN|电气图|原理图|接线图|柱灯|信号灯|I/O表|信号表', re.I), '03_电气图纸'),
    (re.compile(r'CAD|EPLAN|工程工具', re.I), '08_工程工具'),
    (re.compile(r'能源|能耗|电能|Energy', re.I), '10_能效与诊断'),
    (re.compile(r'TS-\d{4,}|BMS-\d{4,}|Tesla|制造标准|螺柱焊|Stud\s*weld', re.I), '02_制造标准'),
    (re.compile(r'项目|现场|调试|验收', re.I), '09_项目文档'),
]


def classify_query(query: str) -> str:
    """判断查询所属大类，返回 category 字符串，无法判断返回空串."""
    for regex, cat in _CATEGORY_RULES:
        if regex.search(query):
            return cat
    return ""


# 分类标签等价组：2026-08 新版手册（FANUC Manual 13.0 CM，34324 chunks）统一标
# "FANUC机器人"，历史库（132815 chunks）用细分标签（如 07_机器人）。分类器只认老标签，
# 导致新版 chunk 被 where_filter 分类过滤误杀（静默退化案例 2026-08-20: M-900iB 换油周期）。
# where_filter 用等价组展开为 $in 匹配，避免新版/旧版标签互相屏蔽。
# 2026-08-21 泛化: 新版手册未做细分分类（全塞 FANUC机器人），所有老分类查询都补充
# FANUC机器人 为等价候选，避免任何分类查询漏掉新版 chunk。若回归明显再收窄到机器人分类。
_CATEGORY_EQUIV = {
    cat: [cat, "FANUC机器人"]
    for cat in ["07_机器人", "01_PLC与控制", "02_制造标准", "03_电气图纸",
                "04_HMI与SCADA", "05_驱动与传动", "06_安全与传感",
                "08_工程工具", "09_项目文档", "10_能效与诊断"]
}


# ── 二级分类规则 ─────────────────────────────────────────────────
_L2_RULES = [
    (re.compile(r'SRVO-\d|MATE-\d|PRIO-\d|SYST-\d|报警代码|alarm', re.I), '报警诊断与故障排除'),
    (re.compile(r'伺服放大器|编码器|servo\s*amp|电池更换|润滑', re.I), '伺服与运动控制'),
    (re.compile(r'Karel|示教器|TP程序|PROGRAM|寄存器', re.I), '编程与示教'),
    (re.compile(r'TIA\s*Portal|STEP\s*7|PLC|功能块|SCL|SICAR', re.I), 'TIA Portal配置'),
    (re.compile(r'PROFINET|OPC\s*UA|总线|DeviceNet|IO映射', re.I), 'IO与通信'),
    (re.compile(r'WinCC|Unified|SCADA|HMI|触摸屏', re.I), 'WinCC配置'),
    (re.compile(r'iRVision|视觉引导|相机标定|视觉定位', re.I), '视觉与传感器'),
    (re.compile(r'变位机|导轨|外部轴|E轴组', re.I), '外部轴与协调'),
    (re.compile(r'焊枪|焊接参数|弧焊|点焊|焊缝', re.I), '焊枪配置'),
    (re.compile(r'变频器|G120|VFD|S120', re.I), '变频器参数'),
    (re.compile(r'安全门|安全回路|急停|安全PLC|SIL', re.I), '安全与维护'),
    (re.compile(r'零点标定|零位校准|MASTERING|参考点', re.I), '系统配置与初始化'),
    (re.compile(r'payload|负载能力|重复定位精度|工作范围|cycle\s*time', re.I), '硬件手册'),
]


def _query_to_l2(query: str) -> str:
    """根据查询关键词推断二级分类。"""
    for regex, l2 in _L2_RULES:
        if regex.search(query):
            return l2
    return ""


# ── Channel Health Manager ──────────────────────────────────────────────

class ChannelManager:
    """管理模型通道的健康状态和故障转移."""

    def __init__(self, channels):
        self.channels = list(channels)
        self.health = {}
        self._lock = threading.Lock()

    def _probe(self, ch):
        timeout = min(ch.get("timeout", 60), 30)  # health check max 30s
        try:
            client = OpenAI(base_url=ch["api_base"], api_key=ch["api_key"], timeout=timeout)
            t0 = time.time()
            resp = client.chat.completions.create(
                model=ch["model_id"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
                timeout=timeout,
            )
            latency = time.time() - t0
            return True, "", latency
        except Exception as e:
            return False, str(e)[:200], 0

    def check_health(self, channel_id):
        ch = next((c for c in self.channels if c["id"] == channel_id), None)
        if not ch:
            return False
        alive, err, latency = self._probe(ch)
        with self._lock:
            self.health[channel_id] = {
                "alive": alive,
                "last_check": time.time(),
                "error": err,
                "latency": latency,
            }
        return alive

    def check_all(self):
        threads = []
        for ch in self.channels:
            t = threading.Thread(target=self.check_health, args=(ch["id"],))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=35)

        for ch in self.channels:
            with self._lock:
                h = self.health.get(ch["id"], {})
            alive = h.get("alive", False)
            lat = h.get("latency", 0)
            err = h.get("error", "")
            if alive:
                print(f"  [{ch['name']}] 可用 ({lat:.1f}s)")
            else:
                print(f"  [{ch['name']}] 不可用: {err[:80]}")

    def is_stale(self, channel_id):
        with self._lock:
            h = self.health.get(channel_id)
        if not h:
            return True
        return time.time() - h["last_check"] > HEALTH_CHECK_INTERVAL

    def get_ordered_channels(self, preferred=None):
        candidates = list(self.channels)

        if preferred and preferred != "auto":
            pref = [c for c in candidates if c["id"] == preferred]
            rest = [c for c in candidates if c["id"] != preferred]
            candidates = pref + rest

        result = []
        for ch in candidates:
            with self._lock:
                h = self.health.get(ch["id"])
            if h and not h["alive"] and not self.is_stale(ch["id"]):
                continue
            result.append(ch)

        return result if result else list(self.channels)

    def mark(self, channel_id, alive, error="", latency=0):
        with self._lock:
            self.health[channel_id] = {
                "alive": alive,
                "last_check": time.time(),
                "error": error,
                "latency": latency,
            }

    def get_status_markdown(self):
        lines = ["| 通道 | 模型 | 状态 | 延迟 | 检查时间 |",
                 "|------|------|------|------|----------|"]
        for ch in self.channels:
            with self._lock:
                h = self.health.get(ch["id"], {})
            alive = h.get("alive")
            if alive is None:
                status = "未检测"
                lat_str = "-"
            elif alive:
                status = "**正常**"
                lat_str = f"{h.get('latency', 0):.1f}s"
            else:
                status = "异常"
                lat_str = "-"
            ago = ""
            if h.get("last_check"):
                ago_s = int(time.time() - h["last_check"])
                if ago_s < 60:
                    ago = f"{ago_s}秒前"
                else:
                    ago = f"{ago_s // 60}分钟前"
            lines.append(f"| {ch['name']} | `{ch['model_id']}` | {status} | {lat_str} | {ago} |")
        return "\n".join(lines)


channel_mgr = ChannelManager(MODEL_CHANNELS)


# ── Retrieval ───────────────────────────────────────────────────────────

_collection = None


def get_collection():
    global _collection
    if _collection is not None:
        return _collection

    import chromadb
    import torch
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"嵌入模型设备: {device}")

    # HF Hub 网络不可达时必须离线加载（模型已缓存在本地）
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    ef = SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device=device,
        trust_remote_code=False,
        local_files_only=True,
    )

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        _collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
    except ValueError:
        _collection = client.get_collection(name=COLLECTION_NAME)
        print(f"⚠ embedding_function 冲突，使用持久化配置")
    print(f"已加载向量库: {_collection.count()} vectors")
    return _collection


def _warmup():
    """预加载双模型 + 实体索引，消除首问 20s+ 冷启动。"""
    def _load_vec():
        try:
            coll = get_collection()
            _build_entity_index(coll)
            logger.info(f"[warmup] 向量库+实体索引加载完成 ({len(_entity_alarm_index or {})} alarm, {len(_entity_model_index or {})} model, {len(_entity_variant_index or {})} variant)")
        except Exception as e:
            logger.warning(f"[warmup] 向量库+索引加载失败: {e}")
    def _load_reranker():
        try:
            _get_reranker()
            logger.info("[warmup] Reranker 加载完成")
        except Exception as e:
            logger.warning(f"[warmup] Reranker 加载失败: {e}")
    threading.Thread(target=_load_vec, daemon=True).start()
    threading.Thread(target=_load_reranker, daemon=True).start()

threading.Thread(target=_warmup, daemon=True).start()

def _build_chunk(doc, meta, score):
    return {
        "index": 0,
        "text": doc,
        "filename": meta.get("filename", meta.get("source", "unknown")),
        "category": meta.get("category", ""),
        "subcategory": meta.get("subcategory", ""),
        "chunk_index": meta.get("chunk_index", 0),
        "total_chunks": meta.get("total_chunks", 1),
        "source": meta.get("source", ""),
        "score": score,
    }


def _keyword_score(doc: str, code: str) -> float:
    """根据报警代码在 chunk 中出现的位置给分: 标题级 > 引用提及."""
    variants = [code, code.replace("-", "\uff0d"), code.replace("-", " \uff0d ")]
    for v in variants:
        pos = doc.find(v)
        if pos != -1 and pos < 200:
            return 0.95
    return 0.85


def _contains_ci(text: str, keyword: str) -> bool:
    """忽略大小写检查 text 是否包含 keyword（去除正则转义后的纯文本）。"""
    clean = keyword.replace("\\s*", " ").replace("\\", "").strip()
    return clean.lower() in text.lower()


_model_file_cache = {}  # model_str -> (files_set, timestamp)
_MODEL_CACHE_TTL = 3600  # 1 小时，型号文档不会频繁变化


def _get_model_files(collection, model: str) -> set:
    cached = _model_file_cache.get(model)
    if cached and time.time() - cached[1] < _MODEL_CACHE_TTL:
        return cached[0]

    files = set()
    # 优先用 BM25 索引内存中的文档（毫秒级子串匹配），回退到 ChromaDB
    if _bm25_index._loaded:
        for doc, meta in zip(_bm25_index.docs, _bm25_index.metas):
            if model in doc:
                fn = meta.get("filename") or meta.get("source", "")
                if fn:
                    files.add(fn)
    else:
        try:
            scan = collection.get(
                where_document={"$contains": model},
                limit=30,
                include=["metadatas"],
            )
            for m in scan["metadatas"]:
                fn = m.get("filename") or m.get("source", "")
                if fn:
                    files.add(fn)
        except Exception:
            pass

    _model_file_cache[model] = (files, time.time())
    return files


def _extract_alarm_codes(query: str) -> list:
    """从查询中提取报警代码 (如 SRVO-023, MATE-001)。"""
    return [m.upper() for m in _ALARM_CODE_RE.findall(query)]


def _extract_model_numbers(query: str) -> list:
    """从查询中提取机器人型号 (如 R-2000iC/210L)。"""
    return _MODEL_SERIES_RE.findall(query.upper())


_VARIANT_QUERY_RE = re.compile(r'(?<![A-Za-z0-9])(\d{3,4}[A-Z]{1,2})(?![A-Za-z0-9])')


def _extract_model_variants(query: str) -> list:
    """从查询中提取型号规格后缀: 210F, 210WE, 165F 等"""
    return list(dict.fromkeys(_VARIANT_QUERY_RE.findall(query.upper())))


# ── 实体索引 (启动时构建一次) ──────────────────────────────────────
_entity_alarm_index = None   # {alarm_code: [(doc, meta, score_hint), ...]}
_entity_model_index = None   # {model_str: [(doc, meta), ...]}
_entity_index_built = False
_entity_variant_index = None # {variant_str: [(doc, meta), ...]}


def _build_entity_index(collection):
    """扫描 has_entity=True 的 chunks，构建报警和型号倒排索引。"""
    global _entity_alarm_index, _entity_model_index, _entity_variant_index, _entity_index_built
    if _entity_index_built:
        return

    _entity_alarm_index = {}
    _entity_model_index = {}
    _entity_variant_index = {}

    # 分批扫描所有 has_entity chunks
    offset = 0
    while True:
        scan = collection.get(
            where={"has_entity": True},
            limit=5000,
            offset=offset,
            include=["documents", "metadatas"],
        )
        if not scan["ids"]:
            break
        for doc, meta in zip(scan["documents"], scan["metadatas"]):
            # 报警索引
            alarms_str = meta.get("entity_alarms", "[]")
            if alarms_str and alarms_str != "[]":
                try:
                    alarms = json.loads(alarms_str)
                    for alarm in alarms:
                        _entity_alarm_index.setdefault(alarm, []).append((doc, meta))
                except (json.JSONDecodeError, TypeError):
                    pass
            # 型号索引
            models_str = meta.get("entity_models", "[]")
            if models_str and models_str != "[]":
                try:
                    models = json.loads(models_str)
                    for model in models:
                        _entity_model_index.setdefault(model, []).append((doc, meta))
                        # 后缀型号索引
                        variants_str = meta.get("entity_model_variants", "[]")
                        if variants_str and variants_str != "[]":
                            try:
                                variants_list = json.loads(variants_str)
                                for v in variants_list:
                                    _entity_variant_index.setdefault(v, []).append((doc, meta))
                            except (json.JSONDecodeError, TypeError):
                                pass
                except (json.JSONDecodeError, TypeError):
                    pass
        offset += len(scan["ids"])

    _entity_index_built = True


def _entity_alarm_search(collection, codes: list, existing: set) -> list:
    """用实体索引精确搜索报警 chunks。"""
    _build_entity_index(collection)
    chunks = []
    for code in codes[:3]:
        matches = _entity_alarm_index.get(code, [])
        for doc, meta in matches:
            if doc in existing:
                continue
            score = 0.92 if code in doc[:200] else 0.85
            c = _build_chunk_v2(doc, meta, score)
            c["_entity_match"] = "alarm"
            chunks.append(c)
            existing.add(doc)
            if len(chunks) >= 5:
                break
    return chunks


def _entity_model_search(collection, models: list, query: str, existing: set) -> list:
    """用实体索引精确搜索型号 chunks。

    2026-08-21: 查询提取的是型号系列（M-900），索引 key 是完整型号（M-900iB/700），
    精确 get 匹配不到 → 加系列前缀匹配兜底 + 代际约束（iB≠iA≠M-900A）+ 数量上限。
    2026-08-23: 代际约束放宽——同系列内同代际优先召回，相邻代际（如 M-900iA）
    以略低分数纳入参考（供 5d 近似参考输出：目标机型数据未覆盖时给相邻机型参考）。
    修正: 精确 key（M-900 系列级 24 chunks）不再短路前缀兜底——统一 rank 排序，
    同代取 ≤1（vector/BM25 已覆盖同代手册），相邻代参考取 ≤2（共 ≤3，上限不变），
    部件/型号类查询下参考组按文本词族（MOTOR/A06B、GEAR/A97L）相关性排序。
    """
    _build_entity_index(collection)
    chunks = []
    added = 0
    # 代际标识: 查询含型号代际标识（M-900iB/R-2000iC 的 iB/iC）时，同代际优先、
    # 相邻代际纳入参考（M-900iB 优先 M-900iB，其次 M-900iA）。仅针对型号格式。
    gen = None
    m = re.search(r'(?i)([A-Z]{1,2}-\d{2,4})(i[A-Z])', query)
    if m:
        gen = m.group(2).upper()
    variants = _extract_model_variants(query)  # 如 280L——同代内 variant 命中最优先

    def _rank_key(k: str) -> int:
        """匹配等级: 3=同代际+规格后缀命中, 2=同代际, 1=同系列相邻代际/系列级, 0=不匹配。"""
        kk = k.upper()
        if not kk.startswith(model.upper()):
            return 0
        if gen is None:
            if variants and any(v in kk for v in variants):
                return 3
            return 2
        if gen in kk:
            if variants and any(v in kk for v in variants):
                return 3
            return 2
        return 1

    for model in models[:3]:
        # 统一前缀扫描（含精确 key 命中；M-900 系列级 key 由 _rank_key 降为参考级）
        matches = []
        for k, v in _entity_model_index.items():
            r = _rank_key(k)
            if r:
                for doc, meta in v:
                    matches.append((doc, meta, r))
        # 同代际（含 variant）在前、相邻代际在后（稳定排序）
        matches.sort(key=lambda x: x[2], reverse=True)
        # 2026-08-23: 部件/型号类查询下，参考组（rank1）内按主题相关性排序——
        # 查询的部件词（电机/减速机等）映射文本词族（MOTOR/A06B、GEAR/A97L），
        # 命中词族多的 chunk（更换部件表/备件表）优先，否则 133 位后的
        # B-82135 电机表永远取不到（先到先得取到规格页/夹具页）。
        if _PART_KW_RE.search(query):
            active_groups = [g for pat, g in _PART_TERM_GROUPS if re.search(pat, query, re.I)]
            def _part_hits(doc: str) -> int:
                d = doc.upper()
                return sum(1 for g in active_groups if any(t in d for t in g))
            ref_start = next((i for i, x in enumerate(matches) if x[2] == 1), len(matches))
            ref_group = matches[ref_start:]
            ref_group.sort(
                key=lambda x: (
                    _part_hits(x[0]),
                    1 if model in x[0][:300].upper() else 0,
                ),
                reverse=True,
            )
            matches = matches[:ref_start] + ref_group
        same_gen_n = 0
        gen_ref_n = 0
        for doc, meta, rank in matches:
            if doc in existing:
                continue
            if rank >= 2:
                # 同代际上限 1：同代手册内容已被 vector/BM25 覆盖，entity 同代只是补充
                # （2026-08-21 教训：无主题相关性的型号 chunk 挤占精确答案；
                # 2026-08-23：名额让给相邻代参考，B-82135 电机表 A06B 需稳定进入）
                if same_gen_n >= 1:
                    continue
                same_gen_n += 1
            else:
                # 相邻代际参考：最多 2 个（规格页 + 电机表等），供 5d 近似参考输出
                if gen_ref_n >= 2:
                    continue
                gen_ref_n += 1
            boost = 0.15 if model in doc[:300].upper() else 0.08
            base = min(0.75 + boost, 0.95)
            score = base if rank >= 2 else base - 0.06  # 相邻代际参考略低
            c = _build_chunk_v2(doc, meta, score)
            c["_entity_match"] = "model"
            if rank == 1:
                c["_gen_reference"] = True  # 标记相邻代际参考（供 5d 近似参考输出）
            chunks.append(c)
            existing.add(doc)
            added += 1
            # 2026-08-21: 上限收紧 8→3——entity 是补充召回，塞太多无主题相关性的
            # 型号 chunk 会挤占含精确答案的高分结果（M-900iB 换油案例）
            if added >= 3:
                break
        # 2026-08-23: 第二遍——existing 命中的实体 chunk（BM25/vector 已召回同文本）
        # 返回升级标记，让合并段给 RRF 版补精确匹配分数/标记。否则实体版被跳过、
        # RRF 低分版被 top_k 截断（B-82135 电机表 A06B 参考丢失案例）。
        upgrade_n = 0
        for doc, meta, rank in matches:
            if doc not in existing:
                continue
            if upgrade_n >= 6:
                break
            boost = 0.15 if model in doc[:300].upper() else 0.08
            base = min(0.75 + boost, 0.95)
            score = base if rank >= 2 else base - 0.06
            c = _build_chunk_v2(doc, meta, score)
            c["_entity_match"] = "model"
            c["_in_existing"] = True
            if rank == 1:
                c["_gen_reference"] = True
            chunks.append(c)
            upgrade_n += 1
        if added >= 3:
            return chunks
    return chunks




def _entity_variant_search(collection, variants: list, query: str, existing: set) -> list:
    """用变体索引精确搜索型号后缀 chunks。"""
    _build_entity_index(collection)
    chunks = []
    for v in variants[:5]:
        matches = _entity_variant_index.get(v, [])
        for doc, meta in matches:
            if doc in existing:
                continue
            boost = 0.12 if v.upper() in doc[:200].upper() else 0.06
            score = min(0.78 + boost, 0.95)
            c = _build_chunk_v2(doc, meta, score)
            c["_variant_match"] = v
            chunks.append(c)
            existing.add(doc)
    return chunks
def _category_l2_search(collection, query: str, target_l2: str, existing: set) -> list:
    """用 category_l2 做二级分类过滤搜索。"""
    chunks = []
    try:
        results = collection.query(
            query_texts=[query],
            where={"category_l2": {"$eq": target_l2}},
            n_results=5,
        )
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0],
        ):
            if doc not in existing:
                c = _build_chunk_v2(doc, meta, 1 - dist)
                c["_l2_filtered"] = True
                chunks.append(c)
                existing.add(doc)
    except Exception as e:
        logger.warning(f"语义去重出错: {e}")
    return chunks


def _topic_tag_boost(chunks: list, query: str):
    """给 topic_tags 匹配查询关键词的 chunk 加分。"""
    query_words = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
    for c in chunks:
        meta_tags = c.get("_topic_tags", "")
        if not meta_tags:
            continue
        try:
            tags = json.loads(meta_tags) if isinstance(meta_tags, str) else meta_tags
        except (json.JSONDecodeError, TypeError):
            continue
        tag_hits = sum(1 for t in tags if any(w in t for w in query_words))
        if tag_hits >= 2:
            c["score"] = min(c["score"] + 0.08, 0.98)
        elif tag_hits >= 1:
            c["score"] = min(c["score"] + 0.04, 0.98)


# ── Cross-encoder reranker（可选） ──────────────────────────────────────
_RERANKER = None
_RERANKER_LOAD_ATTEMPTED = False

def _get_reranker():
    """轻量 cross-encoder reranker — BGE-reranker-base, 6-10s CPU.
    
    比 v2-m3 轻 3-5 倍，但足以区分 PC Interface/DeviceNet 等语义相近概念。
    加载失败时回退到纯 RRF 排序（静默降级）。
    """
    global _RERANKER, _RERANKER_LOAD_ATTEMPTED
    if _RERANKER is not None or _RERANKER_LOAD_ATTEMPTED:
        return _RERANKER
    _RERANKER_LOAD_ATTEMPTED = True
    try:
        import os as _os
        if not _os.environ.get("HF_ENDPOINT"):
            _os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder(_RERANKER_MODEL, max_length=512)
        logger.info(f"Reranker 已加载: {_RERANKER_MODEL}")
        return _RERANKER
    except Exception as e:
        logger.warning(f"Reranker 加载失败 ({_RERANKER_MODEL})，回退纯 RRF: {e}")
        return None


def _rerank_chunks(query: str, chunks: list, rerank_k: int = _RERANK_TOP_K) -> list:
    """用 cross-encoder 对检索结果重排序。

    只对 top-rerank_k 个候选做重排以控制延迟，其余保持原始顺序追加。
    reranker 不可用时返回原始列表。
    """
    if len(chunks) < 2 or not query.strip():
        return chunks

    reranker = _get_reranker()
    if reranker is None:
        return chunks

    candidates = chunks[:rerank_k]
    rest = chunks[rerank_k:]

    try:
        pairs = [(query, c["text"]) for c in candidates]
        scores = reranker.predict(pairs, show_progress_bar=False)
        for i, c in enumerate(candidates):
            c["score"] = float(scores[i])
        candidates.sort(key=lambda c: c["score"], reverse=True)
    except Exception as e:
        logger.warning(f"Rerank 失败，保持原始排序: {e}")
        return chunks

    return candidates + rest


def _build_chunk_v2(doc, meta, score):
    """扩展 _build_chunk，携带新元数据。"""
    c = _build_chunk(doc, meta, score)
    c["entity_alarms"] = meta.get("entity_alarms", "[]")
    c["entity_models"] = meta.get("entity_models", "[]")
    c["topic_tags"] = meta.get("topic_tags", "[]")
    c["category_l2"] = meta.get("category_l2", "")
    c["content_type"] = meta.get("content_type", "")
    c["has_entity"] = meta.get("has_entity", False)
    c["entity_model_variants"] = meta.get("entity_model_variants", "[]")
    # 内部字段用于 boost 计算
    c["_topic_tags"] = meta.get("topic_tags", "[]")
    c["brand"] = meta.get("brand", "unknown")
    return c


# ── BM25 混合检索索引 ──────────────────────────────────────────────────

class BM25Index:
    """BM25 稀疏检索索引 — 从 ChromaDB 构建，pickle 持久化，jieba 中文分词."""

    def __init__(self):
        self.bm25 = None
        self.docs = []
        self.metas = []
        self._loaded = False

    def _ensure_index(self):
        if self._loaded:
            return True
        if not _BM25_AVAILABLE:
            return False

        # 尝试从缓存加载 (分词结果已缓存，重建 BM25 很快)
        if BM25_INDEX_PATH.exists():
            try:
                data = _pickle.loads(BM25_INDEX_PATH.read_bytes())
                self.docs = data["docs"]
                self.metas = data["metas"]
                tokenized = data["tokenized"]
                t0 = time.time()
                self.bm25 = BM25Okapi(tokenized)
                self._loaded = True
                print(f"BM25 索引已从缓存加载: {len(self.docs)} chunks, 重建 {time.time()-t0:.1f}s")
                return True
            except Exception as e:
                print(f"BM25 缓存加载失败，将重建: {e}")
                # 删除损坏缓存
                try:
                    BM25_INDEX_PATH.unlink()
                except Exception:
                    pass

        # 从 ChromaDB 构建
        return self._build_from_chroma()

    def _build_from_chroma(self):
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            coll = client.get_collection(name=COLLECTION_NAME)
            total = coll.count()
            print(f"构建 BM25 索引 ({total} chunks)...")
            t0 = time.time()

            # 分批加载文档
            self.docs = []
            self.metas = []
            batch_size = 10000
            for offset in range(0, total, batch_size):
                batch = coll.get(
                    limit=min(batch_size, total - offset),
                    offset=offset,
                    include=["documents", "metadatas"],
                )
                self.docs.extend(batch["documents"])
                self.metas.extend(batch["metadatas"])

            load_t = time.time() - t0
            print(f"  ChromaDB 加载: {load_t:.1f}s")

            # jieba 分词 (最耗时的步骤)
            t0 = time.time()
            tokenized = [list(jieba.cut(doc)) for doc in self.docs]
            tokenize_t = time.time() - t0
            print(f"  jieba 分词: {tokenize_t:.1f}s")

            # 构建 BM25
            t0 = time.time()
            self.bm25 = BM25Okapi(tokenized)
            self._loaded = True
            print(f"  BM25 构建: {time.time()-t0:.1f}s")

            # 持久化：只存 docs + metas + tokenized，不存 bm25 对象
            t0 = time.time()
            BM25_INDEX_PATH.write_bytes(_pickle.dumps({
                "docs": self.docs, "metas": self.metas, "tokenized": tokenized,
            }))
            print(f"  缓存写入: {time.time()-t0:.1f}s ({BM25_INDEX_PATH.stat().st_size/1024/1024:.0f} MB)")
            print(f"BM25 索引构建完成: {len(self.docs)} chunks, 总耗时 {load_t+tokenize_t:.1f}s")
            return True
        except Exception as e:
            print(f"BM25 索引构建失败: {e}")
            return False

    def search(self, query: str, n_results: int = BM25_TOP_K, where_filter=None) -> list:
        """BM25 搜索，返回 [(doc, meta, bm25_score), ...]"""
        if not self._ensure_index():
            return []
        tokens = list(jieba.cut(query))
        scores = self.bm25.get_scores(tokens)

        # 带过滤的搜索（支持 $eq 与 $in；2026-08-20 修复: $in 此前被静默忽略退回全库）
        if where_filter:
            cat_cond = where_filter.get("category", {})
            if "$eq" in cat_cond:
                cat_key = cat_cond["$eq"]
                filtered = [
                    (i, s) for i, s in enumerate(scores)
                    if self.metas[i].get("category", "") == cat_key
                ]
                if filtered:
                    indices, score_vals = zip(*filtered)
                    indices, score_vals = list(indices), list(score_vals)
                else:
                    return []
            elif "$in" in cat_cond:
                cat_keys = set(cat_cond["$in"])
                filtered = [
                    (i, s) for i, s in enumerate(scores)
                    if self.metas[i].get("category", "") in cat_keys
                ]
                if filtered:
                    indices, score_vals = zip(*filtered)
                    indices, score_vals = list(indices), list(score_vals)
                else:
                    return []
            else:
                indices = list(range(len(scores)))
                score_vals = scores.tolist()
        else:
            indices = list(range(len(scores)))
            score_vals = scores.tolist()

        # 按分数排序取 top-k
        ranked = sorted(zip(indices, score_vals), key=lambda x: x[1], reverse=True)[:n_results]
        results = []
        for idx, sc in ranked:
            if sc > 0:
                results.append((self.docs[idx], self.metas[idx], sc))
        return results

    def invalidate(self):
        """索引失效，下次查询时重建."""
        self._loaded = False
        self.bm25 = None
        self.docs = []
        self.metas = []
        if BM25_INDEX_PATH.exists():
            BM25_INDEX_PATH.unlink()


_bm25_index = BM25Index()


def invalidate_indexes():
    """文档入库/更新后调用：使 BM25 索引与实体索引失效，下次检索自动重建。

    评审 M3: 此前 ingest 路径只写 ChromaDB，BM25 内存索引与实体倒排索引
    不失效，运行中的服务导入新文档后检索不到新内容，必须重启才生效。
    """
    global _entity_index_built
    _bm25_index.invalidate()
    _entity_index_built = False


def _rrf_fusion(vector_results, bm25_results, existing_texts, k=BM25_RRF_K):
    """Reciprocal Rank Fusion — 融合向量和 BM25 排名.

    RRF score = sum(1 / (k + rank_i)) across all lists.
    返回 merged chunks (去重后按 RRF 分数排序).
    """
    # 建立 text -> RRF score 映射
    rrf_scores = {}

    # 向量结果排名
    for rank, (doc, meta, vec_score) in enumerate(vector_results):
        rrf_scores[doc] = rrf_scores.get(doc, 0) + 1.0 / (k + rank + 1)

    # BM25 结果排名
    for rank, (doc, meta, bm25_score) in enumerate(bm25_results):
        rrf_scores[doc] = rrf_scores.get(doc, 0) + 1.0 / (k + rank + 1)

    # 按 RRF 分数排序
    merged = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    # 构建 doc->meta 映射
    doc_meta = {}
    for doc, meta, _ in vector_results:
        doc_meta[doc] = meta
    for doc, meta, _ in bm25_results:
        if doc not in doc_meta:
            doc_meta[doc] = meta

    chunks = []
    for doc, rrf_score in merged:
        if doc in existing_texts:
            continue
        meta = doc_meta.get(doc, {})
        # RRF 分数归一化到 0-1 范围 (理论最大值 = 2/(k+1))
        normalized = min(rrf_score / (2.0 / (k + 1)), 0.98)
        _c = _build_chunk_v2(doc, meta, normalized)
        _c["_rrf"] = True  # 排名融合分数, 与语义分数尺度不同 (2026-08-14)
        chunks.append(_c)
        existing_texts.add(doc)
    return chunks


def retrieve(query: str, top_k: int = DEFAULT_TOP_K, log_channel: str = ""):
    query = _normalize_query(query)
    _req_id = f"rq_{int(time.time()*1000) % 10**8:08d}"  # 短 request_id

    # ── 多问题拆分 ──
    # 当一条消息含"以及/还有/另外/同时/并且"时，拆成多个子问题分别检索再合并
    # 注意：不包含"和/与/及"——这些在中文中更多连接并列短语而非独立问题
    _MULTI_Q_SPLIT_RE = re.compile(r'(?:以及|还有|另外|同时|并且)(?:\s*)')
    # 仅当分隔符两侧都有≥4个中文字符时才拆分（避免把"A以及B"这种短词拆开）
    parts = _MULTI_Q_SPLIT_RE.split(query)
    parts = [p.strip() for p in parts if len(re.findall(r'[\u4e00-\u9fff]', p)) >= 4]

    if len(parts) >= 2:
        logger.info(f"多问题拆分: {len(parts)} 子问题 → {parts}")
        all_chunks = []
        seen_texts = set()
        per_query_k = max(3, top_k // len(parts) + 2)  # 每个子问题分到的 top_k

        for part in parts:
            sub_results = _retrieve_single(part, per_query_k)
            for c in sub_results:
                if c["text"] not in seen_texts:
                    all_chunks.append(c)
                    seen_texts.add(c["text"])

        # 按分数排序，取 top_k*2（给后续 filter 留余量）
        all_chunks.sort(key=lambda x: x["score"], reverse=True)
        result = all_chunks[:top_k * 2]
        if log_channel:
            log_query(query, result, channel_name=log_channel, query_type="qa", request_id=_req_id)
        return result

    result = _retrieve_single(query, top_k)
    if log_channel:
        log_query(query, result, channel_name=log_channel, query_type="qa", request_id=_req_id)
    return result



def _retrieve_single(query: str, top_k: int):
    _t0 = time.time()
    collection = get_collection()
    _t1 = time.time()

    # ── 实体提取 ──
    alarm_codes = _extract_alarm_codes(query)
    model_numbers = _extract_model_numbers(query)

    # ── 查询增强 + 同义词扩展 ──
    # _augment_query → 基于实体类型追加领域术语（规则，零延迟）
    # expand_query  → 同义词扩展
    expanded_query = expand_query(_augment_query(query))

    # ── 大类前置判断 ──
    target_category = classify_query(query)
    target_l2 = _query_to_l2(query)  # 二级分类

    where_filter = None
    if target_category:
        cats = _CATEGORY_EQUIV.get(target_category, [target_category])
        where_filter = (
            {"category": {"$eq": cats[0]}}
            if len(cats) == 1
            else {"category": {"$in": cats}}
        )

    # ── 并行：SAG entity + 向量搜索 + BM25 搜索 ──
    _t_pre = time.time()
    
    # SAG-Lite 混合检索 (如果可用)
    sag_chunks = []
    try:
        import sys as _sys
        _sys.path.insert(0, "/mnt/c/Users/Eric Jia/SAG-poc")
        from sag_hybrid import hybrid_search as _sag_search
        sag_chunks = _sag_search(query, top_k=6)
        logger.info(f"[SAG] entity search: {len(sag_chunks)} results in {time.time()-_t_pre:.3f}s")
    except Exception as _e:
        logger.debug(f"[SAG] unavailable: {_e}")
    
    # SAG 结果优先 (entity-exact > entity-hop)
    _sag_merged = []
    _sag_seen_sources = set()
    for _c in sag_chunks:
        if _c.get('method') == 'entity-exact' and _c['source'] not in _sag_seen_sources:
            _sag_seen_sources.add(_c['source'])
            _sag_merged.append({
                'source': _c['source'], 'text': _c.get('text', ''),
                'score': _c.get('score', 0.95), 'filename': _c['source'],
                '_method': _c['method'], '_match': _c.get('match', ''),
            })
    for _c in sag_chunks:
        if _c.get('method') == 'entity-hop' and _c['source'] not in _sag_seen_sources:
            _sag_seen_sources.add(_c['source'])
            _sag_merged.append({
                'source': _c['source'], 'text': _c.get('text', ''),
                'score': _c.get('score', 0.80), 'filename': _c['source'],
                '_method': _c['method'], '_match': _c.get('match', ''),
            })

    def _do_vector():
        _tv = time.time()
        # 2026-08-21: 候选池扩大到 top_k*3(≥30)——RRF 融合需要双源候选，
        # 向量只取 top_k 时，向量排名靠后但 BM25 靠前的精确答案(如 B-83444 润滑章节
        # 向量第 22 位) 单源进融合 → RRF 低分被挤出 top-N。
        results = collection.query(
            query_texts=[expanded_query], n_results=max(top_k * 3, 30),
            where=where_filter,
        )
        if not results['documents'][0] and where_filter:
            results = collection.query(query_texts=[expanded_query], n_results=max(top_k * 3, 30))
        _tv2 = time.time()
        logger.info(f"[TIMING] vector query: {_tv2-_tv:.2f}s")
        return list(zip(
            results['documents'][0], results['metadatas'][0], results['distances'][0]
        ))

    def _do_bm25():
        _tb = time.time()
        r = _bm25_index.search(expanded_query, n_results=BM25_TOP_K, where_filter=where_filter)
        if not r and where_filter:
            # 分类过滤下无结果时去掉 filter 重试（与向量检索 fallback 一致，2026-08-20）
            r = _bm25_index.search(expanded_query, n_results=BM25_TOP_K)
        logger.info(f"[TIMING] BM25 search: {time.time()-_tb:.2f}s")
        return r

    with ThreadPoolExecutor(max_workers=2) as _exe:
        _vec_fut = _exe.submit(_do_vector)
        _bm25_fut = _exe.submit(_do_bm25)
        vector_results = _vec_fut.result()
        bm25_results = _bm25_fut.result()
    _t_parallel = time.time()
    logger.info(f"[TIMING] vector+BM25 parallel: {_t_parallel-_t_pre:.2f}s")

    # ── RRF 融合 ──
    if bm25_results:
        existing_texts = set()
        rrf_chunks = _rrf_fusion(vector_results, bm25_results, existing_texts)
        # 2026-08-22: 截断放宽 top_k*3——RRF 融合后短文本精确答案（如 R-2000iC 的
        # B-82334CM §7.3.3，向量第 8 + BM25 第 19）RRF 排名 ~15-20，top_k*2=20 截断
        # 会把它切掉；放宽到 30 让 overlap 锚点豁免（见下）有机会保住它。
        chunks = rrf_chunks[:top_k * 3]
    else:
        chunks = [
            _build_chunk_v2(doc, meta, 1 - dist)
            for doc, meta, dist in vector_results
        ]

    existing_texts = {c["text"] for c in chunks}

    # ── 并行：实体精确搜索（alarm + model + variant） ──
    _t_entity = time.time()
    _build_entity_index(collection)
    model_variants = _extract_model_variants(expanded_query)  # 独立于 model_numbers（如 270F/270R 无横杠但需检索）

    with ThreadPoolExecutor(max_workers=3) as _exe:
        _entity_futs = []
        if alarm_codes:
            _entity_futs.append(
                _exe.submit(_entity_alarm_search, collection, alarm_codes, set(existing_texts))
            )
        if model_numbers:
            _entity_futs.append(
                _exe.submit(_entity_model_search, collection, model_numbers, query, set(existing_texts))
            )
        if model_variants:
            _entity_futs.append(
                _exe.submit(_entity_variant_search, collection, model_variants, query, set(existing_texts))
            )

    # 主线程合并结果（统一去重）
    for _fut in _entity_futs:
        for _c in _fut.result():
            if _c.get("_in_existing"):
                # 同文本已在 RRF 候选（BM25/vector 命中）→ 升级：实体精确分 + 标记，
                # 否则实体版被 existing 去重丢弃、RRF 低分版被 top_k 截断
                # （B-82135 电机表 A06B 参考丢失案例）。
                for _cc in chunks:
                    if _cc["text"] == _c["text"]:
                        _cc["score"] = _c["score"]
                        for _k in ("_entity_match", "_gen_reference", "_variant_kw"):
                            if _c.get(_k):
                                _cc[_k] = _c[_k]
                        break
                continue
            if _c["text"] not in existing_texts:
                chunks.append(_c)
                existing_texts.add(_c["text"])
    logger.info(f"[TIMING] entity search: {time.time()-_t_entity:.2f}s (alarms={alarm_codes}, models={model_numbers})")

    # 型号规格后缀加分：多个 variant 命中同一 chunk 时加分
    if len(model_variants) >= 2:
        for c in chunks:
            match_count = sum(1 for v in model_variants if v.upper() in c["text"].upper())
            if match_count >= 2:
                c["score"] = min(c["score"] + 0.15, 0.98)

    # ── 型号后缀变体 $contains 兜底 ──
    # 实体索引可能未覆盖所有变体（如 270F/270R 未在 entity_model_variants 元数据中），
    # 此处直接对变体字符串做全文包含搜索作为兜底
    if model_variants:
        _t_variant_kw = time.time()
        for v in model_variants[:3]:
            try:
                # ponytail: 用 BM25 内存索引做精确子串匹配 (2026-08-12 330L 事件:
                # ChromaDB $contains 的 FTS 把 "330L" 分词为 "330"+"L", 单字符 "L" 大量误匹配,
                # 规格表被误匹配 chunk 同分挤出。BM25 docs 是原始文本, v in doc 精确可靠)。
                _cands = []
                if _bm25_index._loaded:
                    for doc, meta in zip(_bm25_index.docs, _bm25_index.metas):
                        if v in doc and doc not in existing_texts:
                            _pos = doc.upper().find(v.upper())
                            _boost = 0.25 if _pos < 300 else 0.05  # 型号在前部权重高
                            if any(w in doc for w in ("规格", "参数", "动作速度", "可搬运")):
                                _boost += 0.10
                            _c = _build_chunk_v2(doc, meta, min(0.88 + _boost, 0.99))
                            _c["_variant_kw"] = v
                            _cands.append(_c)
                else:
                    # 回退: ChromaDB $contains (tokenization 可能误匹配, 尽力而为)
                    kw = collection.get(
                        where_document={"$contains": v}, limit=50,
                        include=["documents", "metadatas"],
                    )
                    for doc, meta in zip(kw["documents"], kw["metadatas"]):
                        if doc not in existing_texts:
                            _pos = doc.upper().find(v.upper())
                            _boost = 0.25 if _pos >= 0 and _pos < 300 else 0.05
                            if any(w in doc for w in ("规格", "参数", "动作速度", "可搬运")):
                                _boost += 0.10
                            _c = _build_chunk_v2(doc, meta, min(0.88 + _boost, 0.99))
                            _c["_variant_kw"] = v
                            _cands.append(_c)
                # 同分时含速度词优先 (规格表 vs 型号清单页)
                _cands.sort(key=lambda c: (c["score"],
                                           1 if ("速度" in c["text"] or "动作速度" in c["text"]) else 0),
                            reverse=True)
                for _c in _cands[:4]:
                    chunks.append(_c)
                    existing_texts.add(_c["text"])
            except Exception:
                pass
        logger.info(f"[TIMING] variant kw: {time.time()-_t_variant_kw:.2f}s (variants={model_variants})")

    # ── 二级分类补充搜索 ──
    if target_l2:
        l2_chunks = _category_l2_search(collection, query, target_l2, existing_texts)
        chunks.extend(l2_chunks)

    # ── topic_tags 加权 ──
    _topic_tag_boost(chunks, query)

    # 关键词精确补充：当查询含报警代码时，强制召回包含该字符串的 chunks
    _t_alarm_kw = time.time()
    # PDF 中报警代码连字符可能是全角 "－"(U+FF0D) 或半角 "-"，但 entity extraction
    # Phase 1 已标准化 entity_alarms 元数据，此处直接对标准化后的 code 做全文包含匹配
    alarm_codes = _ALARM_CODE_RE.findall(query)
    if alarm_codes:
        # ponytail: chromaDB 1.5.x where_document $or silently returns [] on PersistentClient
        # (no exception raised). Fall back to per-code loop when zero hits.
        kw = {"documents": []}
        try:
            all_variants = []
            for code in alarm_codes[:3]:
                all_variants.append({"$contains": code})
                all_variants.append({"$contains": code.replace("-", "－")})
            kw = collection.get(
                where_document={"$or": all_variants},
                limit=min(15 * len(alarm_codes), 50),
                include=["documents", "metadatas"],
            )
        except Exception:
            pass
        if not kw.get("documents"):
            # per-code fallback (also covers $or silent-empty)
            all_docs, all_metas = [], []
            for code in alarm_codes[:3]:
                try:
                    sub = collection.get(
                        where_document={"$contains": code}, limit=15,
                        include=["documents", "metadatas"],
                    )
                    all_docs.extend(sub.get("documents", []))
                    all_metas.extend(sub.get("metadatas", []))
                except Exception:
                    continue
            kw = {"documents": all_docs, "metadatas": all_metas}
        for code in alarm_codes[:3]:
            for doc, meta in zip(kw.get("documents", []), kw.get("metadatas", [])):
                if doc not in existing_texts:
                    chunks.append(_build_chunk_v2(doc, meta, _keyword_score(doc, code)))
                    existing_texts.add(doc)

    logger.info(f"[TIMING] alarm_code $contains: {time.time()-_t_alarm_kw:.2f}s (codes={alarm_codes})")

    # ── 功能/选项名称关键词精准召回 ──
    # 针对 FANUC 功能名称（PC Interface, RTCP, DeviceNet 等）做精确匹配，
    # 避免向量检索将相似缩写混淆（如 PC Interface ↔ DeviceNet Interface）
    _t_feature_kw = time.time()
    _FEATURE_NAME_KW = _get_feature_name_kw()
    # 以下为兜底逻辑（当 config 未加载时由 _get_feature_name_kw 内联提供）
    _feature_hit = set()
    for pat, variants in _FEATURE_NAME_KW.items():
        if not pat.search(query):
            continue
        fname = pat.pattern.split('|')[0].replace('\\s*', ' ')[:30]
        for v in variants:
            try:
                kw = collection.get(
                    where_document=v, limit=8,
                    include=["documents", "metadatas"],
                )
                for doc, meta in zip(kw["documents"], kw["metadatas"]):
                    if doc not in existing_texts:
                        score = 0.90 if _contains_ci(doc, fname) else 0.78
                        c = _build_chunk_v2(doc, meta, score)
                        c["_feature_match"] = fname
                        chunks.append(c)
                        existing_texts.add(doc)
                        _feature_hit.add(fname)
            except Exception:
                pass
    if _feature_hit:
        logger.info(f"[TIMING] feature_name kw: {time.time()-_t_feature_kw:.2f}s (features={_feature_hit})")

    # 上位机/Robot Interface 关键词强制召回
    _t_kw2 = time.time()
    # 用户问"上位机/寄存器读写"时常与 Robot Interface 文档语义距离远，需精确匹配补回
    _UPPER_COMPUTER_KW = re.compile(r'上位机|robot\s*interface|寄存器读|寄存器写|读写寄存器', re.I)
    if _UPPER_COMPUTER_KW.search(query):
        ri_variants = [
            {"$contains": "Robot Interface"},
            {"$contains": "robot interface"},
            {"$contains": "上位机"},
        ]
        for v in ri_variants:
            try:
                kw = collection.get(
                    where_document=v, limit=10,
                    include=["documents", "metadatas"],
                )
                for doc, meta in zip(kw["documents"], kw["metadatas"]):
                    if doc not in existing_texts:
                        score = 0.92 if "Robot Interface" in doc[:500] else 0.85
                        chunks.append(_build_chunk_v2(doc, meta, score))
                        existing_texts.add(doc)
            except Exception:
                pass
    logger.info(f"[TIMING] upper_computer_kw: {time.time()-_t_kw2:.2f}s")

    # 型号系列关键词补充：当查询含机器人型号时，强制召回该型号的文档
    _t_model = time.time()
    model_series = _MODEL_SERIES_RE.findall(query.upper())
    # 过滤掉已被报警代码捕获的
    model_series = [m for m in model_series if m not in [c.upper() for c in alarm_codes]]
    if model_series:
        # 如果现有结果已有高分命中，跳过型号遍历节省时间
        existing_best = max((c["score"] for c in chunks), default=0)
        # ponytail: 向量高分≠好答案 (搬运页/连接图亦 0.98, 但缺规格内容)。
        # 现有结果不含规格表内容时, 即使分数高也执行型号精确搜索补全 (2026-08-12 330L 事件)
        _has_spec = any(("规格一览" in c["text"]) or ("最大动作速度" in c["text"])
                        or ("可搬运重量" in c["text"]) for c in chunks)
        if existing_best < 0.85 or not _has_spec:
            for model in model_series[:3]:
                model_files = _get_model_files(collection, model)
                # 品牌过滤：查询含 FANUC 时，排除明显非 FANUC 的文档（如 KUKA Series 2000）
                is_fanuc_q = bool(re.search(r'fanuc', query, re.I))
                if is_fanuc_q:
                    model_files = {fn for fn in model_files
                                   if re.search(r'(?i)fanuc|B-\\d{5}|R-30i|M-\\d{3}', fn)}
                for fn in list(model_files)[:5]:  # 最多搜 5 个文件
                    try:
                        fc = collection.query(
                            query_texts=[query],
                            where={"filename": {"$eq": fn}},
                            n_results=2,
                        )
                        for doc, meta, dist in zip(
                            fc["documents"][0], fc["metadatas"][0], fc["distances"][0],
                        ):
                            if doc not in existing_texts:
                                sem_score = 1 - dist
                                # 型号在前300字给额外加分
                                boost = 0.10 if model in doc[:300].upper() else 0.05
                                score = min(sem_score + boost, 0.97)
                                chunks.append(_build_chunk_v2(doc, meta, score))
                                existing_texts.add(doc)
                    except Exception as e:
                        logger.warning(f"型号语义检索失败: {e}")
        # 已在语义结果中的 chunks，如果包含目标型号且分数偏低（语义检索原始分），给予加分
        for c in chunks:
            if c["score"] >= 0.80:
                continue
            for model in model_series:
                if model.upper() in c["text"][:300].upper():
                    c["score"] = c["score"] + 0.15
                    break

    # 话题补充搜索：去掉型号后做全库语义检索 + 关键词检索，捕获跨型号通用规格
    logger.info(f"[TIMING] model_series search: {time.time()-_t_model:.2f}s (models={model_series})")
    _t_topic = time.time()
    _topic_chunks = []
    if model_series:
        topic_q = re.sub(r'[A-Z]{1,2}-\d{2,4}[A-Za-z/\d]*', '', query).strip()
        topic_q = re.sub(r'(?i)fanuc\s*', '', topic_q).strip()
        if len(topic_q) >= 2:
            # 语义补充
            try:
                sup = collection.query(query_texts=[topic_q], n_results=5)
                for doc, meta, dist in zip(
                    sup["documents"][0], sup["metadatas"][0], sup["distances"][0],
                ):
                    if doc not in existing_texts:
                        c = _build_chunk_v2(doc, meta, 1 - dist)
                        c["_topic"] = True
                        chunks.append(c)
                        _topic_chunks.append(c)
                        existing_texts.add(doc)
            except Exception as e:
                logger.debug(f"话题补充搜索失败: {e}")
            # 关键词补充：提取中文关键词做 $contains 检索（用语义重排，避免泛词刷屏）
            _TOPIC_KW = ['电池', '润滑脂', '润滑油', '保养周期', '备件', '配件清单']
            hit_kws = [kw for kw in _TOPIC_KW if kw in topic_q]
            for kw in hit_kws[:2]:
                try:
                    # 在含该关键词的 chunk 中做语义重排
                    kw_r = collection.query(
                        query_texts=[query],
                        where_document={"$contains": kw},
                        n_results=5,
                    )
                    for doc, meta, dist in zip(
                        kw_r["documents"][0], kw_r["metadatas"][0], kw_r["distances"][0],
                    ):
                        if doc not in existing_texts:
                            sem_score = 1 - dist
                            score = min(sem_score + 0.10, 0.85)
                            c = _build_chunk_v2(doc, meta, score)
                            c["_topic"] = True
                            chunks.append(c)
                            _topic_chunks.append(c)
                            existing_texts.add(doc)
                except Exception as e:
                    logger.debug(f"关键词补充搜索失败: {e}")

    # ── 过滤垃圾 chunk ──
    logger.info(f"[TIMING] topic search: {time.time()-_t_topic:.2f}s")
    # 1. 文本过短（纯页码/纯URL）直接丢弃
    # 2. 语义分数过低（与查询不相关）直接丢弃
    # 3. 乱码文本（UTF-8 被错误解码为 Latin-1）丢弃
    # 注意：报警代码关键词补充的 chunk 保留（score 由 _keyword_score 给出，通常 >= 0.6）
    def _is_garbage(c):
        text = c["text"].strip()
        if len(text) < MIN_TEXT_LEN:
            return True
        # 纯 URL / 纯数字 / 纯标点
        if text.startswith("http") or text.startswith("www"):
            return True
        alpha_count = sum(1 for ch in text if ch.isalpha())
        if len(text) < 50 and alpha_count < 5:
            return True
        # 乱码检测：高位 Latin 字符 (À-ÿ) 占比过高 = UTF-8 被当 Latin-1 解码
        latin_high = sum(1 for ch in text if '\u00c0' <= ch <= '\u00ff')
        if len(text) > 50 and latin_high / len(text) > 0.15:
            return True
        return False

    # ponytail: RRF 排名融合分数 (<0.50) 与语义分数尺度不同, 豁免 score 阈值 (2026-08-14
    # 负载推算查询召回 0: 30 个 RRF 结果全被 MIN_SCORE=0.50 滤掉)。文本质量检查仍生效。
    chunks = [c for c in chunks
              if not _is_garbage(c) and (c.get("_rrf") or c["score"] >= MIN_SCORE)]

    # ── 实体型号精确召回提分（2026-08-23）──
    # _entity_model_search 的分数（0.75-0.95）与 vector 相似度分数尺度不同。
    # 注意: 提分必须小——参考/同代实体压过 vector 精确答案会引发跨代套用
    # （M-900iB 换油: B-82135 iA 检修表 +0.12→0.95 压过 B-83444 iB §7.3.3）。
    # 进 top-10 只需 >0.65，故参考 +0.03、同代 +0.02 足够。
    for c in chunks:
        if c.get("_gen_reference"):
            c["score"] = min(c["score"] + 0.03, 0.90)
        elif c.get("_entity_match") == "model":
            c["score"] = min(c["score"] + 0.02, 0.92)

    # 按分数降序排序
    chunks.sort(key=lambda c: c["score"], reverse=True)

    # ponytail: 精确型号匹配 (variant) 结果前置, 防被通用高分 chunk 挤出 (330L 事件:
    # 规格表 0.97 被同文件搬运页 0.98 挤掉)。用户明确问的型号 > 通用相似。
    if any(c.get("_variant_kw") for c in chunks):
        _var = [c for c in chunks if c.get("_variant_kw")]
        _rest = [c for c in chunks if not c.get("_variant_kw")]
        chunks = _var + _rest

    # ── 报警代码精确匹配加分 ──
    # 当查询含报警代码时，对文本中包含该代码的 chunk 加分，确保精确匹配排在语义相似结果前面
    alarm_codes = _ALARM_CODE_RE.findall(query)
    if alarm_codes:
        for c in chunks:
            text_upper = c["text"].upper()
            for code in alarm_codes:
                code_upper = code.upper()
                # 检查是否包含精确报警代码（考虑全角/半角连字符）
                if code_upper in text_upper or code_upper.replace("-", "－") in text_upper:
                    # 精确匹配加分：确保排在语义相似结果前面
                    if c["score"] < 0.95:
                        c["score"] = min(c["score"] + 0.30, 0.95)
                        c["_alarm_exact_match"] = code
                    break

    # ── Cross-encoder 重排序（可选） ──
    # 用 reranker 对 top-K 候选重新评分，提升排序精度。
    # 依赖 sentence-transformers，未安装时自动跳过。
    _t_rerank = time.time()
    chunks = _rerank_chunks(query, chunks)
    logger.info(f"[TIMING] rerank: {time.time()-_t_rerank:.2f}s ({len(chunks)} chunks)")

    # ponytail: rerank 会打乱精确型号匹配(variant)的前置, 这里重新前置 (330L 事件:
    # 规格表是表格文本, cross-encoder 分低会被重排到后, 但它是用户明确问的型号)
    if any(c.get("_variant_kw") for c in chunks):
        _var = [c for c in chunks if c.get("_variant_kw")]
        _rest = [c for c in chunks if not c.get("_variant_kw")]
        chunks = _var + _rest

    # ── rerank 后恢复实体提分（2026-08-23）──
    # cross-encoder 对表格/型号清单文本打低分（B-82135 电机表 A06B 被重排到 10 名外），
    # 但实体索引命中 = 型号精确匹配，可信度高于语义相似度。恢复提分后再排序：
    # - 相邻代际参考（_gen_reference）: +0.03 cap 0.90（同排序前提分，避免压过精确答案）
    # - 同代实体（_entity_match=model）: +0.02 cap 0.92
    _needs_resort = False
    for c in chunks:
        if c.get("_gen_reference"):
            c["score"] = min(c["score"] + 0.03, 0.90)
            _needs_resort = True
        elif c.get("_entity_match") == "model":
            c["score"] = min(c["score"] + 0.02, 0.92)
            _needs_resort = True
    if _needs_resort:
        chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
        # 重新前置 variant（恢复的顺序可能在 sort 后被覆盖）
        if any(c.get("_variant_kw") for c in chunks):
            _var = [c for c in chunks if c.get("_variant_kw")]
            _rest = [c for c in chunks if not c.get("_variant_kw")]
            chunks = _var + _rest


    # ponytail: merge SAG entity results BEFORE diversity filter so entity-exact
    # chunks aren't pushed out of top_k by vector-only chunks
    if _sag_merged:
        _existing = {c.get("text","")[:100] for c in chunks}
        _merged = []
        for _c in _sag_merged:
            if _c.get("text","")[:100] not in _existing:
                _merged.append(_c)
                _existing.add(_c.get("text","")[:100])
        chunks = _merged + chunks

    # 文件多样性：同一文件最多保留 max_per_file 个 chunk，确保覆盖更多文件
    max_per_file = 5 if model_series else top_k  # 型号查询保留规格表等多章节
    if max_per_file < top_k:
        # ponytail: 330L 事件 — 规格表可能仅 BM25 命中 (RRF 排名低) 无 _variant_kw 标记,
        # rerank 后排后, 单遍遍历 break 前未轮到它。两遍扫描:
        # 1) 先收集豁免 chunk (型号变体/规格一览/动作速度), 按"含速度词"排序取前 top_k
        # 2) 再补普通 chunk 到 max_per_file/文件
        _spec_kw = list(model_variants) + ["规格一览", "动作速度"]
        # 2026-08-22: 手册号锚点 chunk 优先保留（R-2000iC 换油案例: B-82334 §7.3.3
        # RRF 排第 17，diversity 截断 top_k 时被砍——锚点命中=强匹配，进 _exempt）
        _anchors = re.findall(r'B-\d{5}[A-Z]{2}', (expanded_query or query).upper())
        _anchor_c_ids = set()
        if _anchors:
            for _c in chunks:
                if any(a in str(_c.get("source", "")).upper() for a in _anchors):
                    _anchor_c_ids.add(id(_c))
        _exempt = [c for c in chunks
                   if c.get("_variant_kw") or c.get("_gen_reference")
                   or any(w in c["text"] for w in _spec_kw) or id(c) in _anchor_c_ids]
        # 排序: 含速度/动作速度词的规格表优先于 score (rerank 可能覆盖 variant 分数,
        # 表格文本 cross-encoder 分低, 330L 事件); 相邻代际参考(_gen_reference)同级别——
        # 5d 近似参考素材, 不能被 B-83684 的 280L 规格表占满前 top_k 挤掉 (2026-08-23)
        _exempt.sort(key=lambda c: (1 if ("速度" in c["text"] or "动作速度" in c["text"]
                                          or c.get("_gen_reference")) else 0,
                                    c["score"]),
                     reverse=True)
        selected = list(_exempt[:top_k])
        selected_ids = {id(c) for c in selected}
        file_count = {}
        for c in chunks:
            if id(c) in selected_ids:
                continue
            fn = c["filename"]
            file_count[fn] = file_count.get(fn, 0) + 1
            if file_count[fn] <= max_per_file:
                selected.append(c)
            if len(selected) >= top_k:
                break
        chunks = selected

    # 话题补充槽位保留：确保至少 2 个话题补充 chunk 进入最终结果
    if _topic_chunks:
        selected_ids = {id(c) for c in chunks}
        missed = [c for c in _topic_chunks if id(c) not in selected_ids]
        missed.sort(key=lambda c: c["score"], reverse=True)
        for tc in missed[:2]:
            chunks.append(tc)

    # ── 品牌过滤：基于 ChromaDB brand 元数据，排除非 FANUC 文档 ──
    # 对比/跨品牌类查询豁免品牌过滤（需要保留双方文档）
    is_compare_q = bool(re.search(r'区别|对比|vs\.?|比较|优缺点|哪个好|选哪', query, re.I))
    # ponytail: 用户 query 含 FANUC 指纹时，对未知 brand 的 chunk 做反向过滤
    #   unknown 占 53% 不能一刀切, 但如果 chunk text 含明确非 FANUC 品牌词, 也排除
    is_fanuc_q = bool(re.search(r'(?i)fanuc|发那科|R-?\d{2,4}i|M-\d{3}i|B-\d{5}EN', query))
    _NON_FANUC_KW = re.compile(r'(?i)kuka|abb|siemens|西门子|发那科以外的|visu\+|karel以外的|rapid reference')
    before = len(chunks)
    def _brand_keep(c):
        if is_compare_q:
            return True
        b = c.get("brand", "unknown")
        if b in ("fanuc", "unknown"):
            if is_fanuc_q and b == "unknown" and _NON_FANUC_KW.search(c.get("text", "")):
                return False
            return True
        return False
    good = [c for c in chunks if _brand_keep(c)]
    if good:
        chunks = good
        removed = before - len(good)
        if removed:
            logger.info(f"品牌过滤: 排除 {removed}/{before} 个, 保留 {len(good)} 个")
    else:
        # 全部是竞品文档：保留 top-5 高分的（品牌过滤告知前台）
        logger.warning(f"品牌过滤: 全部 {before} 个文档为非 FANUC 品牌，保留最高分项")
        chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
        chunks = chunks[:min(5, before)]
        for c in chunks:
            c["_non_fanuc"] = True

    # ── SAG entity 结果置顶 (entity-exact > entity-hop > vector) ──
    if _sag_merged:
        _existing = {c.get("text","")[:100] for c in chunks}
        _merged = []
        for _c in _sag_merged:
            if _c.get("text","")[:100] not in _existing:
                _merged.append(_c)
                _existing.add(_c.get("text","")[:100])
        # SAG results first, then existing chunks
        chunks = _merged + chunks
        logger.info(f"[SAG] merged {len(_merged)} entity results into top of {len(chunks)} total")

    # ── query 改写器 (ponytail, 2026-07-27): 召回为 0 时, 自动追加领域术语再检索一次
    if not chunks:
        _rewrite_terms = []
        if _ALARM_CODE_RE.search(query) and not re.search(r'报警|处理|对策|原因', query):
            _rewrite_terms = ["报警", "处理", "对策"]
        elif re.search(r'\bDB\b|\bTB\b', query) and not re.search(r'指令|轨迹', query):
            _rewrite_terms = ["指令", "轨迹", "速度"]
        elif re.search(r'JD\d+|端口.*针脚', query) and not re.search(r'接口|连接器|引脚', query):
            _rewrite_terms = ["接口", "连接器"]
        elif re.search(r'高惯量', query) and not re.search(r'模式|惯量|负载', query):
            _rewrite_terms = ["模式", "惯量", "负载"]
        if _rewrite_terms:
            logger.info(f"[query-rewrite] retry with terms: {_rewrite_terms}")
            _rewritten = _retrieve_single(query + " " + " ".join(_rewrite_terms), top_k)
            if _rewritten:
                chunks = _rewritten

    # ── 不相关召回守卫 (ponytail, 2026-07-27): 召回 fragment 与 query token 重叠率 < 阈值时降权
    # ponytail: 防 A02/A10/D04 等"召回 5 条全不相关"污染
    # ponytail: 阈值 0.05 → 0.15, 严一档 (实测 F01 overlap=0.0 时降权 0.30 后 score 仍 0.35>0.3 漏过)
    _STOPWORDS = {"的", "是", "怎么", "如何", "fanuc", "机器人", "处理", "报警", "识别", "怎么办"}
    if _BM25_AVAILABLE:
        _q_tokens = set(jieba.cut(query.lower())) - _STOPWORDS
    else:
        _q_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', query.lower())) - _STOPWORDS
    if _q_tokens and chunks:
        # 2026-08-22: 手册号锚点豁免——查询含 B-XXXXX 手册号（_augment_query 锚点）时，
        # source 含该手册号的 chunk 视为精确匹配，不参与 overlap 降权。
        # 反例: R-2000iC 换油查询锚点 B-82334CM，其 7.3.3 短文本 chunk 重叠率 0.13<0.15
        #       被降权 0.5 掉出 top-20（对比长文本检修表 overlap 0.33 不降权）——
        #       短文本精确答案吃亏，锚点本身已是强匹配信号。
        _anchor_ids = set()
        _anchors = re.findall(r'B-\d{5}[A-Z]{2}', (expanded_query or query).upper())
        if _anchors:
            for _c in chunks:
                if any(a in str(_c.get("source", "")).upper() for a in _anchors):
                    _anchor_ids.add(id(_c))
        for _c in chunks:
            if id(_c) in _anchor_ids:
                # 锚点命中: 跳过 overlap 降权 + 加分进 top-N（RRF 分数可能低于通用高分 chunk）
                _c["score"] = min(_c.get("score", 0) + 0.30, 0.95)
                _c["_anchor_boost"] = True
                continue
            if _BM25_AVAILABLE:
                _c_tokens = set(jieba.cut(_c.get("text", "").lower())) - _STOPWORDS
            else:
                _c_tokens = set(re.findall(r'[\w\u4e00-\u9fff]+', _c.get("text", "").lower()))
            _overlap = len(_q_tokens & _c_tokens) / max(len(_q_tokens), 1)
            _c["_overlap"] = round(_overlap, 3)
            # ponytail: 三档 — 0 重叠=几乎无关丢弃; <0.15=勉强降权; >=0.15=保留
            if _overlap == 0:
                _c["score"] = 0.0
            elif _overlap < 0.15:
                _c["score"] = max(_c.get("score", 0) - 0.50, 0.0)
        chunks = [c for c in chunks if c.get("score", 0) > 0]  # 直接丢 overlap=0
        chunks.sort(key=lambda c: c.get("score", 0), reverse=True)
        if chunks and chunks[0].get("score", 0) < 0.3:
            logger.warning(f"[overlap-guard] all {len(chunks)} chunks low-relevance, return []")
            chunks = []

    for i, c in enumerate(chunks):
        c["index"] = i + 1
    logger.info(f"[TIMING] _retrieve_single TOTAL: {time.time()-_t0:.2f}s (init={_t1-_t0:.1f}s, top_k={top_k}, result={len(chunks)} chunks)")
    return chunks


def _extract_section(text: str, max_len: int = 60) -> str:
    """从 chunk 文本开头提取章节标题（第一个段落标题/编号行）。"""
    for line in text.split("\n")[:5]:
        line = line.strip()
        # 匹配章节标题模式: "1.1 概要" "第3章" "7. 远程TCP" "12.1.11 VL_EXPORT"
        if re.match(r'^[\d.]+\s+\S', line):
            return line[:max_len]
        # 匹配 "xxx功能" 或 "xxx概述" 式标题
        if re.match(r'^[\u4e00-\u9fff].{2,30}(功能|操作|设置|维护|说明|概述|介绍|定义|方法|步骤)$', line):
            return line[:max_len]
    return ""

def format_context(chunks):
    parts = []
    for c in chunks:
        cat = f"{c.get('category','?')}/{c.get('subcategory','?')}" if c.get('subcategory') else c.get('category','?')
        # 章节标题提取（三签名的"章节"来源）
        section = _extract_section(c.get('text', ''))
        # 附加元数据信息
        meta_info = []
        if section:
            meta_info.append(f"章节: {section}")
        if c.get('category_l2'):
            meta_info.append(f"细分: {c['category_l2']}")
        if c.get('content_type'):
            meta_info.append(f"类型: {c['content_type']}")
        if c.get('entity_alarms') and c['entity_alarms'] != '[]':
            meta_info.append(f"报警码: {c['entity_alarms']}")
        if c.get('entity_models') and c['entity_models'] != '[]':
            meta_info.append(f"匹配型号: {c['entity_models']}")
        meta_str = f" | {' '.join(meta_info)}" if meta_info else ""
        parts.append(
            f"【片段 {c['index']}】来源文件: **{c['filename']}** | "
            f"分类: {cat}{meta_str} | 相关度: {c['score']:.3f}\n"
            f"{c['text']}"
        )
    return "\n\n".join(parts)


def format_sources(chunks):
    lines = ["### 引用来源\n"]
    seen = set()
    for c in chunks:
        if c['filename'] in seen:
            continue
        seen.add(c['filename'])
        cat = f"{c['category']}/{c['subcategory']}" if c['subcategory'] else c['category']
        lines.append(
            f"- **{c['filename']}** (相关度 {c['score']:.3f}) — {cat}"
        )
    return "\n".join(lines)


def format_retrieval_only(chunks):
    lines = ["【检索结果（仅原文片段，LLM 不可用）】\n"]
    for c in chunks:
        cat = f"{c.get('category','?')}/{c.get('subcategory','?')}" if c.get('subcategory') else c.get('category','?')
        lines.append(f"[{c['index']}] 来源: {c['filename']} — {cat} (相关度 {c['score']:.3f})\n")
        lines.append(f"  {c['text'][:500]}\n")
    return "\n".join(lines)


# ── LLM Generation with Failover ───────────────────────────────────────

def generate_with_failover(query, chunks, preferred, temperature, usage_info=None):
    """带容灾的LLM生成. Yields (token, status_msg).

    usage_info: 可选 dict，填充后包含 {"prompt_tokens", "completion_tokens", "total_tokens"}.
    """
    context = format_context(chunks)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"--- 检索结果 ---\n{context}\n--- 结束 ---\n\n用户问题: {query}"},
    ]

    ordered = channel_mgr.get_ordered_channels(preferred)
    errors = []

    for ch in ordered:
        ch_name = ch["name"]
        yield ("", f"连接 {ch_name}...")

        try:
            if OpenAI is None:
                raise RuntimeError("openai SDK 未安装，请先安装 requirements.txt 中的 openai 依赖")
            client = OpenAI(
                base_url=ch["api_base"],
                api_key=ch["api_key"],
                timeout=ch["timeout"],
            )
            t0 = time.time()

            # 构建请求参数 — 尝试启用 usage 追踪
            kwargs = dict(
                model=ch["model_id"],
                messages=messages,
                temperature=temperature,
                seed=42,
                top_p=1,
                max_tokens=4096,
                stream=True,
                timeout=ch["timeout"],
            )
            # stream_options — 只对兼容的 API 启用
            if ch['name'] not in ('MiMo-Local',):
                kwargs['stream_options'] = {'include_usage': True}

            response = client.chat.completions.create(**kwargs)

            got_content = False
            for part in response:
                # 捕获 usage（通常在最后一个 chunk）
                if hasattr(part, "usage") and part.usage and usage_info is not None:
                    usage_info["prompt_tokens"] = getattr(part.usage, "prompt_tokens", 0) or 0
                    usage_info["completion_tokens"] = getattr(part.usage, "completion_tokens", 0) or 0
                    usage_info["total_tokens"] = getattr(part.usage, "total_tokens", 0) or 0

                if not part.choices:
                    continue
                delta = part.choices[0].delta
                if delta.content:
                    got_content = True
                    yield (delta.content, f"通道: {ch_name}")

            if got_content:
                latency = time.time() - t0
                channel_mgr.mark(ch["id"], True, latency=latency)
                return

            errors.append(f"{ch_name}: 空响应")

        except Exception as e:
            err = str(e)[:200]
            errors.append(f"{ch_name}: {err}")
            channel_mgr.mark(ch["id"], False, error=err)
            yield ("", f"{ch_name} 失败，切换下一通道...")

    error_detail = "\n".join(f"  {e}" for e in errors)
    fallback = format_retrieval_only(chunks)
    yield (
        f"\n\n"
        f"【所有模型通道均不可用，已降级为纯检索模式】\n\n"
        f"错误详情:\n{error_detail}\n\n"
        f"排查建议:\n"
        f"  - 检查网络是否能访问 api.llm.mioffice.cn\n"
        f"  - 本地 Ollama: 运行 ollama serve && ollama pull qwen2.5:3b\n\n"
        f"{fallback}",
        "已降级: 纯检索模式"
    )


def generate_answer(query, chunks, preferred="auto", temperature=DEFAULT_TEMPERATURE):
    """非流式LLM生成，收集全部token返回完整字符串.

    用于 wecom_bot.py 等非流式消费者.
    返回 (answer_text, status_msg).
    """
    t0 = time.time()
    answer = ""
    last_status = ""
    last_ch_name = ""
    last_ch_id = ""
    usage_info = {}
    for token, status in generate_with_failover(query, chunks, preferred, temperature, usage_info=usage_info):
        answer += token
        last_status = status
        if status.startswith("通道: "):
            last_ch_name = status[4:]
    latency_ms = int((time.time() - t0) * 1000)

    for ch in MODEL_CHANNELS:
        if ch["name"] == last_ch_name:
            last_ch_id = ch["id"]
            break

    # 优先使用 API 返回的真实 token 计数
    tok_prompt = usage_info.get("prompt_tokens", 0)
    tok_completion = usage_info.get("completion_tokens", 0)
    if tok_completion == 0:
        tok_completion = estimate_tokens(answer)  # fallback 粗估

    st = "error" if "不可用" in last_status else "success"
    sqlite_query_id = log_query(query, chunks, channel_id=last_ch_id, channel_name=last_ch_name,
              latency_ms=latency_ms, tokens_prompt=tok_prompt,
              tokens_completion=tok_completion,
              status=st, query_type="qa")

    # 自学习: 记录查询 + 知识缺口检测
    query_id = str(sqlite_query_id) if sqlite_query_id else ""
    if _KB_LEARNING:
        scores = [c["score"] for c in chunks] if chunks else []
        top_s = max(scores) if scores else 0.0
        # 自学习记录：传入真实 sqlite_query_id 供 badcase 条目回指；
        # 返回值保持真实 SQLite query_id（修复反馈链路 int(query_id) 断裂）
        kb_learning.log_query(
            query=query, top_score=top_s, chunks_count=len(chunks),
            channel=last_ch_name, answer_length=len(answer), model=last_ch_id,
            sqlite_query_id=sqlite_query_id
        )

    return answer, last_status, query_id


# ── Compare (多轮检索对比) ────────────────────────────────────────────

def retrieve_compare(subjects: list, aspect: str = "", top_k: int = 10):
    """对每个 subject 分别检索，返回 {subject: [chunks]}."""
    result = {}
    for subj in subjects:
        query = f"{subj} {aspect}".strip()
        chunks = retrieve(query, top_k=top_k)
        result[subj] = chunks
    return result


def format_compare_context(grouped_chunks: dict):
    """将分组检索结果格式化为对比 context."""
    parts = []
    for subj, chunks in grouped_chunks.items():
        parts.append(f"===== {subj} 相关文档 =====")
        for c in chunks:
            cat = f"{c['category']}/{c['subcategory']}" if c['subcategory'] else c['category']
            parts.append(
                f"[文件: {c['filename']} | 分类: {cat} | 相关度: {c['score']:.3f}]\n{c['text']}"
            )
        parts.append("")
    return "\n\n".join(parts)


def generate_compare(subjects: list, aspect: str = "", top_k: int = 10,
                     preferred="auto", temperature=0.3):
    """多轮检索 + 对比生成. 返回 (answer, sources, status)."""
    t0 = time.time()
    grouped = retrieve_compare(subjects, aspect, top_k)

    all_chunks = []
    for chunks in grouped.values():
        all_chunks.extend(chunks)

    if not all_chunks:
        log_query(" vs ".join(subjects), [], status="no_results", query_type="compare")
        return f"未找到与「{'、'.join(subjects)}」相关的文档。", [], "no_results"

    context = format_compare_context(grouped)
    subj_str = " vs ".join(subjects)
    aspect_str = f"，聚焦维度：{aspect}" if aspect else ""
    user_query = f"请对比 {subj_str}{aspect_str}"

    messages = [
        {"role": "system", "content": COMPARE_PROMPT},
        {"role": "user", "content": f"--- 检索结果 ---\n{context}\n--- 结束 ---\n\n{user_query}"},
    ]

    ordered = channel_mgr.get_ordered_channels(preferred)
    answer = ""
    last_status = ""
    used_ch = None

    for ch in ordered:
        try:
            client = OpenAI(
                base_url=ch["api_base"],
                api_key=ch["api_key"],
                timeout=ch["timeout"],
            )
            response = client.chat.completions.create(
                model=ch["model_id"],
                messages=messages,
                temperature=temperature,
                seed=42,
                top_p=1,
                max_tokens=4096,
                stream=True,
                timeout=ch["timeout"],
            )
            for part in response:
                if not part.choices:
                    continue
                delta = part.choices[0].delta
                if delta.content:
                    answer += delta.content
                    last_status = f"通道: {ch['name']}"

            if answer:
                channel_mgr.mark(ch["id"], True, latency=0)
                used_ch = ch
                break
        except Exception as e:
            channel_mgr.mark(ch["id"], False, error=str(e)[:200])
            continue

    if not answer:
        answer = "所有 LLM 通道不可用，无法生成对比。"
        last_status = "error"

    latency_ms = int((time.time() - t0) * 1000)
    log_query(
        user_query, all_chunks,
        channel_id=used_ch["id"] if used_ch else "",
        channel_name=used_ch["name"] if used_ch else "",
        latency_ms=latency_ms,
        tokens_completion=estimate_tokens(answer),
        status="success" if used_ch else "error",
        query_type="compare",
    )

    seen = set()
    sources = []
    for c in all_chunks:
        if c["filename"] not in seen:
            seen.add(c["filename"])
            sources.append(c["filename"])

    return answer, sources[:8], last_status


# ── 报告生成 ──────────────────────────────────────────────────────────

REPORT_PROMPT = """你是工业自动化技术文档分析师。根据检索到的文档片段，生成结构化技术报告。

要求：
1. 按主题维度组织内容，每个维度独立成段
2. 引用具体文档编号（如 B-83525CM）作为来源标注
3. 如果多份文档涉及同一知识点，综合归纳而非简单罗列
4. 如有信息冲突/版本差异，明确标注
5. 报告结构：概述→分维度详述→总结建议
6. 控制在 800 字以内，精炼专业"""

COMPARE_REPORT_PROMPT = """你是工业自动化技术文档分析师。根据检索到的多组文档片段，生成对比分析报告。

要求：
1. 按维度逐项对比（如：控制器型号、编程语言、性能参数、适用场景、维护要点）
2. 每个维度分别列出各方要点，标注来源文档
3. 最后给出选型建议或差异总结
4. 控制在 600 字以内"""

CATEGORY_REPORT_PROMPT = """你是工业自动化技术文档分析师。根据检索到的某一分类下的全部文档片段，生成该分类的知识概览报告。

要求：
1. 梳理该分类下的主要知识点和子主题
2. 列出关键文档及其核心内容摘要
3. 指出文档间的关联和互补关系
4. 如有版本差异或信息矛盾，明确标注
5. 最后给出该领域的知识覆盖度评估
6. 控制在 1000 字以内"""


def retrieve_report_chunks(query: str, report_type: str = "theme", top_k: int = 30):
    """报告专用检索 — 拉更多 chunks，宽松过滤."""
    query = _normalize_query(query)
    collection = get_collection()

    # 主题报告用语义检索，分类报告用 category 过滤
    if report_type == "category":
        where_filter = {"category": {"$eq": query}}
        try:
            results = collection.query(query_texts=[query], n_results=top_k, where=where_filter)
        except Exception:
            results = collection.query(query_texts=[query], n_results=top_k)
    else:
        results = collection.query(query_texts=[query], n_results=top_k)

    chunks = [
        _build_chunk_v2(doc, meta, 1 - dist)
        for doc, meta, dist in zip(
            results['documents'][0], results['metadatas'][0], results['distances'][0],
        )
    ]

    # BM25 补充
    bm25_results = _bm25_index.search(query, n_results=top_k)
    if bm25_results:
        existing = {c["text"] for c in chunks}
        for doc, meta, sc in bm25_results:
            if doc not in existing:
                chunks.append(_build_chunk_v2(doc, meta, min(sc / 50, 0.9)))
                existing.add(doc)

    # 过滤垃圾
    def _ok(c):
        text = c["text"].strip()
        if len(text) < 30:
            return False
        latin_high = sum(1 for ch in text if '\u00c0' <= ch <= '\u00ff')
        if len(text) > 50 and latin_high / len(text) > 0.15:
            return False
        return True

    chunks = [c for c in chunks if _ok(c)]
    chunks.sort(key=lambda c: c["score"], reverse=True)

    # 文件多样性：每文件最多 5 个 chunk
    selected = []
    file_count = {}
    for c in chunks:
        fn = c["filename"]
        file_count[fn] = file_count.get(fn, 0) + 1
        if file_count[fn] <= 5:
            selected.append(c)
        if len(selected) >= top_k:
            break

    for i, c in enumerate(selected):
        c["index"] = i + 1
    return selected


def generate_report(topic: str, report_type: str = "theme",
                    compare_target: str = "", top_k: int = 30,
                    preferred: str = "auto", temperature: float = 0.3):
    """生成技术报告. 返回 (answer, sources, status, query_id).

    report_type:
      - "theme": 主题报告 (topic = 查询关键词)
      - "compare": 对比报告 (topic = 对象A, compare_target = 对象B)
      - "category": 分类概览 (topic = 大类名称如 "07_机器人")
    """
    t0 = time.time()

    if report_type == "compare" and compare_target:
        # 对比报告：分别检索两个对象
        chunks_a = retrieve_report_chunks(topic, "theme", top_k // 2)
        chunks_b = retrieve_report_chunks(compare_target, "theme", top_k // 2)
        all_chunks = chunks_a + chunks_b
        prompt = COMPARE_REPORT_PROMPT
        user_query = f"请对比 {topic} 和 {compare_target}"
    elif report_type == "category":
        all_chunks = retrieve_report_chunks(topic, "category", top_k)
        prompt = CATEGORY_REPORT_PROMPT
        user_query = f"请生成「{topic}」分类的知识概览报告"
    else:
        all_chunks = retrieve_report_chunks(topic, "theme", top_k)
        prompt = REPORT_PROMPT
        user_query = f"请生成关于「{topic}」的技术报告"

    if not all_chunks:
        log_query(topic, [], status="no_results", query_type="report")
        return f"未找到与「{topic}」相关的文档。", [], "no_results", ""

    context = format_context(all_chunks)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"--- 检索结果 ---\n{context}\n--- 结束 ---\n\n{user_query}"},
    ]

    ordered = channel_mgr.get_ordered_channels(preferred)
    answer = ""
    last_status = ""
    used_ch = None

    for ch in ordered:
        try:
            client = OpenAI(
                base_url=ch["api_base"],
                api_key=ch["api_key"],
                timeout=ch["timeout"],
            )
            response = client.chat.completions.create(
                model=ch["model_id"],
                messages=messages,
                temperature=temperature,
                seed=42,
                top_p=1,
                max_tokens=4096,
                stream=True,
                timeout=ch["timeout"],
            )
            for part in response:
                if not part.choices:
                    continue
                delta = part.choices[0].delta
                if delta.content:
                    answer += delta.content
                    last_status = f"通道: {ch['name']}"

            if answer:
                channel_mgr.mark(ch["id"], True, latency=0)
                used_ch = ch
                break
        except Exception as e:
            channel_mgr.mark(ch["id"], False, error=str(e)[:200])
            continue

    if not answer:
        answer = "所有 LLM 通道不可用，无法生成报告。"
        last_status = "error"

    latency_ms = int((time.time() - t0) * 1000)
    query_id = log_query(
        user_query, all_chunks,
        channel_id=used_ch["id"] if used_ch else "",
        channel_name=used_ch["name"] if used_ch else "",
        latency_ms=latency_ms,
        tokens_completion=estimate_tokens(answer),
        status="success" if used_ch else "error",
        query_type="report",
    )

    seen = set()
    sources = []
    for c in all_chunks:
        if c["filename"] not in seen:
            seen.add(c["filename"])
            sources.append(c["filename"])

    return answer, sources[:12], last_status, query_id

_kb_stats_cache = {"data": None, "ts": 0}


def get_kb_stats():
    """返回知识库统计 (缓存30秒). {total_vectors, total_files, categories, subcategories}."""
    import time as _t
    now = _t.time()
    if _kb_stats_cache["data"] and now - _kb_stats_cache["ts"] < 30:
        return _kb_stats_cache["data"]

    coll = get_collection()
    total_vectors = coll.count()

    batch_size = 5000
    offset = 0
    file_counts = {}
    cat_counts = {}
    subcat_counts = {}

    while True:
        batch = coll.get(
            include=["metadatas"],
            limit=batch_size,
            offset=offset,
        )
        if not batch["ids"]:
            break
        for m in batch["metadatas"]:
            fn = m.get("filename") or m.get("source") or ""
            if fn:
                file_counts[fn] = file_counts.get(fn, 0) + 1
            cat = m.get("category", "")
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            subcat = m.get("subcategory", "")
            if subcat:
                key = f"{cat}/{subcat}" if cat else subcat
                subcat_counts[key] = subcat_counts.get(key, 0) + 1
        if len(batch["ids"]) < batch_size:
            break
        offset += batch_size

    data = {
        "total_vectors": total_vectors,
        "total_files": len(file_counts),
        "file_counts": file_counts,
        "categories": cat_counts,
        "subcategories": subcat_counts,
    }
    _kb_stats_cache["data"] = data
    _kb_stats_cache["ts"] = now
    return data


# ── Query Log (SQLite) ────────────────────────────────────────────────

QUERY_LOG_DB = Path(os.path.expanduser("~/rag_query_log.db"))
_log_lock = threading.Lock()


def _init_log_db():
    conn = sqlite3.connect(str(QUERY_LOG_DB))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            query_type TEXT NOT NULL DEFAULT 'qa',
            query TEXT NOT NULL,
            category TEXT,
            top_score REAL,
            avg_score REAL,
            num_chunks INTEGER,
            channel_id TEXT,
            channel_name TEXT,
            latency_ms INTEGER,
            tokens_prompt INTEGER,
            tokens_completion INTEGER,
            status TEXT NOT NULL DEFAULT 'success',
            error_msg TEXT,
            risk_tags TEXT,
            has_source INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(query_log)")}
    migrations = [
        ("risk_tags", "ALTER TABLE query_log ADD COLUMN risk_tags TEXT"),
        ("has_source", "ALTER TABLE query_log ADD COLUMN has_source INTEGER NOT NULL DEFAULT 0"),
        ("source_count", "ALTER TABLE query_log ADD COLUMN source_count INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, ddl in migrations:
        if col not in existing_cols:
            conn.execute(ddl)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_ts ON query_log(ts)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_risk_tags ON query_log(risk_tags)
    """)
    # ── 反馈表 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
            query_id INTEGER REFERENCES query_log(id),
            query TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            feedback_text TEXT,
            category TEXT,
            sender TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fb_query ON feedback(query_id)
    """)
    conn.commit()
    conn.close()


try:
    _init_log_db()
except Exception as e:
    logger.warning(f"查询日志数据库初始化失败: {e}")


_NEGATIVE_FEEDBACK_RE = re.compile(
    r"不对|不是这个|没用|不行|还是不行|答非所问|看不懂|没找到|不准确|错了|错误|没有解决"
)


def infer_risk_tags(query: str, chunks: list, latency_ms: int = 0,
                    status: str = "success", error_msg: str = "") -> list:
    """Infer implicit quality-risk tags from retrieval and runtime signals."""
    scores = [c.get("score", 0.0) for c in chunks] if chunks else []
    top_score = max(scores) if scores else 0.0
    filenames = {
        c.get("filename")
        for c in chunks
        if c.get("filename") and c.get("filename") != "unknown"
    }

    tags = []
    if not chunks:
        tags.append("no_chunks")
    if chunks and top_score < RISK_VERY_LOW_CONFIDENCE:
        tags.append("very_low_confidence")
    elif chunks and top_score < RISK_LOW_CONFIDENCE:
        tags.append("low_confidence")
    if chunks and not filenames:
        tags.append("no_source")
    if len(filenames) >= 5 and top_score < 0.8:
        tags.append("source_scatter")
    if status != "success":
        tags.append("runtime_error")
    if error_msg:
        tags.append("has_error_msg")
    if latency_ms and latency_ms >= RISK_SLOW_QUERY_MS:
        tags.append("slow_query")
    if _NEGATIVE_FEEDBACK_RE.search(query or ""):
        tags.append("explicit_negative")
    if re.search(r"图片|截图|照片|拍照|见图|看图", query or ""):
        tags.append("possible_multimodal_gap")

    return list(dict.fromkeys(tags))


_LOG_FALLBACK_PATH = QUERY_LOG_DB.parent / "query_log_fallback.jsonl"
_LOG_FALLBACK_MAX = 1000  # 兜底文件最大行数，超过截断


def log_query(query: str, chunks: list, channel_id: str = "",
              channel_name: str = "", latency_ms: int = 0,
              tokens_prompt: int = 0, tokens_completion: int = 0,
              status: str = "success", error_msg: str = "",
              query_type: str = "qa", category: str = "",
              request_id: str = ""):
    scores = [c["score"] for c in chunks] if chunks else []
    top_score = max(scores) if scores else 0.0
    avg_score = sum(scores) / len(scores) if scores else 0.0
    source_names = {
        c.get("filename")
        for c in chunks
        if c.get("filename") and c.get("filename") != "unknown"
    }
    risk_tags = infer_risk_tags(query, chunks, latency_ms, status, error_msg)

    with _log_lock:
        try:
            conn = sqlite3.connect(str(QUERY_LOG_DB), timeout=5)
            conn.execute("PRAGMA busy_timeout=5000")
            cur = conn.execute(
                """INSERT INTO query_log
                   (query_type, query, category, top_score, avg_score, num_chunks,
                    channel_id, channel_name, latency_ms,
                    tokens_prompt, tokens_completion, status, error_msg,
                    risk_tags, has_source, source_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (query_type, query, category, top_score, avg_score, len(chunks),
                 channel_id, channel_name, latency_ms,
                 tokens_prompt, tokens_completion, status, error_msg,
                 ",".join(risk_tags), 1 if source_names else 0, len(source_names)),
            )
            query_id = cur.lastrowid
            conn.commit()
            conn.close()
            return query_id
        except Exception as e:
            # 兜底：写入本地 JSONL 文件，不丢失日志
            try:
                import json as _json
                entry = {
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "query": query[:200], "top_score": round(top_score, 3),
                    "channel": channel_name, "status": status,
                    "error": str(e)[:100], "request_id": request_id,
                }
                with open(_LOG_FALLBACK_PATH, "a", encoding="utf-8") as f:
                    f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
                # 截断兜底文件防止无限增长
                lines = _LOG_FALLBACK_PATH.read_text().splitlines()
                if len(lines) > _LOG_FALLBACK_MAX:
                    _LOG_FALLBACK_PATH.write_text("\n".join(lines[-_LOG_FALLBACK_MAX:]) + "\n")
            except Exception:
                pass
            logger.warning(f"log_query 失败: {e}")
            return None


def log_feedback(query_id: int, query: str, feedback_type: str,
                 feedback_text: str = "", category: str = "", sender: str = ""):
    """记录用户反馈. feedback_type: 'good' | 'bad' | 'wrong_category' | 'other'"""
    with _log_lock:
        try:
            conn = sqlite3.connect(str(QUERY_LOG_DB))
            conn.execute(
                """INSERT INTO feedback
                   (query_id, query, feedback_type, feedback_text, category, sender)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (query_id, query, feedback_type, feedback_text, category, sender),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"反馈写入失败: {e}")


def get_query_logs(limit: int = 200, offset: int = 0,
                   query_type: str = "", min_date: str = "",
                   max_date: str = ""):
    with _log_lock:
        conn = sqlite3.connect(str(QUERY_LOG_DB))
        conn.row_factory = sqlite3.Row
        where, params = [], []
        if query_type:
            where.append("query_type = ?")
            params.append(query_type)
        if min_date:
            where.append("ts >= ?")
            params.append(min_date)
        if max_date:
            where.append("ts <= ?")
            params.append(max_date)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = conn.execute(
            f"SELECT * FROM query_log {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_log_stats(days: int = 7):
    with _log_lock:
        conn = sqlite3.connect(str(QUERY_LOG_DB))
        conn.row_factory = sqlite3.Row
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

        total = conn.execute(
            "SELECT COUNT(*) c FROM query_log WHERE ts >= ?", (cutoff,)
        ).fetchone()["c"]

        by_day = conn.execute(
            """SELECT substr(ts,1,10) AS day, COUNT(*) c, AVG(top_score) avg_top,
                      AVG(latency_ms) avg_lat, SUM(tokens_prompt+tokens_completion) total_tok
               FROM query_log WHERE ts >= ?
               GROUP BY day ORDER BY day""",
            (cutoff,),
        ).fetchall()

        by_status = conn.execute(
            "SELECT status, COUNT(*) c FROM query_log WHERE ts >= ? GROUP BY status",
            (cutoff,),
        ).fetchall()

        low_score = conn.execute(
            """SELECT query, top_score, ts FROM query_log
               WHERE ts >= ? AND top_score < 0.4 AND top_score > 0
               ORDER BY top_score ASC LIMIT 20""",
            (cutoff,),
        ).fetchall()

        top_queries = conn.execute(
            """SELECT query, COUNT(*) c FROM query_log
               WHERE ts >= ? GROUP BY query ORDER BY c DESC LIMIT 15""",
            (cutoff,),
        ).fetchall()

        risk_rows = conn.execute(
            """SELECT risk_tags, COUNT(*) c FROM query_log
               WHERE ts >= ? AND COALESCE(risk_tags, '') != ''
               GROUP BY risk_tags ORDER BY c DESC LIMIT 50""",
            (cutoff,),
        ).fetchall()

        risk_counts = {}
        for row in risk_rows:
            for tag in (row["risk_tags"] or "").split(","):
                if tag:
                    risk_counts[tag] = risk_counts.get(tag, 0) + row["c"]

        conn.close()
        return {
            "total": total,
            "by_day": [dict(r) for r in by_day],
            "by_status": [dict(r) for r in by_status],
            "low_score_queries": [dict(r) for r in low_score],
            "top_queries": [dict(r) for r in top_queries],
            "risk_tags": [
                {"risk_tag": tag, "c": count}
                for tag, count in sorted(risk_counts.items(), key=lambda item: item[1], reverse=True)
            ],
        }


_QUERY_CLUSTER_STOPWORDS = re.compile(
    r"怎么|如何|什么|一下|请问|查询|介绍|处理|解决|排查|方法|步骤|的|了|和|与|以及|还有|另外|是否|可以|需要|机器人|FANUC",
    re.I,
)


def _query_cluster_key(query: str) -> str:
    """Build a stable, privacy-light key for grouping similar risk queries."""
    normalized = _normalize_query(query or "").upper()
    alarms = _extract_alarm_codes(normalized)
    if alarms:
        prefixes = sorted({code.split("-")[0] for code in alarms})
        return "报警码:" + "/".join(prefixes)

    models = _extract_model_numbers(normalized)
    if models:
        series = sorted({re.sub(r"/.*$", "", model) for model in models})
        return "型号:" + "/".join(series[:3])

    compact = re.sub(r"[^A-Z0-9\u4e00-\u9fff]+", " ", normalized)
    compact = _QUERY_CLUSTER_STOPWORDS.sub(" ", compact)
    tokens = [t for t in compact.split() if len(t) >= 2]
    if not tokens:
        return "其他问题"
    return "关键词:" + " ".join(tokens[:4])


def get_risk_clusters(days: int = 7, top_n: int = 10) -> list:
    """Return top risk query clusters for lightweight weekly review."""
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    with _log_lock:
        conn = sqlite3.connect(str(QUERY_LOG_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        rows = conn.execute(
            """SELECT id, ts, query, top_score, latency_ms, risk_tags, status, source_count
               FROM query_log
               WHERE ts >= ? AND COALESCE(risk_tags, '') != ''
               ORDER BY id DESC LIMIT 1000""",
            (cutoff,),
        ).fetchall()
        conn.close()

    clusters = {}
    for row in rows:
        query = row["query"] or ""
        key = _query_cluster_key(query)
        item = clusters.setdefault(key, {
            "cluster_key": key,
            "count": 0,
            "risk_tags": {},
            "examples": [],
            "avg_top_score": 0.0,
            "avg_latency_ms": 0.0,
            "max_latency_ms": 0,
            "no_source_count": 0,
            "status_counts": {},
        })
        item["count"] += 1
        score = row["top_score"] or 0.0
        latency = row["latency_ms"] or 0
        item["avg_top_score"] += score
        item["avg_latency_ms"] += latency
        item["max_latency_ms"] = max(item["max_latency_ms"], latency)
        if (row["source_count"] or 0) == 0:
            item["no_source_count"] += 1
        status = row["status"] or "unknown"
        item["status_counts"][status] = item["status_counts"].get(status, 0) + 1
        for tag in (row["risk_tags"] or "").split(","):
            if tag:
                item["risk_tags"][tag] = item["risk_tags"].get(tag, 0) + 1
        if len(item["examples"]) < 3:
            item["examples"].append({
                "query": query,
                "top_score": round(score, 4),
                "risk_tags": row["risk_tags"] or "",
                "ts": row["ts"],
            })

    result = []
    for item in clusters.values():
        count = item["count"]
        item["avg_top_score"] = round(item["avg_top_score"] / count, 4) if count else 0.0
        item["avg_latency_ms"] = int(item["avg_latency_ms"] / count) if count else 0
        item["risk_tags"] = [
            {"risk_tag": tag, "c": c}
            for tag, c in sorted(item["risk_tags"].items(), key=lambda pair: pair[1], reverse=True)
        ]
        result.append(item)

    result.sort(
        key=lambda item: (
            item["count"],
            item["no_source_count"],
            -item["avg_top_score"],
            item["max_latency_ms"],
        ),
        reverse=True,
    )
    return result[:top_n]


def build_risk_cluster_report(days: int = 7, top_n: int = 10) -> str:
    """Build a markdown report of top risk clusters without requiring a dashboard."""
    clusters = get_risk_clusters(days=days, top_n=top_n)
    lines = [
        f"# 最近 {days} 天 Top {top_n} 风险问题簇",
        "",
        "本报告基于 query_log 中的 risk_tags 自动聚合，用于每周小步修复。",
        "",
    ]
    if not clusters:
        lines.append("暂无风险问题簇。")
        return "\n".join(lines)

    for idx, item in enumerate(clusters, 1):
        tags = ", ".join(f"{t['risk_tag']}×{t['c']}" for t in item["risk_tags"][:5]) or "无"
        status = ", ".join(f"{k}×{v}" for k, v in item["status_counts"].items()) or "unknown"
        lines.extend([
            f"## {idx}. {item['cluster_key']}",
            "",
            f"- 出现次数：{item['count']}",
            f"- 平均 top_score：{item['avg_top_score']}",
            f"- 平均耗时：{item['avg_latency_ms']}ms，最大耗时：{item['max_latency_ms']}ms",
            f"- 无来源次数：{item['no_source_count']}",
            f"- 风险标签：{tags}",
            f"- 状态分布：{status}",
            "- 示例问题：",
        ])
        for ex in item["examples"]:
            lines.append(f"  - `{ex['query']}` (score={ex['top_score']}, tags={ex['risk_tags']})")
        lines.extend([
            "- 建议动作：优先检查该簇的召回规则、同义词、文档覆盖、回答模板，并将修复后的代表问题加入 regression_set。",
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def get_token_stats(days: int = 7):
    """Token 消耗统计 — 按天、按通道聚合."""
    with _log_lock:
        conn = sqlite3.connect(str(QUERY_LOG_DB))
        conn.row_factory = sqlite3.Row
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

        # 按天汇总
        by_day = conn.execute(
            """SELECT substr(ts,1,10) AS day,
                      SUM(tokens_prompt) total_prompt,
                      SUM(tokens_completion) total_completion,
                      SUM(tokens_prompt + tokens_completion) total,
                      COUNT(*) query_count,
                      ROUND(AVG(tokens_prompt + tokens_completion)) avg_per_query
               FROM query_log WHERE ts >= ?
               GROUP BY day ORDER BY day""",
            (cutoff,),
        ).fetchall()

        # 按通道汇总
        by_channel = conn.execute(
            """SELECT COALESCE(NULLIF(channel_name,''), '未知') AS channel_name,
                      COALESCE(NULLIF(channel_id,''), 'unknown') AS channel_id,
                      SUM(tokens_prompt) total_prompt,
                      SUM(tokens_completion) total_completion,
                      SUM(tokens_prompt + tokens_completion) total,
                      COUNT(*) query_count,
                      ROUND(AVG(tokens_prompt + tokens_completion)) avg_per_query
               FROM query_log WHERE ts >= ?
               GROUP BY channel_name ORDER BY total DESC""",
            (cutoff,),
        ).fetchall()

        # 总计
        overall = conn.execute(
            """SELECT SUM(tokens_prompt) total_prompt,
                      SUM(tokens_completion) total_completion,
                      SUM(tokens_prompt + tokens_completion) total,
                      COUNT(*) query_count
               FROM query_log WHERE ts >= ?""",
            (cutoff,),
        ).fetchone()

        conn.close()
        return {
            "by_day": [dict(r) for r in by_day],
            "by_channel": [dict(r) for r in by_channel],
            "overall": dict(overall) if overall else {},
        }


def get_feedback_stats(days: int = 7):
    """获取反馈统计 — 满意度分布 + 不满查询列表."""
    with _log_lock:
        conn = sqlite3.connect(str(QUERY_LOG_DB))
        conn.row_factory = sqlite3.Row
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))

        # 按 feedback_type 统计
        by_type = conn.execute(
            "SELECT feedback_type, COUNT(*) c FROM feedback WHERE ts >= ? GROUP BY feedback_type",
            (cutoff,),
        ).fetchall()

        # 不满意查询明细（含评论）
        bad_list = conn.execute(
            """SELECT fb.id, fb.ts, fb.query, fb.feedback_type, fb.feedback_text, fb.category, fb.sender
               FROM feedback fb WHERE fb.ts >= ? AND fb.feedback_type IN ('bad','wrong_category')
               ORDER BY fb.id DESC LIMIT 50""",
            (cutoff,),
        ).fetchall()

        # 每日趋势
        by_day = conn.execute(
            """SELECT substr(ts,1,10) AS day,
                      SUM(CASE WHEN feedback_type IN ('good','up') THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN feedback_type IN ('bad','down') THEN 1 ELSE 0 END) bad,
                      SUM(CASE WHEN feedback_type='wrong_category' THEN 1 ELSE 0 END) wrong_cat,
                      COUNT(*) total
               FROM feedback WHERE ts >= ?
               GROUP BY day ORDER BY day""",
            (cutoff,),
        ).fetchall()

        conn.close()

    total = sum(r["c"] for r in by_type)
    stats = {r["feedback_type"]: r["c"] for r in by_type}
    good = stats.get("good", 0) + stats.get("up", 0)
    bad = stats.get("bad", 0) + stats.get("down", 0)

    return {
        "total": total,
        "good": good,
        "bad": bad,
        "wrong_category": stats.get("wrong_category", 0),
        "satisfaction_rate": round(good / (good + bad) * 100, 1) if (good + bad) > 0 else 0,
        "by_type": [dict(r) for r in by_type],
        "by_day": [dict(r) for r in by_day],
        "bad_list": [dict(r) for r in bad_list],
    }


def get_feedback_list(limit: int = 100, offset: int = 0,
                      min_date: str = "", max_date: str = "",
                      filter_type: str = ""):
    """获取反馈列表（分页、筛选）."""
    conn = sqlite3.connect(str(QUERY_LOG_DB))
    conn.row_factory = sqlite3.Row
    where, params = [], []
    if min_date:
        where.append("ts >= ?")
        params.append(min_date)
    if max_date:
        where.append("ts <= ?")
        params.append(max_date)
    if filter_type:
        where.append("feedback_type = ?")
        params.append(filter_type)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"SELECT * FROM feedback {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]