"""Mock-only integration. No real credentials, model responses or authorization."""
import copy,datetime as dt,json,multiprocessing as mp,socket,tempfile,time,unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from binding import HERE,Halt,load_plan,verify_authorization
from http_transport import call_once,parse_response
from meter import EstimatedMeter,price
from run import run_batch,synthetic_http_fixtures
from START import supervise

class HttpEntryTests(unittest.TestCase):
    def plan(self):return load_plan()
    def one(self):
        p=self.plan();r=p['requests'][0];f=synthetic_http_fixtures(p)[r['request_id']]
        return p,r,f
    def temp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);return Path(t.name)
    def envelope(self,fixture):
        return {'kind':'HTTP_RESPONSE','http_status':fixture.get('status',200),'body_complete':True,'raw_body':fixture['raw_body'].encode()}

    def test_missing_auth_before_key_read_or_worker(self):
        p=self.plan();target=self.temp()/'never_created'
        with patch('run.load_keys_after_authorization',side_effect=AssertionError('key read')) as keys,patch('run.call_once',side_effect=AssertionError('HTTP attempted')) as sender:
            with self.assertRaisesRegex(Halt,'AUTHORIZATION_REQUIRED'):run_batch(p,target)
        keys.assert_not_called();sender.assert_not_called();self.assertFalse(target.exists())

    def test_preparation_template_is_not_execution_authorization(self):
        with self.assertRaisesRegex(Halt,'execution_authorized'):
            verify_authorization(HERE/'AUTHORIZATION_TEMPLATE.json',self.plan())

    def test_old_or_different_batch_authorization_denied(self):
        a=json.loads((HERE/'AUTHORIZATION_TEMPLATE.json').read_text());a['batch_id']='OLD_PAID_BATCH'
        f=self.temp()/'old.json';f.write_text(json.dumps(a))
        with self.assertRaisesRegex(Halt,'batch_id'):verify_authorization(f,self.plan())

    def test_simulated_receipt_cannot_authorize_real_http(self):
        a=json.loads((HERE/'AUTHORIZATION_TEMPLATE.json').read_text());a.update(execution_authorized=True,
            allow_public_task_material_to_bound_official_endpoints=True,evidence_class='SYNTHETIC_TEST_ONLY')
        f=self.temp()/'TEST_ONLY.json';f.write_text(json.dumps(a))
        with self.assertRaisesRegex(Halt,'TEST_RECEIPT'):verify_authorization(f,self.plan())

    def test_mock_full_chain_eight_attempts_and_score(self):
        p=self.plan();out=self.temp()/'mock'
        with patch('run.load_keys_after_authorization',side_effect=AssertionError('key read')),patch.object(socket.socket,'connect',side_effect=AssertionError('network')):
            r=run_batch(p,out,mock_fixtures=synthetic_http_fixtures(p))
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(r['attempt_records'],8)
        self.assertEqual(r['real_request_attempts'],0);self.assertEqual(r['automatic_retries'],0)
        self.assertEqual(r['primary_exploratory_result'],'NOT_EVALUATED_SYNTHETIC_FIXTURES')
        self.assertEqual(len(r['arms']),4)
        self.assertTrue(all(x['evaluation']['content_Q']==1 and x['evaluation']['legal_correct_targets']==6 for x in r['arms']))
        ledger=[json.loads(x) for x in (out/'LEDGER.jsonl').read_text().splitlines()]
        self.assertEqual(len({x['request_id'] for x in ledger}),8)
        for row in ledger:
            options=row['transport']['request_options']
            self.assertEqual(options['retries'],0);self.assertFalse(options['redirects']);self.assertFalse(options['trust_env'])
            self.assertEqual(options['wire_body_sha256'],row['body_sha256'])
            self.assertTrue(row['cache_committed']);self.assertIsNone(row['actual_cash'])
        for cur,total in r['estimate_meter']['estimate_spent_native'].items():
            self.assertEqual(Decimal(total),sum((Decimal(x['public_cold_miss_estimate']) for x in ledger if x['currency']==cur),Decimal(0)))
        events=[json.loads(x) for x in (out/'EVENTS.jsonl').read_text().splitlines()]
        for arm in r['arms']:
            rid_prefix=f"R{arm['repeat']}_{arm['arm']}_"
            commits=[x['monotonic_s'] for x in events if x['kind']=='NODE_COMMIT' and x['request_id'].startswith(rid_prefix)]
            merge=next(x['monotonic_s'] for x in events if x['kind']=='MERGE_START' and x['arm']==arm['arm'] and x['repeat']==arm['repeat'])
            self.assertEqual(len(commits),2);self.assertGreaterEqual(merge,max(commits))
        self.assertFalse(any('SYNTHETIC_AUTH_NOT_A_REAL_KEY' in x.read_text(errors='replace') for x in out.iterdir() if x.is_file()))

    def test_schema_failure_saved_but_not_committed_no_followup(self):
        p=self.plan();fixtures=synthetic_http_fixtures(p);bad='R1_A_extract_purchase'
        d=json.loads(fixtures[bad]['raw_body']);d['choices'][0]['message']['content']='[]';fixtures[bad]['raw_body']=json.dumps(d)
        out=self.temp()/'mock';r=run_batch(p,out,mock_fixtures=fixtures)
        self.assertEqual(r['status'],'STOPPED');self.assertEqual(r['attempt_records'],2)
        self.assertFalse(list(out.glob('*TERMINAL.json')))
        record=json.loads((out/(bad+'_RECORD.json')).read_text())
        self.assertFalse(record['cache_committed']);self.assertEqual(record['error_reason'],'NUMERIC_LANE_CONTRACT_FAILURE')
        self.assertTrue((out/(bad+'_HTTP_RESPONSE.bin')).exists());self.assertTrue((out/(bad+'_MODEL_OUTPUT.txt')).exists())

    def test_http_error_no_retry(self):
        p,r,f=self.one();f['status']=429
        with self.assertRaisesRegex(Halt,'HTTP_STATUS_429'):parse_response(self.envelope(f),r,p['accepted_response_models'][r['model']])

    def test_missing_usage_not_silently_zero(self):
        p,r,f=self.one();d=json.loads(f['raw_body']);del d['usage'];f['raw_body']=json.dumps(d)
        with self.assertRaisesRegex(Halt,'USAGE'):parse_response(self.envelope(f),r,p['accepted_response_models'][r['model']])

    def test_usage_total_mismatch_denied(self):
        p,r,f=self.one();d=json.loads(f['raw_body']);d['usage']['total_tokens']=1;f['raw_body']=json.dumps(d)
        with self.assertRaisesRegex(Halt,'TOTAL_MISMATCH'):parse_response(self.envelope(f),r,p['accepted_response_models'][r['model']])

    def test_returned_model_mismatch_denied(self):
        p,r,f=self.one();d=json.loads(f['raw_body']);d['model']='UNBOUND_MODEL';f['raw_body']=json.dumps(d)
        with self.assertRaisesRegex(Halt,'MODEL_MISMATCH'):parse_response(self.envelope(f),r,p['accepted_response_models'][r['model']])

    def test_truncation_keeps_cost_but_stops(self):
        p=self.plan();fixtures=synthetic_http_fixtures(p);bad='R1_A_extract_purchase'
        d=json.loads(fixtures[bad]['raw_body']);d['choices'][0]['finish_reason']='length';fixtures[bad]['raw_body']=json.dumps(d)
        out=self.temp()/'mock';r=run_batch(p,out,mock_fixtures=fixtures)
        record=json.loads((out/(bad+'_RECORD.json')).read_text())
        self.assertEqual(record['error_reason'],'TRUNCATED_OR_NONFINAL_OUTPUT');self.assertIsNotNone(record['public_cold_miss_estimate'])
        self.assertEqual(r['attempt_records'],2);self.assertFalse(record['cache_committed'])

    def test_absolute_client_timeout_terminates_child(self):
        p,r,f=self.one();f['delay_s']=3
        t=time.monotonic();response=call_once(r,'TEST_ONLY_SECRET',timeout_s=.6,fixture=f)
        self.assertEqual(response['kind'],'CLIENT_TIMEOUT');self.assertFalse(response['remote_cancel_confirmed'])
        self.assertLess(time.monotonic()-t,3);self.assertFalse(mp.active_children())

    def test_worker_exit_separate_from_network_timeout(self):
        p,r,f=self.one();f['worker_exit']=True
        response=call_once(r,'TEST_ONLY_SECRET',timeout_s=5,fixture=f)
        self.assertEqual(response['kind'],'WORKER_DIED');self.assertFalse(mp.active_children())

    def test_reflected_secret_redacted_before_persistence(self):
        p,r,f=self.one();secret='SYNTHETIC_REFLECTION_TEST_SECRET'
        f['raw_body']=f['raw_body'].replace('mock-',secret+'-')
        response=call_once(r,secret,timeout_s=5,fixture=f)
        self.assertTrue(response['credential_reflection_redacted']);self.assertNotIn(secret.encode(),response['raw_body'])

    def test_estimate_reservation_includes_inflight(self):
        p=self.plan();m=EstimatedMeter(p,caps={'CNY':'.80','USD':'.05'})
        rs=[r for r in p['requests'] if r['arm']=='A' and r['repeat']==1]
        m.reserve(rs[0],p['rates'][rs[0]['model']])
        with self.assertRaisesRegex(Halt,'RESERVATION'):m.reserve(rs[1],p['rates'][rs[1]['model']])

    def test_duplicate_reservation_no_retry(self):
        p=self.plan();m=EstimatedMeter(p);r=p['requests'][0];rate=p['rates'][r['model']];m.reserve(r,rate)
        with self.assertRaisesRegex(Halt,'DUPLICATE'):m.reserve(r,rate)

    def test_unknown_failed_usage_reservation_retained(self):
        p=self.plan();m=EstimatedMeter(p);r=p['requests'][0];m.reserve(r,p['rates'][r['model']]);before=m.snapshot();m.fail()
        self.assertEqual(before['estimate_reservations_retained_native'],m.snapshot()['estimate_reservations_retained_native'])
        with self.assertRaisesRegex(Halt,'STOPPED'):m.reserve(p['requests'][1],p['rates'][p['requests'][1]['model']])

    def test_observed_overrun_recorded_not_hidden(self):
        p=self.plan();m=EstimatedMeter(p);r=p['requests'][0];rate=p['rates'][r['model']];m.reserve(r,rate)
        usage={'prompt_tokens':200000,'completion_tokens':8192}
        with self.assertRaisesRegex(Halt,'EXCEEDED_AFTER'):m.settle(r,rate,usage)
        self.assertGreater(Decimal(m.snapshot()['estimate_spent_native']['CNY']),Decimal(0))
        self.assertFalse(m.snapshot()['cash_hard_cap_certified'])

    def test_qwen_overrun_uses_observed_price_tier(self):
        rate=self.plan()['rates']['qwen-plus']
        self.assertEqual(price(rate,130000,1000),Decimal('.332'))

    def test_plan_drift_denied_before_key_or_worker(self):
        p=self.plan();p['requests'][0]['endpoint']='https://example.invalid'
        with self.assertRaisesRegex(Halt,'PLAN_NOT_FROZEN'):run_batch(p,self.temp()/'never_created')

    def test_local_batch_watchdog_stops_only_owned_child(self):
        import sys
        result=supervise([sys.executable,'-c','import time; time.sleep(5)'],.2,self.temp()/'watchdog')
        self.assertTrue(result['client_batch_timeout']);self.assertFalse(result['remote_cancellation_confirmed'])
        self.assertLess(result['client_controller_wall_s'],3)

if __name__=='__main__':unittest.main(verbosity=2)
