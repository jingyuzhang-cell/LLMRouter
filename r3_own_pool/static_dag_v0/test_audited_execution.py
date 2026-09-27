"""No model calls. Regression tests for execution validity, not paper outcomes."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from . import exact_pareto as ep, frozen200_run as fz
from .audited_cache import load_prompt_cache, cached_record

TASK=dict(uid='t', question='quantity?',ctx_table='value 2',ctx_text='value 2',answer=2)
class FixtureCaller:
    def __init__(self):
        self.by_key={};self.faults={};self.calls=[]
    def set_fault(self,u,n,m,a,usage=None,lat=None):self.faults[u,n,m]=(a,usage,lat)
    def call(self,key,model,prompt,uid=None,node=None):
        self.calls.append((model,prompt,node))
        if (uid,node,model) in self.faults:answer=self.faults[uid,node,model][0]
        elif node in ('e1','e2'):answer='{"facts":[{"value":2,"evidence":"two"}]}'
        elif node=='r':answer='{"expression":"v0"}'
        elif node=='v':answer=json.dumps({'value':2 if model=='large' else 3})
        else:answer='{"answer":2}'
        r=dict(key=key,model=model,response=dict(status='delivered',answer=answer,usage={'total_tokens':10},latency_s=.1))
        self.by_key[key]=r;return r
    def cost(self,k):return 10
    def lat(self,k):return .1

class ExecutionTests(unittest.TestCase):
    def test_exact_reads_new_config_and_charges_only_executed_nodes(self):
        c=FixtureCaller()
        out=ep.run_config('medium','large','none',1,[TASK],{}, {},c)
        self.assertTrue(out['t']['ok']);self.assertEqual(out['t']['used'],40)
        self.assertEqual(len(c.calls),4)
    def test_exact_gold_does_not_select_actions(self):
        logs=[]
        for gold in (3,999):
            c=FixtureCaller();t=dict(TASK,answer=gold)
            ep.run_config('medium','coder','switch',1,[t],{}, {},c)
            logs.append(c.calls)
        self.assertEqual(*logs)
        self.assertEqual(logs[0][-1][0],'large') # disagreement triggers even when v == gold
    def test_exact_fault_reaches_initial_evidence_and_is_reset(self):
        c=FixtureCaller()
        ep.run_config('medium','large','none',1,[TASK],{'t':('e1','{}')},{},c)
        first=[r for k,r in c.by_key.items() if ':e1:' in k][0]
        self.assertEqual(first['response']['answer'],'{}')
        ep.run_config('medium','large','none',2,[TASK],{}, {},c)
        self.assertFalse(c.faults)
    def test_frozen_gold_does_not_select_actions(self):
        logs=[]
        for gold in (3,999):
            c=FixtureCaller();fz.run_arm('dynamic',[TASK],{},c,{'t':gold},False);logs.append(c.calls)
        self.assertEqual(*logs)
        self.assertEqual(logs[0][-1][0],'large')
    def test_single_fault_cost_uses_development_retry_convention(self):
        c=FixtureCaller();out=fz.run_arm('single',[TASK],{'t':('r','bad')},c,{'t':2},True)
        self.assertEqual(out['t']['used'],20);self.assertFalse(out['t']['ok'])
    def test_cache_snapshot_survives_overrides_and_matches_prompt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/'REQUESTS.jsonl').write_text(json.dumps(dict(key='k',model='m',prompt='p'))+'\n')
            (p/'RESPONSES.jsonl').write_text(json.dumps(dict(key='k',model='m',response=dict(status='delivered',answer='clean')))+'\n')
            cache=load_prompt_cache([p]);r=cached_record(cache,'k','m','p');r['response']['answer']='fault'
            self.assertEqual(cached_record(cache,'k','m','p')['response']['answer'],'clean')
            self.assertIsNone(cached_record(cache,'k','m','new prompt'))
    def test_production_caller_does_not_reuse_fault_by_key(self):
        c=fz.Caller.__new__(fz.Caller);c.by_key={};c.by_mp={};c.faults={};c.current=None;c.proc=None;c.log=None
        c.set_fault('t','r','medium','bad')
        c.call('same','medium','p',uid='t',node='r');c.faults.clear()
        with patch.object(fz.engine,'start_model',side_effect=RuntimeError('cache miss')):
            with self.assertRaisesRegex(RuntimeError,'cache miss'):c.call('same','medium','p',uid='t',node='r')
    def test_historical_real_replay_actions_are_gold_independent(self):
        from . import corrected_replay as replay
        from contextlib import redirect_stdout
        import io
        original_read = Path.read_text
        def changed_gold(path, *args, **kwargs):
            text = original_read(path, *args, **kwargs)
            if path == replay.OUT / 'POLICY.json':
                data = json.loads(text)
                for task in data['tasks']:
                    task['answer'] = 123456789.123
                return json.dumps(data)
            return text
        with tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            replay.run(Path(d) / 'baseline')
            with patch.object(Path, 'read_text', changed_gold):
                replay.run(Path(d) / 'changed_gold')
            baseline = json.loads((Path(d) / 'baseline/CORRECTED_ARMS.json').read_text())
            changed = json.loads((Path(d) / 'changed_gold/CORRECTED_ARMS.json').read_text())
            for arm in ('rd', 'fg'):
                for uid, row in baseline['arms'][arm].items():
                    other = changed['arms'][arm][uid]
                    self.assertEqual(row['keys'], other['keys'])
                    self.assertEqual(row['v_fired'], other['v_fired'])
                    self.assertEqual(row['used'], other['used'])

    def test_frozen_outputs_cannot_be_overwritten(self):
        with self.assertRaises(FileExistsError):ep.run()
        with self.assertRaises(FileExistsError):fz.run()

if __name__=='__main__':unittest.main()
