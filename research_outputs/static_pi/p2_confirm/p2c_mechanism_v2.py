#!/usr/bin/env python3
"""M3-consistent mechanism rebuild (zero calls).
1. For every block, reconstruct each arm's terminal from LEDGER (G6 fallback semantics included),
   re-apply the runner's M3 post-processing deterministically (detect_m3 over reconstructed evidence rows
   and base total), rescore, and CHECK the result equals the stored Q in P2C_RESULTS.json (per arm).
2. Recompute fact transitions G2->G6 on the M3-consistent terminals (final scoring口径), recount stage flips.
3. Rebuild the 26-task mechanism table with the operator's split classes:
   共享上游失效 / 无恢复目标 / 动作无净变化 / 净损失 / 证据错误锚定 / 信息找回(+含锚定损失) / 证据数值纠偏.
Outputs: p2c_analysis/P2C_TASK_MECHANISM_V2.json + P2C_TASK_MECHANISM_TABLE_V2.md; prints reconciliation stats."""
import json, statistics as st, sys
from collections import defaultdict, Counter
from pathlib import Path

HERE = Path('/root/research_outputs/static_pi/p2_confirm')
sys.path.insert(0, str(HERE))
import p2c_runner as RUN
import p2c_scorer as S

R, D5, BT, OLD = RUN.R, RUN.D5, RUN.BT, RUN.OLD
res = json.loads((HERE / 'p2c_runs/P2C_RESULTS.json').read_text())
led = [json.loads(l) for l in open(HERE / 'p2c_runs/LEDGER.jsonl')]
led = [r for r in led if r['phase'] == 'done']
man = json.loads((HERE / 'P2C_FINAL_GOLD_MANIFEST_V3.json').read_text())
meta = {r['task']: r for r in man['contracts']}
ARMS = RUN.ARMS

def block_ctx(task, rep):
    rows_ = [r for r in led if r['task'] == task and r['rep'] == rep]
    e = {n: next((r['text'] for r in rows_ if r['arm'] == 'shared' and r['node'] == n and not r.get('fault')), None)
         for n in ('E_D1', 'E_D2')}
    if any(v is None for v in e.values()):
        return None
    ct = json.loads(Path(meta[task]['file']).read_text())
    docs = {d: v['pages']['1']['text'] for d, v in ct['source_pages'].items()}
    rows, _ = R.evidence_rows({'E_D1': e['E_D1'], 'E_D2': e['E_D2']}, R.SC.doc_index(ct))
    base = BT.total(OLD.extract_json(e['E_D2']), docs['D2'])
    slots3 = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate']) for f in ct['required_facts']]
    return ct, rows, base, slots3

def apply_m3(out, ct, rows, base, slots3):
    if not out:
        return out
    out = json.loads(json.dumps(out))
    m3 = D5.detect_m3(slots3, out, rows, base)
    viol = sorted((f for f, v in m3.items() if v['state'] == 'SELF_EVIDENCE_INCONSISTENT'), key=lambda x: int(x[1:]))
    if viol:
        out['answers'] = [a for a in out.get('answers', []) if not (isinstance(a, dict) and a.get('fact_id') in viol)]
        out['unknown_slots'] = sorted(set(map(str, out.get('unknown_slots', []))) | set(viol), key=lambda x: int(x[1:]))
    return out

def raw_terminal(task, rep, arm):
    rows_ = [r for r in led if r['task'] == task and r['rep'] == rep and r['arm'] == arm
             and r['node'] in ('SINK', 'G1') and not r.get('fault')]
    return json.loads(rows_[-1]['text']) if rows_ else None

mismatch, trans_all, flip_all = [], Counter(), Counter()
tasks_out = {}
for t in sorted(meta):
    reps_out = {}
    for rep in (1, 2):
        v = res[f'{t}_r{rep}']
        ctx = block_ctx(t, rep)
        if ctx is None:
            reps_out[rep] = dict(outcome='shared_fail', q_ok=None)
            continue
        ct, rows, base, slots3 = ctx
        shared_fail = bool(v.get('shared_fault'))
        terms, qcheck = {}, {}
        for a in ARMS:
            status = v['arms'][a]['status']
            if shared_fail and a != 'G1':
                terms[a], qcheck[a] = None, 0.0
                if round(v['arms'][a]['Q'], 6) != 0.0:
                    mismatch.append((f'{t}_r{rep}', a, 0.0, v['arms'][a]['Q']))
                continue
            raw = raw_terminal(t, rep, a)
            if a in ('G3', 'G4', 'G5', 'G6') and (status == 'OK_NO_TARGET' or status.startswith('RECOVERY_FAILED')):
                raw = raw_terminal(t, rep, 'G2')   # fallback / no-action: same object as G2 at runtime
            out = apply_m3(raw, ct, rows, base, slots3) if not shared_fail else raw  # shared-fail G1 is unscored pre-M3 at runtime
            terms[a] = out
            q = S.score(out, ct) if out else None
            qcheck[a] = 0.0 if out is None else round(q['Q_all'], 6)
            stored = round(v['arms'][a]['Q'], 6)
            if qcheck[a] != stored:
                mismatch.append((f'{t}_r{rep}', a, qcheck[a], stored))
        # transitions on M3-consistent terminals
        r2 = {x['fact_id']: x['status'] for x in S.score(terms['G2'], ct)['rows']} if terms['G2'] else None
        r6 = {x['fact_id']: x['status'] for x in S.score(terms['G6'], ct)['rows']} if terms['G6'] else None
        a2 = {a.get('fact_id'): a for a in (terms['G2'] or {}).get('answers', []) if isinstance(a, dict)}
        a6 = {a.get('fact_id'): a for a in (terms['G6'] or {}).get('answers', []) if isinstance(a, dict)}
        tr, flips = defaultdict(list), []
        if r2 and r6:
            for f in r2:
                if r2[f] != r6[f]:
                    tr[f'{r2[f]}->{r6[f]}'].append(f)
                    if r2[f] == 'TP' and r6[f] != 'TP' and a2.get(f, {}).get('doc') in ('D1', 'D2') \
                       and a6.get(f, {}).get('doc') != a2[f]['doc']:
                        flips.append(f)
        for k, fs in tr.items():
            trans_all[k] += len(fs)
        flip_all[len(flips)] += 1 if flips else 0
        st6 = v['arms']['G6']['status']
        outcome = ('shared_fail' if v.get('shared_fault') else 'no_target' if st6 == 'OK_NO_TARGET'
                   else 'recovery_truncated' if st6.startswith('RECOVERY_FAILED') else 'recovered')
        n6 = [r['node'] for r in led if r['task'] == t and r['rep'] == rep and r['arm'] == 'G6']
        reps_out[rep] = dict(outcome=outcome, action=('no_action' if not n6 else 'upstream_J2R+SINK' if 'J2R' in n6 else 'terminal_SINK_only'),
                             transitions={k: fs for k, fs in tr.items()}, stage_flips=flips,
                             Q2=v['arms']['G2']['Q'], Q6=v['arms']['G6']['Q'], Q4=v['arms']['G4']['Q'], q_ok=all(qcheck[a] == round(v['arms'][a]['Q'], 6) for a in ARMS))
    tasks_out[t] = dict(N=meta[t]['scored_N'], reps=reps_out,
                        H2=round(st.mean([res[f'{t}_r{r}']['arms']['G6']['Q'] - res[f'{t}_r{r}']['arms']['G2']['Q'] for r in (1, 2)]), 4),
                        H4=round(st.mean([res[f'{t}_r{r}']['arms']['G6']['Q'] - res[f'{t}_r{r}']['arms']['G4']['Q'] for r in (1, 2)]), 4))
# classification (operator's split)
def classify(t, d):
    outs = [d['reps'][r]['outcome'] for r in (1, 2)]
    TR = lambda r, suf: sum(len(v) for k, v in (d['reps'][r].get('transitions') or {}).items() if k.endswith(suf))
    gains = sum(TR(r, '->TP') for r in (1, 2))
    losses = sum(len(v) for r in (1, 2) for k, v in (d['reps'][r].get('transitions') or {}).items() if k.startswith('TP->'))
    flips = sum(len(d['reps'][r].get('stage_flips') or []) for r in (1, 2))
    absent = sum(len(v) for r in (1, 2) for k, v in (d['reps'][r].get('transitions') or {}).items() if k == 'ABSENT->TP')
    if all(o == 'shared_fail' for o in outs): cls = '共享上游失效型'
    elif all(o in ('shared_fail', 'no_target') for o in outs): cls = '无恢复目标型' + ('（一次重复共享失效）' if 'shared_fail' in outs else '')
    elif gains == 0 and losses == 0: cls = '动作无净变化型'
    elif gains == 0 and losses > 0: cls = '净损失型'
    elif flips >= 2 and losses > gains: cls = '证据错误锚定型'
    elif absent >= max(2, 0.7 * gains): cls = '信息找回型' + ('（含锚定损失）' if flips else '')
    else: cls = '证据/数值纠偏型'
    return cls, gains, losses, flips

rows = []
for t, d in tasks_out.items():
    cls, g, l, fl = classify(t, d)
    rows.append(dict(task=t, N=d['N'], H2=d['H2'], H4=d['H4'], cls=cls, gains=g, losses=l, flips=fl))
cc = defaultdict(lambda: [0, 0.0])
for r in rows:
    cc[r['cls']][0] += 1; cc[r['cls']][1] += r['H2']
out = dict(q_reconciliation=dict(blocks_checked=52 * 6, mismatches=mismatch),
           transitions_m3_consistent=dict(trans_all), rows=rows, class_summary={k: dict(n=v[0], sum_H2=round(v[1], 4)) for k, v in sorted(cc.items())},
           per_task=tasks_out)
(HERE / 'p2c_analysis/P2C_TASK_MECHANISM_V2.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
print('Q reconciliation mismatches:', len(mismatch), mismatch[:8])
print('M3-consistent transitions:', dict(trans_all))
for k, v in sorted(cc.items(), key=lambda x: -x[1][1]):
    print(f'{k}: n={v[0]} sumH2={v[1]:+.3f}')
print('total H2', round(sum(r['H2'] for r in rows), 4))
