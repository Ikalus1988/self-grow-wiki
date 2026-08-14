"""M10/M11 判定逻辑测试: 题库分层对齐 + top_score 判定 + 空库文案兼容。

覆盖 commit c21fa83 中无测试的新逻辑:
- sample_questions 的 _BASIC_LEVELS 分层 (easy/l1/l2 → 基础层, 其余 → 提高层)
- call_rag 解析 API 返回的 top_score
- run_audit 的 score_ok (top_score >= min_score) 判定
- run_audit 空库文案兼容 ("未找到与" / "知识库中未找到")
- badcase 记录含 top_score 字段
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_audit


def _q(qid, level="easy", tag="T", min_score=0.6, must_contain=None):
    return {
        "id": qid,
        "level": level,
        "tag": tag,
        "query": qid,
        "expect": {
            "must_contain_any": must_contain or [],
            "min_top_score": min_score,
        },
    }


def _long_answer() -> str:
    """>= MIN_ANSWER_LEN 的合法答案（不含竞品品牌词）。"""
    return "FANUC机器人LR Mate 200iD伺服焊枪挠度补偿通过修改伺服参数实现。" * 12


class SampleQuestionsLevelMappingTest(unittest.TestCase):
    """M11: 题库分层 easy/medium 对齐。"""

    def test_easy_medium_split_maps_to_basic_advanced(self):
        bank = [_q(f"E{i:03d}", "easy", "基础") for i in range(1, 5)] + [
            _q(f"M{i:03d}", "medium", f"提高{i % 3}") for i in range(1, 9)
        ]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(daily_audit, "_AUDIT_DIR", Path(td)):
                sampled = daily_audit.sample_questions(bank, seed=3)
        levels = {q["level"] for q in sampled}
        self.assertLessEqual(levels, {"easy", "medium"})
        self.assertEqual(
            len([q for q in sampled if q["level"] == "medium"]),
            daily_audit.L3_COUNT,
        )
        self.assertEqual(
            len([q for q in sampled if q["level"] == "easy"]),
            daily_audit.L2_COUNT,
        )

    def test_l1_l2_count_as_basic_level(self):
        """l1/l2 同 easy 归基础层; hard 归提高层。"""
        bank = [_q(f"L1-{i:03d}", "l1", "A") for i in range(1, 4)] + [
            _q(f"L2-{i:03d}", "l2", "A") for i in range(1, 4)
        ] + [_q(f"H{i:03d}", "hard", f"T{i % 2}") for i in range(1, 7)]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(daily_audit, "_AUDIT_DIR", Path(td)):
                sampled = daily_audit.sample_questions(bank, seed=11)
        self.assertEqual(len(sampled), daily_audit.SAMPLE_SIZE)
        self.assertEqual(
            len([q for q in sampled if q["level"] in ("l1", "l2")]),
            daily_audit.L2_COUNT,
        )
        self.assertEqual(
            len([q for q in sampled if q["level"] == "hard"]),
            daily_audit.L3_COUNT,
        )

    def test_unknown_level_goes_to_advanced_pool(self):
        """未知 level 归提高层不丢题, 总量仍补足 7。"""
        bank = [_q(f"U{i:03d}", "", "其他") for i in range(1, 8)]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(daily_audit, "_AUDIT_DIR", Path(td)):
                sampled = daily_audit.sample_questions(bank, seed=5)
        self.assertEqual(len(sampled), daily_audit.SAMPLE_SIZE)


class CallRagTopScoreTest(unittest.TestCase):
    """M11: call_rag 解析 API 返回的 top_score。"""

    class _FakeResp:
        def __init__(self, data: bytes):
            self._data = data

        def read(self):
            return self._data

    def test_call_rag_parses_top_score(self):
        resp_json = json.dumps(
            {"answer": "x" * 200, "top_score": 0.83}
        ).encode("utf-8")
        with mock.patch.object(
            daily_audit.urllib.request,
            "urlopen",
            return_value=self._FakeResp(resp_json),
        ):
            result = daily_audit.call_rag("FANUC机器人测试", top_k=3)
        self.assertEqual(result["top_score"], 0.83)
        self.assertEqual(result.get("error", ""), "")
        self.assertIn("answer", result)

    def test_call_rag_missing_top_score_defaults_to_zero(self):
        resp_json = json.dumps({"answer": "y" * 200}).encode("utf-8")
        with mock.patch.object(
            daily_audit.urllib.request,
            "urlopen",
            return_value=self._FakeResp(resp_json),
        ):
            result = daily_audit.call_rag("FANUC机器人测试")
        self.assertEqual(result["top_score"], 0.0)

    def test_call_rag_error_returns_zero_score(self):
        with mock.patch.object(
            daily_audit.urllib.request,
            "urlopen",
            side_effect=RuntimeError("api down"),
        ):
            result = daily_audit.call_rag("FANUC机器人测试")
        self.assertEqual(result["top_score"], 0.0)
        self.assertIn("error", result)


class RunAuditJudgmentTest(unittest.TestCase):
    """M11: run_audit 的 score_ok / is_empty_kb 判定。"""

    def _run_audit(self, questions, respond):
        """respond: qid -> dict(含 answer/top_score)。用单题题库保证判定稳定。"""
        bank = list(questions)
        td = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, td, ignore_errors=True)

        def fake_call_rag(query_text, top_k=3):
            qid = query_text.replace("FANUC机器人", "", 1)
            return {
                "answer": respond[qid]["answer"],
                "elapsed_s": 0.1,
                "top_score": respond[qid].get("top_score", 0.0),
            }

        with mock.patch.object(daily_audit, "_AUDIT_DIR", td), mock.patch.object(
            daily_audit, "load_question_bank", return_value=bank
        ), mock.patch.object(
            daily_audit, "call_rag", side_effect=fake_call_rag
        ):
            return daily_audit.run_audit(quiet=True), td

    def test_top_score_below_min_score_fails(self):
        q = _q("Q001", "medium", "挠度", min_score=0.6)
        report, _ = self._run_audit(
            [q], {"Q001": {"answer": _long_answer(), "top_score": 0.31}}
        )
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["total"], 1)
        self.assertIn("检索分数不足", report["bad_queries"][0]["reason"])
        self.assertEqual(report["bad_queries"][0]["top_score"], 0.31)

    def test_top_score_meets_min_score_passes(self):
        q = _q("Q002", "medium", "挠度", min_score=0.6)
        report, _ = self._run_audit(
            [q], {"Q002": {"answer": _long_answer(), "top_score": 0.77}}
        )
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["bad_queries"], [])

    def test_empty_kb_new_wording_fails(self):
        q = _q("Q003", "medium", "挠度", min_score=0.6)
        report, _ = self._run_audit(
            [q],
            {"Q003": {"answer": "未找到与「FANUC机器人挠度」相关的文档", "top_score": 0.0}},
        )
        self.assertEqual(report["passed"], 0)
        self.assertIn("知识库未覆盖", report["bad_queries"][0]["reason"])

    def test_empty_kb_old_wording_fails(self):
        q = _q("Q004", "medium", "挠度", min_score=0.6)
        report, _ = self._run_audit(
            [q],
            {"Q004": {"answer": "知识库中未找到相关内容", "top_score": 0.0}},
        )
        self.assertEqual(report["passed"], 0)
        self.assertIn("知识库未覆盖", report["bad_queries"][0]["reason"])

    def test_badcase_pending_record_contains_top_score(self):
        q = _q("Q005", "medium", "挠度", min_score=0.6)
        report, td = self._run_audit(
            [q], {"Q005": {"answer": _long_answer(), "top_score": 0.12}}
        )
        self.assertEqual(report["passed"], 0)
        pending = td / "badcase_pending.jsonl"
        self.assertTrue(pending.exists())
        lines = [l for l in pending.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["query"], "Q005")
        self.assertEqual(entry["top_score"], 0.6)  # 记录 min_score 作为阈值参考
        self.assertEqual(entry["status"], "pending")


if __name__ == "__main__":
    unittest.main()
