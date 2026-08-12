---
type: Alarm Code
title: SRVO-062 BZAL — 脉冲编码器电池电压低
description: 电池电压低于基准值。通电下更换电池，否则丢失位置数据需重新 mastering。
source_manuals: [B-83584CM_06.PDF, B-83574CM_05.PDF]
related_alarms: [SRVO-075]
tags: [alarm, srvo, battery, BZAL]
timestamp: 2026-06-30T22:28:03.626555
---

# SRVO-062 BZAL — 脉冲编码器电池电压低

## 原因
脉冲编码器绝对位置备份电池电压低于基准值。

## 对策
1. 尽快在通电状态下更换电池
2. 未及时更换导致 SRVO-075 → 需零点标定

## 关联
- 更换电池 → 零点标定流程

---

---
## 🔍 原文验证 (2026-07-02)

**通过率**: 2/5 (40%)

**未通过项**:
- ❌ 电池电压低 — chunk中有'电压'但无'低于基准值'表述
- ❌ 通电状态更换 — chunk中为'请在接通电源时更换电池'（意思相同但措辞不同）
- ❌ 位置数据丢失 — 未直接出现

**修正方向**: 措辞微调即可通过（'通电状态'→'接通电源时'）

**状态**: ⚠️ needs-verification | 需对照PDF原文确认后改为 verified
