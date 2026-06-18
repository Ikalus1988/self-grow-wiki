#!/usr/bin/env python3
"""Update MisakaNet lessons.json with new entries."""
import json

with open("/mnt/c/Users/hp/MisakaNet/lessons.json") as f:
    lessons = json.load(f)

new_entries = [
    {
        "id": "github-cli-markdown-body-safety",
        "title": "GitHub CLI 创建 Markdown Issue/PR 正文的安全模式",
        "domain": "devtools",
        "tags": ["github", "gh-cli", "markdown", "shell", "automation", "issue", "pr"],
        "summary": "使用 gh CLI 创建 Issue/PR 时，Markdown 正文应通过 body-file 传递，避免反引号、路径和参数被 shell 提前解释",
        "url": "lessons/github-cli-markdown-body-safety.md",
        "updated": "2026-06-18"
    },
    {
        "id": "communication-native-rag-engineering-roadmap",
        "title": "面向通讯场景的专业知识 RAG 工程收敛复盘",
        "domain": "rag",
        "tags": ["rag", "agent-gateway", "im", "flywheel", "reliability", "roadmap"],
        "summary": "将专业知识 RAG 嵌入通讯场景，通过 Agent 网关、隐式失败信号、质量飞轮和可控稳定性实现工程收敛",
        "url": "lessons/communication-native-rag-engineering-roadmap.md",
        "updated": "2026-06-18"
    },
    {
        "id": "rag-kb-quality-flywheel-self-loop",
        "title": "RAG 知识库质量飞轮：自闭环建设",
        "domain": "rag",
        "tags": ["rag", "flywheel", "quality", "audit", "feedback", "self-learning"],
        "summary": "RAG 知识库巡检、自学习引擎、审核工具、IM 反馈收集四层闭环的设计与实现",
        "url": "lessons/rag-kb-quality-flywheel-self-loop.md",
        "updated": "2026-05-21"
    },
    {
        "id": "wxauto-im-feedback-collection-jsonl-queue",
        "title": "IM 机器人反馈收集与 JSONL 队列审核模式",
        "domain": "rag",
        "tags": ["rag", "feedback", "queue", "jsonl", "wechat", "wxauto", "workflow"],
        "summary": "在微信机器人中实现好评/差评反馈收集，通过 JSONL 队列管理待审核项",
        "url": "lessons/wxauto-im-feedback-collection-jsonl-queue.md",
        "updated": "2026-05-21"
    },
    {
        "id": "audit-sampling-stratified-sampling-for-kb-inspection",
        "title": "巡检题库分层抽样策略",
        "domain": "rag",
        "tags": ["rag", "audit", "sampling", "quality", "test-bank"],
        "summary": "在大题库 + 小样本场景下，按 level 和 tag 分层抽样确保类型覆盖均匀",
        "url": "lessons/audit-sampling-stratified-sampling-for-kb-inspection.md",
        "updated": "2026-05-21"
    }
]

existing_ids = {l["id"] for l in lessons}
added = []
for e in new_entries:
    if e["id"] not in existing_ids:
        lessons.append(e)
        added.append(e["id"])

with open("/mnt/c/Users/hp/MisakaNet/lessons.json", "w") as f:
    json.dump(lessons, f, ensure_ascii=False, indent=2)

print(f"Total: {len(lessons)}, Added: {added}")
