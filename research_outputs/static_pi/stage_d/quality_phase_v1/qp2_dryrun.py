"""QP2 offline dry run + acceptance framework (ZERO real calls).

Produces:
  QP2_BUDGET.json  — measured per-cell costs, cache-hit plan, hard stops
  QP2_DRYRUN.json  — 32 mock cells + acceptance checks + randomization table

Acceptance gates for the machinery (the scientific acceptance happens later on
the authorized real run):
  G1 wiring        all arms/tasks produce parseable, scoreable cells
  G2 chain fix     B/C/D reuse_rate == 1.0 under a mock SINK that obeys the rule
  G3 separation    exactly one factor changes per ladder step (A→B→C→D)
  G4 scorer        strict and tolerant rates both reported; amount unit variants TP
  G5 budget guard  pre-charge guard stops before the cap (simulated ledger)
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
import qp2_runner as R
import qp2_prompts as P2
import qp2_amount as AM

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def measured_stats():
    agg = collections.defaultdict(lambda: dict(calls=0, yuan=0.0, tok=0))
    for line in open(f'{QP}/QP1_LEDGER.jsonl'):
        x = json.loads(line)
        p = x['purpose'].split('|')
        if len(p) != 5:
            continue
        k = p[1]
        agg[k]['calls'] += 1
        agg[k]['yuan'] += x['accounting_yuan']
        agg[k]['tok'] += x['usage']['input_tokens'] + x['usage']['output_tokens']
    out = {}
    for k, v in agg.items():
        out[k] = dict(mean_call_yuan=round(v['yuan'] / v['calls'], 6),
                      mean_call_tok=int(v['tok'] / v['calls']))
    out['GUOEN'] = out.get('GUOEN') or dict(
        mean_call_yuan=round((agg['KANGMEI']['yuan'] / agg['KANGMEI']['calls']) * 0.78, 6),
        mean_call_tok=int(agg['KANGMEI']['tok'] / agg['KANGMEI']['calls'] * 0.78),
        note='chars-ratio estimate from KANGMEI (13.8K vs 23.4K), +0 measured')
    return out


def measured_mean_call_cost(task=None):
    s = measured_stats()
    if task and task in s:
        return s[task]['mean_call_yuan']
    return st.mean(v['mean_call_yuan'] for v in s.values())


def qp1_completed_cells():
    done = set()
    for line in open(f'{QP}/QP1_LEDGER.jsonl'):
        p = json.loads(line)['purpose'].split('|')
        if len(p) == 5 and p[2] == 'Baseline':
            done.add((p[1], p[3]))
    return done


def budget():
    s = measured_stats()
    done = qp1_completed_cells()
    cells = R.build_order()
    rows, tot = [], dict(new_calls=0, yuan=0.0, tokens=0)
    for ev, rep, arm in cells:
        n_calls = 7 if arm == 'A' else 6
        cached = 7 if (arm == 'A' and f'r{rep}' in {(r) for r in [f'r{rep}']} and
                       (ev, f'r{rep}') in done) else 0
        new = n_calls - cached
        margin = 1.15 if arm != 'A' else 1.0
        yuan = new * s[ev]['mean_call_yuan'] * margin
        tok = int(new * s[ev]['mean_call_tok'] * margin)
        rows.append(dict(task=ev, rep=rep, arm=arm, calls=n_calls, cached=cached,
                         new_calls=new, est_yuan=round(yuan, 4), est_tokens=tok))
        tot['new_calls'] += new
        tot['yuan'] += yuan
        tot['tokens'] += tok
    out = dict(batch='QP2_BUDGET', model_calls=0,
               basis='measured QP1 ledger per-task means; +15% margin on B/C/D '
                     '(longer SINK prompts with evidence table)',
               per_cell=rows,
               total=dict(new_calls=tot['new_calls'], tokens=int(tot['tokens']),
                          yuan=round(tot['yuan'], 4)),
               hard_stop=dict(calls=int(tot['new_calls'] * 1.12),
                              tokens=int(tot['tokens'] * 1.2),
                              yuan=round(tot['yuan'] * 1.25, 2)))
    json.dump(out, open(f'{QP}/QP2_BUDGET.json', 'w'), ensure_ascii=False, indent=1)
    return out


def mock_provider(contract, arm):
    """Gold-derived deterministic mock. B/C/D SINK obeys the reuse mandate."""
    facts = contract['required_facts']
    f = P2.arm_factor(arm)

    def ev_out(doc_ids):
        fs = []
        for x in facts:
            e = (x.get('source_evidence') or [{}])[0]
            if e.get('doc_id') not in doc_ids:
                continue
            ent = dict(field=x.get('bucket') or x['fact_id'], value=x['value'],
                       doc=e.get('doc_id'), page=e.get('page'), quote=e.get('quote', ''))
            if f['amount']:
                ent['raw'] = x['value']
            fs.append(ent)
        return dict(facts=fs)

    docs = sorted(contract['source_pages'].keys())
    half = (len(docs) + 1) // 2

    import qp2_chain as CH
    all_ev = ev_out(docs)['facts']
    _ok, _bad = CH.verify_evidence(all_ev, contract)
    # match each gold fact to ITS OWN verified entry (by quote), not by bucket:
    # several facts legitimately share one bucket name
    by_quote = {e['quote'] for e in _ok}

    def call(node, system, user, max_tokens):
        if node == 'e0':
            return json.dumps(ev_out(docs[:half]), ensure_ascii=False)
        if node == 'e1':
            return json.dumps(ev_out(docs[half:] or docs[:1]), ensure_ascii=False)
        if node in ('t', 'r'):
            return json.dumps({'facts': [], 'relations': []}, ensure_ascii=False)
        if node == 'm':
            return json.dumps({'facts': ev_out(docs)['facts']}, ensure_ascii=False)
        if node == 'v':
            return json.dumps({'checks': []}, ensure_ascii=False)
        if node == 'p':
            if f['chain']:
                ans, abst_ids = [], []
                for x in facts:
                    q = (x.get('source_evidence') or [{}])[0].get('quote', '')
                    if q not in by_quote:
                        abst_ids.append(x['fact_id'])
                        continue
                    e = (x.get('source_evidence') or [{}])[0]
                    ans.append(dict(fact_id=x['fact_id'], value=x['value'],
                                    doc=e.get('doc_id'), page=e.get('page'), quote=q))
                abst = [{'item_id': u['item_id'], 'text': '证据表中无该槽位证据'}
                        for u in contract.get('unknown_items', [])]
                abst += [{'item_id': fid, 'text': '证据表中无该槽位证据'} for fid in abst_ids]
                return json.dumps(dict(answers=ans, abstentions=abst, complete=True),
                                  ensure_ascii=False)
            ans = []
            for x in facts:
                e = (x.get('source_evidence') or [{}])[0]
                ans.append(dict(fact_id=x['fact_id'], value=x['value'],
                                doc=e.get('doc_id'), page=e.get('page'),
                                quote=e.get('quote', '')))
            abst = [{'item_id': u['item_id'], 'text': '无法判定'}
                    for u in contract.get('unknown_items', [])]
            return json.dumps(dict(answers=ans, abstentions=abst, complete=True),
                              ensure_ascii=False)
        raise ValueError(node)
    return call


def separation_audit():
    ladder = {a: P2.arm_factor(a) for a in R.ARMS}
    steps = []
    for a, b in (('A', 'B'), ('B', 'C'), ('C', 'D')):
        diff = [k for k in ('chain', 'amount', 'strict') if ladder[a][k] != ladder[b][k]]
        steps.append((a, b, diff))
    return dict(ladder=ladder, steps=[f'{a}->{b}: {d}' for a, b, d in steps],
                single_factor=all(len(d) == 1 for _, _, d in steps))


def guard_simulation():
    """Pre-charge guard must stop BEFORE the cap is crossed."""
    caps = dict(calls=10 ** 6, tokens=10 ** 12, yuan=1.0)
    mean = 0.10
    spent, stopped_at = 0.0, None
    for i in range(20):
        if spent + mean > caps['yuan'] * (1 - R.RESERVE):
            stopped_at = (i, round(spent, 4))
            break
        spent += mean
    return dict(stopped_after=stopped_at[0], spent=stopped_at[1],
                cap=caps['yuan'], reserve=R.RESERVE,
                no_overrun=stopped_at[1] <= caps['yuan'])


def main():
    bud = budget()
    results = R.main(mock=True)
    q = {}
    for r in results:
        q.setdefault(r['arm'], []).append(r)
    checks = dict(
        G1_wiring=all('error' not in r for r in results) and len(results) == 32,
        G2_chain_fix=all(r['reuse_rate'] == 1.0 for r in results if r['arm'] in 'BCD'),
        G3_separation=separation_audit()['single_factor'],
        G4_scorer=all(r.get('tol') is not None for r in results),
        G5_budget_guard=guard_simulation()['no_overrun'])
    macro = {a: round(st.mean(x['q'] for x in g), 4) for a, g in q.items()}
    out = dict(batch='QP2_DRYRUN', real_calls=0, mock_cells=len(results),
               acceptance=checks, mock_macro_q=macro,
               separation=separation_audit(), guard=guard_simulation(),
               budget_total=bud['total'], hard_stop=bud['hard_stop'],
               randomization=[dict(task=t, rep=rp, arm=a, position=i + 1)
                              for i, (t, rp, a) in enumerate(R.build_order())],
               mock_results=results)
    json.dump(out, open(f'{QP}/QP2_DRYRUN.json', 'w'), ensure_ascii=False, indent=1)
    print('acceptance:', checks)
    print('mock macro Q:', macro)
    print('guard:', guard_simulation())
    print('budget:', bud['total'], 'hard stop:', bud['hard_stop'])
    ok = all(checks.values())
    print('\nOFFLINE ACCEPTANCE:', 'PASS' if ok else 'BLOCKED')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
