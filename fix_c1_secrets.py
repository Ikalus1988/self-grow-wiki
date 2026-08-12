#!/usr/bin/env python3
"""C1 修复：把 7 个脚本中的硬编码密钥改为环境变量 / ~/.hermes/.env 读取。"""
import re

FILES = [
    "scripts/audit/audit_chunks_p1.py",
    "scripts/docs/doc_verify.py",
    "scripts/docs/doc_verify_v2.py",
    "scripts/exam/gen_exam.py",
    "scripts/exam/gen_exam_v2.py",
    "scripts/audit/audit_exam_p2.py",
    "scripts/audit/audit_pdf_chunk_v2.py",
]

HELPER = '''
# ── 密钥读取：环境变量优先，~/.hermes/.env 兜底（评审 C1: 不再硬编码） ──
import os as _os

def _load_deepseek_key() -> str:
    """读取 DEEPSEEK_API_KEY：环境变量优先，其次 ~/.hermes/.env。"""
    key = _os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    env_path = _os.path.expanduser("~/.hermes/.env")
    if _os.path.exists(env_path):
        try:
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return ""
'''

for f in FILES:
    src = open(f, encoding="utf-8").read()
    # 1. 变量赋值型密钥（FLASH_KEY / DEEPSEEK_KEY / KEY = "..."）
    src, n1 = re.subn(r'(FLASH_KEY|DEEPSEEK_KEY|KEY)\s*=\s*"[^"]*"',
                      r'\1 = _load_deepseek_key()', src)
    # 2. 内联型 api_key="..."
    src, n2 = re.subn(r'api_key=\s*[^\n,)]*',
                      'api_key=_load_deepseek_key()', src)
    # 3. 在第一个 import/from/shebang 行之后插入 helper
    m = re.search(r'^(import |from |#!|# ).*$', src, re.M)
    if m and (n1 + n2 > 0) and "_load_deepseek_key" not in src.split("def _load_deepseek_key")[0]:
        pos = m.end()
        src = src[:pos] + HELPER + src[pos:]
    open(f, "w", encoding="utf-8").write(src)
    print(f"{f}: 变量替换 {n1} 处, 内联替换 {n2} 处")
