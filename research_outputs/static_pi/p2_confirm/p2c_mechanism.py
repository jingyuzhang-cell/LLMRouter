#!/usr/bin/env python3
"""26-task mechanism decomposition from frozen P2-C data (zero model calls; unit = task, reps in detail).
Per task: doc count, scored N; per rep: anomaly states/targets, G6 action (Z/R from ledger node sequence),
recovery outcome, G2 terminal defect profile (ABSENT / value-wrong / citation-wrong counts), fact-level
G2->G6 transitions (ABSENT->TP = 信息找回; other nonTP->TP = 证据/数值纠偏; TP->nonTP = 损失, with doc-stage flip
flag), per-arm resource use; task-level H2/H4 diffs and a mechanism class. Outputs JSON + markdown table."""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path

HERE = Path('/root/research_outputs/static_pi/p2_confirm')
GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
sys.path.insert(0, str(HERE))
import p2c_scorer as S

ARMS = ['G1', 'G2', 'G3', 'G4', 'G5', 'G6']
res = json.loads((HERE / 'p2c_runs/P2C_RESULTS.json').read_text())
led = [json.loads(l) for l in open(HERE / 'p2c_runs/LEDGER.jsonl')]
led = [r for r in led if r['phase'] == 'done']
man = json.loads((HERE / 'P2C_FINAL_GOLD_MANIFEST_V3.json').read_text())
meta = {r['task']: r for r in man['contracts']}

term_cache = {}
def terminal(task, rep, arm):
    k = (task, rep, arm)
    if k in term_cache:
        return term_cache[k]
    rows = [r for r in led if r['task'] == task and r['rep'] == rep and r['arm'] == arm
            and r['node'] in ('SINK', 'G1') and not r.get('fault')]
    term_cache[k] = json.loads(rows[-1]['text']) if rows else None
    return term_cache[k]

def nodes(task, rep, arm):
    return [r['node'] for r in led if r['task'] == task and r['rep'] == rep and r['arm'] == arm]

def res_use(task, arm):
    rs = [r for r in led if r['task'] == task and r['arm'] == arm]
    return dict(calls=len(rs), tokens=sum((r.get('in') or 0) + (r.get('out') or 0) for r in rs),
                yuan=round(sum(r.get('yuan_accounting') or 0 for r in rs), 4),
                yuan_marg=round(sum(r.get('yuan_marginal') or 0 for r in rs), 4))

tasks = sorted(meta)
rows, agg = [], defaultdict(int)
for t in tasks:
    ct = json.loads(Path(meta[t]['file']).read_text())
    N = meta[t]['scored_N']
    reps = {}
    for rep in (1, 2):
        v = res[f'{t}_r{rep}']
        states = defaultdict(int)
        for s in v['states'].values():
            states[s] += 1
        st6 = v['arms']['G6']['status']
        n6 = nodes(t, rep, 'G6')
        action = ('no_action' if not n6 else 'upstream_J2R+SINK' if 'J2R' in n6 else 'terminal_SINK_only')
        outcome = ('shared_fail' if v.get('shared_fault') else
                   'no_target' if st6 == 'OK_NO_TARGET' else
                   'recovery_truncated' if st6.startswith('RECOVERY_FAILED') else 'recovered')
        t2, t6 = terminal(t, rep, 'G2'), terminal(t, rep, 'G6')
        if t2 is None or t6 is None:
            reps[rep] = dict(outcome=outcome, action=action, defects=None, transitions=None)
            continue
        r2 = {x['fact_id']: x for x in S.score(t2, ct)['rows']}
        r6 = {x['fact_id']: x for x in S.score(t6, ct)['rows']}
        a2 = {a.get('fact_id'): a for a in t2.get('answers', []) if isinstance(a, dict)}
        a6 = {a.get('fact_id'): a for a in t6.get('answers', []) if isinstance(a, dict)}
        defects = dict(ABSENT=sum(r2[f]['status'] == 'ABSENT' for f in r2),
                       value_wrong=sum(r2[f]['status'] in ('VALUE_WRONG', 'CONFLICT') for f in r2),
                       cite_wrong=sum(r2[f]['status'] in ('LOC_WRONG', 'UNSUPPORTED') for f in r2),
                       tp=sum(r2[f]['status'] == 'TP' for f in r2))
        trans = defaultdict(list)
        for f in r2:
            s2, s6 = r2[f]['status'], r6[f]['status']
            if s2 != s6:
                key = f'{s2}->{s6}'
                if s6 == 'TP':
                    key = f'{s2}->TP'
                elif s2 == 'TP':
                    key = 'TP->lost'
                trans[key].append(f)
                agg[key] += 1
        stage_flip = [f for f in trans.get('TP->lost', [])
                      if (a2.get(f, {}).get('doc') in ('D1', 'D2')) and a6.get(f, {}).get('doc') != a2[f]['doc']]
        reps[rep] = dict(outcome=outcome, action=action,
                         anomaly=dict(S1=states['S1'], S2=states['S2'], S3=states['S3'], targets=len(v['targets'])),
                         defects=defects,
                         transitions={k: v2 for k, v2 in trans.items()},
                         stage_flip_losses=stage_flip,
                         Q2=v['arms']['G2']['Q'], Q6=v['arms']['G6']['Q'], Q4=v['arms']['G4']['Q'])
    dH2 = st.mean([res[f'{t}_r{r}']['arms']['G6']['Q'] - res[f'{t}_r{r}']['arms']['G2']['Q'] for r in (1, 2)])
    dH4 = st.mean([res[f'{t}_r{r}']['arms']['G6']['Q'] - res[f'{t}_r{r}']['arms']['G4']['Q'] for r in (1, 2)])
    TR = lambda r, k: ((reps[r].get('transitions') or {}).get(k) or [])
    gains = sum(len(v) for r in (1, 2) for k, v in (reps[r].get('transitions') or {}).items() if k.endswith('->TP'))
    losses = sum(len(TR(r, 'TP->lost')) for r in (1, 2))
    flips = sum(len(reps[r].get('stage_flip_losses') or []) for r in (1, 2))
    absent_gain = sum(len(TR(r, 'ABSENT->TP')) for r in (1, 2))
    if all(reps[r]['outcome'] in ('shared_fail', 'no_target') for r in (1, 2)):
        cls = '无恢复机会（共享失效/无目标）'
    elif flips >= 2 and losses > gains:
        cls = '证据错误锚定型'
    elif gains == 0 and losses == 0:
        cls = '动作无净变化'
    elif absent_gain >= max(2, 0.7 * gains):
        cls = '信息找回型' + ('（含锚定损失）' if flips else '')
    elif gains > 0:
        cls = '证据/数值纠偏型'
    else:
        cls = '净损失型'
    rows.append(dict(task=t, N=N, docs=2, H2=round(dH2, 4), H4=round(dH4, 4),
                     mechanism=cls, gains=gains, losses=losses, stage_flips=flips,
                     g6=res_use(t, 'G6'), g2=res_use(t, 'G2'), reps=reps))

out = dict(aggregate_transitions=dict(agg), tasks=rows)
(HERE / 'p2c_analysis/P2C_TASK_MECHANISM.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))

# markdown
L = ['# P2-C 26 任务机制分解表（零调用，源自冻结数据；统计单位=任务，重复见明细）', '',
     '事实迁移合计（两次重复、全部任务）：' + '，'.join(f'{k}={v}' for k, v in sorted(agg.items())), '',
     '| 任务 | 计分槽 | G6−G2 | G6−G4 | 机制归类 | 找回/纠偏 | 损失 | 阶段漂移 | G6臂 调用/tokens/¥ |',
     '|---|---:|---:|---:|---|---:|---:|---:|---|']
for r in rows:
    L.append(f"| {r['task']} | {r['N']} | {r['H2']:+.3f} | {r['H4']:+.3f} | {r['mechanism']} | {r['gains']} | {r['losses']} | {r['stage_flips']} | {r['g6']['calls']}/{r['g6']['tokens']}/{r['g6']['yuan']:.2f} |")
L += ['', '## 逐重复明细（异常、动作、结果、事实迁移）', '']
for r in rows:
    L.append(f"**{r['task']}**（N={r['N']}，G6−G2={r['H2']:+.3f}，{r['mechanism']}）")
    for rep in ('1', '2'):
        v = r['reps'][int(rep)]
        an = v.get('anomaly'); tr = v.get('transitions')
        line = f"- r{rep}: {v['outcome']}｜动作={v['action']}"
        if an:
            line += f"｜异常 S1/S2/S3={an['S1']}/{an['S2']}/{an['S3']}（目标{an['targets']}）"
        if v.get('defects') is not None:
            d = v['defects']
            line += f"｜G2缺陷: 遗漏{d['ABSENT']} 值错{d['value_wrong']} 引错{d['cite_wrong']} TP{d['tp']}"
            line += f"｜Q2={v['Q2']:.3f}→Q6={v['Q6']:.3f}"
        if tr:
            for k, fs in sorted(tr.items()):
                line += f"｜{k}: {','.join(fs)}"
            if v.get('stage_flip_losses'):
                line += f"｜阶段漂移(D1↔D2): {','.join(v['stage_flip_losses'])}"
        L.append(line)
    L.append('')
(HERE / 'p2c_analysis/P2C_TASK_MECHANISM_TABLE.md').write_text('\n'.join(L) + '\n')
from collections import Counter
print(Counter(r['mechanism'] for r in rows))
print('aggregate', dict(agg))
print('sum H2 by class:')
cc = defaultdict(float)
for r in rows:
    cc[r['mechanism']] += r['H2']
for k, v in sorted(cc.items(), key=lambda x: -x[1]):
    print(f'  {k}: {v:+.3f}')
