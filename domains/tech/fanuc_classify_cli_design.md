# FANUC 文件导入分类 CLI 设计文档
# 对应方案：十二、文件导入功能
# 最后更新：2026-04-11

---

## 目标

用户将 PDF 文件放入待导入目录，CLI 自动：
1. 读取文件摘要（前 3 页 / 前 100 行）
2. 生成预分类建议 + 关键词标签
3. 用户确认 / 调整分类
4. 输出带 metadata 的 JSON，供后续 embedding 入库

---

## 分类体系

### robot_brand（机器人品牌）

| 值 | 说明 |
|----|------|
| FANUC | FANUC 机器人 |
| KUKA | KUKA 机器人 |
| ABB | ABB 机器人 |
| 通用 | 多品牌通用文档 |
| 其他 | 特种机器人/非机器人 |

### doc_type（文档类型）

| 值 | 说明 |
|----|------|
| 编程手册 | KAREL/TP 编程指令、代码示例 |
| 故障诊断 | 报警代码、故障排查、維修 |
| 参数配置 | 系统参数、变量、配置步骤 |
| 维护保养 | 日常保养、点检、润滑 |
| 操作手册 | 操作规程、安全规范 |
| 设备调试 | 视觉/焊机/变位机/夹爪调试 |
| 通讯网络 | 以太网、UOP、ASI、DeviceNet |
| 选型手册 | 机型对比、技术规格 |
| 用户手册 | 基础操作入门 |

### equipment（附属设备）

| 值 | 说明 |
|----|------|
| 焊机 | 焊接设备（麦格米特/福尼斯等）|
| 视觉 | 相机/光源/视觉软件 |
| 变位机 | 二轴/三轴变位机 |
| 夹爪 | 气动/电动夹爪 |
| 传感器 | 力控/安全/距离传感器 |
| 传送带 | 输送系统 |
| 清枪剪丝 | 焊枪清理装置 |
| 水冷机 | 冷却系统 |
| 无 | 无附属设备 |

### tags（关键词标签，手动补充）

示例：`["IO配置", "PMC", "宏程序", "TP指令", "KAREL", "示教", "$变量", "CD38A", "$ENETMODE"]`

---

## CLI 使用方式

```bash
# 单文件
python classify.py input.pdf

# 批量（目录）
python classify.py ./待导入/

# 仅预览（不写入metadata）
python classify.py input.pdf --dry-run

# 指定分类（跳过AI预判）
python classify.py input.pdf --brand FANUC --type 故障诊断
```

---

## 执行流程

```
1. 读取文件摘要
   → PyMuPDF 提取前3页文本（或前100行）
   → 输出 file_summary（500字以内）

2. AI 预分类（调用 MiniMax API）
   → 构造 prompt：输入 file_summary + 分类体系
   → 输出 JSON：{robot_brand, doc_type, equipment, tags[], confidence}

3. 用户确认/调整
   → 打印预分类结果
   → 显示 file_summary 摘要
   → 用户可逐项确认或修改
   → 支持命令行交互输入

4. 输出 metadata JSON
   → 追加写入 manifest.json（增量记录）
   → 同时输出独立的 metadata 文件供 embedding 流程使用
```

---

## AI 预分类 Prompt

```
你是一个专业的工业机器人文档分类助手。根据以下文档摘要，判断其分类。

文档摘要：
{file_summary}

分类选项：
- robot_brand: FANUC | KUKA | ABB | 通用 | 其他
- doc_type: 编程手册 | 故障诊断 | 参数配置 | 维护保养 | 操作手册 | 设备调试 | 通讯网络 | 选型手册 | 用户手册
- equipment: 焊机 | 视觉 | 变位机 | 夹爪 | 传感器 | 传送带 | 清枪剪丝 | 水冷机 | 无

输出格式（仅返回JSON，不要其他内容）：
{
  "robot_brand": "...",
  "doc_type": "...",
  "equipment": "...",
  "tags": ["...", "..."],
  "confidence": 0.85,
  "reason": "简要说明分类依据"
}
```

---

## metadata 输出格式

```json
{
  "file_path": "E:/PDF/FANUC/弧焊包/arc_weld_setup.pdf",
  "file_hash": "a3f5e8d2c1b4...",
  "robot_brand": "FANUC",
  "doc_type": "设备调试",
  "equipment": "焊机",
  "tags": ["弧焊", "焊接参数", "焊枪", "清枪剪丝"],
  "file_summary": "本文档介绍FANUC机器人弧焊系统的配置流程...",
  "classified_at": "2026-04-11T19:00:00+08:00",
  "source": "user_import"
}
```

---

## 待确认事项

1. manifest.json 由谁维护（魔术师还是倒吊人）？
2. embedding 流程读取 manifest 还是独立 metadata 文件？
3. 批量导入时的并发限制（避免 API rate limit）？
