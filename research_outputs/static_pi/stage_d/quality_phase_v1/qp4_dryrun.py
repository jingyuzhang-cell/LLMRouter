"""QP4 offline dry run (zero calls): mock provider, factor separation audit,
budget table from measured ledger means, guard simulation."""
import json, collections, statistics as st, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp4_factorial as F
import qp2_chain as CH

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def task_means():
    agg = collections.defaultdict(lambda: dict(calls=0, yuan=0.0, tok=0))
    for path in (f'{QP}/QP1_LEDGER.jsonl', '/root/research_outputs/static_pi/stage_d/v23a/S2_LEDGER.jsonl'):
        import os
        if not os.path.exists(path):
            continue
        for line in open(path):
            x = json.loads(line)
            t = x['purpose'].split('|')[1]
            agg[t]['calls'] += 1
            agg[t]['yuan'] += x['accounting_yuan']
            agg[t]['tok'] += x['usage']['input_tokens'] + x['usage']['output_tokens']
    return {t: dict(mean_yuan=v['yuan'] / v['calls'], mean_tok=v['tok'] / v['calls'])
            for t, v in agg.items()}


def mean_call_cost():
    m = task_means()
    return st.mean(v['mean_yuan'] for v in m.values())


def budget():
    m = task_means()
    rows, tot = [], dict(calls=0, tokens=0, yuan=0.0)
    for t in F.TASKS:
        calls = 2 * 4 * 6
        yuan = calls * m[t]['mean_yuan'] * 1.08   # longer prompts (+8%)
        tok = calls * m[t]['mean_tok'] * 1.08
        rows.append(dict(task=t, calls=calls, est_yuan=round(yuan, 4), est_tokens=int(tok)))
        tot['calls'] += calls
        tot['yuan'] += yuan
        tot['tokens'] += int(tok)
    out = dict(batch='QP4_BUDGET', model_calls=0, per_task=rows,
               total=dict(calls=tot['calls'], tokens=tot['tokens'], yuan=round(tot['yuan'], 4)),
               hard_stop=F.CAPS)
    json.dump(out, open(f'{QP}/QP4_BUDGET.json', 'w'), ensure_ascii=False, indent=1)
    return out


def mock_provider(contract, cell):
    facts = contract['required_facts']
    f = F.FACTOR[cell]
    docs = sorted(contract['source_pages'].keys())
    half = (len(docs) + 1) // 2

    def ev_out(doc_ids, with_evidence):
        fs = []
        for x in facts:
            e = (x.get('source_evidence') or [{}])[0]
            if e.get('doc_id') not in doc_ids:
                continue
            ent = dict(field=x.get('bucket') or x['fact_id'], value=x['value'])
            if with_evidence:
                ent.update(doc=e.get('doc_id'), page=e.get('page'), quote=e.get('quote', ''))
            if f['h2']:
                ent['raw'] = x['value']
            fs.append(ent)
        return fs

    def call(node, system, user, max_tokens):
        if node == 'e0':
            return json.dumps({'facts': ev_out(docs[:half], f['h1'])}, ensure_ascii=False)
        if node == 'e1':
            return json.dumps({'facts': ev_out(docs[half:] or docs[:1], f['h1'])}, ensure_ascii=False)
        if node in ('t', 'r'):
            return json.dumps({'facts': [], 'relations': []}, ensure_ascii=False)
        if node == 'm':
            return json.dumps({'facts': ev_out(docs, False)}, ensure_ascii=False)
        if node == 'p':
            all_ev = ev_out(docs, True)
            ok_e, _ = CH.verify_evidence(
                [dict(field=e['field'], value=e.get('raw') or e['value'], doc=e['doc'],
                      page=e['page'], quote=e['quote']) for e in all_ev], contract)
            by_quote = {e['quote'] for e in ok_e}
            ans, abst = [], []
            for x in facts:
                e = (x.get('source_evidence') or [{}])[0]
                if f['h1'] and e.get('quote', '') not in by_quote:
                    abst.append(dict(item_id=x['fact_id'], text='证据表中无该槽位证据'))
                    continue
                value = x['value'] if (f['h2'] or not f['h1']) else x['value']
                a = dict(fact_id=x['fact_id'], value=value)
                if f['h1']:
                    a.update(doc=e.get('doc_id'), page=e.get('page'), quote=e.get('quote', ''))
                ans.append(a)
            abst += [dict(item_id=u['item_id'], text='无法判定')
                     for u in contract.get('unknown_items', [])]
            return json.dumps(dict(answers=ans, abstentions=abst, complete=True),
                              ensure_ascii=False)
        raise ValueError(node)
    return call


def main():
    bud = budget()
    results = F.main(mock=True)
    by = collections.defaultdict(list)
    for r in results:
        by[r['cell']].append(r)
    checks = dict(
        G1_wiring=all('error' not in r for r in results) and len(results) == 48,
        G2_h1_reuse=all(r['reuse_rate'] == 1.0 for r in results if r['cell'] in 'BD'),
        G3_factor_ladder=all(
            (F.FACTOR['B']['h1'] and not F.FACTOR['B']['h2'],
             not F.FACTOR['C']['h1'] and F.FACTOR['C']['h2'],
             F.FACTOR['D']['h1'] and F.FACTOR['D']['h2'])),
        G4_scoring=all(r['q'] is not None for r in results))
    macro = {c: round(st.mean(x['q'] for x in g), 4) for c, g in sorted(by.items())}
    json.dump(dict(batch='QP4_DRYRUN', real_calls=0, acceptance=checks,
                   mock_macro_q=macro, budget=bud['total'], hard_stop=F.CAPS,
                   randomization=[dict(task=t, rep=rp, cell=c, position=i + 1)
                                  for i, (t, rp, c) in enumerate(F.build_order())],
                   mock_results=results),
              open(f'{QP}/QP4_DRYRUN.json', 'w'), ensure_ascii=False, indent=1)
    print('acceptance:', checks)
    print('mock macro Q:', macro)
    print('budget:', bud['total'], 'hard stop:', F.CAPS)
    print('OFFLINE:', 'PASS' if all(checks.values()) else 'BLOCKED')


if __name__ == '__main__':
    main()
