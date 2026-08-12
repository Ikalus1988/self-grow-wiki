#!/usr/bin/env python3
"""Extract 3rd-party dependencies from project source files."""
import re

files = [
    "rag_core.py", "kb_learning.py", "daily_audit.py",
    "badcase_review.py",
]

stdlib = {
    "os","sys","time","json","re","logging","math","random","threading",
    "datetime","pathlib","argparse","collections","hashlib","subprocess",
    "urllib","typing","textwrap","pickle","io","shutil","types","functools",
    "itertools","bisect","copy","warnings","statistics","base64","uuid",
    "tempfile","operator","pprint","traceback","ctypes","glob","inspect",
    "abc","enum","html","http","socket","ssl","string","struct","textwrap",
    "configparser","csv","netrc","platform","shelve","sqlite3",
}

imports = set()
for f in files:
    try:
        with open(f) as fh:
            for line in fh:
                m = re.match(r"^\s*(?:import|from)\s+(\S+)", line)
                if m:
                    mod = m.group(1).split(".")[0].split(" import")[0].strip()
                    if mod not in stdlib:
                        imports.add(mod)
    except FileNotFoundError:
        pass

for m in sorted(imports):
    print(m)
