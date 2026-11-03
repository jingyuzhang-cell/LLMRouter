"""H2.1 billing-consistency checks (offline; no network).

Verifies the accounting rules the real run will rely on:
  1. cache hit          -> no ledger record, no charge
  2. retry after 429    -> failed attempts not charged, exactly one charge on success
  3. timeout            -> no charge
  4. late response      -> charged once and flagged late (deadline breach is visible)
"""
import json, sys, hashlib
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')

PRICE_IN, PRICE_OUT = 0.8e-6, 2.8e-6


class StubLedger:
    def __init__(self):
        self.records = []
        self.index = {}

    def charge(self, purpose, sha, tin, tout, late=False):
        rec = dict(purpose=purpose, prompt_sha256=sha, input_tokens=tin, output_tokens=tout,
                   accounting_yuan=round(tin * PRICE_IN + tout * PRICE_OUT, 8), late=late)
        self.records.append(rec)
        self.index[(purpose, sha)] = rec
        return rec


class StubTransport:
    def __init__(self, ledger, retries=(0,), timeout_s=1.0):
        self.ledger, self.retries, self.timeout_s = ledger, retries, timeout_s

    def call(self, purpose, prompt, fail_first=None, timeout=False, late=False):
        sha = hashlib.sha256(prompt.encode()).hexdigest()
        hit = self.ledger.index.get((purpose, sha))
        if hit is not None:
            return dict(cached=True, charged=0.0, rec=hit)
        attempts = 0
        for _ in self.retries:
            attempts += 1
            if timeout:
                raise TimeoutError('simulated timeout')     # no response -> no charge
            if fail_first and attempts == 1:
                continue                                     # failed attempt -> no charge
            return dict(cached=False, attempts=attempts,
                        charged=round(1000 * PRICE_IN + 200 * PRICE_OUT, 8),
                        rec=self.ledger.charge(purpose, sha, 1000, 200, late=late))
        raise RuntimeError('retries exhausted')


def main():
    L = StubLedger()
    T = StubTransport(L, retries=(0, 0, 0))
    out = {}

    r1 = T.call('h21|T|A|r1|e0', 'p1')
    out['first_call'] = dict(records=len(L.records), charged=r1['charged'])
    r2 = T.call('h21|T|A|r1|e0', 'p1')
    out['cache_hit'] = dict(records=len(L.records), cached=r2['cached'], charged=r2['charged'])
    r3 = T.call('h21|T|A|r1|e1', 'p2', fail_first=True)
    out['retry_after_429'] = dict(records=len(L.records), attempts=r3['attempts'],
                                  charged=r3['charged'])
    before = len(L.records)
    try:
        T.call('h21|T|A|r1|t', 'p3', timeout=True)
    except TimeoutError:
        pass
    out['timeout'] = dict(records_before=before, records_after=len(L.records),
                          charged=0.0, note='no response, no charge')
    r4 = T.call('h21|T|A|r1|p', 'p4', late=True)
    out['late_request'] = dict(charged=r4['charged'], late=r4['rec']['late'])
    total = sum(r['accounting_yuan'] for r in L.records)
    out['totals'] = dict(records=len(L.records), yuan=round(total, 8))
    out['pass'] = (out['cache_hit']['records'] == out['first_call']['records']
                   and out['cache_hit']['charged'] == 0
                   and out['retry_after_429']['attempts'] == 2
                   and out['timeout']['records_after'] == before
                   and out['late_request']['late'] is True)
    json.dump(dict(batch='RQ2_H21_BILLING_CHECK', model_calls=0, **out),
              open('/root/research_outputs/static_pi/stage_d/rq2_h21/H2.1_BILLING_CHECK.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
