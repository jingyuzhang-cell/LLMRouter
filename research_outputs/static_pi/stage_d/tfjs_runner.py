#!/usr/bin/env python3
"""TFJS: Terminal-Fidelity Joint Scheduling (operator-directed small causal batch).

Group 1 (report fidelity, paired on IDENTICAL merge facts + verify statuses):
  A_original  : V1 frozen report prompt (model regenerates evidence)
  B_fidelity  : organize-only contract + deterministic fid-based citation backfill
  6 stored adopted-merge sets (V1 DA-JS persistent x3, V2 DA-JS-v2 persistent x3)
  x 2 report variants x 2 reps. Verify recomputed once per set, shared.

Group 2 (scheduling, paired on IDENTICAL extracts + identical injected anomaly):
  per rep: 3 real DS extracts (shared) -> 1 real qwen base merge (truncated, shared)
    Proposed arm : R(qwen, injected->fail) -> pi(DS) -> verify -> B_fidelity report
    DA-JS-v2 arm : decide_v2 -> Z2 (3 DS splits) -> verify -> B_fidelity report
  Group 2 uses the B_fidelity report for BOTH arms (propagation mechanism under
  test); Group 1 separately quantifies the report-variant effect -> no mixed
  attribution.

Discipline: same Gold + same hit rules as V1/V2; Support is the operator-requested
new metric (declared proxy); no new model pool; no re-testing of validated
mechanisms (W1/W2); 192 HOLD untouched.
"""
import os, sys, json, time, argparse
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT
from stage_d_executor import GlobalBudget, RunStore
from da_js_v2 import decide_v2
from rq_dajf_runner import (YUAN, ALLOC, EV, DOCS, _call, truncate, get_docs,
                            extract_prompt, merge_prompt, verify_prompt, report_prompt)
from rq_dajf2_score import adopted_merge_facts

G1_SETS = [  # (batch_dir, strategy, condition, rep)
    ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 1),
    ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 2),
    ('rq_dajf_runs', 'DA-JS-v1', 'persistent', 3),
    ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 1),
    ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 2),
    ('rq_dajf2_runs', 'DA-JS-v2', 'persistent', 3),
]
G1_REPS = 2

FIDELITY_REPORT_USER = (
    "基于以下已核验事实组织终端调查报告。规则：逐条原样保留每条事实的 "
    "fid/value/doc/quote/verify_status 字段，不得改写、截断或省略 value 与 quote；"
    "你只负责组织表达，可为每条事实增加 summary 字段概括其含义；不得新增、合并或删除事实。\n\n"
    "事实：\n{combined}\n\n按系统格式输出 JSON。")


def fid_backfill(report_facts, upstream_combined):
    """Deterministic citation backfill by fid: value/doc/quote/verify_status are
    taken from the upstream fact record verbatim; model text kept only for
    summary/organization."""
    by_fid = {str(f.get('fid', '')): f for f in upstream_combined if isinstance(f, dict)}
    out = []
    for x in report_facts:
        if not isinstance(x, dict):
            continue
        u = by_fid.get(str(x.get('fid', '')))
        if u:
            out.append({**x, 'value': u.get('value', x.get('value', '')),
                        'doc': u.get('doc', x.get('doc', '')),
                        'quote': u.get('quote', x.get('quote', '')),
                        'verify_status': u.get('verify_status', 'unverified')})
        else:
            out.append(x)
    return out


class TFJS:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.deadline = cfg.get('deadline_s', 240)
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'

    def call(self, group, arm, unit, node, role, model, sys_, user, mt, inject=False):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), mt)
        if self.real:
            r = _call(model, sys_, user, mt)
            text = r['text']
            if inject:
                text = truncate(text)
            tin, tout, stop, lat = r['in'], r['out'], r['stop'], r['lat']
        else:
            text = '{"facts":[{"fid":"m1","value":"v","doc":"doc1","quote":"q"}]}'
            if inject:
                text = truncate(text)
            tin, tout, stop, lat = len(user), 64, 'end_turn', 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), group=group, arm=arm, unit=unit, node=node, role=role,
                   model=model, tin=tin, tout=tout, yuan=est, stop=stop, lat=lat,
                   injected=inject)
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def verify_statuses(self, group, arm, unit, merge_out, docs_text):
        vt = self.call(group, arm, unit, 'verify', 'base', ALLOC['verification'],
                       SYS_COMMON + D2_CONTRACT,
                       verify_prompt(json.dumps(merge_out, ensure_ascii=False)[:2000], docs_text),
                       4000)
        ok_v, vf, _ = parse_facts(vt)
        vs = {}
        for v in vf:
            if isinstance(v, dict):
                vs[str(v.get('fid', ''))] = v.get('status', 'unverified')
        return vs

    # ---------------- Group 1 ----------------
    def run_g1(self):
        docs_text = '\n\n'.join(f'[{d}]\n{t[:800]}' for d, t in get_docs().items())
        for (runs_dir, strat, cond, rep) in G1_SETS:
            unit = f"{strat}_{cond}_r{rep}"
            eid = f"G1|{unit}"
            if self.store.completed(eid):
                continue
            self.store.begin(eid)
            t0 = time.time()
            outputs = [json.loads(l) for l in open(HERE / runs_dir / 'outputs.jsonl')]
            ex = [o for o in outputs if o['strategy'] == strat and o['condition'] == cond
                  and o['rep'] == rep]
            rec_json = json.loads((HERE / runs_dir / f"{strat}__{cond}__r{rep}.json").read_text())
            mf = adopted_merge_facts(ex, rec_json.get('actions', []))
            vs = self.verify_statuses('G1', 'shared', unit, mf, docs_text)
            combined = [{**f, 'verify_status': vs.get(str(f.get('fid', '')), 'unverified')}
                        for f in mf if isinstance(f, dict)]
            combined_json = json.dumps(combined, ensure_ascii=False)[:3000]
            rows = []
            for variant in ('A_original', 'B_fidelity'):
                for r in range(1, G1_REPS + 1):
                    if variant == 'A_original':
                        user = report_prompt(combined_json, json.dumps(vs, ensure_ascii=False)[:500])
                    else:
                        user = FIDELITY_REPORT_USER.format(combined=combined_json)
                    t = self.call('G1', variant, unit, 'report', f'r{r}',
                                  ALLOC['report'], SYS_COMMON + D2_CONTRACT, user, 4000)
                    ok, rf, _ = parse_facts(t)
                    if variant == 'B_fidelity':
                        rf = fid_backfill(rf, combined)
                    rows.append(dict(variant=variant, rep=r, n_report=len(rf)))
                    with open(self.outputs, 'a') as f:
                        f.write(json.dumps(dict(ts=time.time(), group='G1-scored',
                                                arm=variant, unit=unit, node='report_final',
                                                role=f'r{r}', model='na', tin=0, tout=0,
                                                yuan=0, stop='na', lat=0, injected=False,
                                                raw_output=json.dumps(rf, ensure_ascii=False)),
                                           ensure_ascii=False) + '\n')
            self.store.commit(dict(exec_id=eid, group='G1', unit=unit, rows=rows,
                                   n_upstream=len(combined),
                                   exec_span_s=round(time.time() - t0, 1),
                                   budget_left=self.gb.left()))
            print(f'  G1 {unit} done left={self.gb.left()["calls_left"]}')

    # ---------------- Group 2 ----------------
    def run_g2_rep(self, rep):
        eid = f"G2|r{rep}"
        if self.store.completed(eid):
            return
        self.store.begin(eid)
        docs = get_docs()
        docs_text = '\n\n'.join(f'[{d}]\n{t[:800]}' for d, t in docs.items())
        t0 = time.time()
        upstream = {}
        for di, dt in docs.items():
            text = self.call('G2', 'shared', f'r{rep}', f'ext_{di}', 'base',
                             ALLOC['extract'], SYS_COMMON, extract_prompt(di, dt), 2000)
            ok, f, _ = parse_facts(text)
            upstream[f'ext_{di}'] = f
        af = [x for nid in upstream for x in upstream[nid] if isinstance(x, dict)]
        mu = merge_prompt(json.dumps(af, ensure_ascii=False)[:3000])
        mm = ALLOC['reason']
        _ = self.call('G2', 'shared', f'r{rep}', 'merge', 'base', mm,
                      SYS_COMMON + D2_CONTRACT, mu, 4000, inject=True)  # shared anomaly
        shared_span = time.time() - t0  # extracts + base merge (shared prefix, both arms)
        arms = {}
        # Proposed: R -> pi
        t_rec0 = time.time()
        actions = ['anomaly:R']
        rt = self.call('G2', 'Proposed', f'r{rep}', 'merge', 'reroll', mm,
                       SYS_COMMON + D2_CONTRACT, mu, 4000, inject=True)
        ok, f2, _ = parse_facts(rt)
        merge_out = []
        if ok and f2:
            merge_out = f2
            actions.append('R:ok')
        else:
            actions.append('R:fail')
            actions.append('pi')
            alt = 'deepseek' if mm == 'qwen' else 'qwen'
            pt = self.call('G2', 'Proposed', f'r{rep}', 'merge', 'reroll2', alt,
                           SYS_COMMON + D2_CONTRACT, mu, 4000)
            ok3, f3, _ = parse_facts(pt)
            if f3:
                merge_out = f3
                actions.append('pi:ok')
            else:
                actions.append('pi:fail')
        arms['Proposed'] = (merge_out, actions, round(time.time() - t_rec0, 1))
        # DA-JS-v2: decide_v2 -> Z2 direct
        t_rec0 = time.time()
        d = decide_v2(self.deadline - (time.time() - t0),
                      min(self.gb.left()['calls_left'], 30), mm, 'merge', p_transient=0.5)
        actions = [f"decide:{d['selected']}"]
        bf = []
        for un in [k for k in upstream if k.startswith('ext_')]:
            if not upstream[un]:
                continue
            sp = f"合并以下事实：\n\n{json.dumps(upstream[un], ensure_ascii=False)[:1500]}\n\n按系统格式输出 JSON。"
            bt = self.call('G2', 'DA-JS-v2', f'r{rep}', f'split_{un}', 'split',
                           'deepseek', SYS_COMMON, sp, 2000)
            bok, bf2, _ = parse_facts(bt)
            if bok and bf2:
                bf += [x for x in bf2 if isinstance(x, dict)]
        merge_out = bf
        actions.append(f"Z2:ok(n={len(bf)})" if bf else 'Z2:fail')
        arms['DA-JS-v2'] = (merge_out, actions, round(time.time() - t_rec0, 1))
        # per-arm verify + B_fidelity report, timed for e2e convention
        rec_arms = {}
        for arm, (mo, acts, rec_s) in arms.items():
            t_vr0 = time.time()
            vs = self.verify_statuses('G2', arm, f'r{rep}', mo, docs_text)
            combined = [{**f, 'verify_status': vs.get(str(f.get('fid', '')), 'unverified')}
                        for f in mo if isinstance(f, dict)]
            user = FIDELITY_REPORT_USER.format(
                combined=json.dumps(combined, ensure_ascii=False)[:3000])
            t = self.call('G2', arm, f'r{rep}', 'report', 'base', ALLOC['report'],
                          SYS_COMMON + D2_CONTRACT, user, 4000)
            ok, rf, _ = parse_facts(t)
            rf = fid_backfill(rf, combined)
            vr_s = round(time.time() - t_vr0, 1)
            with open(self.outputs, 'a') as f:
                f.write(json.dumps(dict(ts=time.time(), group='G2-scored', arm=arm,
                                        unit=f'r{rep}', node='report_final', role='base',
                                        model='na', tin=0, tout=0, yuan=0, stop='na',
                                        lat=0, injected=False,
                                        raw_output=json.dumps(rf, ensure_ascii=False)),
                                   ensure_ascii=False) + '\n')
            rec_arms[arm] = dict(actions=acts, n_merge=len(mo), n_report=len(rf),
                                 L_recovery_s=rec_s, L_verify_report_s=vr_s,
                                 L_e2e_s=round(shared_span + rec_s + vr_s, 1))
        span = time.time() - t0
        self.store.commit(dict(exec_id=eid, group='G2', rep=rep, arms=rec_arms,
                               n_extract_facts=len(af),
                               shared_span_s=round(shared_span, 1),
                               exec_span_s=round(span, 1),
                               deadline_s=self.deadline,
                               budget_left=self.gb.left()))
        print(f'  G2 r{rep} done left={self.gb.left()["calls_left"]}')

    def run(self, stage):
        """Staged gating per operator ruling: Stage1=G1 ONLY (30 calls);
        Stage2=G2 ONLY, hard-refused unless all 6 G1 records already exist
        (gate evaluated out-of-band on TFJS_G1_SCORED.json between stages)."""
        if stage == 1:
            self.run_g1()
        elif stage == 2:
            missing = [f"G1|{s}_{c}_r{r}"
                       for (d, s, c, r) in G1_SETS
                       if not (self.out / f"G1|{s}_{c}_r{r}.json".replace('|', '__')).exists()]
            if missing:
                raise SystemExit(f'STAGE2 REFUSED: G1 incomplete: {missing}')
            for rep in (1, 2, 3):
                self.run_g2_rep(rep)
        print(f'TFJS stage{stage} DONE budget={self.gb.left()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'tfjs_config.json'))
    ap.add_argument('--out', default=str(HERE / 'tfjs_runs'))
    ap.add_argument('--stage', type=int, default=1, choices=(1, 2),
                    help='1=G1 only (gate before 2); 2=G2 only (requires G1 complete)')
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                os.environ[k] = [l.split('=', 1)[1].strip()
                                 for l in open('/root/.env') if l.startswith(k + '=')][0]
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'], 'stage', a.stage)
    else:
        print('MOCK MODE stage', a.stage)
    TFJS(cfg, a.out, a.real).run(a.stage)


if __name__ == '__main__':
    main()
