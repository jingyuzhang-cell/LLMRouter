import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.score_code import program,score,third_party_imports

class CodeScoringTests(unittest.TestCase):
    def test_frozen_test_construction(self):
        source=dict(dataset='mbpp',ground_truth=json.dumps(['assert f(2)==4']))
        self.assertIn('assert f(2)==4',program(source,dict(answer='```python\ndef f(x): return x*2\n```')))
        human=dict(dataset='humaneval',ground_truth=json.dumps(dict(test='def check(f): assert f(2)==4',entry_point='f')))
        self.assertTrue(program(human,dict(answer='def f(x): return 2*x')).endswith('check(f)\n'))

    def test_infrastructure_is_not_quality_zero(self):
        source=dict(dataset='mbpp',ground_truth=json.dumps(['assert f(2)==4']))
        response=dict(status='ok',answer='def f(x): return 2*x')
        self.assertIsNone(score(source,response,executor=lambda _:dict(sandbox_ready=False,passed=False))['quality'])
        self.assertIsNone(score(source,response,executor=lambda _:dict(sandbox_ready=True,passed=False,error_type='ImportError'))['quality'])
        self.assertEqual(score(source,response,executor=lambda _:dict(sandbox_ready=True,passed=False,error_type='AssertionError'))['quality'],0)

    def test_third_party_deferred(self):
        source=dict(dataset='mbpp',ground_truth='[]')
        result=score(source,dict(status='ok',answer='import numpy\n'))
        self.assertEqual(result['evaluation_status'],'dependency_review_required')
        self.assertIsNone(result['quality'])
        self.assertEqual(third_party_imports('import math, random\n'),[])

if __name__=='__main__':unittest.main()
