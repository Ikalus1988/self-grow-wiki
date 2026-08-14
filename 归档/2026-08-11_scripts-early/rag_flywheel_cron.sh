#!/bin/bash
# RAG 飞轮每日自检 cron job
# 用法: 添加到 crontab: 0 9 * * * /mnt/c/Users/Eric Jia/scripts/rag_flywheel_cron.sh

LOG="/mnt/d/MD/RAG知识库/flywheel_daily.log"
PY=/home/eric_jia/mkdocs-env/bin/python3
SCRIPT=/mnt/c/Users/Eric Jia/scripts/rag_flywheel_batch.py

echo "[$(date)] 飞轮开始..." >> $LOG
$PY $SCRIPT 200 >> $LOG 2>&1
echo "[$(date)] 飞轮完成" >> $LOG
