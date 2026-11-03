import tempfile,unittest,fcntl
from pathlib import Path
from unittest.mock import Mock,patch
from kdx_owned_service import OwnedService
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.proc=Mock(pid=12345);self.proc.poll.return_value=None;self.proc.wait.return_value=0;self.spawn=Mock(return_value=self.proc);self.kill=Mock()
 def service(self):return OwnedService(['MOCK'],self.root/'gpu.lock',self.root/'run',300,60,self.spawn,self.kill,lambda pid:True)
 def test_normal_owned_cleanup(self):
  with self.service() as s:s.check_identity({'data':[{'id':'qwen'}]},'qwen');self.assertEqual(s.request(lambda:42),42)
  self.kill.assert_called_once();self.assertTrue(self.spawn.call_args.kwargs['start_new_session'])
 def test_timeout_stops(self):
  with self.assertRaises(TimeoutError):
   with self.service() as s:s.request(lambda:(_ for _ in ()).throw(TimeoutError()))
  self.kill.assert_called_once()
 def test_gpu_lock_busy_no_spawn(self):
  lock=(self.root/'gpu.lock').open('a+');self.addCleanup(lock.close);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  with self.assertRaises(BlockingIOError):self.service().start()
  self.spawn.assert_not_called()
 def test_duplicate_no_spawn(self):
  (self.root/'run').mkdir()
  with self.assertRaises(FileExistsError):self.service().start()
  self.spawn.assert_not_called()
 def test_identity_failure_cleanup(self):
  with self.assertRaises(ValueError):
   with self.service() as s:s.check_identity({'data':[{'id':'wrong'}]},'qwen')
  self.kill.assert_called_once()
 def test_wall_request_rejected(self):
  with self.service() as s:
   s.start_time-=290
   with self.assertRaises(ValueError):s.request(lambda:42)
 def test_cleanup_failure_retains_error(self):
  self.proc.wait.side_effect=TimeoutError()
  with self.assertRaises(ValueError):
   with self.service() as service:raise ValueError('primary')
  self.assertTrue(service.quarantine.exists());self.assertIsNotNone(service.lock)
  service.lock.close()
 def test_idempotent_stop(self):
  s=self.service();s.start();s.stop();s.stop();self.kill.assert_called_once()
 def test_gpu_exit_unconfirmed_quarantine(self):
  s=self.service();s.exit_probe=lambda pid:False;s.start()
  with self.assertRaises(RuntimeError):s.stop()
  self.assertTrue(s.quarantine.exists());self.assertIsNotNone(s.lock)
  s.lock.close();s.lock=None
  newer=OwnedService(['MOCK'],self.root/'gpu.lock',self.root/'other',300,60,self.spawn,self.kill,lambda pid:True)
  with self.assertRaisesRegex(ValueError,'QUARANTINED'):newer.start()
  self.assertEqual(self.spawn.call_count,1)
 def test_probe_failure_quarantine(self):
  s=self.service();s.exit_probe=Mock(side_effect=TimeoutError());s.start()
  with self.assertRaises(RuntimeError):s.stop()
  self.assertIsNotNone(s.lock);s.lock.close()
 def test_crash_marker_blocks_new_manager(self):
  s=self.service();s.start();self.assertTrue(s.quarantine.exists())
  # Simulate OS dropping flock on manager exit, without treating GPU as cleaned.
  s.timer.cancel();s.lock.close();s.lock=None;s.log.close()
  newer=OwnedService(['MOCK'],self.root/'gpu.lock',self.root/'other',300,60,self.spawn,self.kill,lambda pid:True)
  with self.assertRaisesRegex(ValueError,'QUARANTINED'):newer.start()
  self.assertEqual(self.spawn.call_count,1)
 def test_success_removes_active_marker(self):
  s=self.service();s.start();s.stop();self.assertFalse(s.quarantine.exists())
if __name__=='__main__':unittest.main()
