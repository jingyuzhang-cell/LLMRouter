#!/usr/bin/env python3
"""G7 endpoint pre-design analysis (zero calls, zero model access).
A. Per-event attribution of the 10 TP->lost events (RSK6+HW2+HX1+JG1): G2/G6 status, cited doc,
   fact's allowed docs (stage requirement), stage-flip flag — Claude's supplement problem #2.
B. Stage-mismatch baseline for ALL 26 tasks x 2 reps x arms {G2, G6}:
   mismatch = fact cites doc d in {D1,D2}, fact's allowed_citation_docs is a strict subset
   (stage-sensitive fact), and d not in allowed (wrong-stage citation).
   Feeds the G7 fact-level primary-endpoint power simulation.
Reuses the M3-consistent reconstruction from p2c_mechanism_v2.py verbatim (same helpers).
Output: p2c_analysis/P2C_G7_ENDPOINT_BASELINE.json"""
import json, sys
from collections import defaultdict
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


def terminal(task, rep, arm):
    """M3-consistent terminal for G2/G6 (G6 fallback semantics per p2c_mechanism_v2)."""
    v = res[f'{task}_r{rep}']
    ctx = block_ctx(task, rep)
    if ctx is None:
        return None, 'shared_fail'
    ct, rows, base, slots3 = ctx
    if v.get('shared_fault') and arm != 'G1':
        return None, 'shared_fail'
    raw = raw_terminal(task, rep, arm)
    if arm == 'G6':
        status = v['arms']['G6']['status']
        if status == 'OK_NO_TARGET' or status.startswith('RECOVERY_FAILED'):
            raw = raw_terminal(task, rep, 'G2')
    return (apply_m3(raw, ct, rows, base, slots3) if raw else None), 'ok'


LOSS_TASKS = {'RSK_603803', 'HW_600360', 'HX_300427', 'JG_300093'}
events, baseline = [], {}
for t in sorted(meta):
    ct = json.loads(Path(meta[t]['file']).read_text())
    allowed = {f['fact_id']: set(f.get('allowed_citation_docs') or []) for f in ct['required_facts']}
    stage_sensitive = {f: (0 < len(a) < 2) for f, a in allowed.items()}          # 允许且仅允许一份文书
    task_rec = {}
    for rep in (1, 2):
        outs = {}
        for arm in ('G2', 'G6'):
            outs[arm], st_ = terminal(t, rep, arm)
        if outs['G2'] is None or outs['G6'] is None:
            task_rec[rep] = dict(state='shared_fail')
            continue
        sc = {a: S.score(outs[a], ct) for a in outs}
        rowstat = {a: {x['fact_id']: x['status'] for x in sc[a]['rows']} for a in outs}
        ans = {a: {x.get('fact_id'): x for x in outs[a].get('answers', []) if isinstance(x, dict)} for a in outs}
        mm = {}
        for a in outs:
            c = 0
            for f, sensitive in stage_sensitive.items():
                d = ans[a].get(f, {}).get('doc')
                if sensitive and d in ('D1', 'D2') and d not in allowed[f]:
                    c += 1
            mm[a] = c
        task_rec[rep] = dict(state='ok', mismatch=mm,
                             n_stage_sensitive=sum(stage_sensitive.values()), N=len(allowed))
        if t in LOSS_TASKS:
            for f in rowstat['G2']:
                if rowstat['G2'][f] == 'TP' and rowstat['G6'][f] != 'TP':
                    events.append(dict(task=t, rep=rep, fact=f,
                                       g2_status='TP', g6_status=rowstat['G6'][f],
                                       g2_doc=ans['G2'].get(f, {}).get('doc'),
                                       g6_doc=ans['G6'].get(f, {}).get('doc'),
                                       allowed=sorted(allowed[f]),
                                       stage_sensitive=stage_sensitive[f]))
    baseline[t] = task_rec

ok_reps = [(t, r) for t in baseline for r in (1, 2) if baseline[t][r].get('state') == 'ok']
g2_mm = sum(baseline[t][r]['mismatch']['G2'] for t, r in ok_reps)
g6_mm = sum(baseline[t][r]['mismatch']['G6'] for t, r in ok_reps)
sens = sum(baseline[t][r]['n_stage_sensitive'] for t, r in ok_reps)
out = dict(events=events, baseline=baseline,
           summary=dict(evaluable_reps=len(ok_reps), stage_sensitive_fact_slots=sens,
                        mismatch_G2=g2_mm, mismatch_G6=g6_mm))
(HERE / 'p2c_analysis/P2C_G7_ENDPOINT_BASELINE.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(f"可评价区组 {len(ok_reps)}/52；阶段敏感槽 {sens}")
print(f"错配数: G2={g2_mm}  G6={g6_mm}（恢复后残留）")
print('\n== 10 次 TP->lost 逐事件归因 ==')
for e in events:
    print(f"{e['task']}_r{e['rep']} {e['fact']}: TP->{e['g6_status']} 文书 {e['g2_doc']}->{e['g6_doc']} "
          f"允许={e['allowed']} 阶段敏感={e['stage_sensitive']}")
per_task_g6 = {t: sum(baseline[t][r]['mismatch']['G6'] for r in (1, 2) if baseline[t][r].get('state') == 'ok') for t in baseline}
print('\nG6 残留错配任务分布:', {t: c for t, c in sorted(per_task_g6.items(), key=lambda x: -x[1]) if c})
