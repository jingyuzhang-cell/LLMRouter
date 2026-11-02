#!/usr/bin/env python3
"""保护集审计器 R1 合成测试（零调用；验证 0 / 1 / >=2 三级与四元组追溯）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import protection_set_audit as P

ARMS = P.ARMS
SLOTS = P.SLOTS


def make_records(tmp, overrides=None):
    """192 记录；默认全部保护槽正确。overrides: {(slot, arm, sc, rep): status}"""
    overrides = overrides or {}
    for arm in ARMS:
        for sc in ("S3", "S4", "S5"):
            for rep in range(1, 9):
                claims = []
                for slot in SLOTS:
                    st = overrides.get((slot, arm, sc, rep),
                                       "UNKNOWN_PRESERVED" if slot == "U2" else "CORRECT")
                    claims.append({"fact_id": slot, "status": st})
                rec = {"exec_id": f"{arm}|{sc}|r{rep}", "arm": arm,
                       "scenario": sc, "rep": rep,
                       "score": {"claim_results": claims}}
                (tmp / f"{arm}__{sc}__r{rep}.json").write_text(
                    json.dumps(rec, ensure_ascii=False), "utf-8")


class ProtectionAuditR1(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prot_"))

    def test_00_counts_1152_and_pass(self):
        make_records(self.tmp)
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["slot_runs_enumerated"], 1152)
        self.assertEqual(r["n_regressions"], 0)
        self.assertEqual(r["verdict"], "PASS")
        self.assertEqual(r["by_scenario"], {})

    def test_01_one_regression(self):
        make_records(self.tmp, {("B1", "Static", "S3", 1): "INCORRECT"})
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["n_regressions"], 1)
        self.assertEqual(r["verdict"], "PASS WITH REGRESSION")
        self.assertEqual(r["regressions"][0],
                         {"slot": "B1", "arm": "Static", "scenario": "S3",
                          "rep": 1, "exec_id": "Static|S3|r1"})

    def test_02_two_regressions_fail(self):
        make_records(self.tmp, {("B1", "Static", "S3", 1): "INCORRECT",
                                ("E1", "Simple-Dynamic", "S5", 8): "INCORRECT"})
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["n_regressions"], 2)
        self.assertEqual(r["verdict"], "FAIL")
        four = {(x["slot"], x["arm"], x["scenario"], x["rep"]) for x in r["regressions"]}
        self.assertIn(("B1", "Static", "S3", 1), four)
        self.assertIn(("E1", "Simple-Dynamic", "S5", 8), four)

    def test_03_u2_assertion_is_regression(self):
        make_records(self.tmp, {("U2", "π-only", "S4", 3): "UNKNOWN_ASSERTED"})
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["n_regressions"], 1)
        self.assertEqual(r["regressions"][0]["slot"], "U2")

    def test_04_f1_f2_reference_arm_only(self):
        # Static 不在修复臂参考基线上 → 不计倒退
        make_records(self.tmp, {("F1", "Static", "S3", 1): "INCORRECT"})
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["n_regressions"], 0)
        # Proposed 在修复臂参考基线上 → 计倒退
        make_records(self.tmp, {("F1", "Proposed-Dynamic", "S3", 1): "INCORRECT"})
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["n_regressions"], 1)

    def test_05_no_offset_by_target_slots(self):
        # 目标槽（如 D_3）正确不进入保护集；保护槽错即计，不受其他槽影响
        make_records(self.tmp, {("B2", "R-only", "S4", 2): "INCORRECT"})
        r = P.audit(self.tmp, P.default_baseline())
        self.assertEqual(r["n_regressions"], 1)
        self.assertEqual(r["by_scenario"], {"S4": 1})


if __name__ == "__main__":
    unittest.main(verbosity=2)
