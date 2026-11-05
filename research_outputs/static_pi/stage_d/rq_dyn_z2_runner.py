#!/usr/bin/env python3
"""RQ-DYN_V4 minimal runner: S1(pi) + S3(Z2) only, 12 execs.
Clean implementation - no patching. Verifies pi model-specific fallback and Z2 split."""
import os, sys, json, time, argparse, hashlib, re
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts, signals, score_node
from rq2_p2r_v3_runner import D2_CONTRACT, DELIVERY_KINDS, n_upstream_facts, MAXTOK_BASE, D1_PER_FACT, D1_CAP
from rq2_cap_v1_runner import cap_transport
from rq_dyn_v3_runner import CB_MATS, CB_TEXT, TASKS, cb_node_prompt
from stage_d_executor import GlobalBudget, RunStore

YUAN = {'deepseek': 0.0129, 'qwen': 0.02}

def truncate(text, n=20): return text[:n]

class V4Runner:
    def __init__(self, cfg, out, real):
        self.real = real; self.out = Path(out)
        st = self.out / 'state'; st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.ledger = self.out / 'ledger.jsonl'
        self.injection_log = self.out / 'injection_ledger.jsonl'

    def call(self, cell, task, rep, node, role, model, system, user, mt, inject=False):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), mt)
        if self.real:
            r = cap_transport(model, system, user, mt)
            text = r['text']
            if inject:
                orig = text
                text = truncate(text)
                with open(self.injection_log, 'a') as f:
                    f.write(json.dumps(dict(ts=time.time(), cell=cell, task=task, rep=rep,
                        node=node, role=role, model=model, injected=True,
                        raw_sha=hashlib.sha256(orig.encode()).hexdigest()[:12],
                        inj_sha=hashlib.sha256(text.encode()).hexdigest()[:12]),
                        ensure_ascii=False) + '\n')
            tin, tout, stop, lat, mr = r['in'], r['out'], r['stop'], r['lat'], r.get('model')
        else:
            text = json.dumps({"facts": [{"fid": node, "value": "mock", "doc": "doc1",
                "quote": "mock quote"}], "unknown": []}, ensure_ascii=False)
            if inject: text = truncate(text)
            tin, tout, stop, lat, mr = len(user), 64, 'end_turn', 0.01, None
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), cell=cell, task=task, rep=rep, node=node, role=role,
                   model=model, model_resp=mr, max_tokens=mt, tin=tin, tout=tout,
                   yuan=est, stop=stop, lat=lat, injected=inject,
                   prompt_sha=hashlib.sha256((system + '||' + user).encode()).hexdigest()[:16])
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text

    def run_exec(self, cell, task, rep, scenario):
        exec_id = f"{cell}|{scenario}|{task}|r{rep}"
        if self.store.completed(exec_id): return None
        self.store.begin(exec_id)
        dyn = cell == 'DYN'
        upstream, node_recs, actions = {}, [], []
        for node in CB_MATS[task]['nodes']:
            kind, nid = node['kind'], node['node_id']
            delivery = kind in DELIVERY_KINDS
            model = 'deepseek'
            sysp = SYS_COMMON + (D2_CONTRACT if delivery else '')
            ru = node.get('reference_upstream') or {}
            nup = n_upstream_facts(upstream, ru.get('from_nodes', [])) if delivery else 0
            mt = min(D1_CAP, MAXTOK_BASE + D1_PER_FACT * nup) if delivery else MAXTOK_BASE
            userp = cb_node_prompt(task, node, upstream)

            # S1_pi: inject ONLY DS calls on merge (base+reroll). Qwen clean.
            # S3: inject ALL models on merge (base+reroll+reroll2).
            s1_inject = scenario == 'S1_pi' and nid == 'merge' and model == 'deepseek'
            s3_inject_base = scenario == 'S3' and nid == 'merge'
            inject_base = s1_inject or s3_inject_base

            text = self.call(cell, task, rep, nid, 'base', model, sysp, userp, mt, inject=inject_base)
            ok, facts, unk = parse_facts(text)
            sig = signals(node, ok, facts)
            chosen = dict(model=model, facts=facts, unknown=unk, rerolled=False)
            actions_local = []

            if (sig['exec'] or sig['prod'] or sig['cite']):
                # R: same-model reroll
                inj_rr = inject_base  # same injection rule for reroll
                text2 = self.call(cell, task, rep, nid, 'reroll', model, sysp, userp, mt, inject=inj_rr)
                ok2, f2, u2 = parse_facts(text2)
                if score_node(f2) > score_node(facts):
                    chosen = dict(model=model, facts=f2, unknown=u2, rerolled=True)
                    actions_local.append(('R', 'recovered', nid))
                else:
                    actions_local.append(('R', 'failed', nid))

                    if dyn and nid == 'merge' and not ok2:
                        # pi: Qwen fallback
                        # S1_pi: Qwen NOT injected; S3: Qwen IS injected
                        inj_pi = (scenario == 'S3')  # S3: Qwen ALSO truncated; S1_pi: Qwen clean
                        text3 = self.call(cell, task, rep, nid, 'reroll2', 'qwen', sysp, userp, mt, inject=inj_pi)
                        ok3, f3, u3 = parse_facts(text3)
                        if score_node(f3) > score_node(facts):
                            chosen = dict(model='qwen', facts=f3, unknown=u3, rerolled=True)
                            actions_local.append(('pi', 'recovered', nid))
                        else:
                            actions_local.append(('pi', 'failed', nid))

                            # Z2: split per branch (ONLY for merge, after pi failure)
                            if not ok3:
                                branches, bfacts = [], []
                                for un in ru.get('from_nodes', []):
                                    if not upstream.get(un): continue
                                    up2 = {un: upstream[un]}
                                    up2p = cb_node_prompt(task, node, up2)
                                    bt = self.call(cell, task, rep, nid, f'split:{un}',
                                                   'deepseek', sysp, up2p, mt, inject=False)
                                    bok, bf, bu = parse_facts(bt)
                                    branches.append(dict(node=un, ok=bok, n=len(bf)))
                                    if bok:
                                        bfacts += [x for x in bf if isinstance(x, dict)]
                                if bfacts:
                                    chosen = dict(model='deepseek', facts=bfacts, unknown=[],
                                                  rerolled=True, joined=True)
                                actions_local.append(('Z2', f'split+join n={len(bfacts)}', nid))
                    elif dyn and delivery and not ok2 and nid != 'merge':
                        # General delivery pi (non-merge only; merge handled above)
                        inj_pi = False
                        text3 = self.call(cell, task, rep, nid, 'reroll2', 'qwen', sysp, userp, mt, inject=inj_pi)
                        ok3, f3, u3 = parse_facts(text3)
                        if score_node(f3) > score_node(facts):
                            chosen = dict(model='qwen', facts=f3, unknown=u3, rerolled=True)
                            actions_local.append(('pi', 'recovered', nid))
                        else:
                            actions_local.append(('pi', 'failed', nid))

            for a in actions_local:
                actions.append(dict(action=a[0], outcome=a[1], node=a[2]))
            upstream[nid] = chosen['facts']
            node_recs.append(dict(node_id=nid, kind=kind, signals=sig, chosen=chosen,
                                  base_output=dict(ok=ok, facts=facts, n=len(facts), model=model)))
        record = dict(exec_id=exec_id, cell=cell, task=task, rep=rep,
                      nodes=node_recs, actions=actions, budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq_dyn_v4_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq_dyn_v4_runs'))
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip(): raise SystemExit(f'REFUSED: {k}')
        print('REAL MODE — caps:', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else: print('MOCK MODE')
    r = V4Runner(cfg, a.out, a.real)
    done = skipped = 0
    stop = False
    # S1_pi on C_sjzg (3 rep x 2 arms); S3 on C_sjzg (3 rep x 2 arms)
    for scenario, task in [('S3', 'C_sjzg')]:
        for rep in range(1, 4):
            for cell in ('HomDS', 'DYN'):
                eid = f"{cell}|{scenario}|{task}|r{rep}"
                if r.store.completed(eid): skipped += 1; continue
                if r.gb.left()['calls_left'] < 10:
                    print(f'STOP: {eid}'); stop = True; break
                r.run_exec(cell, task, rep, scenario)
                done += 1
                print(f'  {eid} done, left={r.gb.left()["calls_left"]}')
            if stop: break
        if stop: break
    print(f'DONE: {done} skipped={skipped} stopped={stop} budget={r.gb.left()}')

if __name__ == '__main__':
    main()
