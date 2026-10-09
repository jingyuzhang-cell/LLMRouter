import copy
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .runtime import CampaignQuota,run_session,require_admission
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
from collab_scheduler_v1.fault30_protocol import Ledger


class FakeBackend:
    def __init__(self,missing=False):
        self.OUT=None;self.starts=0;self.stops=0;self.calls=0;self.missing=missing
    def start_model(self,m):self.starts+=1;return object(),object(),0
    def stop_model(self,p,l):self.stops+=1
    def call_model(self,m,p):
        self.calls+=1
        return dict(status='delivered',answer='{}',usage=None if self.missing else
            dict(prompt_tokens=60,completion_tokens=40,total_tokens=100))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.protocol=json.loads(Path('collab_scheduler_v1/joint_search_v1/SEARCH_BUDGET_V1.json').read_text())
        self.protocol['max_selected_configurations_per_session']=2
        self.caps=self.protocol['campaign_caps']

    def test_crash_pending_reservation_survives_new_process_view(self):
        caps=dict(sessions=18,new_request_attempts=400,new_total_tokens=3276800,wall_seconds=7200)
        q=CampaignQuota(self.root/'q',caps,'hash');q.reserve('first',self.protocol['per_session_caps']);q.close()
        q=CampaignQuota(self.root/'q',caps,'hash');self.addCleanup(q.close)
        with self.assertRaises(StopRun):q.reserve('second',self.protocol['per_session_caps'])
        with self.assertRaises(ValueError):q.reserve('first',self.protocol['per_session_caps'])

    def test_protocol_change_refused(self):
        q=CampaignQuota(self.root/'q',self.caps,'hash');q.close()
        with self.assertRaises(ValueError):CampaignQuota(self.root/'q',self.caps,'changed')

    def test_campaign_lock_exclusive(self):
        q=CampaignQuota(self.root/'q',self.caps,'hash');self.addCleanup(q.close)
        with self.assertRaises(BlockingIOError):CampaignQuota(self.root/'q',self.caps,'hash')

    def test_settlement_retains_failed_slot_and_actual_spend(self):
        caps=dict(self.caps,sessions=1)
        q=CampaignQuota(self.root/'q',caps,'hash')
        q.reserve('first',self.protocol['per_session_caps'])
        q.settle('first',dict(new_request_attempts=1,new_total_tokens=8192,wall_seconds=10),'INCOMPLETE');q.close()
        q=CampaignQuota(self.root/'q',caps,'hash');self.addCleanup(q.close)
        self.assertEqual(q.sessions['first']['charge']['new_total_tokens'],8192)
        with self.assertRaises(StopRun):q.reserve('second',self.protocol['per_session_caps'])

    def run_fake(self,backend):
        return run_session(campaign=self.root/'campaign',protocol_sha='test-only',
            protocol=self.protocol,method='random',seed=self.protocol['search_seeds'][0],
            tasks=[make_task()],states=[('clean',{}),('fault30',{})],
            selector=lambda c,o:c[0]['id'],ledger=Ledger(),backend=backend,
            bindings=dict(medium='m',large='l',coder='c'),gpu_lock_path=self.root/'gpu.lock')

    def test_complete_session_closes_backend_and_restores_out(self):
        b=FakeBackend()
        with patch('static_dag_v0.run.start_model',side_effect=AssertionError('real GPU forbidden')),patch('static_dag_v0.run.call_model',side_effect=AssertionError('real LLM forbidden')):
            result=self.run_fake(b)
        self.assertEqual(result['status'],'COMPLETE')
        self.assertGreater(b.calls,0);self.assertEqual(b.starts,b.stops)
        self.assertIsNone(b.OUT)
        rows=[json.loads(l) for l in (Path(result['directory'])/'EVALUATIONS.jsonl').read_text().splitlines()]
        self.assertEqual(len(rows),4)
        again=self.run_fake(b)
        self.assertEqual(again['status'],'INCOMPLETE')

    def test_missing_usage_charged_and_stops_without_retry(self):
        b=FakeBackend(missing=True);result=self.run_fake(b)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertEqual(b.calls,1);self.assertEqual(b.starts,b.stops)
        q=CampaignQuota(self.root/'campaign',self.caps,'test-only');self.addCleanup(q.close)
        self.assertEqual(next(iter(q.sessions.values()))['charge']['new_total_tokens'],8192)

    def test_gpu_busy_does_not_start_or_charge(self):
        with (self.root/'gpu.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            b=FakeBackend();result=self.run_fake(b)
            self.assertEqual(result['status'],'INCOMPLETE');self.assertEqual(b.starts,0)
        q=CampaignQuota(self.root/'campaign',self.caps,'test-only');self.addCleanup(q.close)
        self.assertEqual(q.sessions,{})

    def test_cleanup_failure_retains_full_campaign_reservation(self):
        class BadCleanup(FakeBackend):
            def stop_model(self,p,l):raise RuntimeError('stub cleanup failure')
        result=self.run_fake(BadCleanup())
        self.assertEqual(result['status'],'INCOMPLETE')
        q=CampaignQuota(self.root/'campaign',self.caps,'test-only');self.addCleanup(q.close)
        item=next(iter(q.sessions.values()))
        self.assertFalse(item['settled'])
        self.assertEqual(item['charge']['new_request_attempts'],400)

    def test_wall_alarm_interrupts_stub_startup(self):
        import time
        class SlowStartup(FakeBackend):
            def start_model(self,m):
                time.sleep(.2)
                raise AssertionError('deadline failed')
        self.protocol['per_session_caps']['wall_seconds']=60.05
        b=SlowStartup();result=self.run_fake(b)
        self.assertEqual(result['status'],'INCOMPLETE')
        self.assertIn('deadline',result['reason'])
        self.assertEqual(b.calls,0)

    def test_unapproved_protocol_fails_closed(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(PermissionError):
                require_admission(Path('collab_scheduler_v1/joint_search_v1/SEARCH_BUDGET_V1.json'),self.root/'missing.json','wrong')


if __name__=='__main__':unittest.main()
