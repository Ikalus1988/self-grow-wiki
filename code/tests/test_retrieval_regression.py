"""检索召回回归测试 — 关键查询必须命中关键指纹 chunk（top-N 内）。

运行:  python3 -m pytest tests/test_retrieval_regression.py -v

依赖: 真实 ChromaDB (~198k chunks) + BM25 缓存 (~615MB)，首次冷启动 ~30s。
设计: 每个用例 = (查询, [关键指纹], 说明)。指纹用大小写不敏感子串匹配，
      任一指纹出现在 top-N 任一 chunk 即通过。这是手术 A/B/C 的回归网：
      任何排序/召回改动都必须先让本文件全绿。

2026-08-16 建立: 用例来源 = 330L 事件(3) + 负载推算事件(1) + 报警(2) +
  功能名(5) + 上位机(1) + 型号(1) + 话题(1)。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag_core  # noqa: E402

# chromadb 1.5.x RustBindingsAPI 单例 bug: 首调失败、二调成功 (330L 复盘 §7.1)
@pytest.fixture(scope="module")
def ready():
    coll = None
    for attempt in range(1, 4):
        try:
            coll = rag_core.get_collection()
            break
        except Exception:
            time.sleep(3)
    if coll is None:
        pytest.skip("ChromaDB 不可用")
    # 触发一次检索预热 BM25 索引
    rag_core.retrieve("M-900iB 330L 比 280L 慢多少", top_k=5)
    return True


def _hit(query, needles, top_k=10):
    res = rag_core.retrieve(query, top_k=top_k)
    texts = [c["text"] for c in res]
    for nd in needles:
        if not any(nd.lower() in t.lower() for t in texts):
            top = [t[:60].replace("\n", " ") for t in texts[:5]]
            return False, (nd, top)
    return True, None


CASES = [
    ("M-900iB 330L 比 280L 慢多少", ["动作速度"], "330L 事件: 型号对比含规格表"),
    ("M-900iB/330L 最大动作速度是多少", ["M-900iB/330L", "动作速度"], "330L 事件: 精确规格"),
    ("M-900iB/330L 规格", ["M-900iB/330L"], "330L 事件: 规格查询"),
    ("fanuc机器人负载推算报腕部受限报警如何处理", ["SRVO"], "负载推算事件: 报警处理召回"),
    ("SRVO-023 报警怎么处理", ["SRVO-023"], "报警代码: SRVO-023"),
    ("SRVO-066 报警", ["SRVO-066"], "报警代码: SRVO-066"),
    ("上位机读写机器人寄存器", ["Robot Interface"], "上位机: Robot Interface 强制召回"),
    ("PCIF 是什么", ["PC Interface"], "功能名: PCIF"),
    ("DeviceNet 连接", ["DeviceNet"], "功能名: DeviceNet"),
    ("RTCP 远程 TCP", ["RTCP"], "功能名: RTCP"),
    ("高惯量模式", ["高惯量"], "功能名: 高惯量"),
    ("物料搬运 MH 功能", ["物料搬运"], "功能名: 物料搬运"),
    ("R-2000iC 最大速度", ["R-2000iC"], "型号: R-2000iC"),
    ("电池更换 维护", ["电池"], "话题关键词: 电池"),
    # M-900iB 换油周期（静默退化案例 2026-08-20）: 答案=润滑脂更换 3年/11520h，
    # 在 B-83444CM/06、B-83684CM/07、B-83624CM/02 第 7.3 节。指纹验证"换油周期数值可召回"
    # （B-83624CM 第 2 位稳定命中 11520），另用 B-83444 直接查询验证手册可直达。
    ("M-900iB 换油周期", ["11520"], "M-900iB 换油: 润滑脂更换 3年/11520h(静默退化案例 2026-08-20)"),
    ("M-900iB 润滑脂多久换一次", ["11520"], "M-900iB 换油: 周期变体查询"),
]


@pytest.mark.parametrize("query,needles,note", CASES, ids=[c[2] for c in CASES])
def test_recall(ready, query, needles, note):
    ok, miss = _hit(query, needles)
    assert ok, f"[{note}] 查询 {query!r} 未命中指纹 {miss[0]}, top5={miss[1]}"
