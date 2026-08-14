"""MCP 标准化 — @tool 装饰器 + 自动 schema"""
import json, inspect, sys, os
sys.path.insert(0, os.path.dirname(__file__))

_tools = {}

def tool(name, desc, schema=None):
    def dec(fn):
        s = schema or {"type":"object","properties":{"query":{"type":"string","description":desc}},"required":["query"]}
        _tools[name] = {"name":name,"description":desc,"inputSchema":s,"fn":fn}
        return fn
    return dec

def list_tools(): return [{"name":t["name"],"description":t["description"],"inputSchema":t["inputSchema"]} for t in _tools.values()]

def call_tool(name, args):
    if name not in _tools: return json.dumps({"error":"unknown"})
    return _tools[name]["fn"](**args)

@tool("rag_search", "搜索FANUC知识库(200K+文档)")
def rag_search(query): 
    from retriever import get_retriever
    r = get_retriever()
    chunks = r.retrieve(query, 5)
    if not chunks: return "知识库未覆盖"
    return "\n".join(f"[{c.get('source','?')}] {c.get('text','')[:300]}" for c in chunks[:3])

@tool("rag_answer", "搜索+LLM生成完整回答", {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]})
def rag_answer(query):
    from retriever import get_retriever
    r = get_retriever()
    chunks = r.retrieve(query, 5)
    if not chunks: return "知识库未覆盖"
    return "\n\n".join(f"[{c['source']}] {c['text'][:400]}" for c in chunks[:3])

@tool("flywheel_smoke", "5条核心smoke测试")
def flywheel_smoke(query=""):
    from retriever import get_retriever
    r = get_retriever()
    tests = [("SRVO-066","SRVO-066处理"),("TCP","TCP/IP配置"),("阿西莫夫","阿西莫夫"),("变量","物料搬运阀 VR"),("高惯量","高惯量模式")]
    lines = []
    for n,q in tests:
        m = set(c.get('method','') for c in r.retrieve(q,3))
        lines.append(f"{'✅' if 'entity-exact' in m else '⚠️'} {n}: {m}")
    return "\n".join(lines)

def handle(req):
    mid = req.get("id"); m = req.get("method","")
    if m=="initialize": return {"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"rag-mcp","version":"4.0"}}}
    if m=="tools/list": return {"jsonrpc":"2.0","id":mid,"result":{"tools":list_tools()}}
    if m=="tools/call":
        n = req["params"]["name"]; a = req["params"].get("arguments",{})
        return {"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":call_tool(n,a)}]}}
    return {"jsonrpc":"2.0","id":mid,"error":{"code":-32601}}
