#!/usr/bin/env python3
"""OKF Concept 自动生成 Pipeline — 飞轮缺口 → LLM → OKF"""
import sys, os, json, time
sys.path.insert(0, "/mnt/c/Users/Eric Jia/self-grow-wiki")
sys.path.insert(0, "/mnt/c/Users/Eric Jia/SAG-poc")

from sag_hybrid import hybrid_search, search_okf
import rag_core

OKF_ROOT = "/mnt/d/MD/RAG知识库/okf_bundle"

# 飞轮发现的缺口 (可根据飞轮失败项动态生成)
GAPS = [
    {"id": "G01", "category": "alarms", "title": "SRVO-068 DTERR", 
     "query": "SRVO-068 DTERR 报警 通信错误 脉冲编码器 原因 对策 处理"},
    {"id": "G02", "category": "alarms", "title": "SRVO-069 CRCERR",
     "query": "SRVO-069 CRCERR 报警 脉冲编码器 通信 CRC错误"},
    {"id": "G03", "category": "alarms", "title": "SRVO-070 STBERR",
     "query": "SRVO-070 STBERR 报警 脉冲编码器 通信"},
    {"id": "G04", "category": "procedures", "title": "TCP/IP通讯配置",
     "query": "FANUC TCP/IP 通讯配置 主机通讯 IP地址 端口 Server Client 步骤"},
    {"id": "G05", "category": "safety", "title": "Collision Guard",
     "query": "FANUC Collision Guard 碰撞检测 灵敏度 COL GUARD ADJUST 配置"},
]

def generate_concept(gap):
    """从缺口生成 OKF Concept"""
    print(f"  [{gap['id']}] {gap['title']}...")
    
    # 1. 检索
    chunks = hybrid_search(gap['query'], top_k=8)
    if not chunks:
        return None
    
    sources = list(set(c['source'] for c in chunks[:5]))
    
    # 2. 构建 body
    body = f"# {gap['title']}\n\n"
    body += f"## 检索到的相关文档\n\n"
    for i, c in enumerate(chunks[:3]):
        body += f"### 来源 {i+1}: {c['source']}\n\n"
        body += f"{c['text'][:600]}\n\n"
    
    body += "## 来源\n"
    for s in sources:
        body += f"- {s}\n"
    body += f"\n---\n*OKF Pipeline 自动生成 | {datetime.now().strftime('%Y-%m-%d')}*\n"
    
    # 3. 写入文件
    cat_dir = os.path.join(OKF_ROOT, gap['category'])
    os.makedirs(cat_dir, exist_ok=True)
    
    filename = gap['title'].replace(' ', '-').replace('/', '-') + '.md'
    path = os.path.join(cat_dir, filename)
    
    fm = f"---\ntype: {gap['category']}\ntitle: {gap['title']}\ntags: [auto-generated]\ntimestamp: {datetime.now().isoformat()}\n---\n\n"
    
    with open(path, 'w', encoding='utf-8') as f:
        f.write(fm + body)
    
    return path

def main():
    print(f"OKF Pipeline — {len(GAPS)} 缺口")
    created = 0
    for gap in GAPS:
        path = generate_concept(gap)
        if path:
            created += 1
            print(f"    ✅ {os.path.basename(path)}")
    print(f"\n生成 {created}/{len(GAPS)} Concepts → {OKF_ROOT}")

if __name__ == '__main__':
    main()
