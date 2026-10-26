"""Simulated accounting assertions only; no model execution or tokenizer proof."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from reservation_guard import ReservationGuard, Stop


class GuardTests(unittest.TestCase):
    def make(self, **kwargs):
        return ReservationGuard({'CNY':'0.30','USD':'0.10'},certified=True,**kwargs)

    def test_unproven_denied(self):
        with self.assertRaisesRegex(Stop,'UNPROVEN'):
            ReservationGuard({'CNY':'0.30'})

    def test_atomic_concurrent_reservation(self):
        g=self.make()
        def reserve(i):
            try:g.reserve(str(i),'CNY','0.20',1024);return True
            except Stop:return False
        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(reserve,[0,1])),1)

    def test_exact_decimal_boundary(self):
        g=self.make()
        for i in range(3):g.reserve(str(i),'CNY','0.10',1024)
        with self.assertRaises(Stop):g.reserve('4','CNY','0.000001',1)

    def test_settlement_never_counts_same_money_twice(self):
        g=self.make();g.reserve('a','CNY','0.20',1);g.settle('a','0.10')
        g.reserve('b','CNY','0.20',1)
        self.assertEqual(str(g.spent['CNY']+g.reserved['CNY']),'0.30')

    def test_unknown_usage_keeps_reservation_and_stops(self):
        g=self.make();g.reserve('a','CNY','0.20',1)
        with self.assertRaises(Stop):g.settle('a')
        self.assertEqual(str(g.reserved['CNY']),'0.20')
        with self.assertRaises(Stop):g.reserve('b','USD','0.01',1)

    def test_bound_violation_cannot_claim_cash_safety(self):
        g=self.make();g.reserve('a','CNY','0.20',1)
        with self.assertRaisesRegex(Stop,'NOT_UNDONE'):g.settle('a','0.40')
        self.assertTrue(g.stopped)

    def test_duplicate_no_retry(self):
        g=self.make();g.reserve('a','CNY','0.01',1);g.settle('a','0.01')
        with self.assertRaises(Stop):g.reserve('a','CNY','0.01',1)

    def test_native_currency_separate(self):
        g=self.make();g.reserve('a','USD','0.10',1);g.reserve('b','CNY','0.30',1)
        with self.assertRaises(Stop):g.reserve('c','USD','0.01',1)

    def test_request_count_reserved_before_dispatch(self):
        g=self.make(max_calls=1);g.reserve('a','CNY','0.01',1)
        with self.assertRaises(Stop):g.reserve('b','CNY','0.01',1)

    def test_output_count_reserved_before_dispatch(self):
        g=self.make(max_output=1024);g.reserve('a','CNY','0.01',1024)
        with self.assertRaises(Stop):g.reserve('b','CNY','0.01',1)

    def test_wall_before_dispatch(self):
        now=[0]
        g=self.make(clock=lambda:now[0],wall_s=10)
        now[0]=10
        with self.assertRaisesRegex(Stop,'WALL'):g.reserve('a','CNY','0.01',1)

    def test_invalid_amounts(self):
        for value in ['NaN','Infinity','-1']:
            with self.assertRaises(ValueError):self.make().reserve('a','CNY',value,1)


if __name__=='__main__':unittest.main(verbosity=2)
