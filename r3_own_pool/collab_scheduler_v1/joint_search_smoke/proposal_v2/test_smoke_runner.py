"""Zero-model-call tests for the real smoke admission and dispatch path."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .smoke_runner import Budget, StopRun, make_executor_class

CAPS = dict(new_request_attempts=2, new_total_tokens=16384,
            request_token_reservation=8192, max_output_tokens=512,
            wall_seconds=100, logical_calls_per_task_config_state=12)


def response(status='delivered'):
    return dict(status=status, answer='{}', usage=dict(prompt_tokens=60,
                completion_tokens=40, total_tokens=100))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.now = 0
        self.b = Budget(self.path, CAPS.copy(), lambda: self.now)

    def test_reservation_persisted_before_dispatch_and_settlement(self):
        idx = self.b.reserve('a')
        self.assertEqual(json.loads(self.b.path.read_text())['tokens'], 8192)
        self.assertEqual(self.b.charged, 8192)
        self.b.settle(idx, response())
        self.assertEqual((self.b.charged, self.b.actual_tokens), (100, 100))

    def test_failed_usage_charged(self):
        idx = self.b.reserve('a')
        with self.assertRaises(StopRun):
            self.b.settle(idx, response('infrastructure_failure'))
        self.assertEqual(self.b.charged, 100)
        self.assertEqual(self.b.attempts, 1)

    def test_missing_usage_retains_reservation_and_blocks_resume(self):
        idx = self.b.reserve('a')
        with self.assertRaises(StopRun):
            self.b.settle(idx, dict(status='delivered', usage=None))
        self.assertEqual(self.b.charged, 8192)
        self.assertEqual(self.b.pending, {1:8192})
        with self.assertRaises(ValueError):
            Budget(self.path, CAPS)

    def test_request_cap(self):
        for key in ('a', 'b'):
            self.b.settle(self.b.reserve(key), response())
        with self.assertRaises(StopRun):
            self.b.reserve('c')
        self.assertEqual(self.b.attempts, 2)

    def test_token_cap_before_dispatch(self):
        self.b.caps['new_total_tokens'] = 8191
        with self.assertRaises(StopRun):
            self.b.reserve('a')
        self.assertEqual(self.b.attempts, 0)
        self.assertFalse(self.b.path.exists())

    def test_wall_cap_before_dispatch(self):
        self.now = 100
        with self.assertRaises(StopRun):
            self.b.reserve('a')
        self.assertEqual(self.b.attempts, 0)

    def test_invalid_token_totals_stop(self):
        r = response()
        r['usage']['total_tokens'] = 99
        with self.assertRaises(StopRun):
            self.b.settle(self.b.reserve('a'), r)
        self.assertEqual(self.b.charged, 8192)

    def executor(self, dispatch=None):
        self.dispatched = []
        def stub(model, prompt):
            # The production dispatch wrapper must have reserved first.
            self.assertTrue(self.b.pending)
            self.assertTrue(self.b.path.exists())
            self.dispatched.append(prompt)
            return response()
        ex = make_executor_class()(self.path, self.b, dispatch or stub, lambda m: None,
                                   dict(medium='frozen-model-and-generation'))
        ex.begin_cell('clean', 'config')
        return ex

    def test_alias_and_injection_zero_physical(self):
        from collab_scheduler_v1.fault30_run import physical_accounting
        ex = self.executor()
        ex.call('f30:D:F:r:u', 'medium', 'prompt')
        ex.call('f30:D:F:r:fb:u', 'medium', 'prompt')
        ex.set_fault('u', 'r', 'medium', 'synthetic', dict(total_tokens=9000), 99)
        ex.call('f30:D:F:r:esc:u', 'medium', 'prompt', uid='u', node='r')
        totals = physical_accounting(ex.events)
        self.assertEqual((totals['logical_calls'], totals['cache_hits'], totals['injected_calls'],
                          totals['new_requests'], totals['new_tokens']), (3,1,1,1,100))
        self.assertEqual((self.b.attempts,self.b.charged), (1,100))
        self.assertEqual(totals['new_latency_s'], ex.events[0]['response']['latency_s'])

    def test_changed_input_and_fault_scope_miss(self):
        ex = self.executor()
        ex.call('f30:D:F:r:u', 'medium', 'old facts')
        ex.call('f30:D:F:r:fb:u', 'medium', 'new facts')
        ex.begin_cell('fault30', 'config')
        with self.assertRaises(StopRun):
            ex.call('f30:D:F:r:u', 'medium', 'old facts')
        self.assertEqual(len(self.dispatched),2)

    def test_exception_retains_attempt_and_reservation(self):
        def fail(*args):
            raise TimeoutError('stub timeout')
        ex = self.executor(fail)
        with self.assertRaises(TimeoutError):
            ex.call('f30:D:F:r:u', 'medium', 'prompt')
        self.assertEqual((self.b.attempts, self.b.charged),(1,8192))
        self.assertFalse(ex.cache)

    def test_production_evaluator_reconciles_with_dispatch(self):
        from collab_scheduler_v1 import fault30_run as fr, fault30_protocol as fp
        from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
        self.b.caps['new_request_attempts'] = 12
        self.b.caps['new_total_tokens'] = 12*8192
        ex = self.executor()
        ex.bindings.update(large='large', coder='coder')
        task = make_task()
        cid = 'DYNAMICDAG__HETEROGENEOUS__LOCAL_REROUTE__FRESH'
        # Forbid engine startup/calls even if accidental integration regresses.
        with patch('static_dag_v0.run.start_model', side_effect=AssertionError('GPU forbidden')), \
             patch('static_dag_v0.run.call_model', side_effect=AssertionError('LLM forbidden')):
            rows = fr.eval_config(cid, ex, fp.Ledger(), [task], {}, {task['uid']:task})
        row = rows[task['uid']]
        self.assertEqual(row['new_requests'], self.b.attempts)
        self.assertEqual(row['new_tokens'], self.b.actual_tokens)
        self.assertEqual(row['logical_calls'], len(ex.events))
        self.assertGreater(self.b.attempts, 0)


class RunnerTests(unittest.TestCase):
    def run_stub(self, fail=False):
        from . import smoke_runner as runner
        from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
        from static_dag_v0 import run as engine
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'collect/logs').mkdir(parents=True)
            protocol = json.loads((runner.PACKET / 'SMOKE_PROTOCOL.json').read_text())
            protocol['proposed_hard_budget'] = dict(CAPS, new_request_attempts=1000,
                                                   new_total_tokens=8192000)
            for name in ('SMOKE_PROTOCOL.json','TASK_MANIFEST.json'):
                (root / name).write_text('{}')
            tasks = [dict(make_task(), uid=f'stub-{i}') for i in range(8)]
            mock_response = response()
            if fail:
                mock_response['usage'] = None
            with patch.object(runner, 'PACKET', root), patch.object(runner, 'ROOT', root), \
                 patch.object(runner, 'sha', return_value='fixture'), \
                 patch.object(engine, 'OUT', root), \
                 patch.object(engine, 'start_model', return_value=(object(), object(), 0)) as start, \
                 patch.object(engine, 'stop_model') as stop, \
                 patch.object(engine, 'call_model', side_effect=lambda *a: dict(mock_response)) as call:
                result = runner.execute(protocol, tasks, 'stub')
                status = json.loads((root / 'runs/stub/STATUS.jsonl').read_text())
                self.assertEqual(status['attempts'], call.call_count)
                self.assertEqual(start.call_count, stop.call_count)
                with self.assertRaises(FileExistsError):
                    runner.execute(protocol, tasks, 'stub')
            if fail:
                self.assertEqual(result, 2)
                self.assertEqual(status['status'], 'INCOMPLETE')
                self.assertEqual(status['charged_tokens_including_reservations'],8192)
                self.assertEqual(status['completed_cells'], 0)
            else:
                self.assertEqual(result, 0)
                self.assertEqual(status['completed_cells'],64)
                self.assertEqual(status['status'], 'COMPLETE')
                self.assertFalse(status['pending'])

    def test_all_64_cells_with_stub_and_refuse_overwrite(self):
        self.run_stub()

    def test_missing_usage_stops_panel_and_cleans_up(self):
        self.run_stub(fail=True)


if __name__ == '__main__':
    unittest.main()
