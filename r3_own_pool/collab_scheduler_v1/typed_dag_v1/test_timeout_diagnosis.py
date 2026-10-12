"""Zero-network tests of historical request-stop semantics."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from .resource_envelope import request_deadline
from .ab_review_diagnostic import run_cell,global_gate,request_wall_gate
from .heterogeneous_models import SerialModelService
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
class TimeoutTests(unittest.TestCase):
 def test_no_response_absolute_deadline(self):
  import signal
  with self.assertRaises(StopRun):
   with request_deadline(.01):signal.pause()
 def test_read_timeout_is_infrastructure(self):
  r={'state':'INFRASTRUCTURE_ERROR','error':'TimeoutError(read timeout)'}
  with self.assertRaises(StopRun):global_gate(r)
 def test_completed_before_deadline(self):
  with request_deadline(1):value='complete'
  self.assertEqual(value,'complete')
 def test_client_timeout_does_not_prove_server_cancel(self):
  state=dict(server_pending=True)
  with self.assertRaises(StopRun):
   with request_deadline(1):raise StopRun('Request wall timeout; unknown usage reservation retained')
  self.assertTrue(state['server_pending'])
 def test_unknown_usage_preserved(self):
  import tempfile
  from pathlib import Path
  from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget
  with tempfile.TemporaryDirectory() as t:
   b=Budget(Path(t),dict(new_request_attempts=2,new_total_tokens=100,request_token_reservation=50,max_output_tokens=10,wall_seconds=60,logical_calls_per_task_config_state=2))
   b.reserve('request');self.assertEqual(b.actual_tokens,0);self.assertEqual(b.charged,50);self.assertTrue(b.pending)
 def test_timeout_stops_no_retry(self):
  with self.assertRaises(StopRun):global_gate(dict(state='RESOURCE_STOP',error='Request wall timeout'))
 def test_cleanup_kill_after_terminate_timeout(self):
  import subprocess,tempfile
  from pathlib import Path
  proc=SimpleNamespace(poll=lambda:None,terminate=unittest.mock.Mock(),kill=unittest.mock.Mock(),wait=unittest.mock.Mock(side_effect=[subprocess.TimeoutExpired('stub',15),None]))
  with tempfile.TemporaryDirectory() as t:
   s=SerialModelService({}, {},Path(t),lambda:None);s.proc=proc;s.active='medium';s.close()
   proc.terminate.assert_called_once();proc.kill.assert_called_once();self.assertIsNone(s.active)
 def test_global_insufficient_wall(self):
  with self.assertRaises(StopRun):request_wall_gate(485,dict(wall_seconds=544,request_timeout_s=30,cleanup_reserve_s=30))
