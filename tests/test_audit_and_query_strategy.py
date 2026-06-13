import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daily_audit
import rag_core


def _q(qid, level="L3", tag="T"):
    return {"id": qid, "level": level, "tag": tag, "query": qid, "expect": {}}


class AuditSamplingStrategyTest(unittest.TestCase):
    def test_sample_questions_avoids_recent_history_when_pool_available(self):
        bank = [_q(f"L2-{i:03d}", "L2", "A") for i in range(1, 5)] + [
            _q(f"L3-{i:03d}", "L3", f"T{i % 3}") for i in range(1, 12)
        ]
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "audit_reports"
            report_dir.mkdir()
            (report_dir / "audit_2026-05-26.json").write_text(
                json.dumps(
                    {
                        "date": "2026-05-26",
                        "results": [
                            {"qid": "L2-001"},
                            {"qid": "L2-002"},
                            {"qid": "L3-001"},
                            {"qid": "L3-002"},
                            {"qid": "L3-003"},
                            {"qid": "L3-004"},
                            {"qid": "L3-005"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with mock.patch.object(daily_audit, "_AUDIT_DIR", report_dir):
                sampled = daily_audit.sample_questions(bank, seed=7)

        sampled_ids = {q["id"] for q in sampled}
        self.assertEqual(len(sampled), 7)
        self.assertFalse(sampled_ids & {"L2-001", "L2-002", "L3-001", "L3-002", "L3-003", "L3-004", "L3-005"})

    def test_sample_questions_fills_to_sample_size_when_bank_is_l2_only(self):
        bank = [_q(f"L2-{i:03d}", "L2", f"T{i % 3}") for i in range(1, 11)]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(daily_audit, "_AUDIT_DIR", Path(td)):
                sampled = daily_audit.sample_questions(bank, seed=13)

        self.assertEqual(len(sampled), 7)
        self.assertEqual(len({q["id"] for q in sampled}), 7)

    def test_sample_questions_rotates_after_pool_exhausted(self):
        bank = [_q(f"L2-{i:03d}", "L2", "A") for i in range(1, 3)] + [
            _q(f"L3-{i:03d}", "L3", f"T{i % 2}") for i in range(1, 6)
        ]
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "audit_reports"
            report_dir.mkdir()
            (report_dir / "audit_2026-05-26.json").write_text(
                json.dumps({"date": "2026-05-26", "sampled_qids": [q["id"] for q in bank]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with mock.patch.object(daily_audit, "_AUDIT_DIR", report_dir):
                sampled = daily_audit.sample_questions(bank, seed=11)

        self.assertEqual(len(sampled), 7)
        self.assertEqual({q["id"] for q in sampled}, {q["id"] for q in bank})


class QueryStrategyTest(unittest.TestCase):
    def test_normalize_query_splits_fused_alarm_and_english_suffix(self):
        self.assertEqual(
            rag_core._normalize_query("FANUC机器人SRVO-228RIOfuseblown排查"),
            "FANUC机器人SRVO-228 RI/O fuse blown 排查",
        )

    def test_normalize_query_standardizes_field_bus_and_controller_names(self):
        self.assertEqual(
            rag_core._normalize_query("PRIO-323CCLinkCRC错误 R30iB控制柜"),
            "PRIO-323 CC-Link CRC 错误 R-30iB 控制柜",
        )

    def test_augment_query_adds_badcase_domain_anchors(self):
        expanded = rag_core._augment_query("FANUC机器人伺服放大器和电源模块功能")
        self.assertIn("伺服放大器 主电源模块 直流母线", expanded)

        tracking = rag_core._augment_query("发那科机器人圆弧跟踪怎么设置")
        self.assertIn("Through-Arc Tracking", tracking)


if __name__ == "__main__":
    unittest.main()
