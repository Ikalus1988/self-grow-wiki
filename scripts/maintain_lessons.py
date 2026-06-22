#!/usr/bin/env python3
"""maintain_lessons.py

自动化维护脚本：
- 遍历 lessons/ 下的 Markdown 文件（*.md）
- 对于新增或被修改的中文课程文件，调用 LLM 提取：Domain、Keywords（核心关键词列表）并生成英文摘要文件 README.en.md
- 在原始中文 Markdown 与生成的 README.en.md 的 Front-matter 中互相添加 cross_reference 标签，且把 domain/keywords 写入 Front-matter

运行方式：
  export OPENAI_API_KEY=xxx
  export OPENAI_API_BASE=https://api.openai.com/v1   # 可选
  python scripts/maintain_lessons.py [--dry-run]

注意：脚本会在 lessons/.lesson_index.json 中记录已处理文件的 sha1（或修改时间），以便只处理新增/修改的文件。

"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests

# Optional yaml support
try:
    import yaml
except Exception:
    yaml = None

logger = logging.getLogger("maintain_lessons")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REPO_ROOT = Path(__file__).resolve().parent.parent
LESSONS_DIR = REPO_ROOT / "lessons"
INDEX_FILE = LESSONS_DIR / ".lesson_index.json"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")

# If you prefer another LLM provider, extend send_prompt_to_llm

PROMPT_TEMPLATE = '''
You are a helpful assistant experienced in documentation and knowledge base authoring.
Given a Chinese Markdown lesson content, extract the following in JSON format exactly:
{
  "domain": "<single short domain tag, e.g. rag, hardware, plc, wiring>",
  "keywords": ["kw1", "kw2", ...],
  "title_en": "<a short English title>",
  "summary_en": "<a concise English summary, 3-6 short paragraphs or ~100-250 words>",
}
Only output valid JSON. Keywords should be short phrases (2-6 words), ordered by importance. Domain should be a succinct tag.

Input:
"""
{content}
"""
'''

JSON_STRIP_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I | re.M)
FRONT_MATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.S)


def sha1_of_text(text: str) -> str:
    h = hashlib.sha1()
    h.update(text.encode("utf-8"))
    return h.hexdigest()


def load_index() -> Dict[str, Any]:
    if not INDEX_FILE.exists():
        return {}
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_index(idx: Dict[str, Any]):
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_front_matter(text: str) -> (Dict[str, Any], str):
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    fm_text = m.group(1)
    body = text[m.end():]
    if yaml:
        try:
            data = yaml.safe_load(fm_text) or {}
            return data, body
        except Exception:
            pass
    # fallback: simple key: value parsing
    data = {}
    for line in fm_text.splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            data[k.strip()] = v.strip()
    return data, body


def build_front_matter(data: Dict[str, Any]) -> str:
    if yaml:
        fm = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        return f"---\n{fm}---\n\n"
    # fallback simple dump
    lines = [f"{k}: {v}" for k, v in data.items()]
    return "---\n" + "\n".join(lines) + "\n---\n\n"


def send_prompt_to_llm(prompt: str, timeout: int = 60) -> Optional[str]:
    """Send prompt to OpenAI compatible chat completions endpoint and return assistant text.
    This uses the OpenAI REST API /v1/chat/completions if OPENAI_API_BASE points to OpenAI.
    The environment must set OPENAI_API_KEY.
    """
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not set; cannot call LLM")
        return None

    url = OPENAI_API_BASE.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 800,
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        j = r.json()
        # OpenAI response format: choices[0].message.content
        if "choices" in j and j["choices"]:
            return j["choices"][0]["message"]["content"]
        # some other providers may return text directly
        return j.get("text") or json.dumps(j)
    except Exception as e:
        logger.exception("LLM request failed: %s", e)
        return None


def extract_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    # try to find a JSON block
    text = text.strip()
    # sometimes wrapped in ```json ... ```
    text = JSON_STRIP_RE.sub("", text).strip()
    # find first { ... }
    start = text.find("{")
    if start == -1:
        return None
    try:
        obj = json.loads(text[start:])
        return obj
    except Exception:
        # try to salvage by finding a balanced JSON substring
        depth = 0
        for i, ch in enumerate(text[start:]):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:start + i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        return None


def ensure_lesson_dir_for(file_path: Path) -> Path:
    stem = file_path.stem
    lesson_dir = LESSONS_DIR / stem
    lesson_dir.mkdir(exist_ok=True)
    return lesson_dir


def update_front_matter_in_file(path: Path, new_meta: Dict[str, Any], dry_run: bool = False):
    text = path.read_text(encoding="utf-8")
    fm, body = parse_front_matter(text)
    changed = False
    for k, v in new_meta.items():
        if fm.get(k) != v:
            fm[k] = v
            changed = True
    if changed:
        new_text = build_front_matter(fm) + body
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
        logger.info("Updated front-matter: %s", path)
    else:
        logger.info("No front-matter change for %s", path)


def process_lesson(file_path: Path, idx: Dict[str, Any], dry_run: bool = False):
    text = file_path.read_text(encoding="utf-8")
    sha = sha1_of_text(text)
    rel = str(file_path.relative_to(REPO_ROOT))
    if idx.get(rel) == sha:
        logger.debug("No change: %s", rel)
        return

    logger.info("Processing new/changed lesson: %s", rel)
    # call LLM to extract domain/keywords/summary
    prompt = PROMPT_TEMPLATE.format(content=text)
    resp = send_prompt_to_llm(prompt)
    if not resp:
        logger.error("LLM failed for %s, skipping", rel)
        return
    data = extract_json_from_response(resp)
    if not data:
        logger.error("Failed to extract JSON for %s, got: %s", rel, resp[:200])
        return

    domain = data.get("domain") or data.get("Domain") or ""
    keywords = data.get("keywords") or []
    title_en = data.get("title_en") or file_path.stem.replace("-", " ").title()
    summary_en = data.get("summary_en") or ""

    # create lesson dir and README.en.md
    lesson_dir = ensure_lesson_dir_for(file_path)
    readme_en_path = lesson_dir / "README.en.md"

    # Build front-matter for English readme and save
    en_meta = {}
    en_meta["title"] = title_en
    if domain:
        en_meta["domain"] = domain
    if keywords:
        en_meta["keywords"] = keywords
    # cross_reference will be added below
    en_front = build_front_matter(en_meta)
    en_body = f"{summary_en}\n\n---\nGenerated by scripts/maintain_lessons.py"

    if not dry_run:
        readme_en_path.write_text(en_front + en_body, encoding="utf-8")
    logger.info("Wrote English README: %s", readme_en_path)

    # Update original file front-matter: add keywords, domain, cross_reference
    orig_meta, orig_body = parse_front_matter(text)
    if not orig_meta:
        orig_meta = {}
    # ensure keywords is a list
    if keywords:
        orig_meta["keywords"] = keywords
    if domain:
        orig_meta["domain"] = domain
    # cross_reference: point to the generated README.en.md relative path
    cross = orig_meta.get("cross_reference") or []
    rel_en = str(readme_en_path.relative_to(REPO_ROOT))
    if rel_en not in cross:
        cross.append(rel_en)
    orig_meta["cross_reference"] = cross
    if not dry_run:
        new_text = build_front_matter(orig_meta) + orig_body
        file_path.write_text(new_text, encoding="utf-8")
    logger.info("Updated original lesson front-matter: %s", file_path)

    # also update generated README front-matter to point back
    en_meta.setdefault("cross_reference", [])
    rel_orig = rel
    if rel_orig not in en_meta["cross_reference"]:
        en_meta["cross_reference"].append(rel_orig)
    if not dry_run:
        readme_en_path.write_text(build_front_matter(en_meta) + en_body, encoding="utf-8")
    logger.info("Updated README.en.md front-matter with back-reference")

    # record processed
    idx[rel] = sha


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Don't write files; just show what would change")
    args = p.parse_args(argv)

    if not LESSONS_DIR.exists():
        logger.error("lessons/ directory not found: %s", LESSONS_DIR)
        return

    idx = load_index()

    md_files = sorted(LESSONS_DIR.glob("*.md"))
    if not md_files:
        logger.info("No lesson markdown files found in lessons/")
        return

    for md in md_files:
        try:
            process_lesson(md, idx, dry_run=args.dry_run)
        except Exception:
            logger.exception("Failed processing %s", md)

    if not args.dry_run:
        save_index(idx)
        logger.info("Index updated: %s", INDEX_FILE)


if __name__ == "__main__":
    main()
