#!/usr/bin/env python3
"""P2-B pilot executor: 3 tasks × 2 replicates × 6 arms (G1-G6).
Extends the QS runner pattern to multi-task with the corrected G4 rule (P2-A.1 V1.1)."""
import argparse, hashlib, json, os, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SD = HERE.parent / 'stage_d'
sys.path[:0] = [str(HERE), str(SD / 'sc_e1_1'), str(SD / 'sc_e1_1' / 'fork_t1'), str(SD), str(SD / 'qs_confirm')]
import sc_e1_1_runner as R
import sc_e1_runner as OLD
import detectors_v5 as D5
import base_total_v2 as BT
import safety_metrics as SM
import render_fork_t1 as TXT

OUT = HERE / 'p2_runs'
TASKS = [
    ('ZQ_300526', Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT/TASK_CONTRACT_ZQ_300526_v1.json'), 'bf08ccb8'),
    ('CY_600525', Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT/TASK_CONTRACT_CY_600525_v1.json'), 'f7e58047'),
    ('SL_002766', Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT/TASK_CONTRACT_SL_002766_v1.json'), 'c1c0efab'),
]
REPS = 2
ARMS = ('G1', 'G2', 'G3', 'G4', 'G5', 'G6')
ARM_CAPS = {'G1': 2, 'G2': 2, 'G3': 4, 'G4': 4, 'G5': 4, 'G6': 5}
CAPS = dict(calls=180, tokens=1_400_000, yuan=2.20)
ROUTE = {'E_D1': ('ds', 8000), 'E_D2': ('ds', 8000), 'J1': ('ds', 8000), 'J2': ('glm', 8000),
         'J2R': ('glm', 12000), 'SINK': ('ds', 4000), 'G1': ('ds', 8000)}
G1_SYS = ('你是严谨的信息抽取与核验专家。请根据以下文书，逐槽位作答。'
          '只输出 JSON：{"answers": [{"fact_id", "value", "quote", "doc"}], "unknown_slots": []}。'
          '要求：value 按槽位 unit 填写；quote 从原文逐字复制；doc 填 D1 或 D2；'
          '无法确定的槽位写入 unknown_slots。不得使用文书之外的任何信息。')

class Stop(Exception): pass

def sha(t): return hashlib.sha256(t.encode('utf-8')).hexdigest()

# Reuse the QS scorer pattern by parameterizing on contract
class TaskScorer:
    def __init__(self, contract):
        self.ct = contract
        self.facts = {f['fact_id']: f for f in contract['required_facts']}
        import qs_scorer as QS
        # Build a minimal scorer using the same logic
        self._score = QS.score
    def score(self, sink):
        ct = json.loads(json.dumps(self.ct, ensure_ascii=False))
        for f in ct['required_facts']:
            if f['grounding']['rule'] == 'text':
                f['grounding']['rule'] = 'title_set'
                f['grounding']['required_titles'] = [str(f['value'])]
        return self._score(sink, ct)

class Env:
    def __init__(self, transport, ledger, budget):
        self.t, self.l, self.b = transport, ledger, budget
        self.task, self.rep, self.arm = '', 0, ''
    def call(self, node, user, system=None):
        backend, mt = ROUTE[node]
        if system is None:
            system = {'E_D1': R.E_SYS, 'E_D2': R.E_SYS, 'J1': R.J1_SYS, 'J2': R.J2_SYS,
                      'J2R': R.J2_SYS, 'SINK': R.SINK_SYS, 'G1': G1_SYS}[node]
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), task=self.task, rep=self.rep, arm=self.arm,
                   node=node, backend=backend, max_tokens=mt, system_sha256=sha(system),
                   user_sha256=sha(user), chars_in=len(system)+len(user))
        self.b.preflight(backend, system, user, mt)
        url, body = self.t.describe(backend, system, user, mt)
        self.l.write({**rec, 'phase': 'sent', 'url': url, 'request_body': body})
        try:
            res = self.t.call(backend, system, user, mt)
        except Exception as e:
            self.b.book(backend, 0, 0)
            self.l.write({**rec, 'phase': 'done', 'raw_response': None, 'text': '', 'stop': 'transport_error',
                         'error': f'{type(e).__name__}: {e}'[:200]})
            raise Stop(f'{node}/{backend} transport: {e}') from e
        cost = self.b.book(backend, res['in'], res['out'])
        fault, parsed = R.guard('SINK' if node == 'G1' else ('J2' if node == 'J2R' else node), res)
        self.l.write({**rec, 'phase': 'done', 'raw_response': res.get('raw_response'),
                     'response_model': res.get('response_model'), 'text': res.get('text', ''),
                     'stop': res.get('stop'), 'in': res['in'], 'out': res['out'],
                     'yuan_accounting': cost, 'yuan_marginal': cost if backend=='ds' else 0, 'fault': fault})
        if fault: raise Stop(f'{node} fault: {fault}')
        if self.b.reached(): raise Stop(self.b.reached())
        return dict(text=res['text'], parsed=parsed, fault=None)

def load_task(tag, path, sha_prefix):
    ct = json.loads(path.read_text('utf-8'))
    assert hashlib.sha256(path.read_bytes()).hexdigest().startswith(sha_prefix), f'{tag} contract mismatch'
    return ct

def build_g1_user(ct):
    docs = {d: v['pages']['1']['text'] for d, v in ct['source_pages'].items()}
    slots = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                  **({'unit': f['unit']} if f.get('unit') else {})) for f in ct['required_facts']]
    return f"D1:\n{docs['D1']}\n\nD2:\n{docs['D2']}\n\n槽位：{json.dumps(slots, ensure_ascii=False)}"

def run_task_rep(tag, ct, env, scorer, docs_norm, slots_json):
    docs = {d: v['pages']['1']['text'] for d, v in ct['source_pages'].items()}
    # Shared checkpoint
    env.arm = 'shared'
    e1 = env.call('E_D1', R.e_user(docs['D1']))
    e2 = env.call('E_D2', R.e_user(docs['D2']))
    j1 = env.call('J1', R.j1_user({'E_D1': e1['text'], 'E_D2': e2['text']}))
    j2 = env.call('J2', R.j2_user(j1['text'], slots_json))
    e_texts = {'E_D1': e1['text'], 'E_D2': e2['text']}
    rows, _ = R.evidence_rows(e_texts, docs_norm)
    base = BT.total(OLD.extract_json(e_texts['E_D2']), docs['D2'])
    bline = '\n'.join(TXT.BASE_LINE.format(fact_id=f['fact_id'], subject=f['subject'],
                    predicate=f['predicate'], value=base['value'], parties=base['parties'])
                    for f in ct['required_facts'] if D5.slot_type(dict(predicate=f['predicate'])) == 'derived') if base.get('value') else ''
    states = {}
    m1 = D5.detect_m1([dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                            **({'unit': f['unit']} if f.get('unit') else {}))
                       for f in ct['required_facts']], j2['parsed'], rows)
    for f in ct['required_facts']:
        s = m1[f['fact_id']]
        if s['state'] == 'EXPLICIT_SUPPRESSION': states[f['fact_id']] = 'S1'
        elif s['state'] == 'UNKNOWN_LABEL': states[f['fact_id']] = 'S2'
        elif s['state'] == 'OMISSION': states[f['fact_id']] = 'S3'
        else: states[f['fact_id']] = 'OK'
    targets = {k for k, v in states.items() if v in ('S1', 'S2', 'S3')}
    def sink_user(j2t): return f'核验结果：\n{j2t}\n\n{R.evidence_block(rows)}\n\n{bline}\n\n槽位：{slots_json}'

    results = {}
    # G1 Single
    env.arm = 'G1'
    g1 = env.call('G1', build_g1_user(ct))
    results['G1'] = g1['parsed']
    # G2 Static
    env.arm = 'G2'
    g2 = env.call('SINK', sink_user(j2['text']))
    results['G2'] = g2['parsed']
    pre_terminal = g2['parsed']
    # Helper for recovery arms
    def addendum(fids):
        items = []
        by_row = {r['row']: r for r in rows}
        for f in ct['required_facts']:
            if f['fact_id'] in fids and m1[f['fact_id']]['candidate_rows']:
                cands = '；'.join(TXT.A2_ROW.format(row=r, doc=by_row[r]['doc'], quote=by_row[r]['quote'])
                                for r in m1[f['fact_id']]['candidate_rows'])
                items.append(TXT.A2_ITEM.format(fact_id=f['fact_id'], subject=f['subject'],
                                               predicate=f['predicate'], rows=cands))
        return TXT.A2_HEADER + '\n' + '\n'.join(items) if items else ''
    def try_recover(arm, actions):
        env.arm = arm
        try:
            return actions()
        except Stop as s:
            if 'fault' in str(s) or 'budget' in str(s).lower():
                return pre_terminal  # fallback to pre-recovery terminal
            raise

    # G3 Fixed: always J2R + SINK when triggered
    def g3_actions():
        if not targets: return pre_terminal
        jt = env.call('J2R', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets))
        return env.call('SINK', sink_user(jt['text']))['parsed']
    results['G3'] = try_recover('G3', g3_actions)

    # G4 Z-only: Z dynamic (corrected S1 rule), R always full set of chosen layer
    def g4_actions():
        if not targets: return pre_terminal
        s1_only = all(states[f] == 'S1' for f in targets)
        s3_only = all(states[f] == 'S3' for f in targets)
        if s3_only:
            # Check pre-recovery terminal
            pre_ok = all(a.get('fact_id') in (None,) or not a.get('value') or a.get('quote')
                        for a in (pre_terminal or {}).get('answers', []))
            if pre_ok and pre_terminal:
                # If S3 targets answered in pre-terminal, Z=terminal (a2)
                edit = json.dumps(dict(j2['parsed'], verified=[v for v in j2['parsed'].get('verified', [])
                                    if not (isinstance(v, dict) and str(v.get('fact_id')) in targets)]), ensure_ascii=False)
                return env.call('SINK', sink_user(edit))['parsed']
        # S1 or S2 or mixed: Z=upstream (a3) per corrected rule
        jt = env.call('J2R', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets))
        return env.call('SINK', sink_user(jt['text']))['parsed']
    results['G4'] = try_recover('G4', g4_actions)

    # G5 R-only: Z fixed upstream, R dynamic (can edit/skip)
    def g5_actions():
        if not targets: return pre_terminal
        s2_present = any(states[f] == 'S2' for f in targets)
        s3_only = all(states[f] == 'S3' for f in targets)
        if s3_only and pre_terminal:
            # Can skip (R=∅) if pre-terminal already answered targets
            ans = {a.get('fact_id') for a in (pre_terminal or {}).get('answers', []) if isinstance(a, dict)}
            if targets <= ans: return pre_terminal
        if not s2_present:
            # S1 or S3: deterministic edit + SINK only (R={SINK})
            edit = json.dumps(dict(j2['parsed'], verified=[v for v in j2['parsed'].get('verified', [])
                                if not (isinstance(v, dict) and str(v.get('fact_id')) in targets)]), ensure_ascii=False)
            return env.call('SINK', sink_user(edit))['parsed']
        # S2 present: must recheck (R={J2,SINK})
        jt = env.call('J2R', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets))
        return env.call('SINK', sink_user(jt['text']))['parsed']
    results['G5'] = try_recover('G5', g5_actions)

    # G6 Joint: full dynamic (reuse QS-C logic)
    def g6_actions():
        if not targets: return pre_terminal
        s2_present = any(states[f] == 'S2' for f in targets)
        if not s2_present:
            # Try SINK bypass first (R={SINK})
            edit = json.dumps(dict(j2['parsed'], verified=[v for v in j2['parsed'].get('verified', [])
                                if not (isinstance(v, dict) and str(v.get('fact_id')) in targets)]), ensure_ascii=False)
            sc = env.call('SINK', sink_user(edit))
            return sc['parsed']
        jt = env.call('J2R', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets))
        return env.call('SINK', sink_user(jt['text']))['parsed']
    results['G6'] = try_recover('G6', g6_actions)

    # M3 post-processing for ALL arms
    for arm in ARMS:
        out = results[arm]
        if out:
            m3 = D5.detect_m3([dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'])
                              for f in ct['required_facts']], out, rows, base)
            viol = sorted((f for f, v in m3.items() if v['state'] == 'SELF_EVIDENCE_INCONSISTENT'), key=lambda x: int(x[1:]))
            if viol:
                out['answers'] = [a for a in out.get('answers', []) if not (isinstance(a, dict) and a.get('fact_id') in viol)]
                out['unknown_slots'] = sorted(set(map(str, out.get('unknown_slots', []))) | set(viol), key=lambda x: int(x[1:]))
    return results, states, targets

def run_pilot(transport, out_dir=OUT):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ledger = R.Ledger(out_dir / 'LEDGER.jsonl')
    budget = R.Budget(**CAPS)
    env = Env(transport, ledger, budget)
    all_records = {}
    for tag, path, sha_p in TASKS:
        ct = load_task(tag, path, sha_p)
        scorer = TaskScorer(ct)
        docs_norm = R.SC.doc_index(ct)
        slots = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                      **({'unit': f['unit']} if f.get('unit') else {})) for f in ct['required_facts']]
        slots_json = json.dumps(slots, ensure_ascii=False)
        for rep in range(1, REPS + 1):
            env.task, env.rep = tag, rep
            key = f'{tag}_r{rep}'
            try:
                results, states, targets = run_task_rep(tag, ct, env, scorer, docs_norm, slots_json)
            except Stop as s:
                all_records[key] = dict(stopped=str(s)); continue
            rec = {}
            for arm in ARMS:
                sc = scorer.score(results[arm])
                rec[arm] = dict(Q=sc['Q_all'], tp=sc['tp'], wrong=sc['wrong'], asserted=sc['asserted'],
                               safety=SM.metrics(sc))
            all_records[key] = dict(states=states, targets=sorted(targets), arms=rec)
            print(f'  {key}: ' + ' '.join(f'{a}={rec[a]["Q"]:.2f}' for a in ARMS), flush=True)
    (out_dir / 'PILOT_RESULTS.json').write_text(json.dumps(all_records, ensure_ascii=False, indent=1), 'utf-8')
    return all_records

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write-freeze', action='store_true')
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--freeze', default='')
    args = ap.parse_args()
    if args.write_freeze:
        files = [Path(__file__).resolve()] + [p for _, p, _ in TASKS]
        fz = dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  caps=CAPS, arm_caps=ARM_CAPS, tasks=[t[0] for t in TASKS], reps=REPS)
        (HERE / 'FREEZE_P2B.json').write_text(json.dumps(fz, ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_P2B:', hashlib.sha256((HERE / 'FREEZE_P2B.json').read_bytes()).hexdigest()); return
    if args.real:
        if os.environ.get('P2B_GO') != '1': raise SystemExit('REFUSED: P2B_GO=1 required')
        if not args.freeze: raise SystemExit('REFUSED: --freeze required')
        p = HERE / 'FREEZE_P2B.json'
        if hashlib.sha256(p.read_bytes()).hexdigest() != args.freeze: raise SystemExit('REFUSED: freeze mismatch')
        for k in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY'):
            if not os.environ.get(k, '').strip(): raise SystemExit(f'REFUSED: {k} not set')
        run_pilot(R.RealTransport())
    else:
        import qs_mock
        # Use QS mock (simplified for now)
        print('Offline mode: use test file for full validation')

if __name__ == '__main__':
    main()
