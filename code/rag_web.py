#!/usr/bin/env python3
"""RAG智能问答 Web UI — 双模型通道 + 自动容灾.

通道架构:
  - 主通道 (MiMo):  xiaomi/mimo-v2-flash (小米推理模型, 通过内部API)
  - 备通道 (MiMo-Pro):  xiaomi/mimo-v2-pro   (小米推理模型, 通过mioffice.cn)
  - 本地通道:       qwen2.5:3b          (Ollama本地, 离线可用)

容灾策略:
  1. 主模型超时/报错 → 自动降级到备模型
  2. 备模型也失败 → 尝试本地 Ollama
  3. 全部失败 → 返回纯检索结果 + 错误提示
  4. 启动时健康检查，标记可用通道
"""

import argparse
import logging
import os

import gradio as gr

from rag_core import (
    get_collection, retrieve, format_sources,
    generate_with_failover, generate_report, channel_mgr, MODEL_CHANNELS,
    DEFAULT_TOP_K, DEFAULT_TEMPERATURE,
)

logger = logging.getLogger(__name__)


# ── Gradio UI ───────────────────────────────────────────────────────────

def process_query(query, history, top_k, temperature, channel_choice):
    """Main handler."""
    if not query.strip():
        yield history, "", "", channel_mgr.get_status_markdown(), ""
        return

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
    query_id = ""
    for token, st in generate_with_failover(query, chunks, preferred, temperature):
        answer += token
        status = st
        history[-1]["content"] = answer
        yield history, sources_md, "", channel_mgr.get_status_markdown(), ""

    # 自学习: 记录查询
    try:
        import kb_learning
        scores = [c["score"] for c in chunks] if chunks else []
        top_s = max(scores) if scores else 0.0
        query_id = kb_learning.log_query(
            query=query, top_score=top_s, chunks_count=len(chunks),
            channel=status.replace("通道: ", "") if status else "",
            answer_length=len(answer)
        )
    except Exception as e:
        logger.warning(f"查询日志记录失败: {e}")

    if status and "降级" not in status:
        history[-1]["content"] = answer + f"\n\n---\n*{status}*"
    yield history, sources_md, query_id, channel_mgr.get_status_markdown(), ""


def submit_feedback_up(query_id):
    """👍 有用"""
    if not query_id:
        return "请先提问"
    try:
        import kb_learning
        kb_learning.record_feedback(query_id, "up")
        return "✅ 感谢反馈！"
    except Exception as e:
        return f"反馈失败: {e}"


def submit_feedback_down(query_id, comment):
    """👎 没用"""
    if not query_id:
        return "请先提问"
    try:
        import kb_learning
        kb_learning.record_feedback(query_id, "down", comment or "")
        return "✅ 已记录，我们会改进"
    except Exception as e:
        return f"反馈失败: {e}"


def show_gaps():
    """显示知识缺口"""
    try:
        import kb_learning
        gaps = kb_learning.get_gaps(limit=20)
        if not gaps:
            return "暂无知识缺口记录 ✅\n\n当检索分数低于 0.75 时会自动标记为知识缺口。"
        lines = ["# 知识缺口 (低分查询)\n"]
        for g in gaps:
            lines.append(f"- [{g['datetime']}] `{g['query']}` (score={g['top_score']}, chunks={g['chunks_count']})")
        return "\n".join(lines)
    except Exception as e:
        return f"获取失败: {e}"


def show_learning_report():
    """显示自检报告"""
    try:
        import kb_learning
        return kb_learning.generate_report()
    except Exception as e:
        return f"生成失败: {e}"


def do_health_check():
    channel_mgr.check_all()
    return channel_mgr.get_status_markdown()


# ── 报告生成 UI handler ────────────────────────────────────────────

def generate_report_ui(topic, report_type, compare_target):
    """UI handler for report generation."""
    if not topic.strip():
        yield "请输入查询主题或分类名称。", [], ""
        return

    answer, sources, status, query_id = generate_report(
        topic=topic.strip(),
        report_type=report_type,
        compare_target=compare_target.strip() if compare_target.strip() else "",
        top_k=30,
    )
    yield answer, sources, status


def build_ui():
    with gr.Blocks(title="RAG智能问答 — 技术文档知识库") as app:

        gr.Markdown(
            "# RAG 智能问答 — 技术文档知识库\n"
            "> 三通道容灾 (MiMo-Flash + MiMo-Pro + Qwen本地) | "
            "自学习知识库 | 向量检索"
        )

        with gr.Tabs():
            # ── Tab 1: 问答 ──
            with gr.Tab("💬 智能问答"):
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(label="对话", height=500)
                        with gr.Row():
                            query_input = gr.Textbox(
                                label="输入问题",
                                placeholder="例: SRVO-023 报警代码怎么处理？M-900iA 电池更换步骤？",
                                lines=2,
                                scale=5,
                            )
                            send_btn = gr.Button("发送", variant="primary", scale=1)

                        # 反馈按钮
                        with gr.Row():
                            query_id_state = gr.State(value="")
                            feedback_up_btn = gr.Button("👍 有用", size="sm", scale=1)
                            feedback_down_btn = gr.Button("👎 没用", size="sm", scale=1)
                            feedback_comment = gr.Textbox(
                                label="补充说明(可选)", placeholder="哪里不准确？",
                                lines=1, scale=3, visible=False,
                            )
                            feedback_status = gr.Markdown("")

                        def toggle_comment(visible):
                            return gr.update(visible=not visible)

                        feedback_down_btn.click(
                            fn=toggle_comment,
                            inputs=[feedback_comment],
                            outputs=[feedback_comment],
                        )

                    with gr.Column(scale=2):
                        with gr.Accordion("模型通道", open=True):
                            channel_labels = ["自动 (智能切换)"] + [ch["label"] for ch in MODEL_CHANNELS]
                            channel_choice = gr.Radio(
                                channel_labels,
                                value="自动 (智能切换)",
                                label="通道选择",
                            )
                            gr.Markdown(
                                "*自动模式: MiMo-Flash → MiMo-Pro → Qwen本地，逐级降级*"
                            )

                        with gr.Accordion("检索参数", open=False):
                            top_k_slider = gr.Slider(
                                minimum=3, maximum=20, value=DEFAULT_TOP_K, step=1,
                                label="检索数量 (top_k)",
                            )
                            temp_slider = gr.Slider(
                                minimum=0.0, maximum=1.0, value=DEFAULT_TEMPERATURE, step=0.1,
                                label="生成温度",
                            )

                        sources_output = gr.Markdown(
                            value="*提交问题后显示引用来源*",
                            elem_classes=["source-box"],
                        )

                        with gr.Accordion("通道状态", open=True):
                            status_display = gr.Markdown(value=channel_mgr.get_status_markdown())
                            health_btn = gr.Button("刷新健康检查", size="sm")
                            health_btn.click(fn=do_health_check, outputs=[status_display])

                clear_btn = gr.Button("清空对话")
                clear_btn.click(
                    lambda: ([], "*提交问题后显示引用来源*", "", ""),
                    outputs=[chatbot, sources_output, query_input, query_id_state],
                )

                submit_args = dict(
                    fn=process_query,
                    inputs=[query_input, chatbot, top_k_slider, temp_slider, channel_choice],
                    outputs=[chatbot, sources_output, query_id_state, status_display, feedback_status],
                )
                send_btn.click(**submit_args)
                query_input.submit(**submit_args)

                feedback_up_btn.click(
                    fn=submit_feedback_up,
                    inputs=[query_id_state],
                    outputs=[feedback_status],
                )
                feedback_down_btn.click(
                    fn=submit_feedback_down,
                    inputs=[query_id_state, feedback_comment],
                    outputs=[feedback_status],
                )

            # ── Tab 2: 技术报告 ──
            with gr.Tab("📊 技术报告"):
                with gr.Row():
                    with gr.Column(scale=3):
                        report_type_radio = gr.Radio(
                            ["📝 主题报告", "⚖️ 对比报告", "📂 分类概览"],
                            value="📝 主题报告",
                            label="报告类型",
                        )
                        topic_input = gr.Textbox(
                            label="查询主题 / 对象A",
                            placeholder="例: SRVO报警码, M-900机器人维护, 零点标定方法",
                            lines=2,
                        )
                        compare_input = gr.Textbox(
                            label="对比对象B (仅对比报告)",
                            placeholder="例: R-2000iC (与对象A对比)",
                            lines=1,
                            visible=False,
                        )

                        def toggle_compare(report_type):
                            show = "对比" in report_type
                            return gr.update(visible=show)

                        report_type_radio.change(
                            fn=toggle_compare,
                            inputs=[report_type_radio],
                            outputs=[compare_input],
                        )

                        report_btn = gr.Button("生成报告", variant="primary")
                        report_output = gr.Markdown(
                            value="输入主题后点击「生成报告」",
                            elem_classes=["source-box"],
                            label="报告内容",
                        )
                        report_sources = gr.Markdown(
                            value="*报告来源*",
                        )
                        report_status = gr.Markdown("")

                    with gr.Column(scale=2):
                        gr.Markdown("""
                        ### 报告类型说明
                        - **主题报告**: 对特定主题的全面知识总结
                        - **对比报告**: 两个对象的维度对比
                        - **分类概览**: 整个分类的知识覆盖评估

                        报告会检索 30 个相关文档片段，
                        由 LLM 综合生成结构化报告。
                        """)

                        with gr.Accordion("通道状态", open=True):
                            report_channel_status = gr.Markdown(
                                value=channel_mgr.get_status_markdown()
                            )

                        with gr.Accordion("最近报告", open=False):
                            gr.Markdown("报告历史（TODO）")

                report_btn.click(
                    fn=generate_report_ui,
                    inputs=[topic_input, report_type_radio, compare_input],
                    outputs=[report_output, report_sources, report_status],
                )

            # ── Tab 3: 自学习 ──
            with gr.Tab("🧠 自学习"):
                gr.Markdown("## 知识库自学习面板")
                gr.Markdown("系统自动记录每次查询，检测知识缺口，沉淀高质量问答。")

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 知识缺口")
                        gr.Markdown("*检索分数 < 0.75 的查询自动标记为知识缺口*")
                        gaps_btn = gr.Button("刷新缺口列表", size="sm")
                        gaps_display = gr.Markdown("点击刷新查看")
                        gaps_btn.click(fn=show_gaps, outputs=[gaps_display])

                    with gr.Column():
                        gr.Markdown("### 自检报告")
                        gr.Markdown("*包含统计、满意度、FAQ沉淀等*")
                        report_btn = gr.Button("生成报告", size="sm", variant="primary")
                        report_display = gr.Markdown("点击生成查看")
                        report_btn.click(fn=show_learning_report, outputs=[report_display])

    return app


# ── Main ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAG智能问答 Web UI (三通道容灾)")
    parser.add_argument("--port", type=int, default=7860, help="Web端口")
    parser.add_argument("--share", action="store_true", help="创建公网链接")
    parser.add_argument("--skip-health", action="store_true", help="跳过启动健康检查")
    args = parser.parse_args()

    print("正在加载向量库...")
    get_collection()

    if not args.skip_health:
        print("\n通道健康检查:")
        channel_mgr.check_all()

    print(f"\n启动 Web UI: http://localhost:{args.port}")
    if args.share:
        print("⚠️ 警告: --share 已启用, Gradio 将创建公网穿透链接 (评审 M9: 请仅限可信会话使用)")
    app = build_ui()
    # 评审 M9: 默认只绑 127.0.0.1; 需要局域网访问时显式设 RAG_WEB_HOST=0.0.0.0
    app.launch(
        server_name=os.environ.get("RAG_WEB_HOST", "127.0.0.1"),
        server_port=args.port,
        share=args.share,
        theme=gr.themes.Soft(),
        css=".source-box {max-height: 400px; overflow-y: auto;}",
    )


if __name__ == "__main__":
    main()
