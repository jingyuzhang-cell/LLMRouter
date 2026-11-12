#!/usr/bin/env python3
"""RQ_DAJF_V2: DA-JS-v2 three work items (W1 table fix / W2 conditional R-skip / W3 Z2 validation).

Design (frozen pipeline, byte-identical prompts to RQ_DAJF_V1):
  Arms:
    DA-JS-v2  : natural / persistent / persistent_bcap / transient / transient_bcap, 3 reps each
    Proposed  : transient only (R->pi fixed ladder reference; persistent/natural reused from V1)
  Conditions:
    natural          : no injection
    persistent*      : qwen merge output truncated on base AND same-model retries
    transient*       : truncated on base attempt only (retry clean) -- identical signature,
                       matching all prior transient batches (single-shot diagnosis impossible)
    *_bcap           : persistent/transient fault + per-anomaly recovery call budget capped at 2
                       (deployment scenario exercising the VoI probe policy where R is competitive)
  Policy: decide_v2 (eps-dominance, corrected table V2); per-condition-block cold Beta(1,1)
  posterior updated only by R-probe outcomes. Expected behavior:
    persistent (B large)      : Z2 direct, prior-free (rep1-3, 9 calls)
    persistent_bcap (B=2)     : rep1 probe R -> fail -> pi; posterior drops; rep2-3 skip probe -> pi
    transient (B large)       : Z2 direct (9 calls) vs Proposed R-first (7 calls)
    transient_bcap (B=2)      : probe R -> ok (7 calls), posterior stays high
Budget: hard caps via GlobalBudget; stop only at execution boundaries.
"""
import os, sys, json, time, argparse
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT
from stage_d_executor import GlobalBudget, RunStore
from da_js_v2 import decide_v2, PersistencePosterior
from rq_dajf_runner import (YUAN, ALLOC, REPS, EV, DOCS, _call, truncate,
                            get_docs, extract_prompt, merge_prompt, verify_prompt,
                            report_prompt)

CONDS = {  # cond -> (persistent_fault, bcap_or_None); transient = not persistent
    'natural': (False, None),
    'persistent': (True, None),
    'persistent_bcap': (True, 2),
    'transient': (False, None),
    'transient_bcap': (False, 2),
}
V2_ORDER = ['natural', 'persistent', 'persistent_bcap', 'transient', 'transient_bcap']


class FR2:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.deadline = cfg.get('deadline_s', 240)
        self.posteriors = {}  # per condition block, cold Beta(1,1)
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'

    def call(self, strat, cond, rep, node, role, model, sys_, user, mt, inject=False):
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
            text = '{"facts":[{"fid":"m","value":"v","doc":"doc1","quote":"q"}]}'
            if inject:
                text = truncate(text)
            tin, tout, stop, lat = len(user), 64, 'end_turn', 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), strategy=strat, condition=cond, rep=rep, node=node,
                   role=role, model=model, tin=tin, tout=tout, yuan=est, stop=stop,
                   lat=lat, injected=inject)
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    # ---- recovery primitives (identical to V1 implementations) ----
    def do_r(self, s, c, r, mu, mm, inject_retry):
        t = self.call(s, c, r, 'merge', 'reroll', mm, SYS_COMMON + D2_CONTRACT, mu, 4000,
                      inject=inject_retry)
        ok, f, _ = parse_facts(t)
        return f if (ok and f) else None

    def do_pi(self, s, c, r, mu, mm):
        alt = 'deepseek' if mm == 'qwen' else 'qwen'
        t = self.call(s, c, r, 'merge', 'reroll2', alt, SYS_COMMON + D2_CONTRACT, mu, 4000)
        ok, f, _ = parse_facts(t)
        return f if f else None

    def do_z2(self, s, c, r, upstream):
        bf = []
        for un in [k for k in upstream if k.startswith('ext_')]:
            if not upstream[un]:
                continue
            sp = f"合并以下事实：\n\n{json.dumps(upstream[un], ensure_ascii=False)[:1500]}\n\n按系统格式输出 JSON。"
            bt = self.call(s, c, r, f'split_{un}', 'split', 'deepseek', SYS_COMMON, sp, 2000)
            bok, bf2, _ = parse_facts(bt)
            if bok and bf2:
                bf += [x for x in bf2 if isinstance(x, dict)]
        return bf

    def run_exec(self, strat, cond, rep):
        exec_id = f"{strat}|{cond}|r{rep}"
        if self.store.completed(exec_id):
            return None
        self.store.begin(exec_id)
        persistent, bcap = CONDS[cond]
        docs = get_docs()
        docs_text = '\n\n'.join(f'[{d}]\n{t[:800]}' for d, t in docs.items())
        upstream = {}
        actions = []
        t0 = time.time()
        for di, dt in docs.items():
            text = self.call(strat, cond, rep, f'ext_{di}', 'base', ALLOC['extract'],
                             SYS_COMMON, extract_prompt(di, dt), 2000)
            ok, f, _ = parse_facts(text)
            upstream[f'ext_{di}'] = f
        af = []
        for nid in upstream:
            af += [x for x in upstream[nid] if isinstance(x, dict)]
        mu = merge_prompt(json.dumps(af, ensure_ascii=False)[:3000])
        mm = ALLOC['reason']
        inject_base = (cond != 'natural')  # transient/persistent: base attempt truncated
        text = self.call(strat, cond, rep, 'merge', 'base', mm, SYS_COMMON + D2_CONTRACT,
                         mu, 4000, inject=inject_base)
        ok, facts, _ = parse_facts(text)
        anomaly = (not ok) or len(facts) == 0
        merge_out = facts if ok else []

        if not anomaly:
            actions.append('merge:ok')
        elif strat == 'Proposed':
            actions.append('anomaly:R')
            f2 = self.do_r(strat, cond, rep, mu, mm, inject_retry=persistent)
            if f2:
                merge_out = f2
                actions.append('R:ok')
            else:
                actions.append('R:fail')
                actions.append('pi')
                f3 = self.do_pi(strat, cond, rep, mu, mm)
                if f3:
                    merge_out = f3
                    actions.append('pi:ok')
                else:
                    actions.append('pi:fail')
        else:  # DA-JS-v2
            post = self.posteriors.setdefault(cond, PersistencePosterior())
            D_rem = self.deadline - (time.time() - t0)
            B_rem = min(self.gb.left()['calls_left'], 30) if bcap is None else \
                min(self.gb.left()['calls_left'], bcap)
            d1 = decide_v2(D_rem, B_rem, mm, 'merge', p_transient=post.p_transient())
            actions.append(f"decide:{d1['selected']}(p={post.p_transient():.2f},"
                           f"rem={D_rem:.0f}s,B={B_rem})")
            sel = d1['selected']
            if sel == 'Z2_split_R':
                bf = self.do_z2(strat, cond, rep, upstream)
                if bf:
                    merge_out = bf
                    actions.append(f'Z2:ok(n={len(bf)})')
                else:
                    actions.append('Z2:fail')
            elif sel == 'LOCAL_pi':
                f3 = self.do_pi(strat, cond, rep, mu, mm)
                if f3:
                    merge_out = f3
                    actions.append('pi:ok')
                else:
                    actions.append('pi:fail')
            elif sel == 'R_PROBE_THEN_ESCALATE':
                f2 = self.do_r(strat, cond, rep, mu, mm, inject_retry=persistent)
                if f2:
                    post.update(True)
                    merge_out = f2
                    actions.append(f'R:ok(p->{post.p_transient():.2f})')
                else:
                    post.update(False)
                    actions.append(f'R:fail(p->{post.p_transient():.2f})')
                    D2r = self.deadline - (time.time() - t0)
                    B2r = max(min(self.gb.left()['calls_left'], 30) if bcap is None
                              else min(self.gb.left()['calls_left'], bcap) - 1, 0)
                    d2 = decide_v2(D2r, B2r, mm, 'merge',
                                   p_transient=post.p_transient())
                    actions.append(f"escalate:{d2['selected']}(p={post.p_transient():.2f})")
                    if d2['selected'] == 'LOCAL_pi':
                        f3 = self.do_pi(strat, cond, rep, mu, mm)
                        if f3:
                            merge_out = f3
                            actions.append('pi:ok')
                        else:
                            actions.append('pi:fail')
                    elif d2['selected'] == 'Z2_split_R':
                        bf = self.do_z2(strat, cond, rep, upstream)
                        if bf:
                            merge_out = bf
                            actions.append(f'Z2:ok(n={len(bf)})')
                        else:
                            actions.append('Z2:fail')
            else:
                actions.append('decide:NONE(no feasible recovery)')

        upstream['merge'] = merge_out
        vt = self.call(strat, cond, rep, 'verify', 'base', ALLOC['verification'],
                       SYS_COMMON + D2_CONTRACT,
                       verify_prompt(json.dumps(merge_out, ensure_ascii=False)[:2000], docs_text),
                       4000)
        ok_v, vf, _ = parse_facts(vt)
        vs = {}
        for v in vf:
            if isinstance(v, dict):
                vs[str(v.get('fid', ''))] = v.get('status', 'unverified')
        combined = [{**mf, 'verify_status': vs.get(str(mf.get('fid', '')), 'unverified')}
                    for mf in merge_out if isinstance(mf, dict)]
        rt = self.call(strat, cond, rep, 'report', 'base', ALLOC['report'],
                       SYS_COMMON + D2_CONTRACT,
                       report_prompt(json.dumps(combined, ensure_ascii=False)[:3000],
                                     json.dumps(vs, ensure_ascii=False)[:500]), 4000)
        ok_r, rf, _ = parse_facts(rt)
        span = time.time() - t0
        record = dict(exec_id=exec_id, strategy=strat, condition=cond, rep=rep,
                      actions=actions, n_merge=len(merge_out), n_report=len(rf),
                      exec_span_s=round(span, 1), deadline_s=self.deadline,
                      deadline_met=bool(span <= self.deadline),
                      budget_left=self.gb.left())
        self.store.commit(record)
        return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq_dajf2_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq_dajf2_runs'))
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
    r = FR2(cfg, a.out, a.real)
    done = skipped = 0
    stop = False
    for cond in V2_ORDER:  # block order: posteriors evolve within each condition block
        for rep in range(1, REPS + 1):
            for strat in (['DA-JS-v2'] + (['Proposed'] if cond == 'transient' else [])):
                eid = f"{strat}|{cond}|r{rep}"
                if r.store.completed(eid):
                    skipped += 1
                    continue
                if r.gb.left()['calls_left'] < 10:
                    print('STOP')
                    stop = True
                    break
                r.run_exec(strat, cond, rep)
                done += 1
                print(f'  {eid} done left={r.gb.left()["calls_left"]}')
            if stop:
                break
        if stop:
            break
    print(f'DONE: {done} skip={skipped} budget={r.gb.left()}')


if __name__ == '__main__':
    main()
