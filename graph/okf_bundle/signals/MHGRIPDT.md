---
type: Variable Register File
title: MHGRIPDT.VR — Material Handling Gripper Parameter Data
description: FANUC 物料搬运抓手参数配置文件，17个字段定义抓手完整配置，含I/O映射和参数设定
source_file: mhgripdt.vr (2,278 bytes)
controller: FANUC V9.4.0468
application: FAP V2.0.8
backup_date: 2026-05-24
tags: [vr, material-handling, gripper, io-mapping, signal]
timestamp: 2026-07-01T00:27:09.603089
---

# MHGRIPDT.VR — 物料搬运抓手参数数据

## 文件格式

- Magic Header: `FE EF` (FANUC VR 专用)
- 版本: `0x0001`, 大端序
- 压缩: 未压缩 10,646 bytes, 压缩比 ~4.7:1
- 变量组名: **MHGRIPDT** (MH Gripper Data)

## 字段结构

| 身份 | I/O 映射 | 参数 |
|------|---------|------|
| ID | CLAMP_OPEN | _DELAY (延时) |
| NAME | CLAMP_CLOSE | C_TIMEOUT (超时) |
| MADE | VAC_FEEDBA | BLOWOFF (吹气) |
| | VSENSOR | TGL_GRP (切换组) |
| | VALVE_TOA | IGNOREFBB (忽略反馈) |

- 检测字段: PART_PRS, _CHK, _PRES, REL

## I/O 信号映射 (从二进制偏移提取)

| 偏移 | 值 | 可能用途 |
|------|-----|---------|
| 0x034B | 34 | DI/DO |
| 0x043F | 41 | DI/DO |
| 0x054F | 11 | DI/DO |
| 0x05E1 | 200 | DI/DO |
| 0x05E4 | 7 | DI/DO |
| 0x05E6 | 28 | DI/DO |
| 0x066A | 56 | DI/DO |
| 0x0796 | 12 | DI/DO |

## 参数数值

| 偏移 | 值 | 含义 |
|------|-----|------|
| 0x07D5 | 30.02s | 超时 |
| 0x07DD | 29.94s | 超时 |
| 0x083D | 17.02 | 压力 (PSI/bar) |
| 0x0845 | 54.62 | 压力 |
| 0x084D | 53.37 | 压力 |
| 0x0304 | 15.17 | 位置/距离 |

## MH .vr 文件家族

| 文件 | 大小 | 功能 |
|------|------|------|
| mhgripdt.vr | 2,278B | 抓手参数 |
| mhadvrcy.vr | 370B | 高级回收 |
| mhgrprtn.vr | 1,026B | 抓手保护 |
| mhmnlcfrm.vr | 93B | 手动确认 |
| mhsrchon.vr | 88B | 搜索功能 |

## 跨机器人一致性

- **结构**: 同版本控制器完全统一 (V9.4.0468 + FAP V2.0.8)
- **数据**: I/O 地址和参数值因机器人接线和工艺而异
- **解析**: 无开源工具; 可通过 Roboguide / 示教器 Variable Editor / KAREL WRITE 导出

---
*飞轮 F01/F02 缺口补充 | 来源: mhgripdt.vr 逆向分析 2026-06-30*

---
## 🔍 原文验证 (2026-07-02)

**通过率**: 2/5 (40%)

**未通过项**:
- ❌ 变量组名 — 未找到
- ❌ CLAMP_OPEN/CLAMP_CLOSE — 这些来自VR文件二进制分析，不在RAG向量库中

**修正方向**: MHGRIPDT 信息来自单独的VR文件逆向分析(非chunk)，标注来源即可

**状态**: ⚠️ needs-verification | 需对照PDF原文确认后改为 verified
