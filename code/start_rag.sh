#!/bin/bash
# RAG 智能问答系统 — 一键启动脚本
# 启动 Ollama + RAG Web UI + RAG API (供微信机器人调用)

set -e

export OLLAMA_MODELS="/mnt/d/ollama/models"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export PATH="$HOME/.local/bin:$PATH"
export CUDA_VISIBLE_DEVICES=""

echo "=== RAG 智能问答系统启动 ==="

# 1. 启动 Ollama
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "[1/3] 启动 Ollama..."
    nohup ollama serve > /tmp/ollama.log 2>&1 &
    sleep 3
    echo "  Ollama PID: $(pgrep -f 'ollama serve')"
else
    echo "[1/3] Ollama 已在运行"
fi

# 2. 启动 RAG Web UI
if ! curl -s http://localhost:7860/ > /dev/null 2>&1; then
    echo "[2/3] 启动 RAG Web UI..."
    source /home/eric_jia/mkdocs-env/bin/activate
    PYTHONUNBUFFERED=1 nohup python3 /mnt/c/Users/Eric Jia/self-grow-wiki/rag_web.py --port 7860 > /tmp/rag_web.log 2>&1 &
    echo "  等待启动..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:7860/ > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    echo "  RAG Web UI PID: $(pgrep -f 'rag_web.py')"
else
    echo "[2/3] RAG Web UI 已在运行"
fi

# 3. 启动 RAG API (供 Windows 微信机器人调用)
if ! curl -s http://localhost:8002/health > /dev/null 2>&1; then
    echo "[3/4] 启动 RAG API..."
    source /home/eric_jia/mkdocs-env/bin/activate
    PYTHONUNBUFFERED=1 nohup python3 /mnt/c/Users/Eric Jia/self-grow-wiki/rag_api.py > /tmp/rag_api.log 2>&1 &
    echo "  等待启动..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:8002/health > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    echo "  RAG API PID: $(pgrep -f 'rag_api.py')"
else
    echo "[3/4] RAG API 已在运行"
fi

# 4. 启动管理面板
if ! curl -s http://localhost:7861/ > /dev/null 2>&1; then
    echo "[4/4] 启动管理面板..."
    source /home/eric_jia/mkdocs-env/bin/activate
    PYTHONUNBUFFERED=1 nohup python3 /mnt/c/Users/Eric Jia/self-grow-wiki/rag_admin.py --port 7861 --skip-health > /tmp/rag_admin.log 2>&1 &
    echo "  等待启动..."
    for i in $(seq 1 30); do
        if curl -s http://localhost:7861/ > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    echo "  管理面板 PID: $(pgrep -f 'rag_admin.py')"
else
    echo "[4/4] 管理面板已在运行"
fi

echo ""
echo "=== 服务状态 ==="
echo "  RAG Web UI:   http://localhost:7860"
echo "  管理面板:      http://localhost:7861"
echo "  Ollama API:   http://localhost:11434"
echo "  RAG API:      http://localhost:8002 (微信机器人接口)"
echo ""
echo "  三通道: MiMo-Flash (云) → MiMo-Pro (云) → Qwen2.5:3b (本地)"
echo ""
echo "  Windows 侧启动微信机器人: python Desktop\\wxauto_bot.py"
echo "  停止: pkill -f ollama; pkill -f rag_web; pkill -f rag_api; pkill -f rag_admin"
