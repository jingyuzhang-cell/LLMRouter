import unittest
from replay_cells import execute_cells,replay
class CellTests(unittest.TestCase):
 def test_real_matrix_keeps_unknown(self):
  r=replay();self.assertEqual(len(r['rows']),8);self.assertEqual(len(r['remaining_missing_cells']),4)
  self.assertTrue(all(x['Q'] is None for x in r['rows']))
  self.assertTrue(all(x['latency_s'] is None for x in r['rows'] if x['status']=='MISSING'))
 def test_normal_failure_continues_independent_cells(self):
  statuses=['OBSERVED_MODEL_FAILURE','MISSING','OBSERVED_COMMITTED']
  r=execute_cells(range(3),lambda i:dict(status=statuses[i]),max_cells=3,wall_seconds=10)
  self.assertEqual([x['status'] for x in r['rows']],statuses);self.assertIsNone(r['stop'])
 def test_system_error_stops(self):
  calls=[]
  def worker(i):
   calls.append(i)
   raise ValueError('corrupt source')
  r=execute_cells(range(3),worker,max_cells=3,wall_seconds=10)
  self.assertEqual(calls,[0]);self.assertEqual(r['stop'],'SYSTEM_ERROR')
 def test_limits_stop_before_next_cell(self):
  calls=[]
  def worker(i):calls.append(i);return dict(status='MISSING')
  r=execute_cells(range(3),worker,max_cells=1,wall_seconds=10)
  self.assertEqual(calls,[0]);self.assertEqual(r['stop'],'CELL_LIMIT')
  calls.clear();r=execute_cells(range(3),worker,max_cells=3,wall_seconds=0)
  self.assertEqual(calls,[]);self.assertEqual(r['stop'],'WALL_LIMIT')
if __name__=='__main__':unittest.main()
