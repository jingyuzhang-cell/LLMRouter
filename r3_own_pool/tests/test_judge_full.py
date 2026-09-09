import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.judge_full import messages,parse_grade,run,replay
from router_v2.data import sha


def fixture(root):
    c=root/'cohort';c.mkdir();r=root/'raw';r.mkdir()
    rows=[dict(query_id=str(i),query='q'*9000+'{answer}'+str(i),dataset='arenahard') for i in range(3)]
    (c/'queries.jsonl').write_text('\n'.join(map(json.dumps,rows)))
    (c/'split.json').write_text(json.dumps(dict(train=['0'],validation=['1'],test=['2'])))
    (c/'MANIFEST.json').write_text(json.dumps(dict(query_sha256=sha(c/'queries.jsonl'),split_counts=dict(train=1,validation=1,test=1))))
    for slot in ('small','medium','large','reasoning'):
        (r/f'{slot}.jsonl').write_text('\n'.join(json.dumps(dict(query_id=str(i),status='ok',answer='x'*9000+slot)) for i in range(3)))
    return c,r


def client(valid=True):
    response=NS(choices=[NS(message=NS(content=json.dumps(dict(score=8,correctness=4,completeness=2,clarity=2)) if valid else 'broken'),finish_reason='stop')],usage=None,model='qwen-max')
    return NS(chat=NS(completions=NS(create=Mock(return_value=response))))

class JudgeTests(unittest.TestCase):
    def test_no_truncation_or_data_substitution(self):
        q='q'*9000+'{answer}';a='a'*10000
        text=messages(q,a)[1]['content']
        self.assertIn(json.dumps(q),text)
        self.assertIn(json.dumps(a),text)

    def test_strict_rubric(self):
        with self.assertRaises(ValueError):parse_grade('{"score": 12}')
        with self.assertRaises(ValueError):parse_grade(json.dumps(dict(score=8,correctness=6,completeness=2,clarity=2)))
        with self.assertRaises(ValueError):parse_grade(json.dumps(dict(score=True,correctness=1,completeness=0,clarity=0)))

    def test_resumption_train_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c,r=fixture(root);mock=client()
            first=run(c,r,root/'out',mock,2)
            self.assertEqual(first['calls_this_run'],2)
            second=run(c,r,root/'out',mock,10)
            self.assertEqual(second['calls_this_run'],2)
            self.assertEqual(second['terminal_cells'],4)
            self.assertEqual(run(c,r,root/'out',mock,10)['calls_this_run'],0)
            events=[json.loads(l) for l in (root/'out/ATTEMPTS.jsonl').read_text().split('\n') if l]
            self.assertEqual({e['query_id'] for e in events},{'0'})
            intents=[e for e in events if e['event']=='intent']
            self.assertTrue(all(e['answer_chars']>8000 for e in intents))

    def test_failed_judge_never_becomes_quality_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c,r=fixture(root);mock=client(False)
            result=run(c,r,root/'out',mock,10)
            self.assertEqual(result['phase'],'CIRCUIT_OPEN')
            self.assertEqual(result['calls_this_run'],3)
            attempts,terminal=replay(root/'out/ATTEMPTS.jsonl')
            self.assertEqual(len(terminal),0)
            self.assertLessEqual(max(attempts.values()),2)

if __name__=='__main__':unittest.main()
