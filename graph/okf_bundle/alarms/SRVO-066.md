---
type: Alarm Code
title: SRVO-066 CSAL — 脉冲编码器 ROM 异常
description: 脉冲编码器 ROM 校验和数据异常。更换电机或脉冲编码器，执行 mastering。
source_manuals: [B-83284EN-1_07_01.PDF, fanuc_system_r-j2.pdf]
related_alarms: [SRVO-068, SRVO-069, SRVO-070, SRVO-088]
tags: [alarm, srvo, pulse-coder, rom]
timestamp: 2026-06-30T22:28:03.626552
---

# SRVO-066 CSAL — 脉冲编码器 ROM 异常

## 原因
脉冲编码器 ROM 校验和数据异常。

## 对策
1. 更换电机或脉冲编码器，执行 mastering
2. 需重新上电
3. 若与 SRVO-068/069/070 同时发生，忽略本报警

## 关联
- SRVO-088 CSAL(追踪) 对策参阅本报警
- 脉冲编码器报警汇总: BZAL / CSAL / DTERR / CRCERR

## 来源
- B-83284EN-1_07_01.PDF
- fanuc_system_r-j2_user_manual.pdf

---

---
## 🔍 原文验证 (2026-07-02)

**通过率**: 1/5 (20%)

**未通过项**:
- ❌ 更换电机或脉冲编码器 — chunk 实际内容为 SRVO-063 RCAL
- ❌ mastering — 相关chunk未提及
- ❌ 需重新上电 — 未找到原文支持
- ❌ SRVO-088 CSAL — top-8 chunks无此关联

**修正方向**: 需从 web/knowledge 库补充 SRVO-066 全文后再验证

**状态**: ⚠️ needs-verification | 需对照PDF原文确认后改为 verified
