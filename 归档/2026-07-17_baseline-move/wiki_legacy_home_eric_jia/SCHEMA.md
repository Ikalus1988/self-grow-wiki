# Wiki Schema — FANUC Robot Knowledge Base

## Domain
FANUC 工业机器人官方手册知识库 — 操作、编程、参数配置、报警诊断、系统集成。
覆盖 145 份 FANUC 官方手册（B-XXXXXEN/CM 系列），来源为 `chunks_v3` 批次（34,100 chunks，143 PDFs 原始建库）。

## Source Provenance
- **Raw PDFs**: `chunks_v3/*.json` 元数据记录了原始 PDF 路径（`/mnt/f/project/*/`）
- **Vector DB**: ChromaDB `chroma_db_v4/edoc_v10_m3`（BGE-m3 embedding，1024维，~34,100 chunks）
- **Chunk metadata**: 每个 chunk 含 `source`（PDF文件名）、`page`、`chunk_id`

## Conventions

### File naming
- Entities: `fanuc-[model-series].md`，例如 `fanuc-30i-model-a.md`
- Concepts: `alarm-[code].md`、`parameter-[group]-[name].md`、`programming-[topic].md`
- Comparisons: `comparison-[topic-a-vs-b].md`
- 全部小写，空格用连字符

### Frontmatter (required on every wiki page)
```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [from taxonomy below]
sources: [raw/papers/pdf-filename.PDF]
confidence: high | medium | low
contested: true | false
contradictions: [other-page-slug]
---
```

### Wikilinks
- 每个页面至少 2 个 outbound `[[wikilinks]]`
- Entities 链接到相关 Concepts 和其他 Entities
- Concepts 链接到父概念和子概念

### Provenance
- 每条 claim 标注 `^[raw/papers/B-XXXXXEN_XX.PDF]` 源 PDF
- Alarm code 页必须引用具体手册（SRVO-XXX → B-83034EN，参考 B-82874EN）

### Update Policy
- 新信息冲突 → 标注 `contradictions:` 并注明日期
- 不要静默覆盖，保持旧 claim + 新 claim 并存
- `confidence: low` 用于单来源或新报警代码早期汇总

## Tag Taxonomy

### By Category
- **Robot Series**: 30i, 31i, 32i, 35i, R-30iA, R-30iB, R-30iBplus
- **Content Type**: alarm, parameter, programming, operation, integration, maintenance
- **Manual Category**: operator-manual, maintenance-manual, troubleshooting, programming-guide, system-config
- **Language**: CN, EN, DE (手册语言版本)
- **Alarm Class**: SRVO (伺服), SYST (系统), INTP (程序), IO (I/O), PENS (PEN 相关的 pendant)

### Alarm Code Prefixes
- `SRVO-` : Servo/伺服报警（最常见）
- `SYST-` : System/系统报警
- `INTP-` : Interpreter/程序解释报警
- `SOFT-` : Software software限位/碰撞
- `PNS-` : 程序号选择

## Page Thresholds

- **Create entity page** when a model/series appears in 3+ PDFs or is referenced by alarm/parameter pages
- **Create alarm page** when an alarm code appears in any PDF — unique entries (SRVO-001, SRVO-050, etc.)
- **Create parameter page** when a parameter group (e.g., $PARAM_KAREL_*) is documented across 2+ manuals
- **Create programming page** when a TP/Karel instruction appears
- **DON'T create** for passing mentions in footnotes, minor variable names, or one-off mentions

## Entity Pages

Include:
- 模型代号与定位（30i vs 31i vs R-30iB）
- 关键差异（运动控制轴数、IO扩展能力）
- 相关报警代码（wikilinks）
- 相关手册列表

## Concept Pages

### Alarm Pages
- 报警代码（如 `SRVO-001`、`SRVO-050`）
- 可能原因
- 排查步骤（编号列表）
- 相关参数
- 关联手册页码
- Wikilinks 到 relevant entities

### Parameter Pages
- 参数组（如 `$PARAM_KAREL`、`$SCREEN`）
- 含义
- 默认值
- 修改风险
- 关联报警

### Programming Pages
- 指令名称（TP 指令如 `MOVJ`，Karel 指令如 `FOR`/`ENDFOR`）
- 语法格式
- 示例程序片段
- 关联概念

## Comparisons
- 同系列对比（30i vs 31i vs 35i）
- 碰撞检测方案（hard/soft  vs 冲突检测）

## raw/ Frontmatter
```yaml
---
source_url: file:///mnt/f/project/[subdir]/[filename.PDF]
ingested: YYYY-MM-DD
file_hash: <sha256 of PDF body>
manual_id: B-XXXXXEN_XX
language: EN|CN|DE
---
```

## Lint Criteria
- Orphan pages (>90 days no inbound links)
- Broken wikilinks
- Missing frontmatter
- Tags not in taxonomy
- confidence: low 且 180 天无更新
- log.md 超过 500 条需 rotation

## Directory Structure
```
~/wiki/
├── SCHEMA.md
├── index.md
├── log.md
├── raw/
│   └── papers/        # FANUC PDF 元数据记录
├── entities/          # 机器人型号、系统组件
├── concepts/          # 报警代码、参数、编程概念
├── comparisons/       # 跨型号/跨方案对比
└── queries/           # 有价值的查询结果归档
```
