"""S2 ablation-fidelity audit (zero calls; reads the ledger).

For every B-condition cell, check whether the target document's E output still
contains the target slots' values (amount-aware / normalized containment). If it
does, the field was NOT ablated in practice and the S2 verdict is uninterpretable.
Also audits A-condition extraction as the baseline.

Output: S2_ABLATION_AUDIT.json
"""
import json, re, sys, unicodedata
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
import s2_grade as G
from real_provider_v22 import extract_any

ROOT = '/root/research_outputs/static_pi/stage_d/v23a'


def norm(x):
    x = unicodedata.normalize('NFKC', str(x if x is not None else ''))
    return re.sub(r'\s+', '', x)


def contains_value(output_obj, value, fid):
    text = norm(json.dumps(output_obj, ensure_ascii=False))
    v = norm(value)
    if v and v in text:
        return True
    # amount-aware: any numeric token from the value that parses equal in text
    for m in re.findall(r'-?\d[\d,，.]*', str(value)):
        n = norm(m).replace(',', '')
        if n and n in text.replace(',', '').replace('，', ''):
            return True
    return False


def main():
    recs = [json.loads(l) for l in open(f'{ROOT}/S2_LEDGER.jsonl')]
    cands = {t['event_key']: t for t in json.load(open(f'{ROOT}/TASK_CANDIDATES_V23A.json'))['candidates']}
    by = {}
    for r in recs:
        p = r['purpose'].split('|')
        if len(p) < 5:
            continue
        task, cond, rep, node = p[1], p[2], p[3], p[4]
        by.setdefault((task, cond, rep), {})[node] = r
    out = {}
    for (task, cond, rep), nodes in sorted(by.items()):
        cand = cands.get(task)
        if not cand:
            continue
        contract = json.load(open(cand['contract']))
        facts = {f['fact_id']: f for f in contract['required_facts']}
        tdocs = sorted({(facts[f].get('source_evidence') or [{}])[0].get('doc_id')
                        for f in cand['target_slots'] if f in facts} - {None})
        leaks, checked = [], 0
        for doc in tdocs:
            rec = nodes.get(f'E:{doc}')
            if not rec:
                continue
            try:
                obj = extract_any(rec['text'])
            except Exception:
                obj = {'raw': rec['text']}
            for fid in cand['target_slots']:
                f = facts.get(fid)
                if not f:
                    continue
                checked += 1
                if contains_value(obj, f.get('value'), fid):
                    leaks.append(dict(fact_id=fid, doc=doc, value=str(f.get('value'))[:40]))
        out.setdefault(task, {})[f'{cond}|{rep}'] = dict(
            target_docs=tdocs, checked=checked, leaks=leaks, n_leaks=len(leaks))
    summary = {}
    for task, cells in out.items():
        b = [c for k, c in cells.items() if k.startswith('B')]
        a = [c for k, c in cells.items() if k.startswith('A')]
        summary[task] = dict(
            A_leak_rate=round(sum(c['n_leaks'] for c in a) / max(1, sum(c['checked'] for c in a)), 3),
            B_leak_rate=round(sum(c['n_leaks'] for c in b) / max(1, sum(c['checked'] for c in b)), 3),
            B_cells_with_leak=sum(1 for c in b if c['n_leaks']),
            B_cells=len(b))
    json.dump(dict(batch='PHASE_V23A_S2_ABLATION_AUDIT', model_calls=0,
                   note='leak = target value still present in the target document E output',
                   summary=summary, detail=out),
              open(f'{ROOT}/S2_ABLATION_AUDIT.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{'task':34s} {'A_leak':>7s} {'B_leak':>7s} {'B_cells_leak':>12s}")
    for t, s in summary.items():
        print(f"{t[:34]:34s} {s['A_leak_rate']:7.2f} {s['B_leak_rate']:7.2f} "
              f"{s['B_cells_with_leak']}/{s['B_cells']:>11d}")
    tot_b = sum(s['B_cells'] for s in summary.values())
    leak_b = sum(s['B_cells_with_leak'] for s in summary.values())
    print(f'\nB cells with at least one target value still extracted: {leak_b}/{tot_b}')


if __name__ == '__main__':
    main()
