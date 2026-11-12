#!/usr/bin/env python3
"""TFJS-V2 Step 2: C-arm (identity+evidence-complete fidelity report).

Single-variable contrast vs frozen TFJS_V1 G1 arms on the SAME 6 upstream sets:
  A_original (frozen) vs B_fidelity (frozen, colliding fids) vs C_identity (new):
  C input facts carry branch-namespaced unique fids (split_node::fid); same
  organize-only contract as B; deterministic backfill by namespaced fid.
Primary endpoint: dQ_report(C-B) = coverage transfer (headroom +12.8pp ceiling).
Preregistered expectation: dES ~ 0 (corrected ES already ~0.93 both arms).
A/B are NOT re-run (operator rule: no re-testing validated mechanisms).
Budget: 6 sets x (1 verify on namespaced facts + 2 C reports) = 18 calls.
"""
import os, sys, json, time, argparse
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, ALLOC, _call, get_docs, verify_prompt
from tfjs_runner import FIDELITY_REPORT_USER, fid_backfill
from tfjs_v2_step1 import SETS, branch_facts


def namespaced_upstream(runs_dir, strat, cond, rep):
    """Rebuild branch-namespaced, collision-free upstream fact set from stored splits."""
    outputs = [json.loads(l) for l in open(HERE / runs_dir / 'outputs.jsonl')]
    brs = branch_facts(outputs, strat, cond, rep)
    out = []
    for node, facts in brs.items():
        for f in facts:
            out.append({'fid': f"{node}::{f.get('fid', '')}",
                        'value': f.get('value', ''), 'doc': f.get('doc', ''),
                        'quote': f.get('quote', '')})
    return out


class V2:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'

    def call(self, unit, node, role, model, sys_, user, mt):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), mt)
        if self.real:
            r = _call(model, sys_, user, mt)
            text, tin, tout, stop, lat = r['text'], r['in'], r['out'], r['stop'], r['lat']
        else:
            text = '{"facts":[{"fid":"x::f1","value":"v","doc":"doc1","quote":"q"}]}'
            tin, tout, stop, lat = len(user), 64, 'end_turn', 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, node=node, role=role, model=model,
                   tin=tin, tout=tout, yuan=est, stop=stop, lat=lat)
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def run_set(self, runs_dir, strat, cond, rep):
        unit = f"{strat}_{cond}_r{rep}"
        eid = f"C|{unit}"
        if self.store.completed(eid):
            return
        self.store.begin(eid)
        docs_text = '\n\n'.join(f'[{d}]\n{t[:800]}' for d, t in get_docs().items())
        mf = namespaced_upstream(runs_dir, strat, cond, rep)
        vt = self.call(unit, 'verify', 'base', ALLOC['verification'],
                       SYS_COMMON + D2_CONTRACT,
                       verify_prompt(json.dumps(mf, ensure_ascii=False)[:2000], docs_text), 4000)
        _, vf, _ = parse_facts(vt)
        vs = {}
        for v in vf:
            if isinstance(v, dict):
                vs[str(v.get('fid', ''))] = v.get('status', 'unverified')
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in mf]
        user = FIDELITY_REPORT_USER.format(
            combined=json.dumps(combined, ensure_ascii=False)[:3000])
        rows = []
        for r in (1, 2):
            t = self.call(unit, 'report', f'r{r}', ALLOC['report'],
                          SYS_COMMON + D2_CONTRACT, user, 4000)
            _, rf, _ = parse_facts(t)
            rf = fid_backfill(rf, combined)
            rows.append(dict(rep=r, n_report=len(rf)))
            with open(self.outputs, 'a') as f:
                f.write(json.dumps(dict(ts=time.time(), unit=unit, node='report_final',
                                        role=f'r{r}', model='na', tin=0, tout=0, yuan=0,
                                        stop='na', lat=0,
                                        raw_output=json.dumps(rf, ensure_ascii=False)),
                                   ensure_ascii=False) + '\n')
        self.store.commit(dict(exec_id=eid, unit=unit, n_upstream=len(combined), rows=rows,
                               budget_left=self.gb.left()))
        print(f'  C {unit} done left={self.gb.left()["calls_left"]}')

    def run(self):
        for (runs_dir, strat, cond, rep, _) in SETS:
            self.run_set(runs_dir, strat, cond, rep)
        print(f'TFJS-V2 DONE budget={self.gb.left()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'tfjs_v2_config.json'))
    ap.add_argument('--out', default=str(HERE / 'tfjs_v2_runs'))
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
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE')
    V2(cfg, a.out, a.real).run()


if __name__ == '__main__':
    main()
