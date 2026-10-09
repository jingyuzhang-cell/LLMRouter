"""Zero-call tests: physical accounting, dry runs, exact 8/1/2/5 case."""
import unittest
from .fault30_run import physical_accounting


def record(tokens=100, latency=.2, **flags):
    response = dict(usage=dict(total_tokens=tokens), latency_s=latency)
    if 'alias_of' in flags:
        return dict(alias_of=flags['alias_of'], response=response)
    response.update(flags)
    return dict(response=response)


class PhysicalAccountingTests(unittest.TestCase):
    def test_user_example(self):
        rows = [record() for _ in range(5)] + [record(injected_fault=True)] + [
            record(tokens=9999, latency=900, alias_of='old:a'),
            record(tokens=9999, latency=900, alias_of='old:b')]
        got = physical_accounting(rows)
        self.assertEqual((got['logical_calls'], got['injected_calls'],
                          got['cache_hits'], got['new_requests']), (8, 1, 2, 5))
        self.assertEqual(got['new_tokens'], 500)
        self.assertAlmostEqual(got['new_latency_s'], 1)

    def test_dry_is_not_physical(self):
        got = physical_accounting([record(dry_new=True), record(alias_of='dry:old')])
        self.assertEqual(got['dry_calls'], 1)
        for field in ('new_requests', 'new_tokens', 'new_latency_s'):
            self.assertEqual(got[field], 0)

    def test_cache_only(self):
        got = physical_accounting([record(alias_of='historical')])
        self.assertEqual(got['cache_hits'], 1)
        for field in ('new_requests', 'new_tokens', 'new_latency_s'):
            self.assertEqual(got[field], 0)

    def test_failed_attempt_usage_still_counts(self):
        rec = record(tokens=73, latency=2)
        rec['response']['status'] = 'failed'
        got = physical_accounting([rec])
        self.assertEqual(got['new_requests'], 1)
        self.assertEqual(got['new_tokens'], 73)
        self.assertEqual(got['new_latency_s'], 2)

    def test_empty(self):
        self.assertEqual(physical_accounting([])['new_requests'], 0)


if __name__ == '__main__':
    unittest.main()
