import copy,json,socket,tempfile,unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
    from executor import FakeMeter,load_config,run,synthetic_fixtures,Stop

class BindingTests(unittest.TestCase):
    def go(self,c=None,f=None,caps=None):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        p=Path(t.name)/'run'
        f=f or FakeMeter(synthetic_fixtures())
        with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')):
            r=run(c or load_config(),f,p,caps)
        return r,p,f

    def test_complete_fake_chain_meter_and_score(self):
        r,p,f=self.go();self.assertEqual(r['status'],'COMPLETE')
        self.assertEqual(r['physical_fake_calls'],8);self.assertEqual(len(set(f.calls)),8)
        self.assertEqual(r['real_model_calls'],0);self.assertEqual(r['retries'],0)
        self.assertTrue(all(x['evaluation']['content_Q']==1 and x['evaluation']['legal_correct_targets']==6 for x in r['results']))
        ledger=[json.loads(x) for x in (p/'LEDGER.jsonl').read_text().splitlines()]
        self.assertEqual(len(ledger),8)
        for cur,total in r['simulated_spent_native'].items():
            self.assertEqual(Decimal(total),sum((Decimal(x['cash_simulated']) for x in ledger if x['native_currency']==cur),Decimal(0)))
        self.assertTrue(all(x['cash_actual'] is None for x in ledger))

    def test_same_input_resources_and_only_allocation_changes(self):
        c=load_config()
        for node in ['extract_purchase','extract_payables']:
            rs=[r for r in c['requests'] if r['node_id']==node]
            self.assertEqual(len({r['messages_sha256'] for r in rs}),1)
        self.assertEqual(c['initial_cache'],{});self.assertFalse(c['recovery_enabled'])
        self.assertFalse(c['structure_change_enabled'])
        self.assertEqual(set(c['common_arm_caps_native']),{'CNY','USD'})

    def test_merge_waits_for_both_commits(self):
        r,p,_=self.go();es=[json.loads(s) for s in (p/'EVENTS.jsonl').read_text().splitlines()]
        for x in r['results']:
            ids={f"R{x['repeat']}_{x['arm']}_{n}" for n in ['extract_purchase','extract_payables']}
            cs=[e['monotonic_s'] for e in es if e['event']=='BRANCH_COMMIT' and e['request_id'] in ids]
            m=next(e['monotonic_s'] for e in es if e['event']=='MERGE_START' and e['arm']==x['arm'] and e['repeat']==x['repeat'])
            self.assertEqual(len(cs),2);self.assertGreaterEqual(m,max(cs))

    def test_insufficient_budget_before_any_dispatch(self):
        r,p,f=self.go(caps={'CNY':'0.01','USD':'0.001'})
        self.assertEqual(r['status'],'STOPPED');self.assertEqual(f.calls,[])
        self.assertFalse(list(p.glob('*TERMINAL.json')))

    def test_bad_contract_not_committed_no_downstream_or_retry(self):
        c=load_config();bad='R1_A_extract_purchase'
        r,p,f=self.go(c,FakeMeter(synthetic_fixtures(),bad_schema_id=bad))
        self.assertEqual(r['status'],'STOPPED');self.assertNotIn(bad,r['cache_keys'])
        self.assertFalse(list(p.glob('*TERMINAL.json')))
        self.assertEqual(len(f.calls),len(set(f.calls)));self.assertLessEqual(len(f.calls),2)

    def test_transport_failure_retains_reservation_stops_batch(self):
        r,p,f=self.go(f=FakeMeter(synthetic_fixtures(),fail_id='R1_A_extract_purchase'))
        self.assertEqual(r['status'],'STOPPED');self.assertGreater(Decimal(r['retained_reservations_native']['CNY']),0)
        self.assertLessEqual(len(f.calls),2)

    def test_output_overflow_stops_before_commit(self):
        bad='R1_A_extract_purchase';r,p,f=self.go(f=FakeMeter(synthetic_fixtures(),token_overflow_id=bad))
        self.assertIn('TOKEN_BOUND',r['stop_reason']);self.assertNotIn(bad,r['cache_keys'])

    def test_dedup_no_resume(self):
        r,p,f=self.go()
        other=FakeMeter(synthetic_fixtures())
        with self.assertRaises(FileExistsError):run(load_config(),other,p)
        self.assertEqual(other.calls,[])

    def test_real_transport_explicitly_denied(self):
        class NoSend:
            def call(self,r):raise AssertionError('must not send')
        with self.assertRaisesRegex(Stop,'REAL_TRANSPORT'):run(load_config(),NoSend(),'/tmp/never_dispatch_this_pilot')

    def test_contract_hash_mismatch_rejected(self):
        with patch('executor.digest',return_value='SIMULATED_BAD_HASH'):
            with self.assertRaisesRegex(Stop,'FROZEN_IDENTITY'):load_config()

    def test_stale_cache_fingerprint_blocks_merge(self):
        r,p,f=self.go(f=FakeMeter(synthetic_fixtures(),cache_tamper_id='R1_A_extract_purchase'))
        self.assertIn('CACHE_FINGERPRINT',r['stop_reason'])
        self.assertFalse(list(p.glob('*TERMINAL.json')))

    def test_valid_but_wrong_content_not_hardcoded_success(self):
        fixtures=synthetic_fixtures()
        fixtures['extract_purchase']['items'][0]['fields']['amount']['number']='-1'
        r,p,f=self.go(f=FakeMeter(fixtures))
        self.assertEqual(r['status'],'COMPLETE')
        self.assertTrue(all(x['evaluation']['content_Q']<1 and x['evaluation']['legal_correct_targets']==5 for x in r['results']))

    def test_mutated_runtime_config_denied(self):
        c=load_config();c['requests'][0]['body']['messages'][0]['content']='changed'
        with self.assertRaisesRegex(Stop,'CONFIG_NOT_FROZEN'):self.go(c)

if __name__=='__main__':unittest.main(verbosity=2)
