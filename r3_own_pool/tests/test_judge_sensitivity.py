import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from router_v2.audit_judge_sensitivity import component_quality, summarize

class SensitivityTests(unittest.TestCase):
    def row(self, slot, primary, correct, complete=0, clarity=0):
        return dict(query_id='q', slot=slot, quality=primary,
                    rubric=dict(correctness=correct, completeness=complete, clarity=clarity))

    def test_reversal_tie_and_best_set(self):
        rows = [self.row('small', .9, 2), self.row('medium', .8, 6),
                self.row('large', .8, 4), self.row('reasoning', .1, 1)]
        result = summarize(rows)['counts']
        self.assertEqual(result['comparable_same_query_pairs'], 6)
        self.assertEqual(result['strict_order_reversals'], 2)
        self.assertEqual(result['tie_status_changes'], 1)
        self.assertEqual(result['best_slot_set_changes'], 1)

    def test_invalid_components_are_not_zero(self):
        for value in (None, True, float('nan'), 7):
            self.assertIsNone(component_quality(self.row('small', .5, value)))
        report = summarize([self.row('small', .5, None)])
        self.assertIsNone(report['mean_absolute_label_difference'])
        self.assertEqual(report['counts']['unusable_components'], 1)

    def test_incomplete_queries_have_no_four_slot_claim(self):
        report = summarize([self.row('small', .5, 5), self.row('large', .5, 5)])
        self.assertEqual(report['counts']['tie_status_changes'], 0)
        self.assertEqual(report['counts'].get('complete_four_slot_queries', 0), 0)

if __name__ == '__main__': unittest.main()
