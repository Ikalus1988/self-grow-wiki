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

from openai import OpenAI

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


def _normalize_query(query: str) -> str:
    """将查询中的无连字符型号/报警代码规范化为带连字符形式."""
    q = query
    # M900 → M-900, R2000 → R-2000
    q = re.sub(r'(?<![A-Za-z0-9])([A-Z]{1,2})(\d{2,4})(?!\d)', r'\1-\2', q)
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
    "360": ["M-900iB/360L", "M-900iB/360"],
    "300": ["M-900iB/300L", "M-900iB/300"],
    "270": ["M-900iB/270L", "M-900iB/270"],
    "210": ["R-2000iC/210F", "R-2000iC/210WE"],
    "200": ["R-2000iC/200E"],
    "180": ["R-2000iC/180F"],
    "165": ["R-2000iC/165F", "M-20iD/165F"],
    "120": ["Arc Mate 120iC"],
    "100": ["M-710iC/100"],
    "70": ["M-710iC/70"],
    "50": ["M-710iC/50", "M-20iD/50"],
    "35": ["M-20iD/35"],
    "25": ["M-20iD/25", "LR Mate 200iD/25"],
    "20": ["M-20iD/20"],
    "12": ["LR Mate 200iD/12", "Arc Mate 120iC/12L"],
    "7": ["LR Mate 200iD/7L"],
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

    # 短中文查询（2-10 字）且无明确实体：追加领域词提升匹配
    if 2 <= chinese_chars <= 8 and not alarm_codes and not model_numbers:
        if any(kw in query for kw in ['机器人', '伺服', '报警', '故障', '参数',
                                       '规格', '操作', '维护', '安装', '调试']):
            aug_parts.append("FANUC 工业机器人")

    if not aug_parts:
        return query
    return f"{query} {' '.join(aug_parts)}"


# ── Config ──────────────────────────────────────────────────────────────
CHROMA_DIR = Path("/home/hp/rag_chromadb")
COLLECTION_NAME = "wiki_docs"
EMBEDDING_MODEL = "BAAI/bge-base-zh-v1.5"

PATHS = {
    "chromadb": str(CHROMA_DIR),
    "query_log_db": "/home/hp/rag_query_log.db",
    "conflict_report": "/home/hp/kb_conflict_report.md",
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
    {
        "id": "deepseek",
        "name": "DeepSeek-V3",
        "label": "DeepSeek (备用)",
        "model_id": "deepseek-chat",
        "api_base": "https://api.deepseek.com/v1",
        "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
        "timeout": 60,
    },
    {
        "id": "qwen-local",
        "name": "Qwen2.5-3B (本地)",
        "label": "Qwen (本地Ollama)",
        "model_id": "qwen2.5:3b",
        "api_base": OLLAMA_BASE,
        "api_key": "ollama",
        "timeout": 120,
    },
]

DEFAULT_TOP_K = 8
MIN_SCORE = 0.45          # 语义分数低于此阈值的 chunk 直接丢弃
MIN_TEXT_LEN = 30         # chunk 文本少于该字符数视为垃圾
DEFAULT_TEMPERATURE = 0.3
HEALTH_CHECK_INTERVAL = 120

# BM25 混合检索配置
BM25_INDEX_PATH = CHROMA_DIR / "bm25_index.pkl"
BM25_TOP_K = 20           # BM25 候选数量
BM25_ALPHA = 0.4          # 向量分数权重 (1-alpha = BM25 权重)
BM25_RRF_K = 60           # RRF 常数 (越小 BM25 影响越大)

# Cross-encoder rerank（可选，依赖 sentence-transformers）
_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
_RERANK_TOP_K = 25        # 对 top-K 候选做 rerank，其余保持原始排序

SYSTEM_PROMPT = """你是工业自动化技术文档助手。根据检索到的文档片段回答用户问题。
要求：
1. 综合所有检索到的文档片段，进行跨文档归纳总结
2. 对于笼统/归纳性问题（如"报警码种类"、"有哪些类型"），需要：
   - 先列出所有检索到的类别/种类
   - 每个类别简要说明用途或示例
   - 如果检索到的文档覆盖不完整，说明"基于当前文档，主要有以下几类"
3. 直接给出要点，不用表格，不用Markdown格式
4. 回答控制在400字以内，简洁清晰
5. **每个要点末尾必须标注来源文件名**，格式为 (文件: 文件名)。如果多个要点来自同一文件，只需标注一次。
   示例：M-710iC/50 的 J2 轴速度 175°/s (文件: B-82274CM_第3章_基本规格表)
6. 如果检索内容不足以回答，只说"知识库中未找到相关内容，建议换个关键词试试"，不要推荐具体的搜索词、手册名称或型号
7. 如果用户问题太宽泛，先基于已检索到的内容简要回答，然后说"如需更详细的信息，可以补充具体型号或操作步骤再试"
8. 绝对不要编造或猜测知识库中不存在的内容
9. 通用零部件（电池、润滑脂、密封圈等）的规格通常在同一厂商的多个型号间通用，可以参考引用，但需注明"参考同系列机型文档" """

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

    ef = SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device=device,
        trust_remote_code=False,
    )

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = client.get_collection(name=COLLECTION_NAME, embedding_function=ef)
    print(f"已加载向量库: {_collection.count()} vectors")
    return _collection


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
            where={"has_entity": {"$eq": True}},
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
    """用实体索引精确搜索型号 chunks。"""
    _build_entity_index(collection)
    chunks = []
    for model in models[:3]:
        matches = _entity_model_index.get(model, [])
        for doc, meta in matches:
            if doc in existing:
                continue
            boost = 0.15 if model in doc[:300].upper() else 0.08
            score = min(0.75 + boost, 0.95)
            c = _build_chunk_v2(doc, meta, score)
            c["_entity_match"] = "model"
            chunks.append(c)
            existing.add(doc)
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


def _get_reranker():
    """获取 cross-encoder reranker 实例（懒加载，仅首次调用时初始化）。"""
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        from sentence_transformers import CrossEncoder
        _RERANKER = CrossEncoder(_RERANKER_MODEL)
        logger.info(f"Cross-encoder reranker 已加载: {_RERANKER_MODEL}")
        return _RERANKER
    except ImportError:
        logger.info("sentence-transformers 未安装，跳过 cross-encoder rerank")
        return None
    except Exception as e:
        logger.warning(f"Cross-encoder 加载失败: {e}")
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

        # 带过滤的搜索
        if where_filter:
            cat_key = where_filter.get("category", {}).get("$eq", "")
            if cat_key:
                filtered = [
                    (i, s) for i, s in enumerate(scores)
                    if self.metas[i].get("category", "") == cat_key
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
        chunks.append(_build_chunk_v2(doc, meta, normalized))
        existing_texts.add(doc)
    return chunks


def retrieve(query: str, top_k: int = DEFAULT_TOP_K):
    query = _normalize_query(query)

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
        return all_chunks[:top_k * 2]

    return _retrieve_single(query, top_k)


def _retrieve_single(query: str, top_k: int):
    collection = get_collection()

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
        where_filter = {"category": {"$eq": target_category}}

    # ── 并行：向量搜索 + BM25 搜索 ──
    def _do_vector():
        results = collection.query(
            query_texts=[expanded_query], n_results=top_k,
            where=where_filter,
        )
        if not results['documents'][0] and where_filter:
            results = collection.query(query_texts=[expanded_query], n_results=top_k)
        return list(zip(
            results['documents'][0], results['metadatas'][0], results['distances'][0]
        ))

    def _do_bm25():
        return _bm25_index.search(expanded_query, n_results=BM25_TOP_K, where_filter=where_filter)

    with ThreadPoolExecutor(max_workers=2) as _exe:
        _vec_fut = _exe.submit(_do_vector)
        _bm25_fut = _exe.submit(_do_bm25)
        vector_results = _vec_fut.result()
        bm25_results = _bm25_fut.result()

    # ── RRF 融合 ──
    if bm25_results:
        existing_texts = set()
        rrf_chunks = _rrf_fusion(vector_results, bm25_results, existing_texts)
        chunks = rrf_chunks[:top_k * 2]
    else:
        chunks = [
            _build_chunk_v2(doc, meta, 1 - dist)
            for doc, meta, dist in vector_results
        ]

    existing_texts = {c["text"] for c in chunks}

    # ── 并行：实体精确搜索（alarm + model + variant） ──
    _build_entity_index(collection)
    model_variants = _extract_model_variants(expanded_query) if model_numbers else []

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
            if _c["text"] not in existing_texts:
                chunks.append(_c)
                existing_texts.add(_c["text"])

    # 型号规格后缀加分：多个 variant 命中同一 chunk 时加分
    if len(model_variants) >= 2:
        for c in chunks:
            match_count = sum(1 for v in model_variants if v.upper() in c["text"].upper())
            if match_count >= 2:
                c["score"] = min(c["score"] + 0.15, 0.98)

    # ── 二级分类补充搜索 ──
    if target_l2:
        l2_chunks = _category_l2_search(collection, query, target_l2, existing_texts)
        chunks.extend(l2_chunks)

    # ── topic_tags 加权 ──
    _topic_tag_boost(chunks, query)

    # 关键词精确补充：当查询含报警代码时，强制召回包含该字符串的 chunks
    # PDF 中报警代码连字符可能是全角 "－"(U+FF0D) 或半角 "-"，但 entity extraction
    # Phase 1 已标准化 entity_alarms 元数据，此处直接对标准化后的 code 做全文包含匹配
    alarm_codes = _ALARM_CODE_RE.findall(query)
    if alarm_codes:
        # 收集所有报警码的所有变体，一次 $or 查询（ChromaDB ≥0.4.5 支持 where_document $or）
        all_variants = []
        for code in alarm_codes[:3]:
            all_variants.append({"$contains": code})
            all_variants.append({"$contains": code.replace("-", "－")})
        try:
            kw = collection.get(
                where_document={"$or": all_variants},
                limit=min(15 * len(alarm_codes), 50),
                include=["documents", "metadatas"],
            )
            for code in alarm_codes[:3]:
                for doc, meta in zip(kw["documents"], kw["metadatas"]):
                    if doc not in existing_texts:
                        chunks.append(_build_chunk_v2(doc, meta, _keyword_score(doc, code)))
                        existing_texts.add(doc)
        except Exception:
            # $or 不支持时，对每个 code 做单次 $contains（不遍历全角变体——entity_alarms 已标准化）
            for code in alarm_codes[:3]:
                try:
                    kw = collection.get(
                        where_document={"$contains": code}, limit=15,
                        include=["documents", "metadatas"],
                    )
                    for doc, meta in zip(kw["documents"], kw["metadatas"]):
                        if doc not in existing_texts:
                            chunks.append(_build_chunk_v2(doc, meta, _keyword_score(doc, code)))
                            existing_texts.add(doc)
                except Exception:
                    pass

    # 上位机/Robot Interface 关键词强制召回
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

    # 型号系列关键词补充：当查询含机器人型号时，强制召回该型号的文档
    model_series = _MODEL_SERIES_RE.findall(query.upper())
    # 过滤掉已被报警代码捕获的
    model_series = [m for m in model_series if m not in [c.upper() for c in alarm_codes]]
    if model_series:
        # 如果现有结果已有高分命中，跳过型号遍历节省时间
        existing_best = max((c["score"] for c in chunks), default=0)
        if existing_best < 0.85:
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

    chunks = [c for c in chunks if not _is_garbage(c) and c["score"] >= MIN_SCORE]

    # 按分数降序排序
    chunks.sort(key=lambda c: c["score"], reverse=True)

    # ── Cross-encoder 重排序（可选） ──
    # 用 reranker 对 top-K 候选重新评分，提升排序精度。
    # 依赖 sentence-transformers，未安装时自动跳过。
    chunks = _rerank_chunks(query, chunks)

    # 文件多样性：同一文件最多保留 max_per_file 个 chunk，确保覆盖更多文件
    max_per_file = 3 if model_series else top_k
    if max_per_file < top_k:
        selected = []
        file_count = {}
        for c in chunks:
            fn = c["filename"]
            file_count[fn] = file_count.get(fn, 0) + 1
            if file_count[fn] <= max_per_file:
                selected.append(c)
            if len(selected) >= top_k:
                break
        chunks = selected
    else:
        chunks = chunks[:top_k]

    # 话题补充槽位保留：确保至少 2 个话题补充 chunk 进入最终结果
    if _topic_chunks:
        selected_ids = {id(c) for c in chunks}
        missed = [c for c in _topic_chunks if id(c) not in selected_ids]
        missed.sort(key=lambda c: c["score"], reverse=True)
        for tc in missed[:2]:
            chunks.append(tc)

    # ── 品牌过滤：查询明确提 FANUC 时，排除非 FANUC 文档（如 KUKA） ──
    if re.search(r'fanuc', query, re.I):
        _fanuc_pat = re.compile(r'(?i)fanuc|B-\d{5}|R-30i[AB]|M-\d{3}|A-\d{5}')
        filtered = [c for c in chunks
                    if _fanuc_pat.search(c.get("filename", "") + c.get("source", ""))]
        if filtered:
            chunks = filtered

    for i, c in enumerate(chunks):
        c["index"] = i + 1
    return chunks


def format_context(chunks):
    parts = []
    for c in chunks:
        cat = f"{c['category']}/{c['subcategory']}" if c['subcategory'] else c['category']
        # 附加元数据信息
        meta_info = []
        if c.get('category_l2'):
            meta_info.append(f"细分: {c['category_l2']}")
        if c.get('content_type'):
            meta_info.append(f"类型: {c['content_type']}")
        if c.get('entity_alarms') and c['entity_alarms'] != '[]':
            meta_info.append(f"报警码: {c['entity_alarms']}")
        if c.get('entity_models') and c['entity_models'] != '[]':
            meta_info.append(f"匹配型号: {c['entity_models']}")
        meta_str = f" | {' '.join(meta_info)}" if meta_info else ""
        # 文件名加粗强调，LLM 更容易注意到
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
        cat = f"{c['category']}/{c['subcategory']}" if c['subcategory'] else c['category']
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
        query_id = kb_learning.log_query(
            query=query, top_score=top_s, chunks_count=len(chunks),
            channel=last_ch_name, answer_length=len(answer), model=last_ch_id
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

QUERY_LOG_DB = Path("/home/hp/rag_query_log.db")
_log_lock = threading.Lock()


def _init_log_db():
    conn = sqlite3.connect(str(QUERY_LOG_DB))
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
            error_msg TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_log_ts ON query_log(ts)
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


_init_log_db()


def log_query(query: str, chunks: list, channel_id: str = "",
              channel_name: str = "", latency_ms: int = 0,
              tokens_prompt: int = 0, tokens_completion: int = 0,
              status: str = "success", error_msg: str = "",
              query_type: str = "qa", category: str = ""):
    scores = [c["score"] for c in chunks] if chunks else []
    top_score = max(scores) if scores else 0.0
    avg_score = sum(scores) / len(scores) if scores else 0.0

    with _log_lock:
        try:
            conn = sqlite3.connect(str(QUERY_LOG_DB))
            cur = conn.execute(
                """INSERT INTO query_log
                   (query_type, query, category, top_score, avg_score, num_chunks,
                    channel_id, channel_name, latency_ms,
                    tokens_prompt, tokens_completion, status, error_msg)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (query_type, query, category, top_score, avg_score, len(chunks),
                 channel_id, channel_name, latency_ms,
                 tokens_prompt, tokens_completion, status, error_msg),
            )
            query_id = cur.lastrowid
            conn.commit()
            conn.close()
            return query_id
        except Exception:
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

        conn.close()
        return {
            "total": total,
            "by_day": [dict(r) for r in by_day],
            "by_status": [dict(r) for r in by_status],
            "low_score_queries": [dict(r) for r in low_score],
            "top_queries": [dict(r) for r in top_queries],
        }


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
