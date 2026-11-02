"""M7-3B WP2: GROSS Budget Guard — v2.1 (P0 remediation, audit rounds 1+2).

Round 1 (unified remediation list B1-B5):
  B1  A settled (node, attempt) can never be re-reserved: reserve() rejects
      keys present in _settled_keys with AlreadySettled. Every execution
      instance is one-shot.
  B2  Invalid reservations are rejected (InvalidReservation): non-positive
      OR non-integer OR boolean per_call_reserve / calls.
  B3  Outstanding reservations carry BOTH reserved tokens AND reserved CALL
      COUNT. Call-cap arithmetic uses reserved calls; settle() increments
      settled_calls by the reserved count or an explicitly reported executed
      subset, which must be a true integer in [1, reserved_calls] — ZERO is
      refused (a consumed execution counts >=1 call; a launch that never
      happened is released via cancel(), never a zero-call settle). A
      refused settlement RESTORES the reservation (nothing is consumed).
  B4  Partial-unknown settlement keeps KNOWN values: unknown sides are
      provisionally filled only up to the reserved headroom, flagged in
      provisional_parts, and revisable. Overrun computed on the combined
      total.
  B5  Invalid actuals are rejected in settle()/revise() (InvalidSettlement):
      negative OR non-integer OR boolean values. revise() may apply a
      negative DELTA — a legitimate downward correction, not a fabricated
      headroom increase.

Round 2 (operator independent-audit findings):
  -   executed_calls range/type hard constraint (see B3 above).
  -   Strict integer typing for ALL ledger quantities (bool excluded).
  -   headroom() shares the exact parameter gate of reserve()
      (_validate_reservation_params) — feasibility and enforcement can
      never disagree on which inputs are legal.

All v1.1 guarantees (G1-G6, internal lock, journal, no silent path) are
preserved. Deterministic; thread-safe; zero model calls.
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class BudgetExceeded(RuntimeError):
    """Hard stop. Raised by reserve() when the G5 invariant would break."""


class DuplicateReservation(RuntimeError):
    """An outstanding reservation already exists for this key."""


class AlreadySettled(RuntimeError):
    """B1: this (node, attempt) was already settled — execution instances
    are one-shot; re-reserving would double-count calls and tokens."""


class SettleWithoutReservation(RuntimeError):
    """No outstanding reservation and no settled record for this key."""


class InvalidReservation(RuntimeError):
    """B2: non-positive per_call_reserve or calls."""


class InvalidSettlement(RuntimeError):
    """B5: negative actual token values."""


def _valid_int(v) -> bool:
    """Strict non-negative-integer gate: excludes bool (a subclass of int)
    and non-integers. Ledger quantities are integers only."""
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_reservation_params(calls: int, unit: int) -> None:
    """Shared param gate for reserve() AND headroom() — the feasibility
    query and the enforcement gate must accept exactly the same inputs
    (audit: headroom/reserve calibration consistency)."""
    if not _valid_int(calls) or calls < 1:
        raise InvalidReservation(
            f'calls must be an integer >= 1 (got {calls!r})')
    if not _valid_int(unit) or unit <= 0:
        raise InvalidReservation(
            f'per_call_reserve must be a positive integer (got {unit!r})')


@dataclass(frozen=True)
class OutstandingReservation:
    reserved_tok: int
    calls: int


@dataclass(frozen=True)
class SettleRecord:
    node: str
    attempt: int
    actual_in: int
    actual_out: int
    reserved: int
    outcome: str
    overrun: bool
    provisional_parts: Tuple[str, ...] = ()   # ('in',) / ('out',) / both


@dataclass
class GrossBudgetGuard:
    max_calls: int
    max_tokens: int
    reserve_per_call: int = 2500
    label: str = 'M7-3'

    settled_actual: int = 0
    settled_calls: int = 0
    outstanding: Dict[Tuple[str, int], OutstandingReservation] = field(default_factory=dict)
    _settled_keys: Dict[Tuple[str, int], SettleRecord] = field(default_factory=dict)
    journal: List[dict] = field(default_factory=list)
    _overruns: List[SettleRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------- queries --

    @property
    def guaranteed_settled(self) -> int:
        return self.settled_actual

    @property
    def outstanding_tokens(self) -> int:
        return sum(r.reserved_tok for r in self.outstanding.values())

    @property
    def outstanding_calls(self) -> int:
        return sum(r.calls for r in self.outstanding.values())

    @property
    def conservative_outstanding_plus_settled(self) -> int:
        return self.settled_actual + self.outstanding_tokens

    def headroom(self, calls: int = 1,
                 per_call_reserve: Optional[int] = None) -> Tuple[bool, int, int]:
        with self._lock:
            unit = per_call_reserve if per_call_reserve is not None \
                else self.reserve_per_call
            _validate_reservation_params(calls, unit)   # same gate as reserve()
            tok = self.max_tokens - self.conservative_outstanding_plus_settled
            cal = self.max_calls - self.settled_calls - self.outstanding_calls
            need = calls * unit
            return (tok >= need and cal >= calls, tok, cal)

    # --------------------------------------------------------- operations --

    def reserve(self, node: str, attempt: int, calls: int = 1,
                per_call_reserve: Optional[int] = None) -> int:
        """Pre-call hard gate (G5): settled + outstanding(tok) + amount <=
        max_tokens AND settled + outstanding(calls) + calls <= max_calls."""
        with self._lock:
            key = (node, attempt)
            # B2 (+audit): strict integer/type gate, shared with headroom()
            unit = per_call_reserve if per_call_reserve is not None \
                else self.reserve_per_call
            try:
                _validate_reservation_params(calls, unit)
            except InvalidReservation:
                self.journal.append({'op': 'reserve_invalid', 'node': node,
                                     'attempt': attempt, 'calls': calls,
                                     'per_call_reserve': unit})
                raise
            if key in self.outstanding:
                raise DuplicateReservation(f'{key} already reserved')
            # B1: settled keys are one-shot execution instances
            if key in self._settled_keys:
                self.journal.append({'op': 'reserve_denied_settled', 'node': node,
                                     'attempt': attempt})
                raise AlreadySettled(
                    f'{key} already settled — execution instances are '
                    f'one-shot; re-reserve refused')
            amount = calls * unit
            tok_slack = self.max_tokens - self.conservative_outstanding_plus_settled
            call_slack = self.max_calls - self.settled_calls - self.outstanding_calls
            if amount > tok_slack or calls > call_slack:
                self.journal.append({'op': 'reserve_denied', 'node': node,
                                     'attempt': attempt, 'calls': calls,
                                     'amount': amount, 'tok_slack': tok_slack,
                                     'call_slack': call_slack})
                raise BudgetExceeded(
                    f'G5 hard stop: need {amount} tok/{calls} calls, slack '
                    f'{tok_slack} tok/{call_slack} calls (settled='
                    f'{self.settled_actual}, outstanding_tok='
                    f'{self.outstanding_tokens}, outstanding_calls='
                    f'{self.outstanding_calls})')
            self.outstanding[key] = OutstandingReservation(amount, calls)
            self.journal.append({'op': 'reserve', 'node': node, 'attempt': attempt,
                                 'calls': calls, 'reserved_tok': amount})
            return amount

    def settle(self, node: str, attempt: int, actual_in: Optional[int],
               actual_out: Optional[int], outcome: str = 'success',
               executed_calls: Optional[int] = None) -> SettleRecord:
        """Replace the reservation with TRUE consumption.

        B4: known sides are never overwritten. Unknown sides are filled
        provisionally only up to the reserved amount (conservative), flagged
        in provisional_parts, and revisable via revise().
        B3: settled_calls += the reservation's reserved call count (or the
        explicitly reported executed subset — the discrepancy is journaled).
        B5: negative actuals rejected.
        """
        with self._lock:
            key = (node, attempt)
            if key not in self.outstanding:
                raise SettleWithoutReservation(
                    f'{key} has no outstanding reservation — double/phantom '
                    f'settle refused')
            res = self.outstanding.pop(key)
            # B3 (+audit round 3): executed_calls must be a true integer in
            # [1, reserved_calls]. ZERO is REFUSED: an execution instance
            # that consumed tokens counts at least one call, and a launch
            # that never happened must be released via cancel(), never via a
            # zero-call settle — otherwise call quota is silently freed
            # (operator-reproduced bypass). Any violation restores the
            # reservation (a refused op consumes nothing).
            if executed_calls is not None and (
                    not _valid_int(executed_calls)
                    or executed_calls < 1 or executed_calls > res.calls):
                self.journal.append({'op': 'settle_invalid', 'node': node,
                                     'attempt': attempt,
                                     'executed_calls': executed_calls,
                                     'reserved_calls': res.calls})
                self.outstanding[key] = res
                raise InvalidSettlement(
                    f'executed_calls must be an integer in '
                    f'[1, {res.calls}] (got {executed_calls!r}); a launch '
                    f'that never happened must use cancel(), not a '
                    f'zero-call settle')
            # (+audit) actual token values must be true non-negative integers
            for side, v in (('in', actual_in), ('out', actual_out)):
                if v is not None and (not _valid_int(v) or v < 0):
                    self.journal.append({'op': 'settle_invalid', 'node': node,
                                         'attempt': attempt, 'side': side,
                                         'value': v})
                    self.outstanding[key] = res
                    raise InvalidSettlement(
                        f'{side} tokens must be a non-negative integer '
                        f'(got {v!r})')
            known = {s: v for s, v in (('in', actual_in), ('out', actual_out))
                     if v is not None}
            known_sum = sum(known.values())
            provisional_parts = tuple(s for s in ('in', 'out') if s not in known)
            if provisional_parts:
                outcome = 'partial_unknown' if known else 'unknown_actual'
                total = max(res.reserved_tok, known_sum)
            else:
                total = known_sum
            a_in = known.get('in', 0 if 'in' in provisional_parts else 0)
            # distribute provisional headroom ONLY to unknown sides; known
            # sides keep their values in every branch (B4: the fully-known
            # case must not clobber actual_out with prov_total)
            prov_total = total - known_sum
            if 'in' in provisional_parts and 'out' in provisional_parts:
                a_in, a_out = prov_total, 0
            elif 'in' in provisional_parts:
                a_in, a_out = prov_total, known.get('out', 0)
            elif 'out' in provisional_parts:
                a_in, a_out = known.get('in', 0), prov_total
            else:
                a_in, a_out = known.get('in', 0), known.get('out', 0)
            rec = SettleRecord(node=node, attempt=attempt, actual_in=a_in,
                               actual_out=a_out, reserved=res.reserved_tok,
                               outcome=outcome, overrun=total > res.reserved_tok,
                               provisional_parts=provisional_parts)
            used_calls = res.calls if executed_calls is None else executed_calls
            self.settled_actual += total
            self.settled_calls += used_calls
            self._settled_keys[key] = rec
            if rec.overrun:
                self._overruns.append(rec)
            self.journal.append({'op': 'settle', 'node': node, 'attempt': attempt,
                                 'actual_tok': total, 'reserved_tok': res.reserved_tok,
                                 'reserved_calls': res.calls,
                                 'executed_calls': used_calls,
                                 'outcome': outcome, 'overrun': rec.overrun,
                                 'provisional_parts': list(provisional_parts)})
            return rec

    def revise(self, node: str, attempt: int, actual_in: int, actual_out: int,
               note: str = 'late_response') -> SettleRecord:
        """Adjust an already-settled entry to true consumption by DELTA.
        B5: new values must be >= 0 (negative delta itself is legitimate)."""
        with self._lock:
            key = (node, attempt)
            old = self._settled_keys.get(key)
            if old is None:
                raise SettleWithoutReservation(
                    f'{key} has no settled record to revise')
            # (+audit) revise targets must be true non-negative integers
            for side, v in (('in', actual_in), ('out', actual_out)):
                if not _valid_int(v) or v < 0:
                    self.journal.append({'op': 'revise_invalid', 'node': node,
                                         'attempt': attempt, 'side': side,
                                         'value': v})
                    raise InvalidSettlement(
                        f'revise {side} must be a non-negative integer '
                        f'(got {v!r})')
            old_actual = old.actual_in + old.actual_out
            new_actual = actual_in + actual_out
            delta = new_actual - old_actual
            self.settled_actual += delta
            rec = SettleRecord(node=node, attempt=attempt, actual_in=actual_in,
                               actual_out=actual_out, reserved=old.reserved,
                               outcome=f'revised:{old.outcome}',
                               overrun=new_actual > old.reserved)
            self._settled_keys[key] = rec
            if delta > 0 and new_actual > old.reserved:
                self._overruns.append(rec)
            self.journal.append({'op': 'revise', 'node': node, 'attempt': attempt,
                                 'old_tok': old_actual, 'new_tok': new_actual,
                                 'delta': delta, 'note': note})
            return rec

    def cancel(self, node: str, attempt: int) -> int:
        """Release an UNSETTLED reservation; idempotent."""
        with self._lock:
            key = (node, attempt)
            released = self.outstanding.pop(key, OutstandingReservation(0, 0)).reserved_tok
            self.journal.append({'op': 'cancel', 'node': node, 'attempt': attempt,
                                 'released_tok': released})
            return released

    def summary(self) -> dict:
        with self._lock:
            return {'label': self.label,
                    'settled_actual_tokens': self.settled_actual,
                    'settled_calls': self.settled_calls,
                    'outstanding_reservations': len(self.outstanding),
                    'outstanding_tokens': self.outstanding_tokens,
                    'outstanding_calls': self.outstanding_calls,
                    'conservative_binding': self.conservative_outstanding_plus_settled,
                    'caps': {'tokens': self.max_tokens, 'calls': self.max_calls,
                             'reserve_per_call': self.reserve_per_call},
                    'overruns': [{'node': r.node, 'attempt': r.attempt,
                                  'actual': r.actual_in + r.actual_out,
                                  'reserved': r.reserved} for r in self._overruns],
                    'journal_len': len(self.journal)}
