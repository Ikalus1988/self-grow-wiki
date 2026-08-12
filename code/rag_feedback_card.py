#!/usr/bin/env python3
"""RAG 飞书反馈卡片 — 发送带 👍👎 按钮的交互卡片到飞书群.

用法:
  python3 rag_feedback_card.py --query-id 151 --query "SRVO-023 报警" --answer "..."
  python3 rag_feedback_card.py --query-id 151 --query "SRVO-023 报警"  # 无答案摘要
  python3 rag_feedback_card.py --test  # 发送测试卡片

依赖: 飞书应用凭证从 ~/.hermes/.env 读取
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def load_env():
    """从 ~/.hermes/.env 读取飞书凭证."""
    env_path = Path.home() / ".hermes" / ".env"
    env = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_tenant_token(app_id: str, app_secret: str, domain: str = "feishu") -> str:
    """获取 tenant_access_token."""
    base = "https://open.feishu.cn" if domain == "feishu" else "https://open.larksuite.com"
    url = f"{base}/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {result}")
    return result["tenant_access_token"]


def build_feedback_card(query_id: int, query: str, answer_summary: str = "") -> dict:
    """构建带 👍👎 按钮的飞书交互卡片."""
    # 截断过长的内容
    if len(query) > 200:
        query = query[:200] + "..."
    if answer_summary and len(answer_summary) > 500:
        answer_summary = answer_summary[:500] + "..."

    elements = []

    # 查询内容
    elements.append({
        "tag": "markdown",
        "content": f"**问题:** {query}",
    })

    # 答案摘要（可选）
    if answer_summary:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": f"**回答摘要:**\n{answer_summary}",
        })

    elements.append({"tag": "hr"})

    # 反馈按钮
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "👍 有用"},
                "type": "primary",
                "value": {
                    "hermes_rag_feedback": "good",
                    "query_id": query_id,
                    "query": query[:100],  # 截断避免 payload 过大
                },
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "👎 没用"},
                "type": "danger",
                "value": {
                    "hermes_rag_feedback": "bad",
                    "query_id": query_id,
                    "query": query[:100],
                },
            },
        ],
    })

    # 底部提示
    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text", "content": "反馈将帮助改进知识库质量"},
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "📚 RAG 知识库回答", "tag": "plain_text"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_resolved_card(query_id: int, feedback_type: str, query: str) -> dict:
    """构建反馈确认后的卡片（替换原卡片）."""
    emoji = "👍" if feedback_type == "good" else "👎"
    label = "有用" if feedback_type == "good" else "没用"
    color = "green" if feedback_type == "good" else "red"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"content": "📚 RAG 知识库回答", "tag": "plain_text"},
            "template": color,
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**问题:** {query}",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": f"**{emoji} 感谢反馈！** 已记录为「{label}」\n\n_反馈将用于优化知识库检索和回答质量_",
            },
        ],
    }


def send_card(token: str, chat_id: str, card: dict, domain: str = "feishu",
              reply_to: str = None) -> dict:
    """发送交互卡片到飞书群."""
    base = "https://open.feishu.cn" if domain == "feishu" else "https://open.larksuite.com"
    url = f"{base}/open-apis/im/v1/messages"

    # 构建请求体
    body = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    if reply_to:
        # 回复特定消息
        url = f"{base}/open-apis/im/v1/messages/{reply_to}/reply"
        body = {
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }

    data = json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
        },
    )

    # 确定 receive_id_type
    if not reply_to:
        if chat_id.startswith("ou_"):
            url += "?receive_id_type=open_id"
        elif chat_id.startswith("oc_"):
            url += "?receive_id_type=chat_id"
        else:
            url += "?receive_id_type=chat_id"
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {token}",
            },
        )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code}", "body": body}


def main():
    parser = argparse.ArgumentParser(description="发送 RAG 反馈卡片到飞书群")
    parser.add_argument("--query-id", type=int, help="RAG query_log 中的 ID")
    parser.add_argument("--query", type=str, default="", help="原始查询")
    parser.add_argument("--answer", type=str, default="", help="回答摘要（可选）")
    parser.add_argument("--chat-id", type=str,
                        default="oc_1bf03d465a785da56ae541a1ce5e77fa",
                        help="目标飞书群 ID")
    parser.add_argument("--reply-to", type=str, help="回复的消息 ID（可选）")
    parser.add_argument("--test", action="store_true", help="发送测试卡片")
    parser.add_argument("--json", action="store_true", help="仅输出卡片 JSON，不发送")
    args = parser.parse_args()

    # 加载凭证
    env = load_env()
    app_id = env.get("FEISHU_APP_ID")
    app_secret = env.get("FEISHU_APP_SECRET")
    domain = env.get("FEISHU_DOMAIN", "feishu")

    if not app_id or not app_secret:
        print("❌ 缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET", file=sys.stderr)
        sys.exit(1)

    # 测试模式
    if args.test:
        args.query_id = 0
        args.query = "测试问题：FANUC SRVO-023 报警如何处理？"
        args.answer = "SRVO-023 是停止时误差过大报警，可能原因包括..."

    if not args.query_id and not args.test:
        print("❌ 需要 --query-id 或 --test", file=sys.stderr)
        sys.exit(1)

    # 构建卡片
    card = build_feedback_card(args.query_id, args.query, args.answer)

    # 仅输出 JSON
    if args.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
        return

    # 发送
    print(f"📤 发送反馈卡片到 {args.chat_id}...")
    token = get_tenant_token(app_id, app_secret, domain)
    result = send_card(token, args.chat_id, card, domain, args.reply_to)

    if result.get("code") == 0:
        msg_id = result.get("data", {}).get("message_id", "?")
        print(f"✅ 卡片已发送: message_id={msg_id}")
        print(f"   等待用户点击 👍👎 按钮...")
    else:
        print(f"❌ 发送失败: {json.dumps(result, ensure_ascii=False)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
