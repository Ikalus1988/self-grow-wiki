#!/usr/bin/env python3
"""飞书 RAG Bot — WebSocket 接收群消息 → 调用 RAG API → 回复."""
import json, os, time, re, urllib.request, urllib.error, threading, queue

# ── 配置 ──
BOT_NAME = os.environ.get("FEISHU_BOT_NAME", "").upper()
_prefix = f"{BOT_NAME}_" if BOT_NAME else ""

def _load_env():
    """Load credentials from ~/.hermes/.env for flexible bot identity switching."""
    env = {}
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

_env = _load_env()

FEISHU_APP_ID = (
    os.environ.get(f"{_prefix}FEISHU_APP_ID")
    or os.environ.get("FEISHU_APP_ID")
    or _env.get(f"{_prefix}FEISHU_APP_ID")
    or _env.get("FEISHU_APP_ID")
)
FEISHU_APP_SECRET = (
    os.environ.get(f"{_prefix}FEISHU_APP_SECRET")
    or os.environ.get("FEISHU_APP_SECRET")
    or _env.get(f"{_prefix}FEISHU_APP_SECRET")
    or _env.get("FEISHU_APP_SECRET")
)
assert FEISHU_APP_ID and FEISHU_APP_SECRET, "缺少飞书凭证: 设置 FEISHU_APP_ID + FEISHU_APP_SECRET 或 {NAME}_FEISHU_APP_ID 格式"

RAG_API_URL = os.environ.get("RAG_API_URL", "http://localhost:8002/query")
WS_URL = "wss://open.feishu.cn/open-apis/event/v1/ws"
print(f"🤖 Bot: {BOT_NAME or 'default'} | App: {FEISHU_APP_ID[:8]}...")

# ── Token 管理 ──
_tenant_token = None
_token_expire = 0

def get_tenant_token():
    global _tenant_token, _token_expire
    if _tenant_token and time.time() < _token_expire - 60:
        return _tenant_token
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    if result.get("code") != 0:
        raise RuntimeError(f"Token失败: {result}")
    _tenant_token = result["tenant_access_token"]
    _token_expire = time.time() + result.get("expire", 7200)
    return _tenant_token

def feishu_get(path):
    token = get_tenant_token()
    url = f"https://open.feishu.cn{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def feishu_post(path, body):
    token = get_tenant_token()
    url = f"https://open.feishu.cn{path}"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def send_message(chat_id, text, msg_type="text"):
    """发送消息到飞书群."""
    content = json.dumps({"text": text}, ensure_ascii=False)
    body = {"receive_id": chat_id, "msg_type": msg_type, "content": content}
    try:
        resp = feishu_post("/open-apis/im/v1/messages?receive_id_type=chat_id", body)
        if resp.get("code") != 0:
            print(f"发送失败: {resp}")
        return resp
    except Exception as e:
        print(f"发送异常: {e}")

def query_rag(question):
    """调用本地 RAG API."""
    data = json.dumps({"query": question}).encode()
    req = urllib.request.Request(RAG_API_URL, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"answer": f"RAG 服务异常: {e}", "status": "error"}

def extract_question(text):
    """从飞书消息文本中提取问题（去除 @ 等）."""
    # 去除 @ 提及
    text = re.sub(r'@\S+', '', text).strip()
    return text

# ── WebSocket 事件处理 ──
import websocket

def on_message(ws, raw):
    try:
        event = json.loads(raw)
        msg_type = event.get("type")
    except:
        return

    if msg_type == "im.message.receive_v1":
        msg_data = event.get("event", {}).get("message", {})
        chat_id = msg_data.get("chat_id", "")
        content = json.loads(msg_data.get("content", "{}"))
        text = content.get("text", "")

        question = extract_question(text)
        if not question or len(question) < 2:
            return

        print(f"[RAG-Bot] 收到: {question} (chat={chat_id})")
        result = query_rag(question)
        answer = result.get("answer", "未找到相关内容")
        status = result.get("status", "")
        elapsed = result.get("elapsed", 0)

        # 限制长度
        if len(answer) > 2000:
            answer = answer[:1990] + "\n\n... (已截断)"

        suffix = f"\n\n⏱ {elapsed:.1f}s | {status}" if status else f"\n\n⏱ {elapsed:.1f}s"
        final = answer + suffix
        send_message(chat_id, final)

def on_error(ws, error):
    print(f"[RAG-Bot] WS Error: {error}")

def on_close(ws, code, msg):
    print(f"[RAG-Bot] WS 断开 (code={code}), 3s 后重连...")
    time.sleep(3)
    start_bot()

def on_open(ws):
    print("[RAG-Bot] 飞书 WebSocket 已连接，等待消息...")

def start_bot():
    token = get_tenant_token()
    ws_url = f"{WS_URL}?token={token}"
    ws = websocket.WebSocketApp(ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open)
    ws.run_forever(ping_interval=30, ping_timeout=10)

if __name__ == "__main__":
    print("[RAG-Bot] 启动飞书 RAG 机器人...")
    start_bot()
