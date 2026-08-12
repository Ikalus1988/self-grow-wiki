#!/usr/bin/env python3
"""Scan local lessons/ directory and rebuild lessons/_index.json.

Scope: this script only manages lessons inside this repository
(self-grow-wiki). It does not touch MisakaNet's lessons.json — that
file is owned by a different repo and updated via a separate process.

Output: lessons/_index.json — list of {id, title, domain, tags, url,
updated} entries parsed from each lesson's frontmatter.

Usage:
  python3 _update_lessons.py             # rebuild _index.json from disk
"""
import json
import re
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
LESSONS_DIR = HERE / "lessons"
INDEX_FILE = LESSONS_DIR / "_index.json"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """Extract simple YAML-ish frontmatter. Returns {} if absent or malformed."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


def _slug_from_filename(name: str) -> str:
    return name[: -len(".md")] if name.endswith(".md") else name


def build_index() -> list:
    """Walk lessons/*.md and produce an index entry per file."""
    entries = []
    if not LESSONS_DIR.is_dir():
        return entries
    for md_path in sorted(LESSONS_DIR.glob("*.md")):
        try:
            text = md_path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta = _parse_frontmatter(text)
        slug = _slug_from_filename(md_path.name)
        entries.append({
            "id": meta.get("id", slug),
            "title": meta.get("title", slug),
            "domain": meta.get("domain", ""),
            "tags": meta.get("tags", []),
            "url": f"lessons/{md_path.name}",
            "updated": meta.get("updated", str(date.today())),
        })
    return entries


def main() -> int:
    entries = build_index()
    INDEX_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Indexed {len(entries)} lesson(s) → {INDEX_FILE.relative_to(HERE)}")
    for e in entries:
        print(f"  - [{e['domain'] or '?'}] {e['id']}: {e['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())