# Wiki Log

> Chronological record of all wiki actions. Append-only.
> Format: `## [YYYY-MM-DD] action | subject`
> Actions: ingest, update, query, lint, create, archive, delete
> When this file exceeds 500 entries, rotate: rename to log-YYYY.md, start fresh.

## [2026-04-26] create | Wiki initialized
- Domain: FANUC 工业机器人知识库
- Structure created with SCHEMA.md, index.md, log.md
- Sources: 145 FANUC 官方手册（B-XXXXXEN/CM 系列），chunks_v3 批次
- Raw PDFs location: /mnt/f/project/*/
- Vector DB: /mnt/d/Eric/知识库/chroma_db_v4/edoc_v10_m3

## [2026-04-26] ingest | Initial PDF source catalog
- Source: chunks_v3/*.json metadata
- 143 PDF filenames cataloged in raw/papers/
- manual_id, language, chunk_count extracted from filename pattern and JSON stats
- Total chunks: ~34,100 across all sources

## [2026-04-26] create | Entity pages (3)
- [[fanuc-r30ib-controller]] — R-30iB controller entity
- [[fanuc-arc-mate-robot]] — ARC Mate robot series entity
- [[fanuc-30i-series]] — 30i/31i/35i series comparison
- Sources: B-83034EN_08, B-82874EN_13, B-83284* alarm manuals
- Wikilinks: all entities cross-linked

## [2026-04-26] create | Concept pages (4)
- [[alarm-srvo-001]] — Emergency stop alarm
- [[alarm-srvo-050]] — Collision detection alarm
- [[alarm-syst-overall]] — System alarm overview
- [[programming-tp]] — Teach Pendant programming basics
- Sources: B-83284EN-1_07_01.PDF (alarm manual), operator manuals
- All pages have 2+ wikilinks

## [2026-07-17] ingest | FANUC Robot i series 综合样本
- Source: FANUC_Robot_i_series_brochure_zh_2021.PDF
- Pages: 12, Size: 11478661 bytes
- SHA256: 211ed46861fb352b
- Type: 产品样本/宣传册 (扫描图像 PDF)
- Dedup: 通过 — wiki_docs 库内无 'Robot i series' / '上海发那科' / '综合样本' 任一来源
- Verdict: 入 wiki raw/papers/ (用户授权 '通过就入库')
- Caveat: 扫描件无文字层,进 wiki_docs 向量库需 vision ingest 或文本目录提炼
## [2026-07-17] ingest | FANUC Robot i series 综合样本 → wiki_docs (chunks)
- Source: FANUC_Robot_i_series_brochure_zh_2021.PDF
- Pages: 12, Size: 11478661 bytes, SHA256: 211ed46861fb352b
- Dedup: 通过 (chroma_meta source/filename LIKE '%Robot i series%'/'%上海发那科%' 全部 0 命中)
- Verdict: 入库 (image-placeholder chunks, 扫描件无文字层)
- Pipeline: pymupdf get_text → 0 chars → fallback to vision_verified placeholder chunks (1 per page)
- Embedding: BGE-base-zh-v1.5 (768-dim, CUDA, mean-pool)
- Chunks added: 12 (FANUC_i_series_2021_p01..p12)
- Collection: wiki_docs (200842 → 200854)
- Metadata: category=07_机器人, manual_type=产品样本/宣传册 (Brochure), ingested=2026-07-17, ingest_method=image-placeholder
- Caveat: 每页 chunk 是 placeholder (含 page 标记 + image count + vision 摘要), 非真实 OCR 文字
- 后续: BM25 rebuild (~/rag_chromadb/bm25_index.pkl) 跳过 → 添加 when RAG 实际需要 keyword 命中此 PDF
- 后续: 真 OCR (tesseract/easyocr/paddleocr) → 安装 when 用户要按关键词召回具体页面内容
