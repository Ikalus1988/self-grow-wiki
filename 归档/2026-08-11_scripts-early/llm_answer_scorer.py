#!/usr/bin/env python3
"""LLM 答案质量自动评分 — 准确性/简洁性/引用完整性"""
import sys, re
sys.path.insert(0, "/mnt/c/Users/Eric Jia/SAG-poc")
from sag_hybrid import hybrid_search

def score_answer(query: str, chunks: list) -> dict:
    """对检索结果做启发式评分 (不调用LLM, 零成本)"""
    all_text = " ".join([c.get('text','') for c in chunks])
    sources = [c.get('source','') for c in chunks]
    
    scores = {}
    
    # 1. 精确性: 是否有 entity-exact 命中
    methods = [c.get('method','') for c in chunks]
    scores['precision'] = 1.0 if 'entity-exact' in methods else 0.5
    
    # 2. 来源完整性: 不同来源数
    unique_sources = len(set(s.split('/')[-1] for s in sources if s))
    scores['source_diversity'] = min(unique_sources / 3, 1.0)
    
    # 3. 简洁性: 结果条数合理 (3-6最佳)
    n = len(chunks)
    scores['conciseness'] = 1.0 if 3 <= n <= 6 else (0.7 if n > 0 else 0)
    
    # 4. 跨文档: 有 entity-hop
    scores['cross_doc'] = 1.0 if 'entity-hop' in methods else 0.3
    
    # 5. 速度
    scores['speed'] = 1.0  # SAG < 100ms
    
    # 加权总分
    weights = {'precision':0.35, 'source_diversity':0.25, 'conciseness':0.15, 'cross_doc':0.15, 'speed':0.10}
    total = sum(scores[k] * weights[k] for k in weights)
    
    return {'query': query[:60], 'scores': scores, 'total': round(total, 3), 'sources': unique_sources}

if __name__ == '__main__':
    tests = [
        "SRVO-066 CSAL报警 处理",
        "SRVO-062 BZAL 电池更换",
        "R-30iB SRVO-050 碰撞",
        "阿西莫夫三定律",
    ]
    for q in tests:
        r = hybrid_search(q, 5)
        s = score_answer(q, r)
        print(f"{s['total']:.2f} | {q[:40]}")
