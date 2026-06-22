# Notes for reviewers

This branch adds:
- log_db.py: DB abstraction for query_log (already pushed earlier)
- rag_core.py modified to delegate logging to log_db
- scripts/maintain_lessons.py: the automation script you requested

scripts/maintain_lessons.py details:
- Traverses lessons/*.md, detects new or changed files using .lesson_index.json
- Calls an OpenAI-compatible chat completions endpoint (OPENAI_API_BASE + /chat/completions)
  using OPENAI_API_KEY. The script expects the model gpt-4o-mini to be available; change
  the model in the script if needed.
- Creates lessons/<basename>/README.en.md with English summary and front-matter
- Updates both original lesson front-matter and generated README front-matter to include
  domain, keywords and cross_reference linking to each other.

How to run locally:
  export OPENAI_API_KEY=...
  python scripts/maintain_lessons.py

Dry-run mode:
  python scripts/maintain_lessons.py --dry-run

