import copy,json,unittest,tempfile,hashlib
import score
from pathlib import Path
import reference_policy as R
ROOT=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
 def setUp(self):
  self.ref=json.loads((ROOT/'REFERENCE_DECISIONS.json').read_text());self.facts={f'T{i}':{'content':'CORRECT','support':'SUPPORTED','reason':'synthetic test only'} for i in range(1,7)}
 def test_pending_reference_is_permitted_but_cannot_score(self):
  R.validate(ROOT,self.ref);m=R.metrics(self.ref['targets']['evaluation'],self.facts)
  self.assertIsNone(m['full_terminal_Q']);self.assertIsNone(m['INDEPENDENT_ADJUDICATED']['partial_fact_score']);self.assertEqual(len(m['pending_reference_ids']),6)
 def test_nonindependent_separate_and_unknown_excluded(self):
  for i in ('T1','T2'):
   self.ref['targets']['evaluation'][i].update(tier='PROJECT_REVIEWED_NONINDEPENDENT',reviewer='SYNTHETIC_TEST',date='2026-10-30',rationale='fixture',evidence_locator='fixture')
  R.validate(ROOT,self.ref);self.facts['T2']['content']='UNKNOWN'
  m=R.metrics(self.ref['targets']['evaluation'],self.facts);p=m['PROJECT_REVIEWED_NONINDEPENDENT']
  self.assertEqual(p['partial_fact_score'],1);self.assertEqual(p['resolved_ids'],['T1']);self.assertEqual(p['reference_coverage'],2/6);self.assertEqual(p['resolved_coverage'],1/6);self.assertIsNone(m['full_terminal_Q'])
 def test_cannot_self_upgrade_to_independent(self):
  self.ref['targets']['evaluation']['T1']['tier']='INDEPENDENT_ADJUDICATED'
  with self.assertRaises(ValueError):R.validate(ROOT,self.ref)
 def test_wrong_and_missing_count_only_on_reviewed_scope(self):
  self.ref['targets']['evaluation']['T1']['tier']='PROJECT_REVIEWED_NONINDEPENDENT';self.facts['T1']['content']='WRONG'
  m=R.metrics(self.ref['targets']['evaluation'],self.facts)
  self.assertEqual(m['PROJECT_REVIEWED_NONINDEPENDENT']['partial_fact_score'],0);self.assertEqual(len(m['pending_reference_ids']),5)
 def test_scoring_all_pending_preserves_null_and_frozen_scope(self):
  with tempfile.TemporaryDirectory() as tmp:
   run=Path(tmp)
   (run/'REFERENCE_SCOPE.json').write_text(json.dumps(self.ref,ensure_ascii=False,indent=2))
   sha=hashlib.sha256((run/'REFERENCE_SCOPE.json').read_bytes()).hexdigest()
   (run/'RUN_CONTEXT.json').write_text(json.dumps({'reference_decisions_sha256':sha}))
   arms=[]
   for arm in ('Static-Pi','Dynamic-Pi'):
    file='P1_'+arm+'.RAW.json';(run/file).write_text(json.dumps({'outputs':{'answer':{'text':'SYNTHETIC ONLY'}}}))
    arms.append({'arm':arm,'full_output_file':file,'task_complete':True})
   (run/'RESULT.json').write_text(json.dumps({'pairs':[{'pair_id':'P1','arms':arms}]}))
   score.export(run)
   d=json.loads((run/'blind_review/DECISIONS_TEMPLATE.json').read_text());d.update(reviewer='SYNTHETIC_TEST_NOT_HUMAN',date='2026-10-30',independent=False)
   df=run/'test_decisions.json';df.write_text(json.dumps(d))
   result=score.score(run,df)
   for a in result['pairs'][0]['arms']:
    self.assertIsNone(a['terminal_success']);self.assertIsNone(a['score_with_provenance']['quality']['full_terminal_Q'])
   (run/'REFERENCE_SCOPE.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'PRE_EXECUTION_REFERENCE_SCOPE_CHANGED'):score.score(run,df)
if __name__=='__main__':unittest.main(verbosity=2)
