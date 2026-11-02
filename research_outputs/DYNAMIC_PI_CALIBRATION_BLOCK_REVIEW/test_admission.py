import copy,json,unittest
from pathlib import Path
from admission import assess
ROOT=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION')
RUN=Path('/root/research_outputs/DYNAMIC_PI_DEV_EXPLORATION_RUN')
class Tests(unittest.TestCase):
 def setUp(self):
  self.nodes=json.loads((ROOT/'evaluation/DAG.json').read_text())['nodes']
  self.models=[m['request_model'] for m in json.loads((ROOT/'EXPERIMENT_CONFIG.json').read_text())['models']]
  self.profiles=json.loads((RUN/'CALIBRATION.json').read_text());self.remaining=['timeline','relations','verify','report']
 def test_actual_failure_stops_before_evaluation(self):
  r=assess(self.nodes,self.models,self.profiles,self.remaining)
  self.assertEqual(r['decision'],'STOP_BEFORE_EVALUATION_NO_REMAINING_PI_CHOICE');self.assertEqual(r['remaining_assignment_count'],1)
 def test_partial_coverage_not_global_completeness_gate(self):
  # Logic check at a DIFFERENT hypothetical checkpoint, not a new experiment:
  # actual saved extraction measurements exist for both models; no fabricated values.
  r=assess(self.nodes,self.models,self.profiles,['extract_notice'])
  self.assertEqual(r['decision'],'CANDIDATE_SPACE_PRESENT_REQUIRE_SHARED_HARD_CONSTRAINT_CHECK')
  self.assertEqual(r['remaining_assignment_count'],2)
 def test_required_unknown_is_not_imputed(self):
  p=copy.deepcopy(self.profiles);p.pop('capital.report.v1|deepseek-flash')
  r=assess(self.nodes,self.models,p,self.remaining)
  self.assertEqual(r['decision'],'HOLD_UNMEASURED_REQUIRED_NODE');self.assertIn('report',r['uncovered'])
 def test_no_mutation_or_schema_unwrap(self):
  before=copy.deepcopy(self.profiles);assess(self.nodes,self.models,self.profiles,self.remaining);self.assertEqual(before,self.profiles)
  response=json.loads((RUN/'requests/cal_0__extract_1/RESPONSE.bin').read_text());output=json.loads(response['choices'][0]['message']['content'])
  self.assertNotEqual(set(output),{'claims'});self.assertEqual(set(output),{'node_id','contract','schema'})
if __name__=='__main__':unittest.main(verbosity=2)
