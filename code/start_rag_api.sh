#!/bin/bash
# RAG API 自启动脚本 — 防重复、可追踪、可 kill
# 用法:
#   ./start_rag_api.sh          # 启动
#   ./start_rag_api.sh kill     # 停止
#   ./start_rag_api.sh restart  # 重启
#   ./start_rag_api.sh status   # 查看状态

API_PORT=8002
PID_FILE="/tmp/rag_api.pid"
LOG_FILE="/tmp/rag_api.log"

start() {
    if curl -s http://localhost:${API_PORT}/health > /dev/null 2>&1; then
        echo "[OK] RAG API 已在运行 (pid=$(cat $PID_FILE 2>/dev/null))"
        return 0
    fi
    echo "[START] 启动 RAG API (port ${API_PORT})..."
    cd /mnt/c/Users/Eric Jia/self-grow-wiki || exit 1
    source /home/eric_jia/mkdocs-env/bin/activate 2>/dev/null
    PYTHONUNBUFFERED=1 nohup python3 /mnt/c/Users/Eric Jia/self-grow-wiki/rag_api.py > ${LOG_FILE} 2>&1 &
    PID=$!
    echo $PID > $PID_FILE
    echo "  PID: $PID, 日志: $LOG_FILE"
    for i in $(seq 1 15); do
        if curl -s http://localhost:${API_PORT}/health > /dev/null 2>&1; then
            echo "[OK] RAG API 就绪"
            return 0
        fi
        sleep 1
    done
    echo "[WARN] 启动超时，日志: $LOG_FILE"
    return 1
}

kill_proc() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat $PID_FILE)
        if kill -0 $PID 2>/dev/null; then
            echo "[KILL] 停止 RAG API (pid=$PID)"
            kill $PID 2>/dev/null; sleep 1; kill -9 $PID 2>/dev/null
        fi
        rm -f $PID_FILE
    else
        PIDS=$(pgrep -f "rag_api.py" 2>/dev/null)
        [ -n "$PIDS" ] && kill $PIDS 2>/dev/null && echo "[KILL] 停止 $PIDS"
    fi
    sleep 1
    curl -s http://localhost:${API_PORT}/health > /dev/null 2>&1 \
        && echo "[WARN] 端口未释放" || echo "[OK] 端口已释放"
}

case ${1:-start} in
    start) start ;;
    kill|stop) kill_proc ;;
    restart) kill_proc; sleep 1; start ;;
    status)
        if [ -f "$PID_FILE" ] && kill -0 $(cat $PID_FILE) 2>/dev/null; then
            echo "RAG API: 运行中 (pid=$(cat $PID_FILE))"
        elif curl -s http://localhost:${API_PORT}/health > /dev/null 2>&1; then
            echo "RAG API: 运行中 (无 pid 文件)"
        else
            echo "RAG API: 未运行"
        fi
        ;;
    *) echo "用法: $0 {start|kill|restart|status}" ;;
esac
