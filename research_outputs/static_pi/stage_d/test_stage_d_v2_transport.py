"""Offline tests for the V2.0 transport. NO network calls."""
import json, os, sys, tempfile
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import stage_d_v2_transport as T

def test_request_shape():
    b = T.build_request('glm53flash', 'S', 'U', 100)
    assert b['thinking'] == {'type': 'enabled'}, b['thinking']
    assert b['reasoning_effort'] == 'low', b.get('reasoning_effort')
    assert 'response_format' not in b
    b2 = T.build_request('deepseek', 'S', 'U', 100)
    assert b2['thinking'] == {'type': 'disabled'}, b2['thinking']
    b3 = T.build_request('deepseek', 'S', 'return JSON', 100)
    assert b3.get('response_format') == {'type': 'json_object'}
    b4 = T.build_request('deepseek', 'S', 'plain', 100)
    assert 'response_format' not in b4
    print('  request_shape: PASS')

def test_ledger_fields():
    d = tempfile.mkdtemp(); p = os.path.join(d, 'l.jsonl')
    L = T.Ledger(p)
    L.add(dict(usage=dict(input_tokens=100, output_tokens=50), accounting_yuan=T.accounting_yuan(100, 50),
               alias='glm53flash', thinking_mode='enabled', reasoning_effort='low'))
    rec = json.loads(open(p).read().strip())
    for f in ('thinking_mode', 'reasoning_effort', 'accounting_yuan', 'usage', 'alias'):
        assert f in rec, f
    assert L.tokens == 150
    print(f'  ledger_fields: PASS (tokens={L.tokens}, cost=¥{L.cost:.6f})')

def test_cost_math():
    assert abs(T.accounting_yuan(1_000_000, 0) - 0.8) < 1e-9
    assert abs(T.accounting_yuan(0, 1_000_000) - 2.8) < 1e-9
    print('  cost_math: PASS (1M in = ¥0.8, 1M out = ¥2.8)')

def test_retry_cap_logic():
    d = tempfile.mkdtemp(); p = os.path.join(d, 'l.jsonl')
    L = T.Ledger(p)
    for i in range(3):
        L.add(dict(usage=dict(input_tokens=10, output_tokens=10), accounting_yuan=T.accounting_yuan(10,10),
                   alias='deepseek', thinking_mode='disabled', reasoning_effort=None))
    tr = T.Transport(L, cap_calls=3)
    try:
        tr.call('deepseek', 's', 'u', 10, 'x', timeout_s=1)
        raise AssertionError('should have raised on cap')
    except RuntimeError as e:
        assert 'cap' in str(e)
    print('  call_cap: PASS')

if __name__ == '__main__':
    print('=== V2.0 transport offline tests (no network) ===')
    test_request_shape(); test_ledger_fields(); test_cost_math(); test_retry_cap_logic()
    print('ALL PASS')
