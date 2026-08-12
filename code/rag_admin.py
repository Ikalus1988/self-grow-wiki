#!/usr/bin/env python3
"""RAG 项目管理面板 — Gradio 6.x 多 Tab 仪表板.

端口 7861，与现有 rag_web.py (7860) / rag_api.py (8002) 并行运行。
"""

import argparse
import logging
import os
import threading
import time
from pathlib import Path

import gradio as gr
import requests
import kb_learning

logger = logging.getLogger(__name__)

from rag_core import (
    get_collection, retrieve, format_sources,
    generate_with_failover, generate_compare,
    channel_mgr, MODEL_CHANNELS, PATHS,
    DEFAULT_TOP_K, DEFAULT_TEMPERATURE,
    get_kb_stats, MIOFFICE_API_BASE, OLLAMA_BASE,
    log_query, get_query_logs, get_log_stats, get_token_stats,
    estimate_tokens, invalidate_indexes,
)

REPORT_PATH = Path(PATHS["conflict_report"])

# ── helpers ────────────────────────────────────────────────────────────

def _service_alive(port):
    try:
        return requests.get(f"http://localhost:{port}/health", timeout=3).ok
    except Exception:
        try:
            return requests.get(f"http://localhost:{port}/", timeout=3).status_code < 500
        except Exception:
            return False


def _badge(text, color):
    return f'<span style="background:{color};color:#fff;padding:2px 8px;border-radius:4px;font-size:0.85em">{text}</span>'


# ═════════════════════════���════════════════════════════════════════════
#  Tab 1 — 仪表板
# ══════════════════════════════════════════════════════════════════════

def refresh_dashboard():
    stats = get_kb_stats()
    tv = stats["total_vectors"]
    tf = stats["total_files"]
    cats = stats.get("categories", {})
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:8]

    alive = sum(1 for ch in MODEL_CHANNELS
                if channel_mgr.health.get(ch["id"], {}).get("alive"))
    total_ch = len(MODEL_CHANNELS)

    cards = f"""
### 系统概览

| 指标 | 数值 |
|------|------|
| 向量总数 | **{tv:,}** |
| 文档总数 | **{tf:,}** |
| LLM 通道 | **{alive}/{total_ch}** 可用 |
"""
    if top_cats:
        cards += "\n**知识分类 TOP 8：**\n"
        for cat, cnt in top_cats:
            cards += f"- {cat}：{cnt} chunks\n"

    online = f"""### {_badge('已上线', '#22c55e')} 在线功能

- **智能问答** — 语义检索 + LLM 生成，三通道容灾
- **报警代码增强检索** — 自动识别 SRVO-023 等报警代码，混合关键词+语义
- **深度对比** — 多对象分别检索后合并对比 (微信 /对比 + 本面板)
- **微信机器人** — wxauto 驱动，群聊 @触发，/查 /对比 /状态 /帮助
- **通道容灾** — MiMo → Qwen云端 → Qwen本地，逐级降级
- **分段发送** — 长回复自动按段落拆分，避免微信截断"""

    developed = f"""### {_badge('已开发', '#3b82f6')} 已开发（本面板可用）

- **知识库浏览** — 文件列表、chunk预览、分类统计
- **矛盾自检** — 多版本文档自动对比，生成矛盾报告
- **语义搜索测试** — 可视化 retrieve() 结果，调试检索质量"""

    planned = f"""### {_badge('规划中', '#a855f7')} 待开发

**基础管理**
- ~~文档上传管理~~ — {_badge('已上线', '#22c55e')} Tab 8
- ~~查询日志分析~~ — {_badge('已上线', '#22c55e')} Tab 6
- ~~Token 消耗监控~~ — {_badge('已上线', '#22c55e')} Tab 7
- **知识库版本管理** — 文档版本追踪、旧版自动标记/清理
- **自动过期提醒** — 标准文档到期提醒 (Tesla TS / JLR 等)

**自成长**
- **知识缺口自检** — 分析历史查询的未命中和低分记录，生成知识缺口清单，提示管理员补充哪类文档
- **主动补全目标** — 根据缺口清单和文档分类，自动规划"下一步应补充什么"，并追踪补充进度
- **知识覆盖度评估** — 对比已有文档与行业标准文档目录，标出覆盖空白

**自省 · 主动学习**
- **问题预判** — 基于历史查询模式，预测用户可能提出但知识库暂无答案的问题，提前预警
- **答案置信度追踪** — 对每次回答记录检索分数和 LLM 判断，识别"回答了但可能不准"的高风险问题
- **知识点关联图** — 构建文档间知识点关联，发现同一设备的多个文档版本、互相矛盾的技术描述

**报告 · 复盘 · 自我纠错**
- **周期复盘报告** — 定期生成：本周热点问题 / 回答质量评估 / 知识库命中率趋势
- **错误积累与纠正** — 用户对回答标注"不准确"后，记录案例并提示更新对应文档
- **经验库** — 将高质量的问答对沉淀为经验文档，反哺知识库，形成良性循环"""

    return cards, online, developed, planned


def build_tab_dashboard():
    with gr.Tab("仪表板"):
        gr.Markdown("# RAG 项目管理面板")
        refresh_btn = gr.Button("刷新数据", size="sm")
        cards = gr.Markdown()
        with gr.Row():
            with gr.Column():
                online_md = gr.Markdown()
            with gr.Column():
                dev_md = gr.Markdown()
        with gr.Accordion("待开发功能路线图", open=False):
            plan_md = gr.Markdown()
        refresh_btn.click(fn=refresh_dashboard, outputs=[cards, online_md, dev_md, plan_md])
        app_load_outputs = [cards, online_md, dev_md, plan_md]
    return app_load_outputs


# ══════════════════════════════════════════════════════════════════════
#  Tab 2 — 智能问答
# ══════════════════════════════════════════════════════════════════════

def process_query(query, history, top_k, temperature, channel_choice):
    if not query.strip():
        yield history, "", ""
        return

    t0 = time.time()
    chunks = retrieve(query, top_k=int(top_k))
    sources_md = format_sources(chunks)

    channel_map = {"自动 (智能切换)": "auto"}
    for ch in MODEL_CHANNELS:
        channel_map[ch["label"]] = ch["id"]
    preferred = channel_map.get(channel_choice, "auto")

    history = history or []
    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": ""})

    answer = ""
    status = ""
    last_ch_name = ""
    usage_info = {}
    for token, st in generate_with_failover(query, chunks, preferred, temperature, usage_info=usage_info):
        answer += token
        status = st
        if st.startswith("通道: "):
            last_ch_name = st[4:]
        history[-1]["content"] = answer
        yield history, sources_md, ""

    if status and "降级" not in status:
        history[-1]["content"] = answer + f"\n\n---\n*{status}*"

    latency_ms = int((time.time() - t0) * 1000)
    ch_id = ""
    for ch in MODEL_CHANNELS:
        if ch["name"] == last_ch_name:
            ch_id = ch["id"]
            break

    # 优先使用 API 返回的真实 token 计数
    tok_prompt = usage_info.get("prompt_tokens", 0)
    tok_completion = usage_info.get("completion_tokens", 0)
    if tok_completion == 0:
        tok_completion = estimate_tokens(answer)

    log_query(query, chunks, channel_id=ch_id, channel_name=last_ch_name,
              latency_ms=latency_ms, tokens_prompt=tok_prompt,
              tokens_completion=tok_completion,
              status="error" if "不可用" in status else "success",
              query_type="qa")
    yield history, sources_md, ""


def build_tab_chat():
    with gr.Tab("智能问答"):
        with gr.Row():
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(label="对话", height=480)
                with gr.Row():
                    query_input = gr.Textbox(
                        label="输入问题", lines=2, scale=5,
                        placeholder="例: SRVO-023报警怎么处理？G120变频器调试步骤？",
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)
            with gr.Column(scale=2):
                channel_labels = ["自动 (智能切换)"] + [ch["label"] for ch in MODEL_CHANNELS]
                channel_choice = gr.Radio(channel_labels, value="自动 (智能切换)", label="通道选择")
                top_k_slider = gr.Slider(3, 20, value=DEFAULT_TOP_K, step=1, label="检索数量 (top_k)")
                temp_slider = gr.Slider(0.0, 1.0, value=DEFAULT_TEMPERATURE, step=0.1, label="生成温度")
                sources_output = gr.Markdown("*提交问题后显示引用来源*")

        clear_btn = gr.Button("清空对话", size="sm")
        clear_btn.click(lambda: ([], "*提交问题后显示引用来源*", ""),
                        outputs=[chatbot, sources_output, query_input])

        args = dict(
            fn=process_query,
            inputs=[query_input, chatbot, top_k_slider, temp_slider, channel_choice],
            outputs=[chatbot, sources_output, query_input],
        )
        send_btn.click(**args)
        query_input.submit(**args)


# ══════════════════════════════════════════════════════════════════════
#  Tab 3 — 深度对比
# ══════════════════════════════════════════════════════════════════════

def run_compare(subject_a, subject_b, aspect, top_k, temperature):
    if not subject_a.strip() or not subject_b.strip():
        return "请输入两个对比对象", ""
    subjects = [subject_a.strip(), subject_b.strip()]
    answer, sources, status = generate_compare(
        subjects=subjects, aspect=aspect.strip(),
        top_k=int(top_k), temperature=temperature,
    )
    src_text = ""
    if sources:
        src_text = "### 引用来源\n" + "\n".join(f"- {s}" for s in sources)
    return answer, src_text


def build_tab_compare():
    with gr.Tab("深度对比"):
        gr.Markdown("输入两个对比对象，可选聚焦维度。系统会分别检索后合并送给 LLM 生成结构化对比。")
        with gr.Row():
            subject_a = gr.Textbox(label="对象 A", placeholder="例: KUKA")
            subject_b = gr.Textbox(label="对象 B", placeholder="例: ABB")
            aspect = gr.Textbox(label="聚焦维度（可选）", placeholder="例: 编程语言")
        with gr.Row():
            top_k = gr.Slider(5, 20, value=10, step=1, label="每对象检索数")
            temp = gr.Slider(0.0, 1.0, value=0.3, step=0.1, label="生成温度")
        compare_btn = gr.Button("开始对比", variant="primary")
        result_md = gr.Markdown()
        sources_md = gr.Markdown()
        compare_btn.click(
            fn=run_compare,
            inputs=[subject_a, subject_b, aspect, top_k, temp],
            outputs=[result_md, sources_md],
        )


# ══════════════════════════════════════════════════════════════════════
#  Tab 4 — 知识库浏览
# ══════════════════════════════════════════════════════════════════════

_file_cache = {"files": {}, "ts": 0}


def _get_file_list():
    now = time.time()
    if _file_cache["files"] and now - _file_cache["ts"] < 60:
        return _file_cache["files"]
    stats = get_kb_stats()
    _file_cache["files"] = stats.get("file_counts", {})
    _file_cache["ts"] = now
    return _file_cache["files"]


def kb_overview():
    stats = get_kb_stats()
    tv = stats["total_vectors"]
    tf = stats["total_files"]
    cats = stats.get("categories", {})
    subcats = stats.get("subcategories", {})
    top_cats = sorted(cats.items(), key=lambda x: -x[1])[:15]
    top_subcats = sorted(subcats.items(), key=lambda x: -x[1])[:15]
    lines = [f"**向量总数:** {tv:,}　　**文档总数:** {tf:,}\n"]
    if top_cats:
        lines.append("**分类分布:**\n")
        for cat, cnt in top_cats:
            lines.append(f"- {cat}: {cnt:,} chunks")
    if len(cats) > 15:
        lines.append(f"- ... 共 {len(cats)} 个分类")
    if top_subcats:
        lines.append("\n**子分类分布:**\n")
        for sc, cnt in top_subcats:
            lines.append(f"- {sc}: {cnt:,} chunks")
    if len(subcats) > 15:
        lines.append(f"- ... 共 {len(subcats)} 个子分类")
    return "\n".join(lines)


def search_files(keyword, category_filter=None, subcategory_filter=None):
    fc = _get_file_list()
    # 先按 category/subcategory 过滤文件列表
    if category_filter and category_filter != "全部":
        # 需要从 collection 里按 category 过滤
        coll = get_collection()
        where = {"category": {"$eq": category_filter}}
        if subcategory_filter and subcategory_filter != "全部":
            where["subcategory"] = {"$eq": subcategory_filter}
        try:
            r = coll.get(where=where, include=["metadatas"], limit=10000)
            filtered_fns = set()
            for m in r["metadatas"]:
                fn = m.get("filename") or m.get("source") or ""
                if fn:
                    filtered_fns.add(fn)
            fc = {fn: cnt for fn, cnt in fc.items() if fn in filtered_fns}
        except Exception as e:
            logger.warning(f"文件名过滤失败: {e}")
    elif subcategory_filter and subcategory_filter != "全部":
        coll = get_collection()
        try:
            r = coll.get(where={"subcategory": {"$eq": subcategory_filter}},
                         include=["metadatas"], limit=10000)
            filtered_fns = set()
            for m in r["metadatas"]:
                fn = m.get("filename") or m.get("source") or ""
                if fn:
                    filtered_fns.add(fn)
            fc = {fn: cnt for fn, cnt in fc.items() if fn in filtered_fns}
        except Exception as e:
            logger.warning(f"子类过滤失败: {e}")

    if not keyword.strip():
        items = sorted(fc.items(), key=lambda x: -x[1])[:50]
    else:
        kw = keyword.strip().lower()
        items = [(fn, cnt) for fn, cnt in fc.items() if kw in fn.lower()]
        items.sort(key=lambda x: -x[1])
        items = items[:50]
    if not items:
        return "未找到匹配文件"
    lines = [f"共 {len(items)} 个文件（最多显示50个）\n"]
    for fn, cnt in items:
        lines.append(f"- **{fn}** ({cnt} chunks)")
    return "\n".join(lines)


def _get_categories():
    """获取所有分类列表."""
    stats = get_kb_stats()
    cats = sorted(stats.get("categories", {}).keys())
    return ["全部"] + cats


def _get_subcategories(category_filter=None):
    """获取子分类列表."""
    stats = get_kb_stats()
    subcats = stats.get("subcategories", {})
    if category_filter and category_filter != "全部":
        prefix = f"{category_filter}/"
        items = [k.split("/", 1)[1] for k in subcats if k.startswith(prefix)]
    else:
        items = [k.split("/", 1)[1] if "/" in k else k for k in subcats]
    return ["全部"] + sorted(set(items))


def _on_category_change(cat):
    """分类变化时更新子分类下拉."""
    subcats = _get_subcategories(cat)
    return gr.Dropdown(choices=subcats, value="全部")


def preview_file(filename):
    if not filename.strip():
        return "请输入文件名"
    coll = get_collection()
    try:
        r = coll.get(
            where={"filename": {"$eq": filename.strip()}},
            limit=5,
            include=["documents", "metadatas"],
        )
    except Exception:
        return "查询出错，请检查文件名"
    if not r["ids"]:
        return f"未找到文件: {filename}"
    pairs = list(zip(r["documents"], r["metadatas"]))
    pairs.sort(key=lambda x: x[1].get("chunk_index", 0))
    lines = [f"**{filename}** — 前 {len(pairs)} 个 chunks\n"]
    for doc, meta in pairs:
        idx = meta.get("chunk_index", "?")
        cat = meta.get("category", "")
        lines.append(f"**Chunk {idx}** | {cat}")
        lines.append(f"> {doc[:300]}{'...' if len(doc) > 300 else ''}\n")
    return "\n".join(lines)


def test_retrieve(query, top_k):
    if not query.strip():
        return "请输入查询"
    chunks = retrieve(query, top_k=int(top_k))
    lines = [f"检索到 {len(chunks)} 个 chunks:\n"]
    for c in chunks:
        cat = f"{c['category']}/{c['subcategory']}" if c.get('subcategory') else c.get('category', '')
        lines.append(
            f"**[{c['index']}]** score={c['score']:.3f} | **{c['filename']}** | {cat}")
        lines.append(f"> {c['text'][:200]}{'...' if len(c['text']) > 200 else ''}\n")
    return "\n".join(lines)


def build_tab_kb():
    with gr.Tab("知识库浏览"):
        overview_md = gr.Markdown()
        refresh_kb = gr.Button("刷新统计", size="sm")
        refresh_kb.click(fn=kb_overview, outputs=[overview_md])

        gr.Markdown("---")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 文件搜索")
                file_kw = gr.Textbox(label="文件名关键词", placeholder="例: FANUC")
                with gr.Row():
                    cat_dd = gr.Dropdown(label="分类筛选", choices=_get_categories(), value="全部", scale=1)
                    subcat_dd = gr.Dropdown(label="子分类筛选", choices=_get_subcategories(), value="全部", scale=1)
                # 分类变化时联动子分类下拉
                cat_dd.change(fn=_on_category_change, inputs=[cat_dd], outputs=[subcat_dd])
                search_btn = gr.Button("搜索", size="sm")
                file_list_md = gr.Markdown()
                search_btn.click(fn=search_files, inputs=[file_kw, cat_dd, subcat_dd], outputs=[file_list_md])
                file_kw.submit(fn=search_files, inputs=[file_kw, cat_dd, subcat_dd], outputs=[file_list_md])

            with gr.Column():
                gr.Markdown("### 文档预览")
                preview_input = gr.Textbox(label="完整文件名", placeholder="例: B-83525CM_08.PDF")
                preview_btn = gr.Button("预览", size="sm")
                preview_md = gr.Markdown()
                preview_btn.click(fn=preview_file, inputs=[preview_input], outputs=[preview_md])

        gr.Markdown("---\n### 语义搜索测试")
        with gr.Row():
            test_query = gr.Textbox(label="测试查询", placeholder="例: SRVO-023 停止时误差过大", scale=4)
            test_topk = gr.Slider(3, 20, value=8, step=1, label="top_k", scale=1)
        test_btn = gr.Button("检索", size="sm")
        test_result = gr.Markdown()
        test_btn.click(fn=test_retrieve, inputs=[test_query, test_topk], outputs=[test_result])
        test_query.submit(fn=test_retrieve, inputs=[test_query, test_topk], outputs=[test_result])

    return overview_md


# ══════════════════════════════════════════════════════════════════════
#  Tab 5 — 矛盾自检
# ══════════════════════════════════════════════════════════════════════

_selfcheck_status = {"running": False, "log": ""}


def load_report():
    if not REPORT_PATH.exists():
        return "尚未生成自检报告。点击「运行自检」开始。"
    return REPORT_PATH.read_text(encoding="utf-8")


def run_selfcheck_bg(limit):
    if _selfcheck_status["running"]:
        return "自检正在运行中，请等待..."
    _selfcheck_status["running"] = True
    _selfcheck_status["log"] = "启动自检...\n"

    def _run():
        try:
            # kb_selfcheck 位于 scripts/ 子目录，注入 sys.path（评审 M4）
            import sys
            from pathlib import Path as _P
            _scripts = _P(__file__).resolve().parent / "scripts"
            if str(_scripts) not in sys.path:
                sys.path.insert(0, str(_scripts))
            from kb_selfcheck import run_selfcheck
            limit_val = int(limit) if limit else None
            report = run_selfcheck(limit=limit_val)
            REPORT_PATH.write_text(report, encoding="utf-8")
            _selfcheck_status["log"] += "自检完成！报告已保存。\n"
        except Exception as e:
            _selfcheck_status["log"] += f"自检出错: {e}\n"
        finally:
            _selfcheck_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return "自检已在后台启动，请稍候后点击「刷新报告」..."


def get_selfcheck_log():
    status = "运行中..." if _selfcheck_status["running"] else "空闲"
    return f"**状态:** {status}\n\n```\n{_selfcheck_status['log'][-2000:]}\n```"


def build_tab_selfcheck():
    with gr.Tab("矛盾自检"):
        gr.Markdown("对知识库中同名多版本文档进行自动矛盾检测。编制年份新的文档优先采信。")
        with gr.Row():
            limit_input = gr.Number(label="扫描组数限制（空=全部）", value=5, precision=0)
            run_btn = gr.Button("运行自检", variant="primary")
        run_msg = gr.Markdown()
        run_btn.click(fn=run_selfcheck_bg, inputs=[limit_input], outputs=[run_msg])

        with gr.Row():
            refresh_report = gr.Button("刷新报告", size="sm")
            refresh_log = gr.Button("查看日志", size="sm")
        report_md = gr.Markdown()
        log_md = gr.Markdown()
        refresh_report.click(fn=load_report, outputs=[report_md])
        refresh_log.click(fn=get_selfcheck_log, outputs=[log_md])


# ══════════════════════════════════════════════════════════════════════
#  Tab — 自学习反馈
# ══════════════════════════════════════════════════════════════════════

def _sl_overview():
    stats = kb_learning.get_stats()
    lines = [
        "### 自学习总览\n",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 总查询数 | {stats['total_queries']} |",
        f"| 知识缺口数 | {stats['total_gaps']} |",
        f"| 缺口率 | {stats['gap_rate']}% |",
        f"| 平均检索分数 | {stats['avg_score']} |",
        f"| 用户反馈数 | {stats['total_feedback']} |",
        f"| 沉淀FAQ数 | {stats['total_faq']} |",
    ]
    if stats.get("top_gaps"):
        lines.append("\n### 知识缺口热点 (重复低分查询)\n")
        for q, cnt in stats["top_gaps"]:
            lines.append(f"- [{cnt}次] `{q}`")
    return "\n".join(lines)


def _sl_gaps(limit):
    gaps = kb_learning.get_gaps(limit=int(limit))
    if not gaps:
        return "暂无知识缺口记录"
    lines = [f"### 知识缺口列表 (共 {len(gaps)} 条)\n"]
    lines.append("| 时间 | 查询 | 分数 | Chunks |")
    lines.append("|------|------|------|--------|")
    for g in gaps:
        lines.append(f"| {g['datetime']} | {g['query'][:40]} | {g['top_score']:.3f} | {g['chunks_count']} |")
    return "\n".join(lines)


def _sl_feedback(days):
    fb = kb_learning.get_feedback_summary(days=int(days))
    lines = [
        f"### 反馈汇总 (近 {fb['period_days']} 天)\n",
        f"- 👍 **{fb['up']}** 次 / 👎 **{fb['down']}** 次",
        f"- 满意度: **{fb['satisfaction_rate']}%**\n",
    ]
    if fb["down_queries"]:
        lines.append("### 不满意的查询\n")
        for dq in fb["down_queries"]:
            lines.append(f"- `{dq['query']}` {dq.get('comment', '')} ({dq['datetime']})")
    return "\n".join(lines)


def _sl_faq():
    faqs = kb_learning.get_faq_pairs(limit=50)
    if not faqs:
        return "暂无自动沉淀FAQ"
    lines = [f"### 自动沉淀 FAQ (共 {len(faqs)} 条)\n"]
    lines.append("| 查询 | 命中次数 | 沉淀时间 |")
    lines.append("|------|---------|---------|")
    for f in faqs:
        lines.append(f"| {f['query'][:50]} | {f['hit_count']} | {f.get('datetime', '')} |")
    return "\n".join(lines)


def _sl_report():
    return kb_learning.generate_report()


def build_tab_selflearning():
    with gr.Tab("自学习反馈"):
        gr.Markdown("知识库自学习闭环：查询日志 → 知识缺口检测 → 用户反馈 → FAQ沉淀")

        with gr.Row():
            sl_overview_md = gr.Markdown()
        sl_refresh = gr.Button("刷新总览", size="sm")
        sl_refresh.click(fn=_sl_overview, outputs=[sl_overview_md])

        gr.Markdown("---")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 知识缺口")
                sl_gap_limit = gr.Slider(10, 100, value=30, step=10, label="显示条数")
                sl_gap_btn = gr.Button("查看缺口", size="sm")
                sl_gap_md = gr.Markdown()
                sl_gap_btn.click(fn=_sl_gaps, inputs=[sl_gap_limit], outputs=[sl_gap_md])

            with gr.Column():
                gr.Markdown("### 用户反馈")
                sl_fb_days = gr.Slider(1, 90, value=7, step=1, label="统计天数")
                sl_fb_btn = gr.Button("查看反馈", size="sm")
                sl_fb_md = gr.Markdown()
                sl_fb_btn.click(fn=_sl_feedback, inputs=[sl_fb_days], outputs=[sl_fb_md])

        gr.Markdown("---")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 自动沉淀 FAQ")
                sl_faq_btn = gr.Button("查看FAQ", size="sm")
                sl_faq_md = gr.Markdown()
                sl_faq_btn.click(fn=_sl_faq, outputs=[sl_faq_md])

            with gr.Column():
                gr.Markdown("### 综合报告")
                sl_report_btn = gr.Button("生成报告", variant="primary", size="sm")
                sl_report_md = gr.Markdown()
                sl_report_btn.click(fn=_sl_report, outputs=[sl_report_md])

    return sl_overview_md


# ══════════════════════════════════════════════════════════════════════
#  Tab 6 — 查询日志分析
# ══════════════════════════════════════════════════════════════════════

def _format_log_overview(days):
    days = int(days) if days else 7
    stats = get_log_stats(days=days)
    total = stats["total"]
    by_day = stats["by_day"]

    lines = [f"### 近 {days} 天查询概览\n"]
    lines.append(f"**查询总数:** {total}　　**日均:** {total / max(len(by_day), 1):.1f}\n")

    if by_day:
        lines.append("| 日期 | 查询数 | 平均最高分 | 平均延迟 | Token消耗 |")
        lines.append("|------|--------|-----------|---------|----------|")
        for d in by_day:
            lines.append(
                f"| {d['day']} | {d['c']} | {d['avg_top']:.2f} "
                f"| {d['avg_lat']:.0f}ms | {d['total_tok'] or 0:,} |"
            )
    else:
        lines.append("*暂无数据*")

    return "\n".join(lines)


def _format_top_queries(days):
    days = int(days) if days else 7
    stats = get_log_stats(days=days)
    queries = stats["top_queries"]
    if not queries:
        return "*暂无数据*"
    lines = ["### 高频查询 TOP 15\n", "| 查询 | 次数 |", "|------|------|"]
    for q in queries:
        lines.append(f"| {q['query'][:60]} | {q['c']} |")
    return "\n".join(lines)


def _format_low_score(days):
    days = int(days) if days else 7
    stats = get_log_stats(days=days)
    low = stats["low_score_queries"]
    if not low:
        return "**无低分查询** — 检索质量良好"
    lines = ["### 低分查询（top_score < 0.4）\n",
             "这些查询可能代表知识缺口，建议评估是否需要补充文档。\n",
             "| 查询 | 最高分 | 时间 |", "|------|--------|------|"]
    for q in low:
        lines.append(f"| {q['query'][:50]} | {q['top_score']:.3f} | {q['ts']} |")
    return "\n".join(lines)


def _format_status_dist(days):
    days = int(days) if days else 7
    stats = get_log_stats(days=days)
    by_status = stats["by_status"]
    if not by_status:
        return "*暂无数据*"
    lines = ["### 状态分布\n", "| 状态 | 次数 |", "|------|------|"]
    for s in by_status:
        lines.append(f"| {s['status']} | {s['c']} |")
    return "\n".join(lines)


def _format_recent_logs(limit):
    limit = int(limit) if limit else 30
    logs = get_query_logs(limit=limit)
    if not logs:
        return "*暂无查询记录*"
    lines = ["### 最近查询明细\n",
             "| 时间 | 类型 | 查询 | 最高分 | 通道 | 延迟 | 状态 |",
             "|------|------|------|--------|------|------|------|"]
    for r in logs:
        q = r["query"][:35] + ("..." if len(r["query"]) > 35 else "")
        lines.append(
            f"| {r['ts'][5:]} | {r['query_type']} | {q} "
            f"| {r['top_score']:.2f} | {r['channel_name'] or '-'} "
            f"| {r['latency_ms']}ms | {r['status']} |"
        )
    return "\n".join(lines)


def build_tab_query_log():
    with gr.Tab("查询日志"):
        with gr.Row():
            days_input = gr.Number(label="统计天数", value=7, precision=0, minimum=1, maximum=90)
            refresh_log_btn = gr.Button("刷新统计", variant="primary", size="sm")

        overview_md = gr.Markdown()
        with gr.Row():
            with gr.Column():
                top_q_md = gr.Markdown()
            with gr.Column():
                status_md = gr.Markdown()
        low_md = gr.Markdown()

        gr.Markdown("---")
        with gr.Row():
            log_limit = gr.Slider(10, 200, value=30, step=10, label="显示条数")
            recent_btn = gr.Button("查看明细", size="sm")
        recent_md = gr.Markdown()

        refresh_log_btn.click(
            fn=lambda d: (_format_log_overview(d), _format_top_queries(d),
                          _format_status_dist(d), _format_low_score(d)),
            inputs=[days_input],
            outputs=[overview_md, top_q_md, status_md, low_md],
        )
        recent_btn.click(fn=_format_recent_logs, inputs=[log_limit], outputs=[recent_md])

    return overview_md


# ══════════════════════════════════════════════════════════════════════
#  Tab 7 — Token 监控
# ══════════════════════════════════════════════════════════════════════

# MiMo 系列定价 (元/千token) — 内部平台可能免费，按实际计费调整
TOKEN_PRICING = {
    "mimo-flash": {"input": 0.0, "output": 0.0, "label": "MiMo-Flash (内部)"},
    "mimo-pro":   {"input": 0.0, "output": 0.0, "label": "MiMo-Pro (内部)"},
    "qwen-local": {"input": 0.0, "output": 0.0, "label": "Qwen 本地 (免费)"},
    "unknown":    {"input": 0.0, "output": 0.0, "label": "未知"},
}


def _format_token_overview(days):
    days = int(days) if days else 7
    stats = get_token_stats(days=days)
    ov = stats["overall"]
    total = ov.get("total") or 0
    total_in = ov.get("total_prompt") or 0
    total_out = ov.get("total_completion") or 0
    qc = ov.get("query_count") or 0

    lines = [f"### 近 {days} 天 Token 消耗概览\n"]
    lines.append(f"**查询总数:** {qc}　　**Token 总量:** {total:,}")
    lines.append(f"**输入 Token:** {total_in:,}　　**输出 Token:** {total_out:,}")
    if qc > 0:
        lines.append(f"**单次查询平均:** {total // qc:,} tokens\n")
    else:
        lines.append("")
    return "\n".join(lines)


def _format_token_daily(days):
    days = int(days) if days else 7
    stats = get_token_stats(days=days)
    by_day = stats["by_day"]
    if not by_day:
        return "*暂无数据*"
    lines = ["### 每日 Token 消耗趋势\n",
             "| 日期 | 查询数 | 输入Token | 输出Token | 合计 | 单次平均 |",
             "|------|--------|-----------|-----------|------|----------|"]
    for d in by_day:
        lines.append(
            f"| {d['day']} | {d['query_count']} | {d['total_prompt'] or 0:,} "
            f"| {d['total_completion'] or 0:,} | {d['total'] or 0:,} "
            f"| {d['avg_per_query'] or 0:,} |"
        )
    return "\n".join(lines)


def _format_token_channel(days):
    days = int(days) if days else 7
    stats = get_token_stats(days=days)
    by_ch = stats["by_channel"]
    if not by_ch:
        return "*暂无数据*"
    lines = ["### 按通道分布\n",
             "| 通道 | 查询数 | 输入Token | 输出Token | 合计 | 占比 |",
             "|------|--------|-----------|-----------|------|------|"]
    grand_total = max(sum(c["total"] or 0 for c in by_ch), 1)
    for c in by_ch:
        t = c["total"] or 0
        pct = t / grand_total * 100
        ch_label = c["channel_name"] or c["channel_id"]
        lines.append(
            f"| {ch_label} | {c['query_count']} | {c['total_prompt'] or 0:,} "
            f"| {c['total_completion'] or 0:,} | {t:,} | {pct:.1f}% |"
        )
    return "\n".join(lines)


def _format_token_cost(days):
    days = int(days) if days else 7
    stats = get_token_stats(days=days)
    by_ch = stats["by_channel"]
    if not by_ch:
        return "*暂无数据*"

    lines = ["### 费用估算\n"]
    lines.append("*定价基于配置文件 TOKEN_PRICING（当前均为内部/免费通道，费用为 0）*\n")
    lines.append("| 通道 | 输入费用 | 输出费用 | 合计费用 |")
    lines.append("|------|----------|----------|----------|")

    total_cost = 0.0
    for c in by_ch:
        cid = c["channel_id"] or "unknown"
        pricing = TOKEN_PRICING.get(cid, TOKEN_PRICING["unknown"])
        cost_in = (c["total_prompt"] or 0) / 1000 * pricing["input"]
        cost_out = (c["total_completion"] or 0) / 1000 * pricing["output"]
        cost = cost_in + cost_out
        total_cost += cost
        lines.append(
            f"| {c['channel_name'] or cid} "
            f"| ¥{cost_in:.4f} | ¥{cost_out:.4f} | ¥{cost:.4f} |"
        )
    lines.append(f"\n**总费用估算: ¥{total_cost:.4f}**")
    if total_cost == 0:
        lines.append("\n> 所有通道均为内部/免费，无实际费用。如切换到付费 API，"
                     "修改 rag_admin.py 中的 TOKEN_PRICING 配置。")
    return "\n".join(lines)


def build_tab_token():
    with gr.Tab("Token 监控"):
        with gr.Row():
            days_input = gr.Number(label="统计天数", value=7, precision=0,
                                   minimum=1, maximum=90)
            refresh_btn = gr.Button("刷新", variant="primary", size="sm")

        overview_md = gr.Markdown()
        with gr.Row():
            with gr.Column():
                daily_md = gr.Markdown()
            with gr.Column():
                channel_md = gr.Markdown()
        cost_md = gr.Markdown()

        refresh_btn.click(
            fn=lambda d: (_format_token_overview(d), _format_token_daily(d),
                          _format_token_channel(d), _format_token_cost(d)),
            inputs=[days_input],
            outputs=[overview_md, daily_md, channel_md, cost_md],
        )

    return [overview_md, daily_md, channel_md, cost_md]


# ══════════════════════════════════════════════════════════════════════
#  Tab 8 — 文档上传管理
# ══════════════════════════════════════════════════════════════════════

UPLOAD_DIR = Path("/home/eric_jia/uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

_import_status = {"running": False, "log": "", "done": 0, "total": 0}


def _extract_pdf_text(pdf_path: str) -> str:
    """从 PDF 提取文本 — pymupdf4llm 优先, pymupdf 回退."""
    try:
        import pymupdf4llm
        return pymupdf4llm.to_markdown(pdf_path)
    except Exception:
        import fitz
        doc = fitz.open(pdf_path)
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text


def _chunk_text(text: str, filename: str, category: str, subcategory: str = "") -> list:
    """切分文本为带 metadata 的 chunks."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    import hashlib

    MAX_LEN = 100000
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=100,
        separators=["\n\n", "\n", "。", "；", " ", ""],
    )
    parts = splitter.split_text(text)
    src_hash = hashlib.md5(filename.encode()).hexdigest()
    return [{
        "id": f"{src_hash}_{i}",
        "text": part,
        "metadata": {
            "source": f"upload://{filename}",
            "filename": filename,
            "category": category,
            "subcategory": subcategory,
            "file_type": "pdf",
            "chunk_index": i,
            "total_chunks": len(parts),
        },
    } for i, part in enumerate(parts)]


def _import_single_file(filepath: Path, category: str, subcategory: str,
                        collection, log_fn) -> int:
    """导入单个文件, 返回新增 chunk 数."""
    fn = filepath.name
    ext = filepath.suffix.lower()

    if ext == ".json":
        # JSON 格式: [{text, metadata, id}, ...] 或 {chunks: [...]}
        import json
        data = json.loads(filepath.read_text("utf-8"))
        if isinstance(data, dict) and "chunks" in data:
            data = data["chunks"]
        if not isinstance(data, list):
            log_fn(f"  [跳过] JSON 格式不识别")
            return 0
        chunks = []
        for i, item in enumerate(data):
            text = item.get("text", "")
            if not text.strip():
                continue
            meta = item.get("metadata", {})
            meta.setdefault("filename", fn)
            meta.setdefault("category", category)
            if subcategory:
                meta.setdefault("subcategory", subcategory)
            meta.setdefault("file_type", "json")
            meta.setdefault("chunk_index", i)
            cid = item.get("id", f"upload_{fn}_{i}")
            chunks.append({"id": cid, "text": text, "metadata": meta})
        log_fn(f"  JSON 解析完成: {len(chunks)} chunks")

    elif ext == ".pdf":
        log_fn(f"  提取 PDF 文本...")
        text = _extract_pdf_text(str(filepath))
        if not text.strip():
            log_fn(f"  [跳过] PDF 无文本内容")
            return 0
        chunks = _chunk_text(text, fn, category, subcategory)
        log_fn(f"  PDF 切分完成: {len(chunks)} chunks")

    elif ext in (".txt", ".md"):
        text = filepath.read_text("utf-8")
        if not text.strip():
            log_fn(f"  [跳过] 文件为空")
            return 0
        chunks = _chunk_text(text, fn, category, subcategory)
        log_fn(f"  文本切分完成: {len(chunks)} chunks")

    else:
        log_fn(f"  [跳过] 不支持的文件格式: {ext}")
        return 0

    # 写入 ChromaDB
    BATCH = 256
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        collection.add(
            ids=[c["id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[c["metadata"] for c in batch],
        )
    # M3: 入库成功后使 BM25/实体索引失效，运行中的服务无需重启即可检索新内容
    invalidate_indexes()
    return len(chunks)


def run_upload_import(files, category, subcategory):
    """Gradio 回调 — 后台导入上传的文件."""
    if not files:
        return "请先上传文件"
    if not category.strip():
        return "请填写分类名称"

    _import_status["running"] = True
    _import_status["log"] = "启动导入...\n"
    _import_status["done"] = 0
    _import_status["total"] = len(files)

    def _run():
        try:
            from rag_core import get_collection
            coll = get_collection()
            before_count = coll.count()

            total_chunks = 0
            for f in files:
                fn = Path(f).name if hasattr(f, "name") else Path(str(f)).name
                # Gradio 上传的文件路径
                src = Path(f) if isinstance(f, str) else Path(f.name)
                _import_status["log"] += f"\n[{fn}]\n"

                n = _import_single_file(src, category.strip(), subcategory.strip(),
                                        coll, lambda msg: _import_status["log"].__setitem__(
                                            slice(None), _import_status["log"] + msg + "\n"))
                total_chunks += n
                _import_status["done"] += 1
                _import_status["log"] += f"  完成: {n} chunks\n"

            after_count = coll.count()
            _import_status["log"] += (
                f"\n=== 全部导入完成 ===\n"
                f"文件数: {len(files)}, 新增 chunks: {total_chunks}\n"
                f"向量库: {before_count} → {after_count}\n"
            )
        except Exception as e:
            _import_status["log"] += f"\n导入出错: {e}\n"
        finally:
            _import_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return f"已在后台启动导入 ({len(files)} 个文件)，请稍候..."


def get_import_log():
    st = _import_status
    status = f"运行中 ({st['done']}/{st['total']})" if st["running"] else "空闲"
    return f"**状态:** {status}\n\n```\n{st['log'][-3000:]}\n```"


def _list_uploaded_files():
    """列出 uploads 目录中的文件."""
    if not UPLOAD_DIR.exists():
        return "*上传目录不存在*"
    files = sorted(UPLOAD_DIR.iterdir())
    if not files:
        return "*暂无上传文件*"
    lines = [f"### 已上传文件 ({len(files)})\n"]
    for f in files:
        size = f.stat().st_size
        if size > 1024 * 1024:
            size_str = f"{size / 1024 / 1024:.1f} MB"
        elif size > 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size} B"
        lines.append(f"- **{f.name}** ({size_str})")
    return "\n".join(lines)


def build_tab_upload():
    with gr.Tab("文档上传"):
        gr.Markdown("上传 JSON/PDF/TXT/MD 文件到知识库。支持批量上传。")

        with gr.Row():
            with gr.Column(scale=3):
                file_upload = gr.File(
                    label="选择文件",
                    file_count="multiple",
                    file_types=[".json", ".pdf", ".txt", ".md"],
                )
            with gr.Column(scale=2):
                category = gr.Textbox(label="分类名称 *", placeholder="例: FANUC机器人")
                subcategory = gr.Textbox(label="子分类（可选）", placeholder="例: 操作说明书")

        with gr.Row():
            upload_btn = gr.Button("开始导入", variant="primary")
            refresh_files_btn = gr.Button("刷新文件列表", size="sm")

        upload_msg = gr.Markdown()
        import_log_md = gr.Markdown()
        uploaded_files_md = gr.Markdown()

        upload_btn.click(
            fn=run_upload_import,
            inputs=[file_upload, category, subcategory],
            outputs=[upload_msg],
        )
        refresh_files_btn.click(fn=_list_uploaded_files, outputs=[uploaded_files_md])

    return [upload_msg, import_log_md, uploaded_files_md]


# ══════════════════════════════════════════════════════════════════════
#  Tab 9 — 系统管理
# ══════════════════════════════════════════════════════════════════════

def refresh_channels():
    channel_mgr.check_all()
    return channel_mgr.get_status_markdown()


def check_services():
    services = [
        ("RAG API", 8002, "/health"),
        ("RAG Web UI", 7860, "/"),
        ("Ollama", 11434, "/"),
        ("管理面板", 7861, "/"),
    ]
    lines = ["| 服务 | 端口 | 状态 |", "|------|------|------|"]
    for name, port, _ in services:
        alive = _service_alive(port)
        st = _badge("运行中", "#22c55e") if alive else _badge("未运行", "#ef4444")
        lines.append(f"| {name} | {port} | {st} |")
    return "\n".join(lines)


def get_config_info():
    return f"""### 当前配置（只读）

| 配置项 | 值 |
|--------|-----|
| Mioffice API | `{MIOFFICE_API_BASE}` |
| Ollama | `{OLLAMA_BASE}` |
| ChromaDB | `/home/eric_jia/rag_chromadb` |
| 嵌入模型 | `BAAI/bge-base-zh-v1.5` |
| 向量集合 | `wiki_docs` |

修改配置请编辑 `/home/eric_jia/rag_core.py` 后重启服务。"""


def build_tab_system():
    with gr.Tab("系统管理"):
        with gr.Row():
            with gr.Column():
                gr.Markdown("### LLM 通道状态")
                channel_md = gr.Markdown()
                ch_btn = gr.Button("刷新通道检查", size="sm")
                ch_btn.click(fn=refresh_channels, outputs=[channel_md])
            with gr.Column():
                gr.Markdown("### 服务状态")
                svc_md = gr.Markdown()
                svc_btn = gr.Button("检测服务", size="sm")
                svc_btn.click(fn=check_services, outputs=[svc_md])

        config_md = gr.Markdown()
        cfg_btn = gr.Button("查看配置", size="sm")
        cfg_btn.click(fn=get_config_info, outputs=[config_md])

    return channel_md, svc_md


# ══════════════════════════════════════════════════════════════════════
#  App Assembly
# ══════════════════════════════════════════════════════════════════════

def build_app():
    with gr.Blocks(title="RAG 管理面板") as app:
        gr.Markdown("# RAG 项目管理面板")

        with gr.Tabs():
            dash_outputs = build_tab_dashboard()
            build_tab_chat()
            build_tab_compare()
            kb_overview_md = build_tab_kb()
            build_tab_selfcheck()
            sl_overview_md = build_tab_selflearning()
            log_overview_md = build_tab_query_log()
            token_outputs = build_tab_token()
            build_tab_upload()
            channel_md, svc_md = build_tab_system()

        app.load(fn=refresh_dashboard, outputs=dash_outputs)
        app.load(fn=kb_overview, outputs=[kb_overview_md])
        app.load(fn=lambda: channel_mgr.get_status_markdown(), outputs=[channel_md])
        app.load(fn=_sl_overview, outputs=[sl_overview_md])
        app.load(fn=check_services, outputs=[svc_md])
        # Token 监控自动加载
        app.load(fn=lambda: (_format_token_overview(7), _format_token_daily(7),
                             _format_token_channel(7), _format_token_cost(7)),
                 outputs=token_outputs)

    return app


def main():
    parser = argparse.ArgumentParser(description="RAG 管理面板")
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--share", action="store_true")
    parser.add_argument("--skip-health", action="store_true")
    args = parser.parse_args()

    print("加载向量库...")
    get_collection()

    if not args.skip_health:
        print("通道健康检查...")
        channel_mgr.check_all()

    print(f"启动管理面板: http://localhost:{args.port}")
    if args.share:
        print("⚠️ 警告: --share 已启用, Gradio 将创建公网穿透链接 (评审 M9: 请仅限可信会话使用)")
    app = build_app()
    # 评审 M9: 默认只绑 127.0.0.1; 需要局域网访问时显式设 RAG_ADMIN_HOST=0.0.0.0
    app.launch(
        server_name=os.environ.get("RAG_ADMIN_HOST", "127.0.0.1"),
        server_port=args.port,
        share=args.share,
        theme=gr.themes.Soft(),
    )


if __name__ == "__main__":
    main()
