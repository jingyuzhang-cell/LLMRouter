import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.data import sha
from router_v2.score_available import run,score


class ScoringTests(unittest.TestCase):
    def test_math_and_choices(self):
        self.assertEqual(score(dict(dataset='gsm8k',ground_truth='42'),dict(status='ok',answer='#### 42'))['quality'],1)
        self.assertEqual(score(dict(dataset='mmlupro',ground_truth='B'),dict(status='ok',answer='Answer: A'))['quality'],0)

    def test_failure_and_truncation_not_dropped(self):
        source=dict(dataset='gsm8k',ground_truth='42')
        missing=score(source,dict(status='failed',answer=None))
        self.assertEqual(missing['quality'],0)
        self.assertEqual(missing['evaluation_status'],'generation_failure')
        self.assertEqual(score(source,dict(status='truncated',answer='#### 42'))['quality'],1)
        self.assertEqual(score(source,dict(status='ok',answer='no number'))['evaluation_status'],'answer_parse_failed')

    def test_code_is_never_executed(self):
        self.assertIsNone(score(dict(dataset='mbpp'),dict(status='ok',answer="raise RuntimeError('must not execute')")))

    def test_cache_binding_and_test_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cohort=root/'cohort';cohort.mkdir();raw=root/'raw';raw.mkdir()
            rows=[dict(query_id=str(i),query=f'question{i}',dataset='gsm8k',ground_truth='42') for i in range(3)]
            (cohort/'queries.jsonl').write_text('\n'.join(map(json.dumps,rows)))
            split=dict(train=['0'],validation=['1'],test=['2'])
            (cohort/'split.json').write_text(json.dumps(split))
            (cohort/'MANIFEST.json').write_text(json.dumps(dict(query_sha256=sha(cohort/'queries.jsonl'),split_counts={k:1 for k in split})))
            path=raw/'small.jsonl'
            path.write_text(json.dumps(dict(query_id='0',status='ok',answer='#### 42'))+'\n'+json.dumps(dict(query_id='2',status='ok',answer='#### 42'))+'\n')
            first=run(cohort,raw,root/'out')
            self.assertEqual(first['new_records'],1)
            self.assertEqual(run(cohort,raw,root/'out')['new_records'],0)
            self.assertEqual(first['counts']['missing_response'],3)
            cached=[json.loads(l) for l in (root/'out/SCORES.jsonl').read_text().split('\n') if l]
            self.assertEqual([r['query_id'] for r in cached],['0'])
            path.write_text(json.dumps(dict(query_id='0',status='ok',answer='#### 43'))+'\n')
            self.assertEqual(run(cohort,raw,root/'out')['new_records'],1)
            with self.assertRaisesRegex(ValueError,'Unknown partition'):
                run(cohort,raw,root/'forbidden','bogus')
            # Test partition is scorable only as the operator-authorized sealed run (2026-09-09).
            path.write_text(json.dumps(dict(query_id='2',status='ok',answer='#### 42'))+'\n')
            sealed=run(cohort,raw,root/'sealed','test')
            self.assertEqual([json.loads(l)['query_id'] for l in (root/'sealed/SCORES.jsonl').read_text().split('\n') if l],['2'])
            self.assertEqual(sealed['partition'],'test')
            protocol=root/'out/PROTOCOL.json'
            protocol.write_text('{}')
            with self.assertRaisesRegex(ValueError,'protocol changed'):
                run(cohort,raw,root/'out')

if __name__=='__main__':unittest.main()
