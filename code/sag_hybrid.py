"""
SAG-Lite 混合检索引擎 (L2)
===========================
Vector + SQL Entity-Join 混合检索
集成到 rag_core 管道中，替换纯向量检索

用法:
    from sag_hybrid import hybrid_search
    results = hybrid_search("SRVO-066 报警 涉及DI425", top_k=5)
"""

import sqlite3, re
from pathlib import Path

DB_PATH = Path("/mnt/c/Users/Eric Jia/SAG-poc/sag_lite.db")

def _expand_query_entities(conn, query: str) -> str:
    """Entity-aware query expansion: 检测已有entity类型, 补充缺失的关联类型"""
    has_alarm = bool(re.findall(r'SRVO[\s\-]*\d{3,4}', query))
    has_signal = bool(re.findall(r'(DI|DO|RI|RO)\s*\[?\s*\d', query))
    has_model = bool(re.findall(r'R-\d{4}i[A-G]|M-\d{1,3}i[A-G]', query))
    has_concept = bool(re.search(r'(零点标定|MASTER|碰撞检测|焊接|负载|惯量|坐标)', query, re.I))
    
    additions = []
    
    if has_alarm and not has_signal:
        alarm_code = re.findall(r'SRVO[\s\-]*(\d{3,4})', query)
        if alarm_code:
            av = 'SRVO-' + alarm_code[0]
            rows = conn.execute("""
                SELECT entity_b_value, shared_chunks FROM entity_edges
                WHERE entity_a_type='alarm_code' AND entity_a_value=?
                AND entity_b_type='manual' ORDER BY shared_chunks DESC LIMIT 1
            """, (av,)).fetchall()
            if rows:
                additions.append(rows[0][0])
    
    if additions:
        return query + " " + " ".join(additions)
    return query

def hybrid_search(query: str, top_k: int = 6):
    """混合检索: entity精确匹配 + entity-hop扩展 (+query扩展)"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    # 0. Query 扩展: entity-aware 补全缺失类型
    expanded_query = _expand_query_entities(conn, query)
    if expanded_query != query:
        query = expanded_query
    
    # 1. 从查询提取 entities
    entities = []
    for prefix, num in re.findall(r'(DI|DO|RI|RO)\s*\[?\s*(\d{1,4})', query):
        entities.append(('signal', f'{prefix}{num}'))
    for num in re.findall(r'SRVO[\s\-]*(\d{3,4})', query):
        entities.append(('alarm_code', f'SRVO-{num}'))
    for m in re.findall(r'(B-\d{5}[A-Z]{2,3})', query):
        entities.append(('manual', m))
    for m in set(re.findall(r'(R-\d{4}i[A-G](?:\s*Plus)?)', query)):
        entities.append(('model_num', m.strip()))
    # v2 扩展类型
    for m in re.findall(r'(FENCE|EAS|E-Stop|DCS|Collision\s*Guard)', query, re.I):
        entities.append(('safety', m.upper()))
    for m in re.findall(r'(BZAL|CSAL|DTERR|CRCERR|STBERR|HCAL|OVC|OHAL2|BLAL|CMAL|CLALM|SPHAL)', query, re.I):
        entities.append(('alarm_noprefix', m.upper()))
    for m in re.findall(r'(零点标定|MASTER|脉冲复位|碰撞检测|焊接参数|焊接缺陷|负载设定|高惯量|坐标系|TOOL\s*FRAME|USER\s*FRAME)', query, re.I):
        entities.append(('concept', m))
    for m in re.findall(r'(更换.*电池|更换电池|BATTERY|BACKUP|备份|RESTORE|恢复|IMAGE\s*BACKUP|KAREL|TP程序|Socket通讯|TCP/IP|主机通讯|PULSE\s*RESET|IMAGE\s*备份)', query, re.I):
        entities.append(('procedure', m.upper() if m.isascii() else m))
    for m in re.findall(r'(MH\s*Valve|物料搬运阀|Tooling\s*Valve|Clamp\s*Valve|Vacuum\s*Valve|Part\s*Present)', query, re.I):
        entities.append(('valve', m))
    
    # 负例过滤: 有model无alarm时不召回通用手册chunk
    has_alarm_entity = any(e[0] in ('alarm_code','alarm_noprefix') for e in entities)
    has_model_only = any(e[0]=='model_num' for e in entities) and not has_alarm_entity
    
    results, seen_sources = [], set()
    
    # 2. Phase 1: entity 精确匹配
    for etype, evalue in entities:
        rows = conn.execute("""
            SELECT c.source, c.id, SUBSTR(c.text,1,600) as text,
                   e.entity_type, e.entity_value
            FROM chunks c JOIN entities_v2 e ON c.id = e.chunk_id
            WHERE e.entity_type=? AND e.entity_value=?
            LIMIT 2
        """, (etype, evalue)).fetchall()
        for row in rows:
            if row['source'] not in seen_sources:
                seen_sources.add(row['source'])
                results.append({
                    'source': row['source'],
                    'text': row['text'],
                    'match': f"{row['entity_type']}:{row['entity_value']}",
                    'method': 'entity-exact',
                    'score': 0.95,
                })
    
    # 3. Phase 2: entity-hop 扩展 (top 3 entities)
    for etype, evalue in entities[:3]:
        edges = conn.execute("""
            SELECT entity_b_type, entity_b_value, shared_chunks
            FROM entity_edges
            WHERE entity_a_type=? AND entity_a_value=?
            ORDER BY shared_chunks DESC LIMIT 3
        """, (etype, evalue)).fetchall()
        for edge in edges:
            btype, bval, shared = edge
            if shared < 2:  # 过滤弱关联
                continue
            row = conn.execute("""
                SELECT c.source, SUBSTR(c.text,1,400) as text
                FROM chunks c JOIN entities_v2 e ON c.id = e.chunk_id
                WHERE e.entity_type=? AND e.entity_value=? LIMIT 1
            """, (btype, bval)).fetchone()
            if row and row['source'] not in seen_sources:
                seen_sources.add(row['source'])
                results.append({
                    'source': row['source'],
                    'text': row['text'],
                    'match': f"hop: {etype}:{evalue} → {btype}:{bval} ({shared} shared)",
                    'method': 'entity-hop',
                    'score': 0.75 + 0.05 * min(shared, 5),
                })
    
    conn.close()
    return results[:top_k]


# ── OKF Bundle 索引 ──
import os as _os, yaml as _yaml

OKF_ROOT = "/mnt/d/MD/RAG知识库/okf_bundle"

def _parse_frontmatter(path: str) -> dict:
    """解析 OKF Concept frontmatter"""
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if content.startswith('---'):
        parts = content.split('---', 2)
        if len(parts) >= 3:
            try:
                return _yaml.safe_load(parts[1]) or {}
            except:
                return {}
    return {}

def search_okf(query: str, top_k: int = 5) -> list:
    """搜索 OKF Bundle 中的 Concepts (简单关键词匹配)"""
    results = []
    if not _os.path.exists(OKF_ROOT):
        return results
    
    for root, dirs, files in _os.walk(OKF_ROOT):
        for f in files:
            if f.endswith('.md') and f not in ('index.md',):
                path = _os.path.join(root, f)
                with open(path, 'r', encoding='utf-8') as fh:
                    text = fh.read()
                
                # 跳过未验证的 Concept (needs-verification 且未人工确认)
                if 'needs-verification' in text and 'status: verified' not in text:
                    continue
                
                rel = _os.path.relpath(path, OKF_ROOT)
                concept_id = rel.replace('.md', '')
                
                if any(kw.lower() in text.lower() for kw in query.split() if len(kw) >= 2):
                    fm = _parse_frontmatter(path)
                    results.append({
                        'source': f'okf://{concept_id}',
                        'text': text[:800],
                        'match': f"okf:{fm.get('type','concept')}:{fm.get('title','')}",
                        'method': 'okf-concept',
                        'score': 0.90,
                    })
    
    return results[:top_k]


def hybrid_search_okf(query: str, top_k: int = 8):
    """混合检索 v2: OKF concept > entity exact > entity hop"""
    entity_results = hybrid_search(query, top_k=6)
    okf_results = search_okf(query, top_k=3)
    
    merged, seen = [], set()
    for r in okf_results:
        if r['source'] not in seen:
            seen.add(r['source']); merged.append(r)
    for r in entity_results:
        if r['source'] not in seen:
            seen.add(r['source']); merged.append(r)
    
    return merged[:top_k]


def get_entity_context(chunk_ids: list) -> dict:
    """获取 chunk 的 entity 上下文（用于增强 LLM prompt）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    context = {}
    for cid in chunk_ids[:5]:
        entities = conn.execute("""
            SELECT entity_type, entity_value FROM entities_v2 WHERE chunk_id=?
        """, (cid,)).fetchall()
        context[cid] = [(e['entity_type'], e['entity_value']) for e in entities]
    
    conn.close()
    return context


if __name__ == "__main__":
    import time
    tests = [
        "SRVO-066 CSAL报警 和 DI425 有关系吗",
        "SRVO-062 BZAL 更换电池后的零点标定步骤",
        "R-30iB 上 SRVO-050 碰撞检测如何复位",
    ]
    for q in tests:
        t0 = time.time()
        r = hybrid_search(q)
        print(f"\n── {q} ({len(r)} results, {time.time()-t0:.3f}s) ──")
        for i, rr in enumerate(r):
            print(f"  [{i+1}] [{rr['method']}] {rr['match']}")
            print(f"      {rr['source'][:50]}")
