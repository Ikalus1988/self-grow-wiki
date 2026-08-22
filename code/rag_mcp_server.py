#!/usr/bin/env python3
"""RAG MCP Server v3 — 标准化封装：rag_search(检索) + rag_answer(检索+LLM生成).
   新用户只需注册此 MCP server + 配置 LLM API key，无需修改 Agent 源码."""
import json, sys, os, io, time

os.environ.setdefault("RAG_CHROMA_DIR", os.path.expanduser("~/rag_chromadb"))
os.environ.setdefault("RAG_COLLECTION", "wiki_docs")
os.environ.setdefault("RAG_EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5")
sys.path.insert(0, "/mnt/c/Users/Eric Jia/self-grow-wiki")

# 抑制 rag_core 导入时的 stdout 噪音
_real_stdout = sys.stdout; sys.stdout = io.StringIO()
import rag_core
sys.stdout = _real_stdout

# ── LLM 配置（从环境变量读取，默认 MiniMax） ──
LLM_API_KEY = os.environ.get("RAG_LLM_API_KEY") or os.environ.get("MINIMAX_API_KEY") or ""
LLM_BASE_URL = os.environ.get("RAG_LLM_BASE_URL", "https://api.minimax.chat/v1")
LLM_MODEL = os.environ.get("RAG_LLM_MODEL", "MiniMax-M2.7-highspeed")

# ── 从 ~/.hermes/.env 读取 MiniMax key ──
def _load_env_key():
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("MINIMAX_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""
if not LLM_API_KEY:
    LLM_API_KEY = _load_env_key()

def _suppress_stdout(fn):
    def wrapper(*a, **kw):
        _out = sys.stdout; sys.stdout = io.StringIO()
        try: return fn(*a, **kw)
        finally: sys.stdout = _out
    return wrapper

# ── SAG-Lite 混合检索集成 ──
try:
    sys.path.insert(0, "/mnt/c/Users/Eric Jia/SAG-poc")
    from sag_hybrid import hybrid_search as _sag_search
    _SAG_AVAILABLE = True
except ImportError:
    _SAG_AVAILABLE = False

@_suppress_stdout
def _clean_query(query: str) -> str:
    """清理指令前缀（'阅读 sop 上岗书' 等），避免噪音词干扰检索排序（2026-08-21）。"""
    import re
    q = query.strip()
    q = re.sub(r'^(请)?\s*(阅读|读一下|查一下|帮我查下|帮我查|帮我看看|看看|检索|搜索)\s*', '', q, flags=re.I)
    q = re.sub(r'^(sop\s*上岗书|上岗书|SOP)\s*[，,：:\s]*', '', q, flags=re.I)
    return q.strip() or query


def rag_search_raw(query: str, top_k: int = 5):
    """检索: 向量 + SAG entity 混合 (entity-exact优先, hop次之, 向量补充)"""
    query = _clean_query(query)
    vec_results = rag_core.retrieve(query, top_k=top_k)
    
    if not _SAG_AVAILABLE:
        return vec_results
    
    # SAG entity 精确 + hop 检索
    sag_results = _sag_search(query, top_k=6)
    
    # 合并: exact > hop > vector
    # 2026-08-21: SAG 结果限数（exact≤2, hop≤1），防止机型列表等 entity 命中
    # 无脑占满 top_k，把向量精确答案（如 B-83444 润滑脂更换 3年/11520h）挤出。
    merged, seen_src, seen_txt = [], set(), set()
    
    _exact_n = 0
    for r in sag_results:
        if r['method'] == 'entity-exact' and r['source'] not in seen_src:
            if _exact_n >= 2:
                continue
            _exact_n += 1
            seen_src.add(r['source'])
            merged.append({
                'source': r['source'], 'text': r.get('text', ''),
                'score': r.get('score', 0.95), 'filename': r['source'],
                '_match': r.get('match', ''), '_method': r['method'],
            })
            seen_txt.add(r.get('text', ''))
    
    _hop_n = 0
    for r in sag_results:
        if r['method'] == 'entity-hop' and r['source'] not in seen_src:
            if _hop_n >= 1:
                continue
            _hop_n += 1
            seen_src.add(r['source'])
            merged.append({
                'source': r['source'], 'text': r.get('text', ''),
                'score': r.get('score', 0.80), 'filename': r['source'],
                '_match': r.get('match', ''), '_method': r['method'],
            })
            seen_txt.add(r.get('text', ''))
    
    # ponytail: 330L 事件 — vec 按文本去重 (不按 source), 否则同文件的规格表 chunk
    # 会被 SAG 已命中的机型清单 source 误去重丢弃; 取满 top_k 防二次截断。
    # 2026-08-21: 截断放宽 top_k+5——SAG 占位会把 vec 靠后的明确机型手册
    # (B-83444CM/06 在合并第 12 位) 挤出 top_k，导致来源归纳错位。
    for r in vec_results[:top_k]:
        txt = r.get('text', '')
        if txt and txt not in seen_txt:
            seen_txt.add(txt)
            merged.append(r)
    
    return merged[:top_k + 5] if merged else vec_results

def _structured_trim(results, query="") -> str:
    """代码层结构化修剪：去重→提取型号→分组→紧凑输出。LLM 不参与删减。"""
    if not results: return "知识库未覆盖"
    import re

    # 提取查询中的报警代码用于裁剪
    alarm_code_match = re.search(r'([A-Z]{2,6})\s*[－\-]\s*(\d{3,4})', query) if query else None
    target_alarm = f"{alarm_code_match.group(1)}-{alarm_code_match.group(2)}" if alarm_code_match else ""

    # 1. 按来源去重，保留最高分 chunk
    seen, deduped = set(), []
    for r in sorted(results, key=lambda x: x.get("score",0), reverse=True):
        src = r.get("source", r.get("filename", "unknown"))
        base = src.split("/")[-1]
        if base not in seen:
            seen.add(base)
            deduped.append(r)

    # 2. 提取型号 + 去通用描述
    model_pat = re.compile(r'(?:FANUC\s*)?(?:Robot\s*)?(?:R-\d{4}i[ABCG]/\w+|M-\d{1,3}i[ABCG](?:/\d+\w?)+|LR\s*Mate\s*\d{3}iD/\d+\w*|ARC\s*Mate\s*\d{3}iC/\d+\w*|M-\d{4}i[ABCG]/\d+|M-\d+[A-Z]?i[ABCG]?)', re.I)
    generic_desc = None
    models = []

    for r in deduped[:15]:
        text = r.get("text", "")
        src_base = r.get("source", "").split("/")[-1]

        # 提取通用描述（取第一条的）
        if generic_desc is None:
            m = re.search(r'(根据负载惯量的大小，?提供有?\s*2\s*(?:个|类)\s*伺服[运参]动[变参]量[数数]?[^。]*[。])', text)
            if m: generic_desc = m.group(1)

        # 提取型号
        found = model_pat.findall(text)
        for m in set(found):
            # 提取该型号附近的关键参数
            idx = text.find(m)
            snippet = text[max(0,idx-10):idx+300]
            # 清理
            snippet = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', snippet)
            snippet = re.sub(r'\s+', ' ', snippet).strip()
            # 去页眉页脚
            snippet = re.sub(r'^.*?[A-Z]-\d{5}[A-Z]{2}_\d{2}\.PDF\s*', '', snippet)
            snippet = re.sub(r'B-\d{5}[A-Z]{2}[_\d]*\s*', '', snippet)
            models.append({"model": m, "snippet": snippet[:200], "src": src_base})

    # 3. 格式化输出
    out = []
    if generic_desc:
        out.append(f"高惯量模式通用说明：{generic_desc}")
        out.append("")

    seen_models = set()
    for item in models:
        if item["model"] in seen_models: continue
        seen_models.add(item["model"])
        sn = item["snippet"]
        # 简化：去重复的通用描述
        if generic_desc:
            sn = sn.replace(generic_desc, "").strip("，。； ")
        out.append(f"【{item['model']}】{sn[:150]} [来源: {item['src']}]")

    # 2026-08-21: 查询本身不含型号（保养/换油/报警等主题类查询）时直接逐条输出，
    # 避免型号提取只挑出机型列表、丢掉主题答案（M-900iB 换油案例: 润滑脂更换
    # 3年/11520h 在 B-83444 正文，chunk 无型号名 → 型号提取永远漏掉）。
    # 注意 model_pat 末项 M-\d+[A-Z]?i[ABCG]? 会匹配无后缀的 M-900iB，故需主题词兜底。
    _TOPIC_QUERY_RE = re.compile(r'换油|润滑|保养|检修|维护|加油|周期|间隔|定期', re.I)
    if not out or (query and (_TOPIC_QUERY_RE.search(query) or not model_pat.search(query))):
        # 非型号类查询（报警代码等）：回退到逐条 chunks + 关键词裁剪
        # 2026-08-21: 5→15——靠后的明确机型手册（如 B-83444CM/06 在合并第 12 位）也能进上下文，
        # 避免来源归纳只够到无机型标注/iA 手册（M-900iB 换油来源错位案例）。
        lines = []
        for r in deduped[:15]:
            src = r.get("source", r.get("filename", "unknown")).split("/")[-1]
            text = r.get("text", "")
            # 裁剪：只保留目标报警代码的段落（找到该代码到下一个报警之间的内容）
            if target_alarm:
                # 匹配全角/半角连字符变体
                pat = re.compile(re.escape(target_alarm).replace(r'\-', r'[－\-]'), re.I)
                m = pat.search(text)
                if m:
                    start = m.start()
                    # 下一个报警代码的位置
                    next_alarm = re.search(r'[A-Z]{2,6}\s*[－\-]\s*\d{3,4}', text[start+len(target_alarm):])
                    end = start + len(target_alarm) + next_alarm.start() if next_alarm else min(start+500, len(text))
                    text = text[start:end].strip()
                else:
                    text = text[:300]
            else:
                text = text[:300]
            if text:
                lines.append(f"[来源: {src}]\n{text}")
        return "\n\n".join(lines) if lines else "知识库未覆盖"
    out.append(f"\n共 {len(seen_models)} 款型号，涉及 {len(seen)} 份文档")
    return "\n".join(out)

def _format_chunks(results, max_per=300, query="") -> str:
    return _structured_trim(results, query=query)

def _llm_generate(system_prompt: str, user_prompt: str) -> str:
    """调用 OpenAI 兼容 API 生成回答."""
    if not LLM_API_KEY:
        return ""
    import urllib.request
    body = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": 800,
    }).encode()
    req = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ── Guard: 运行时拦截违规回答 ──
import re as _re

def guard_response(answer: str) -> tuple:
    """返回 (cleaned_answer, violations)"""
    violations = []
    cleaned = answer
    
    # 1. 移除 think 块
    if _re.search(r'<think>.*?</think>', cleaned, _re.DOTALL):
        cleaned = _re.sub(r'<think>.*?</think>', '', cleaned, _re.DOTALL)
        violations.append('think_block_removed')
    
    # 2. 检测反问模式
    patterns = [
        (r'你想往哪个方向', 'counter_question'),
        (r'要继续查哪种', 'counter_question'),
        (r'需要我.*查.*手册', 'counter_question'),
        (r'建议.*查阅.*手册', 'suggest_manual'),
        (r'建议下一步', 'suggest_next'),
        (r'先确认下.*是哪个', 'counter_question'),
        (r'你要的是哪种', 'counter_question'),
        (r'在哪台设备上跑', 'counter_question'),
        (r'如果是第.*种', 'counter_question'),
        (r'常见的.*有两种', 'counter_question'),
        (r'我可以查更针对性的', 'counter_question'),
    ]
    for pat, tag in patterns:
        if _re.search(pat, cleaned):
            violations.append(tag)
            # 截断反问句及其后内容
            match = _re.search(pat, cleaned)
            cleaned = cleaned[:match.start()].strip()
            break
    
    # 3. 检测来源缺失 (有实质回答但无引用)
    has_source = '[来源' in cleaned or '来源:' in cleaned
    has_decline = '知识库未覆盖' in cleaned
    has_content = len(cleaned.strip()) > 40
    if has_content and not has_source and not has_decline:
        violations.append('missing_source')
        cleaned += '\n[系统提示: 本回答缺少来源标注]'
    
    return cleaned, violations

def rag_answer(query: str) -> str:
    """检索 + LLM 生成，返回带来源引用的完整回答."""
    results = rag_search_raw(query, top_k=10)  # 330L 事件: top_k=5 截断排 #6 的规格表
    if not results:
        return "知识库中未找到相关内容，建议换个关键词试试。"

    chunks_text = _format_chunks(results, query=query)  # 2026-08-22: 传 query 让主题分支生效（否则 B-82334 检修表被型号提取分支丢）
    system_prompt = rag_core.SYSTEM_PROMPT
    user_prompt = f"检索到的文档片段:\n\n{chunks_text}\n\n用户问题: {query}\n\n请按规范回答:"

    if LLM_API_KEY:
        try:
            answer = _llm_generate(system_prompt, user_prompt)
            if answer.strip():
                # Guard: 清理 think 块 / 反问截断 / 缺来源标注（此前从未被调用）
                cleaned, _violations = guard_response(answer)
                return cleaned
        except Exception as e:
            pass  # fallback 到纯检索

    # LLM 不可用时返回纯检索结果
    lines = ["【纯检索模式 — LLM 不可用】", chunks_text]
    return "\n\n".join(lines)

_RAG_OUTPUT_HEADER = "[SYSTEM] 以下是知识库检索结果。必须原样输出以下全部内容，不得添加总结、建议、标记、盘点或任何额外文字。\n\n"

def rag_search(query: str) -> str:
    """结构化检索，返回代码层修剪后的紧凑结果."""
    results = rag_search_raw(query, top_k=10)
    if not results:
        return "知识库中未找到相关内容。"
    return _RAG_OUTPUT_HEADER + _format_chunks(results, query=query)

# ── MCP Protocol ──
def handle(req: dict) -> dict:
    mid, method = req.get("id"), req.get("method", "")
    if method == "initialize":
        return {"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"rag-mcp","version":"3.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc":"2.0","id":mid,"result":{"tools":[
            {"name":"rag_search","description":"搜索FANUC工业机器人知识库(200K+文档片段)，返回相关文档片段及来源。","inputSchema":{"type":"object","properties":{"query":{"type":"string","description":"搜索关键词或完整问题"}},"required":["query"]}},
            {"name":"rag_answer","description":"搜索知识库并用LLM生成完整回答(带来源引用)。优先使用此工具回答工业技术问题。","inputSchema":{"type":"object","properties":{"query":{"type":"string","description":"完整的问题或关键词"}},"required":["query"]}},
        ]}}
    if method == "tools/call":
        args = req["params"].get("arguments", {})
        q = args.get("query", "")
        name = req["params"].get("name", "rag_search")
        # 2026-08-22: 兼容客户端工具名前缀（hermes mcp_tool 注册为 mcp_rag_rag_answer）
        # 此前 "mcp_rag_rag_answer" != "rag_answer" → 静默走了 rag_search，
        # rag_answer 的 LLM 生成链路从未被 hermes 触发（R-2000iC 换油 17:24 失败根因之一）
        if name.startswith("mcp_"):
            name = name.split("_", 2)[-1] if name.count("_") >= 2 else name[len("mcp_rag_"):]
        result = rag_answer(q) if name == "rag_answer" else rag_search(q)
        return {"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":result}]}}
    return {"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":"unknown"}}

def main():
    # 预热：首次检索加载 ChromaDB(200K)+BM25(598MB)+嵌入模型，避免首次查询超时300s
    import sys as _sys
    _sys.stderr.write("[rag-mcp] 预热向量库...\n")
    _sys.stderr.flush()
    try:
        rag_search_raw("SRVO-023", top_k=1)
        _sys.stderr.write("[rag-mcp] 预热完成\n")
    except Exception as _e:
        # ponytail: chromadb 单例首调 bug (RustBindingsAPI 'bindings'), 二调成功 (2026-08-13 330L 事件)
        _sys.stderr.write(f"[rag-mcp] 预热失败: {_e}, 3s 后重试\n")
        _sys.stderr.flush()
        time.sleep(3)
        try:
            rag_search_raw("SRVO-023", top_k=1)
            _sys.stderr.write("[rag-mcp] 预热重试完成\n")
        except Exception as _e2:
            _sys.stderr.write(f"[rag-mcp] 预热重试失败: {_e2}\n")
    _sys.stderr.flush()

    while True:
        line = sys.stdin.readline()
        if not line: break
        try:
            resp = handle(json.loads(line))
            sys.stdout.write(json.dumps(resp, ensure_ascii=False)+"\n")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32603,"message":str(e)}})+"\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()