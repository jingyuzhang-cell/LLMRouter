"""Regression tests for the execution stack (zero-call).
Locks in the two fixes whose loss caused real-batch failures:
  T1 _doc_text MUST reach the prompt (lost once -> 69% empty outputs)
  T2 contract gate tiering returns reason codes
  T3 real output cap = 3072 (truncation cause, 2/6 failures)
"""
import os
import sys

sys.path.insert(0, '/root/r3_own_pool/deadline_reward_v1')
sys.path.insert(0, '/root/r3_own_pool')
os.environ['RUNTIME_V2_GO'] = '1'


class FakeDS:
    def __init__(self):
        self.prompt = None
        self.max_out = None

    def __call__(self, prompt, creds, max_out_tokens=2048):
        self.prompt = prompt
        self.max_out = max_out_tokens
        return dict(answer='{"facts": ["x"]}', tokens_in=len(prompt) // 2,
                    tokens_out=5, latency_s=1.0, cash_cny=0.0)


def test_t1_doc_in_prompt():
    from runtime_v2_exec import RealBackend, Meter
    import runtime_v2_retrieval as RET
    b = RealBackend.__new__(RealBackend)
    b.meter = Meter(); b.cap_calls = 10; b.cap_cash = 10.0
    b._call_ds = FakeDS(); b._creds = {}
    b.rp = RET.LocalCorpusProvider()
    node = dict(id='n1', role='extraction', inputs=[],
                contract=dict(produces=['facts']),
                _doc_text='DOCMARKER' * 500)
    b.execute(node, 'Flash', [])
    assert 'DOCMARKER' in b._call_ds.prompt, 'T1 FAIL: doc lost again'
    assert len(b._call_ds.prompt) > 3000, 'T1 FAIL: prompt too short'
    print('T1 doc-in-prompt: PASS')


def test_t2_gate_reasons():
    from runtime_v2_exec import enforce_contract
    ok, why, _ = enforce_contract('{"facts": []}', ['facts'])
    assert not ok and 'empty_field' in why[1]
    ok, why, _ = enforce_contract('not json', ['facts'])
    assert not ok and 'parse_fail' in why[1]
    ok, why, _ = enforce_contract('{"facts": ["x"]}', ['facts'])
    assert ok and why is None
    print('T2 gate reason codes: PASS')


def test_t3_output_cap():
    from runtime_v2_exec import RealBackend, Meter
    import runtime_v2_retrieval as RET
    b = RealBackend.__new__(RealBackend)
    b.meter = Meter(); b.cap_calls = 10; b.cap_cash = 10.0
    b._call_ds = FakeDS(); b._creds = {}
    b.rp = RET.LocalCorpusProvider()
    node = dict(id='n1', role='extraction', inputs=[],
                contract=dict(produces=['facts']))
    b.execute(node, 'Flash', [])
    assert b._call_ds.max_out == 3072, 'T3 FAIL: cap not 3072'
    print('T3 output cap 3072: PASS')


if __name__ == '__main__':
    test_t1_doc_in_prompt()
    test_t2_gate_reasons()
    test_t3_output_cap()
    print('ALL PASS')


def test_t4_full_output_saved():
    """Stage-B/C precondition: ledger keeps COMPLETE terminal answers
    (operator ruling 2026-10-29: truncation allowed for display only)."""
    import json
    from runtime_v2_exec import RealBackend, Meter
    import runtime_v2_retrieval as RET
    b = RealBackend.__new__(RealBackend)
    b.meter = Meter(); b.cap_calls = 10; b.cap_cash = 10.0
    long_answer = '{"facts": ["' + 'LONGFACT' * 400 + '"]}'
    class F2(FakeDS):
        def __call__(self, prompt, creds, max_out_tokens=2048):
            super().__call__(prompt, creds, max_out_tokens)
            return dict(answer=long_answer, tokens_in=100, tokens_out=99,
                        latency_s=1.0, cash_cny=0.0)
    b._call_ds = F2(); b._creds = {}
    b.rp = RET.LocalCorpusProvider()
    node = dict(id='n1', role='extraction', inputs=[],
                contract=dict(produces=['facts']))
    b.execute(node, 'Flash', [])
    rec = b.meter.events[-1] if b.meter.events else None
    import json as _j
    # read the last ledger line instead
    line = open('/root/r3_own_pool/deadline_reward_v1/runtime_v2_corpus/'
                'NODE_LEDGER.jsonl').readlines()[-1]
    r = _j.loads(line)
    assert len(r['output_text']) == len(long_answer), 'T4 FAIL: truncated'
    print('T4 full-output-in-ledger: PASS (%d chars)' % len(r['output_text']))
