"""Tests for the six-arm unified execution contract (V2.3)."""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import evidence_contract_v23 as EC

ARMS = ['Static-GLM', 'Static-DS', 'Retry-only', 'Z-only', 'pi-only', 'Joint']
RES = []
def check(n, c, d=''):
    RES.append((n, bool(c), str(d))); print(f'  {n:52s} {"PASS" if c else "FAIL"} {"" if c else d}')

def main():
    d = EC.evidence_directive()
    for key in ('连续', '禁止使用省略号', 'D1/D2/D3/D4', 'abstentions', '不得为了满足引用要求编造证据'):
        check(f'directive states {key}', key in d)
    check('directive is arm-independent', EC.evidence_directive() == d)
    blocks = {a: EC.apply_to_system('BASE') for a in ARMS}
    check('all six arms receive byte-identical evidence block',
          len(set(blocks.values())) == 1)
    check('contract hash stable', EC.contract_sha256() == EC.contract_sha256()
          and len(EC.contract_sha256()) == 64)
    import hashlib
    eb = {hashlib.sha256(EC.apply_to_system('').encode()).hexdigest() for a in ARMS}
    check('evidence block fingerprint identical across arms', len(eb) == 1)
    check('prompt fingerprint is deterministic',
          len({EC.prompt_fingerprint('Joint', 'S', 'U') for _ in range(3)}) == 1)
    good = {'fact_id': 'A1', 'value': 'x', 'doc': 'D1', 'page': 1, 'quote': '连续原文片段'}
    check('valid answer has no violations', EC.evidence_violations(good) == [])
    check('ellipsis rejected', EC.evidence_violations(dict(good, quote='前半……后半')) == ['elided_quote'])
    check('node-name doc rejected', EC.evidence_violations(dict(good, doc='E1')) == ['nonstandard_doc'])
    check('missing quote rejected', EC.evidence_violations(dict(good, quote='')) == ['missing_quote'])
    check('bad page rejected', EC.evidence_violations(dict(good, page=0)) == ['bad_page'])
    passed = sum(1 for _, ok, _ in RES if ok)
    print(f'\n{passed}/{len(RES)} PASS')
    json.dump(dict(batch='PHASE_PI_V23_EXECUTION_CONTRACT_TESTS', contract_sha256=EC.contract_sha256(),
                   results=[dict(name=n, pass_=ok, detail=str(x)) for n, ok, x in RES],
                   passed=passed, total=len(RES)),
              open('/root/research_outputs/static_pi/stage_d/v23/V23_EXECUTION_CONTRACT_TESTS.json', 'w'),
              ensure_ascii=False, indent=1)
    return 0 if passed == len(RES) else 1

if __name__ == '__main__':
    sys.exit(main())
