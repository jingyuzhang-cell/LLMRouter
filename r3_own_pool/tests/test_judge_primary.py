import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2 import judge_full,judge_primary
from test_judge_full import fixture,client

class PrimaryJudgeTests(unittest.TestCase):
    def test_primary_not_component_sum(self):
        parsed=judge_primary.parse_grade('{"score":8,"correctness":6,"completeness":2,"clarity":2}')
        self.assertEqual(parsed['score'],8)
        self.assertFalse(parsed['components_consistent'])
        with self.assertRaises(ValueError):judge_primary.parse_grade('{"score":NaN}')
        with self.assertRaises(ValueError):judge_primary.parse_grade('{"score":true}')

    def test_migration_preserves_budgets_and_selects_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cohort,raw=fixture(root);bad_sum=client()
            bad_sum.chat.completions.create.return_value.choices[0].message.content='{"score":8,"correctness":6,"completeness":2,"clarity":2}'
            judge_full.run(cohort,raw,root/'old',bad_sum,10)
            old_bytes=(root/'old/ATTEMPTS.jsonl').read_bytes()
            amendment=judge_primary.migrate(root/'old',root/'new')
            self.assertEqual(amendment['consumed_calls'],3)
            self.assertEqual(amendment['new_primary_labels'],2)
            ok=client()
            result=judge_primary.run_with_history(cohort,raw,root/'new',ok,10)
            self.assertEqual(result['terminal_cells'],4)
            self.assertEqual(ok.chat.completions.create.call_count,2)
            attempts,terminal=judge_primary.replay(root/'new/ATTEMPTS.jsonl')
            self.assertLessEqual(max(attempts.values()),2)
            self.assertEqual(sum(attempts.values()),5)
            self.assertEqual((root/'old/ATTEMPTS.jsonl').read_bytes(),old_bytes)
            self.assertEqual(judge_primary.run_with_history(cohort,raw,root/'new',ok,10)['calls_this_run'],0)
            with (root/'old/ATTEMPTS.jsonl').open('a') as f:f.write('\n')
            with self.assertRaisesRegex(ValueError,'Historical attempts changed'):
                judge_primary.run_with_history(cohort,raw,root/'new',ok,10)

    def test_replay_never_picks_larger_later_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal.jsonl'
            rows=[dict(event='grade',key='x',quality=.4),dict(event='grade',key='x',quality=.9)]
            path.write_text('\n'.join(map(json.dumps,rows)))
            _,terminal=judge_primary.replay(path)
            self.assertEqual(terminal['x']['quality'],.4)

if __name__=='__main__':unittest.main()
