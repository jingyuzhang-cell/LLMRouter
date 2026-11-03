import unittest
from kdx_cleanup_wait import wait_for_exit
class Tests(unittest.TestCase):
 def setUp(self):self.now=0
 def clock(self):return self.now
 def sleep(self,n):self.now+=n
 def call(self,probe,deadline=10):return wait_for_exit(probe,deadline,probe_bound=1,interval=.2,clock=self.clock,sleep=self.sleep)
 def test_worker_delayed(self):self.assertGreater(self.call(lambda:self.now>=1),1)
 def test_worker_never(self):
  with self.assertRaises(TimeoutError):self.call(lambda:False)
 def test_gpu_delay(self):self.assertGreater(self.call(lambda:self.now>=2),1)
 def test_multiple_workers(self):self.assertGreater(self.call(lambda:all(self.now>=n for n in [1,2,3])),1)
 def test_no_budget_no_probe(self):
  calls=[]
  with self.assertRaises(TimeoutError):self.call(lambda:calls.append(1),deadline=.5)
  self.assertEqual(calls,[])
 def test_probe_overruns(self):
  def probe():self.now+=2;return True
  with self.assertRaises(TimeoutError):self.call(probe)
if __name__=='__main__':unittest.main()
