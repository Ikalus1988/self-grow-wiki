# RAG 飞轮自检工作流

> 创建时间: 2026-06-29
> 最后更新: 2026-06-30 (v1.1 — 变量/IO调优 + expand_query)
> 触发词: "飞轮" (Feishu/Hermes CLI 中发送即启动)
> 脚本路径: `/mnt/c/Users/Eric Jia/scripts/rag_flywheel.py`

---

## 触发方式

| 方式 | 命令 |
|------|------|
| 飞书 Bot | 发送 `飞轮` 或 `飞轮测试` |
| Hermes CLI | `飞轮` |
| 手动 | `python3 /mnt/c/Users/Eric Jia/scripts/rag_flywheel.py` |
| 详细模式 | `飞轮详情` 或 `python3 rag_flywheel.py --detail` |

## 工作流

1. 收到 "飞轮" 触发词
2. 运行 `rag_flywheel_eval.py`（30 条预定义查询）
3. 对每条查询评估：速度 / 来源引用 / 召回精度 / 相关性 / 源文件匹配
4. 生成飞书格式评估卡片
5. 回复到飞书群

## 评估维度 (7项)

| 维度 | 说明 | 本次通过率 |
|------|------|-----------|
| speed | 检索速度 < 20s | 97% (29/30) |
| has_sources | 是否附带引用源 | 100% (30/30) |
| recall | 预期关键词命中率 | 90% (27/30) |
| relevance | top1 相关性 score > 0.3 | 100% (30/30) |
| source_match | 来源合理性 | 100% (19/19 applicable) |

## 30条测试查询分类

| 分类 | 数量 | 通过率 | 说明 |
|------|------|--------|------|
| 报警代码 | 12 | 92% | SRVO-001~SRVO-214 |
| 操作流程 | 6 | 100% | 零点标定/电池更换/坐标系等 |
| 跨文档归纳 | 5 | 60% | 安全功能/通信协议/脉冲编码器汇总 |
| 参数设定 | 4 | 100% | 负载/焊接/速度倍率/高惯量 |
| 边界情况 | 3 | 67% | 非FANUC/不存在报警/无关话题 |

## 基线数据 (2026-06-29)

- 向量库: wiki_docs / 200,835 documents
- 嵌入模型: BGE-base-zh-v1.5 (768-dim)
- 总通过率: **86.7%** (26/30)
- 平均速度: 2.8s (冷启动首次 ~35s)
- 失败项: 4 条 (1条速度/3条召回)

## 待改进项

1. **跨文档归纳召回** (C01/C03): 安全功能对比、通信协议对比需补充专题文档
2. **冷启动优化**: 首次查询 35s → 可考虑服务常驻预热
3. **降级策略**: KUKA/非FANUC 查询需明确降级回答模板
4. **LLM 生成质量**: 当前仅评估检索质量，需增加 LLM 答案的准确性和修剪质量评估
5. **变量/IO 概念混淆** (F01/F02, v1.1新增): `expand_query`已生效(同义词表+8条)，但MHGRIPDT/MHMENU VR文件未入库，且检索仍返回报警手册而非material handling文档

## v1.1 飞轮调优 (2026-06-30)

### 变更
- 新增 **F类"飞轮调优"** 测试用例 (F01, F02)
- `synonyms.json` 新增 8 条变量/VR/IO 相关同义词映射
- 评估框架新增 `expand` 维度（验证 expand_query 是否触发+命中）
- 总测试查询: 30 → 32 条

### F01: 变量扩展检索
```
查询: "物料搬运阀的变量配置 MHGRIPDT MHMENU VR"
扩展后: +VR Variable Register 系统变量 寄存器 $ KAREL变量 ...
结果: VR✅ 变量✅ | MHGRIPDT❌ MHMENU❌ (VR文件未入库)
```

### F02: 变量IO概念区分
```
查询: "物料搬运阀输入信号DI配置和变量VR有什么区别"
扩展后: +VR Variable Register ... DI Digital Input I/O信号 ...
结果: DI✅ VR✅ 变量✅ | 信号❌ (英文signal未匹配中文"信号")
```

### 待入库
- `MHGRIPDT.VR` / `MHMENU.VR` 物料搬运变量文件

## 文件清单

| 文件 | 用途 |
|------|------|
| `scripts/rag_flywheel.py` | 飞轮入口（飞书格式报告） |
| `scripts/rag_flywheel_eval.py` | 评估核心（32条查询+8维评分） |
| `memory/rag-flywheel.md` | 本文档（记忆索引） |
| `self-grow-wiki/synonyms.json` | 同义词表（56条，含变量/VR映射） |
