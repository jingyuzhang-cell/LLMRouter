"""Targeted adapter tests, not a new scheduling-benefit experiment."""
import unittest,json,copy,pathlib,socket,importlib.util,math
import numeric_binding as b
ROOT=pathlib.Path('/root/capital_opinion_pilot/v5_rl_controlled_preregistration_v1')
H=pathlib.Path('/root/r3_own_pool/ab_numeric_recovery_controlled_execution_v1/REAL_RUN_20261019_023824')
class BindingTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  def deny(*a,**kw):raise AssertionError('NETWORK_FORBIDDEN')
  socket.socket=deny;socket.create_connection=deny
  cls.states={f'C{i:02d}':json.loads((ROOT/'paired_states'/f'C{i:02d}_r1_V5.json').read_text()) for i in range(8)}
  cls.record=json.loads((H/'A_RESULT.json').read_text());cls.raw=(H/'A_MODEL_OUTPUT.txt').read_text()
 def payload(self):return copy.deepcopy(self.states['C00']['branches']['extract_payables']['payload'])
 def test_01_existing_valid_payload(self):self.assertEqual(b.inspect_contract(self.payload(),'extract_payables')['status'],'VALID')
 def test_02_native_array_not_repaired(self):self.assertEqual(b.inspect_contract(self.payload()['items'],'extract_payables')['status'],'SCHEMA_REJECTED')
 def test_03_omission_and_duplicate_rejected(self):
  for rows in [self.payload()['items'][:2],[self.payload()['items'][0]]*3]:self.assertEqual(b.inspect_contract({'items':rows},'extract_payables')['status'],'SCHEMA_REJECTED')
 def test_04_invalid_id_is_hard_contract_failure(self):
  s=self.states['C03'];e=b.adapt_shared_state(s);self.assertFalse(e['contract_valid']['extract_purchase']);self.assertEqual(len(e['feedback_records']),2);self.assertTrue(all(r['class']=='CONFIRMED-INVALID' for r in e['feedback_records']))
 def test_05_cache_payload_tamper_blocked(self):
  s=copy.deepcopy(self.states['C00']);s['branches']['extract_purchase']['payload']['items'][0]['fields']['amount']['number']=1
  self.assertFalse(b.adapt_shared_state(s)['contract_valid']['extract_purchase'])
 def test_06_pair_identical_effective_feedback(self):
  for cid in self.states:
   for rep in (1,2):
    a=json.loads((ROOT/'paired_states'/f'{cid}_r{rep}_V5.json').read_text());r=json.loads((ROOT/'paired_states'/f'{cid}_r{rep}_RL.json').read_text())
    self.assertEqual(b.adapt_shared_state(a),b.adapt_shared_state(r))
 def test_07_merge_requires_both_valid_branches(self):
  e=b.adapt_shared_state(self.states['C01'])
  with self.assertRaises(ValueError):b.deterministic_merge(e['outputs'])
 def test_08_valid_merge_preserves_six_rows(self):
  outputs=b.adapt_shared_state(self.states['C00'])['outputs']
  self.assertEqual(len(b.deterministic_merge({n:outputs[n] for n in b.TEMPLATES})['items']),6)
  self.assertEqual(len(outputs['merge_numeric']['items']),6)
 def test_09_no_fee_envelope_no_execution(self):
  with self.assertRaisesRegex(ValueError,'CASH_ENVELOPE'):b.make_scheduler_state(self.states['C01'],[],None)
 def test_10_request_matches_actual_history(self):self.assertEqual(b.request_for('extract_payables','deepseek-flash')['body'],json.loads((H/'A_REQUEST.json').read_text()))
 def observation(self,**kw):
  args=dict(request=b.request_for('extract_payables','deepseek-flash'),raw_model_text=self.raw,usage=self.record['usage'],wall_s=self.record['client_call_wall_s'],response_model=self.record['model_returned'],http_status=200);args.update(kw);return b.observe_response(**args)
 def test_11_unknown_fee_not_zero(self):
  x=self.observation();self.assertTrue(x['usage_identified']);self.assertIsNone(x['executor_callback']['cash_cost']);self.assertIsNone(x['actual_bill']);self.assertTrue(x['stop_required'])
 def test_12_unknown_usage_stops(self):self.assertTrue(self.observation(usage=None)['stop_required'])
 def test_13_response_identity_required(self):self.assertFalse(self.observation(response_model='wrong')['executor_callback']['contract_ok'])
 def test_14_request_drift_rejected(self):
  req=b.request_for('extract_payables','deepseek-flash');req['body']['max_tokens']=1025
  with self.assertRaisesRegex(ValueError,'DRIFT'):self.observation(request=req)
 def test_15_terminal_partial_separate_from_full(self):
  e=b.adapt_shared_state(self.states['C01']);d=b.evaluate_delivery(e['outputs']);self.assertFalse(d['terminal_complete']);self.assertEqual(d['legal_branch_correct_target_coverage'],.5);self.assertEqual(d['legal_terminal_correct_target_coverage'],0)
 def test_16_no_paid_gate_bypass(self):
  with self.assertRaisesRegex(b.PaidExecutionBlocked,'NO_EXPERIMENT'):b.execution_gate(self.states['C01'],[],None,None,None)
 def test_17_public_contract_parity(self):
  # Import guard definitions only; never import run_once.py, key_for or sender.
  p=pathlib.Path('/root/r3_own_pool/ab_numeric_recovery_controlled_execution_v1/binding_helpers.py');spec=importlib.util.spec_from_file_location('historical_guard',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  m.SCHEMA=b.SCHEMA;m.TASK=b.TASK;m.VAR={(x['node_id'],x['model_id']):x for x in b.VARIANTS.values()};m.INITIAL={'extract_purchase':'qwen-flash','extract_payables':'deepseek-flash'}
  for cid in self.states:
   for n,branch in self.states[cid]['branches'].items():
    if branch['payload'] is None:continue
    raw=json.dumps(branch['payload'],ensure_ascii=False);self.assertEqual(b.inspect_contract(raw,n)['status'],m.bounded_guard(raw,n)[0])
 def test_18_unknown_tool_cost_not_silently_zero(self):
  with self.assertRaisesRegex(ValueError,'TOOL_LATENCY_UNIDENTIFIED'):b.make_scheduler_state(self.states['C01'],[],{'CNY':1,'USD':1})
if __name__=='__main__':unittest.main(verbosity=2)
