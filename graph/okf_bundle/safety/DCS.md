---
type: Safety Function
title: DCS — Dual Check Safety
tags: [safety, dcs]
timestamp: 2026-07-02
---

# DCS — 虚拟安全领域

- 无需物理围栏, 虚拟区域+速度限制
- 密码保护参数修改
- 违反后需特定恢复操作

| 功能 | 类型 | 触发 | 恢复 |
|------|------|------|------|
| FENCE | 物理 | 围栏门 | 关门+RESET |
| EAS | 物理 | 外部设备 | 设备复位 |
| DCS | 虚拟 | 位置/速度 | 特定操作 |
| E-Stop | 物理 | 按钮 | 释放+RESET |

---
## 🔍 原文验证 (2026-07-02)

**通过率**: 1/4 (25%)

**未通过项**:
- ❌ 虚拟安全区域 — chunk讨论的是机器人安全设置，未提DCS
- ❌ 密码保护 — 未找到
- ❌ 速度检查 — 未找到

**修正方向**: DCS 相关内容可能在其他手册(B-83184)中，当前chunk未覆盖

**状态**: ⚠️ needs-verification | 需对照PDF原文确认后改为 verified
