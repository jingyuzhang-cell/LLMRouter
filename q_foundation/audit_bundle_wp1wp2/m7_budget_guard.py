"""M7-3B Work Package 2: GROSS Budget Guard (ZERO model calls) — v1.1 hardened.

A reservation-aware hard-cap ledger between the decision engine and the
executor. Guarantees by construction:

  G1  Separate accounting: call-count and tokens each tracked as
      (settled actual) vs (outstanding reservations); the engine's net
      dc_hat (decision-comparison delta) is a different number and is
      never conflated with this ledger.
  G2  Reservation vs actual recorded separately per call; settle() replaces
      the reservation with the TRUE consumption.
  G3  No double-use of quota: reservations keyed by (node, attempt);
      duplicates rejected; concurrent nodes' reservations all bind the cap.
      v1.1: ALL mutating operations serialize under an internal lock —
      concurrent reserve() calls cannot interleave check-then-act (audit
      concern #1). The M7-3 driver is serial by design; the lock is the
      second line of defense.
  G4  Failed / timeout / cancelled calls keep TRUE consumption. Cancel
      releases only UNSETTLED reservations and is idempotent. Unknown
      actual consumption settles provisionally at the reserved amount,
      flagged 'unknown_actual', and is revisable.
  G5  Over-budget is a HARD stop raised at RESERVE time (pre-call gate):
        settled + sum(outstanding) + reserve_amount <= max_tokens
        settled_calls + len(outstanding) + calls <= max_calls
      v1.1: per-call reservation is not a flat constant — the caller passes
      the calibrated upper bound
        per_call_reserve = calibrated_input_bound + margin x max_output_tokens
      (pilot v2.2 lesson). The GLOBAL guarantee is conditional on actuals
      respecting the calibrated bound; any breach is caught post-settle,
      flagged, and never hidden (audit concern #2). There is no silent path.
  G6  Post-settle overrun (actual > reserved) recorded truthfully and fed
      to margin recalibration.

  v1.1 settle-consistency hardening (audit concern #3):
    - settle() on a key with NO outstanding reservation raises
      SettleWithoutReservation (every launch must be reserved; prevents
      double settle / phantom settle)
    - revise() adjusts an already-settled entry by its true delta —
      handles late responses after timeout settle and provisional
      unknown-actual corrections; never double-counts
    - cancel() is idempotent (second cancel releases 0)

Deterministic (no clock, no randomness); thread-safe via internal lock.
"""
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class BudgetExceeded(RuntimeError):
    """Hard stop. Raised by reserve() when the G5 invariant would break."""


class DuplicateReservation(RuntimeError):
    """G3: (node, attempt) already holds an outstanding reservation."""


class SettleWithoutReservation(RuntimeError):
    """v1.1: settle/revise on a key that has no settled record — every
    settle must follow a reserve; prevents double/phantom accounting."""


@dataclass(frozen=True)
class SettleRecord:
    node: str
    attempt: int
    actual_in: int
    actual_out: int
    reserved: int
    outcome: str            # success | failed | timeout | unknown_actual
    overrun: bool


@dataclass
class GrossBudgetGuard:
    max_calls: int
    max_tokens: int
    reserve_per_call: int = 2500            # fallback flat calibration
    label: str = 'M7-3'

    settled_actual: int = 0
    settled_calls: int = 0
    outstanding: Dict[Tuple[str, int], int] = field(default_factory=dict)
    _settled_keys: Dict[Tuple[str, int], SettleRecord] = field(default_factory=dict)
    journal: List[dict] = field(default_factory=list)
    _overruns: List[SettleRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------- queries --

    @property
    def guaranteed_settled(self) -> int:
        return self.settled_actual

    @property
    def conservative_outstanding_plus_settled(self) -> int:
        return self.settled_actual + sum(self.outstanding.values())

    def headroom(self, calls: int = 1,
                 per_call_reserve: Optional[int] = None) -> Tuple[bool, int, int]:
        with self._lock:
            tok = self.max_tokens - self.conservative_outstanding_plus_settled
            cal = self.max_calls - self.settled_calls - len(self.outstanding)
            need = calls * (per_call_reserve or self.reserve_per_call)
            return (tok >= need and cal >= calls, tok, cal)

    # --------------------------------------------------------- operations --

    def reserve(self, node: str, attempt: int, calls: int = 1,
                per_call_reserve: Optional[int] = None) -> int:
        """Pre-call hard gate. per_call_reserve should be the calibrated
        upper bound: calibrated_input_bound + margin x max_output_tokens."""
        with self._lock:
            key = (node, attempt)
            if key in self.outstanding:
                raise DuplicateReservation(f'{key} already reserved')
            amount = calls * (per_call_reserve or self.reserve_per_call)
            tok_slack = self.max_tokens - self.conservative_outstanding_plus_settled
            call_slack = self.max_calls - self.settled_calls - len(self.outstanding)
            if amount > tok_slack or calls > call_slack:
                self.journal.append({'op': 'reserve_denied', 'node': node,
                                     'attempt': attempt, 'calls': calls,
                                     'amount': amount, 'tok_slack': tok_slack,
                                     'call_slack': call_slack})
                raise BudgetExceeded(
                    f'G5 hard stop: need {amount} tok/{calls} calls, slack '
                    f'{tok_slack} tok/{call_slack} calls (settled='
                    f'{self.settled_actual}, outstanding='
                    f'{sum(self.outstanding.values())})')
            self.outstanding[key] = amount
            self.journal.append({'op': 'reserve', 'node': node, 'attempt': attempt,
                                 'calls': calls, 'reserved_tok': amount})
            return amount

    def settle(self, node: str, attempt: int, actual_in: Optional[int],
               actual_out: Optional[int], outcome: str = 'success') -> SettleRecord:
        """Replace the reservation with TRUE consumption. actuals None ->
        provisional at reserved amount with outcome 'unknown_actual'
        (revisable via revise()). Settling a non-reserved key is an error."""
        with self._lock:
            key = (node, attempt)
            if key not in self.outstanding:
                raise SettleWithoutReservation(
                    f'{key} has no outstanding reservation — double/phantom '
                    f'settle refused')
            reserved = self.outstanding.pop(key)
            if actual_in is None or actual_out is None:
                actual_in, actual_out, outcome = 0, reserved, 'unknown_actual'
            actual = actual_in + actual_out
            rec = SettleRecord(node=node, attempt=attempt, actual_in=actual_in,
                               actual_out=actual_out, reserved=reserved,
                               outcome=outcome, overrun=actual > reserved)
            self.settled_actual += actual
            self.settled_calls += 1
            self._settled_keys[key] = rec
            if rec.overrun:
                self._overruns.append(rec)
            self.journal.append({'op': 'settle', 'node': node, 'attempt': attempt,
                                 'actual_tok': actual, 'reserved_tok': reserved,
                                 'outcome': outcome, 'overrun': rec.overrun})
            return rec

    def revise(self, node: str, attempt: int, actual_in: int, actual_out: int,
               note: str = 'late_response') -> SettleRecord:
        """Adjust an already-settled entry to its true consumption by DELTA
        (handles late responses after timeout settle and provisional
        unknown-actual corrections). Never counts twice: only the difference
        between true and previously-settled is applied."""
        with self._lock:
            key = (node, attempt)
            old = self._settled_keys.get(key)
            if old is None:
                raise SettleWithoutReservation(
                    f'{key} has no settled record to revise')
            old_actual = old.actual_in + old.actual_out
            new_actual = actual_in + actual_out
            delta = new_actual - old_actual
            self.settled_actual += delta          # may be negative: correction
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
        """Release an UNSETTLED reservation; idempotent (second cancel -> 0)."""
        with self._lock:
            key = (node, attempt)
            released = self.outstanding.pop(key, 0)
            self.journal.append({'op': 'cancel', 'node': node, 'attempt': attempt,
                                 'released_tok': released})
            return released

    def summary(self) -> dict:
        with self._lock:
            return {'label': self.label,
                    'settled_actual_tokens': self.settled_actual,
                    'settled_calls': self.settled_calls,
                    'outstanding_reservations': len(self.outstanding),
                    'outstanding_tokens': sum(self.outstanding.values()),
                    'conservative_binding': self.conservative_outstanding_plus_settled,
                    'caps': {'tokens': self.max_tokens, 'calls': self.max_calls,
                             'reserve_per_call': self.reserve_per_call},
                    'overruns': [{'node': r.node, 'attempt': r.attempt,
                                  'actual': r.actual_in + r.actual_out,
                                  'reserved': r.reserved} for r in self._overruns],
                    'journal_len': len(self.journal)}
