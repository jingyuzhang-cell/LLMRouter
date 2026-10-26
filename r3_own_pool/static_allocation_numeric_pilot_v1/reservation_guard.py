"""Offline-tested reservation accounting, NOT provider token certification.

No network, credentials, environment reads or experiment imports. Caller must
certify token bounds/rates before constructing a dispatch-capable guard.
"""
from decimal import Decimal, InvalidOperation
from threading import RLock
from time import monotonic


class Stop(RuntimeError):
    pass


def amount(value):
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid amount') from exc
    if not d.is_finite() or d < 0:
        raise ValueError('amount must be finite and nonnegative')
    return d


class ReservationGuard:
    def __init__(self, caps, max_calls=20, max_output=49152,
                 wall_s=3600, certified=False, clock=monotonic):
        if not certified:
            raise Stop('UNPROVEN_TOKEN_OR_RATE_BOUND')
        if max_calls <= 0 or max_output <= 0 or wall_s <= 0:
            raise ValueError('invalid limits')
        self.caps = {k: amount(v) for k,v in caps.items()}
        self.spent = {k: Decimal(0) for k in caps}
        self.reserved = {k: Decimal(0) for k in caps}
        self.max_calls, self.max_output = max_calls, max_output
        self.wall_s, self.clock, self.start = wall_s, clock, clock()
        self.claims, self.output_reserved = {}, 0
        self.stopped = False
        self.lock = RLock()

    def reserve(self, request_id, currency, cash_bound, output_cap):
        bound = amount(cash_bound)
        if type(output_cap) is not int or output_cap <= 0:
            raise ValueError('invalid output limit')
        with self.lock:
            if self.stopped:
                raise Stop('BATCH_STOPPED')
            if self.clock()-self.start >= self.wall_s:
                self.stopped = True
                raise Stop('WALL_LIMIT')
            if request_id in self.claims:
                raise Stop('NO_RETRY_OR_DUPLICATE')
            if len(self.claims) >= self.max_calls:
                raise Stop('REQUEST_LIMIT')
            if currency not in self.caps:
                raise Stop('UNKNOWN_CURRENCY')
            if self.output_reserved+output_cap > self.max_output:
                raise Stop('OUTPUT_LIMIT')
            if self.spent[currency]+self.reserved[currency]+bound > self.caps[currency]:
                raise Stop('CASH_RESERVATION_LIMIT')
            self.reserved[currency] += bound
            self.output_reserved += output_cap
            self.claims[request_id] = {'currency':currency,'bound':bound,'settled':False}

    def settle(self, request_id, actual_cash=None, failed=False):
        with self.lock:
            claim = self.claims[request_id]
            if claim['settled']:
                raise Stop('DOUBLE_SETTLEMENT')
            if failed or actual_cash is None:
                # Unknown billing cannot release the reservation or allow more work.
                self.stopped = True
                raise Stop('FAILED_OR_UNKNOWN_USAGE_RESERVATION_RETAINED')
            try:
                actual = amount(actual_cash)
            except ValueError:
                self.stopped = True
                raise Stop('INVALID_USAGE_RESERVATION_RETAINED')
            if actual > claim['bound']:
                # Cannot undo external billing: reject the certification and stop.
                self.stopped = True
                raise Stop('BOUND_VIOLATED_EXTERNAL_COST_NOT_UNDONE')
            currency = claim['currency']
            self.reserved[currency] -= claim['bound']
            self.spent[currency] += actual
            claim['settled'] = True
