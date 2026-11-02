"""E04_P2_REFERENCE_FACTS validator (ZERO model calls).

Acceptance per protocol §七: every fact must carry a verbatim evidence span
that exists in its stated document (whitespace-stripped containment), all six
categories present, counts consistent, fact-id roster emitted for the report
prompt. Run: python3 m8_p2_facts_check.py  (exit 0 iff all pass)
"""
import json
import re
import sys

FACTS = 'E04_P2_REFERENCE_FACTS.json'
DOCS = {
    'doc1': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20260910.txt',
    'doc2': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261009.txt',
    'doc3': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261013.txt',
}


def norm(s):
    return re.sub(r'\s+', '', s)


def main():
    spec = json.load(open(FACTS, encoding='utf-8'))
    docs = {k: norm(open(p, encoding='utf-8').read()) for k, p in DOCS.items()}
    facts = spec['facts']
    errors = []

    ids = [f['fact_id'] for f in facts]
    if len(ids) != len(set(ids)):
        errors.append('duplicate fact_id')

    for f in facts:
        fid = f['fact_id']
        if f['evidence_doc'] not in docs:
            errors.append(f'{fid}: unknown doc {f["evidence_doc"]}')
            continue
        if norm(f['evidence_span']) not in docs[f['evidence_doc']]:
            errors.append(f'{fid}: span NOT found in {f["evidence_doc"]}')
        rule = f['value_match_rule']
        if rule == 'set' and not f.get('required_elements'):
            errors.append(f'{fid}: set rule without required_elements')
        if rule in ('exact_string', 'numeric', 'date') and not f.get('allowed_expressions'):
            errors.append(f'{fid}: {rule} rule without allowed_expressions')

    cats = {f['category'] for f in facts}
    expected_cats = set(spec['summary']['categories'])
    if cats != expected_cats:
        errors.append(f'category set mismatch: {cats ^ expected_cats}')
    if len(facts) != spec['summary']['n_facts']:
        errors.append('n_facts mismatch')
    n_crit = sum(1 for f in facts if f['critical'])
    if n_crit != spec['summary']['n_critical']:
        errors.append(f'n_critical mismatch: {n_crit}')

    # numeric facts: the expected number must itself appear inside the span
    for f in facts:
        if f['value_match_rule'] == 'numeric':
            vals = [v.replace(',', '') for v in f['allowed_expressions']]
            if not any(v in norm(f['evidence_span']).replace(',', '') for v in vals):
                errors.append(f'{f["fact_id"]}: numeric value not grounded in span')

    for e in errors:
        print(f'  [FAIL] {e}')
    n_pass = len(facts) * 1  # span checks are the per-fact gate
    if errors:
        print(f'\nFAILED: {len(errors)} error(s)')
        return 1
    print(f'  [PASS] {len(facts)}/{len(facts)} evidence spans verified verbatim '
          f'in stated docs (whitespace-stripped)')
    print(f'  [PASS] categories {sorted(cats)} all present; '
          f'critical {n_crit}/{len(facts)}')
    print(f'  [PASS] all numeric values grounded in their spans')
    roster = [{'fact_id': f['fact_id'], 'category': f['category']} for f in facts]
    json.dump(roster, open('E04_P2_FACT_ROSTER.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'  [PASS] report-prompt roster written: E04_P2_FACT_ROSTER.json '
          f'({len(roster)} entries, ids+categories only)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
