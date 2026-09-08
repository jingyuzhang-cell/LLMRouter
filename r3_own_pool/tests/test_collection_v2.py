import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import tempfile
import unittest
R=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(R/'collect'))
import storage
import runner
from models import clients

class CollectionTests(unittest.TestCase):
    def test_unicode_line_separator_inside_answer(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"raw.jsonl"
            answer="first"+chr(0x2028)+"second"
            p.write_text(json.dumps(dict(query_id="x",status="ok",answer=answer),ensure_ascii=False)+"\n")
            self.assertEqual(storage.canonical_rows(p)["x"]["answer"],answer)

    def test_failed_retry_preserves_first_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'raw.jsonl'
            rows=[dict(query_id='x',status='failed'),dict(query_id='x',status='ok',answer='kept'),dict(query_id='x',status='failed')]
            p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            self.assertEqual(storage.canonical_rows(p)['x']['answer'],'kept')

    def test_dead_server_fails_without_health_poll(self):
        with self.assertRaisesRegex(RuntimeError,'exited with code'):
            runner.wait_healthy(process=NS(poll=lambda:1,returncode=1))

    def test_stream_without_finish_is_not_success(self):
        chunk=NS(choices=[NS(delta=NS(content='hello'),finish_reason=None)])
        client=NS(chat=NS(completions=NS(create=lambda **kw:iter([chunk]))))
        row=clients.generate(client,'model',dict(query='x',task_type='math'))
        self.assertEqual(row['status'],'failed')
        self.assertTrue(row['cost']['tokens_estimated'])

    def test_zero_completion_tokens_preserved(self):
        chunk=NS(choices=[NS(delta=NS(content='hello'),finish_reason='stop')])
        usage=NS(choices=[],usage=NS(model_dump=lambda:dict(prompt_tokens=3,completion_tokens=0)))
        client=NS(chat=NS(completions=NS(create=lambda **kw:iter([chunk,usage]))))
        row=clients.generate(client,'model',dict(query='x',task_type='math'))
        self.assertEqual(row['cost']['tokens_output'],0)
        self.assertFalse(row['cost']['tokens_estimated'])

    def test_frozen_cohort(self):
        runner.ARGS=NS(pilot=False)
        rows=runner.source_rows()
        self.assertEqual(len(rows),5000)
        self.assertEqual(len({r['query'] for r in rows}),5000)
        split=json.loads((R/'data/cohort_full_v2/split.json').read_text())
        sets=[set(split[k]) for k in ('train','validation','test')]
        self.assertEqual([len(s) for s in sets],[3500,750,750])
        self.assertFalse(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])
        self.assertEqual(set.union(*sets),{r['query_id'] for r in rows})

    def test_callback_exception_propagates(self):
        previous=clients.generate
        clients.generate=lambda *args:dict(status='ok')
        try:
            def broken(*args):raise OSError('disk full')
            with self.assertRaisesRegex(RuntimeError,'worker failed'):
                clients.collect_parallel(None,'x',[{'query':'x'}],n_threads=1,on_done=broken)
        finally:clients.generate=previous

if __name__=='__main__':unittest.main()
