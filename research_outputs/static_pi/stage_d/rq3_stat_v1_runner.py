#!/usr/bin/env python3
"""RQ3_STAT_V1 runner: HomDS (deepseek all) vs HetQR (qwen on reason nodes
only) under the validated D1+D2 delivery mechanism. NO verification calls.
Interleaved per (task,rep); RunStore checkpoint resume; dual base/reroll
outputs; per-call model_resp drift audit. Real mode requires --real AND env
STAGE_D_REAL_CALLS_AUTHORIZED=1 AND DEEPSEEK_API_KEY AND QWEN_API_KEY.
Mock mode = zero real calls.
"""
import os, sys, json, time, argparse, hashlib
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import (MATS, TASKS, REPS, SYS_COMMON, node_prompt,
                            parse_facts, signals, score_node)
from rq2_p2r_v3_runner import D2_CONTRACT, DELIVERY_KINDS, D1_PER_FACT, \
    D1_CAP, MAXTOK_BASE, n_upstream_facts
from rq2_cap_v1_runner import cap_transport
from stage_d_executor import GlobalBudget, RunStore

YUAN = {'deepseek': 0.0129, 'qwen': 0.02}
CELLS = ('HomDS', 'HetQR')
REROLL_TIMEOUT_S = 180


class R3Runner:

    def __init__(self, cfg, out_dir, real):
        self.real = real
        self.out_dir = Path(out_dir)
        state = self.out_dir / 'state'
        state.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'),
                               state)
        self.store = RunStore(state, self.out_dir)
        self.ledger = self.out_dir / 'ledger.jsonl'

    def call(self, cell, task, rep, node_id, role, model, system, user,
             max_tokens):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), max_tokens)
        if self.real:
            r = cap_transport(model, system, user, max_tokens)
            text, tin, tout = r['text'], r['in'], r['out']
            stop, lat, mresp = r['stop'], r['lat'], r.get('model')
        else:
            text = json.dumps({"facts": [{"fid": node_id, "value": "mock",
                                          "doc": "doc1",
                                          "quote": "mock quote"}],
                               "unknown": []}, ensure_ascii=False)
            tin, tout, stop, lat, mresp = len(user), 64, 'end_turn', 0.01, None
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), cell=cell, task=task, rep=rep,
                   node=node_id, role=role, model=model, model_resp=mresp,
                   max_tokens=max_tokens, tin=tin, tout=tout, yuan=est,
                   stop=stop, lat=lat,
                   prompt_sha=hashlib.sha256(
                       (system + '||' + user).encode()).hexdigest()[:16])
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text, rec

    def run_exec(self, cell, task, rep):
        exec_id = f"{cell}|{task}|r{rep}"
        if self.store.completed(exec_id):
            return None
        self.store.begin(exec_id)
        upstream = {}
        node_recs = []
        for node in MATS['tasks'][task]['nodes']:
            kind = node['kind']
            delivery = kind in DELIVERY_KINDS
            base_model = ('qwen' if (cell == 'HetQR' and kind == 'reason')
                          else 'deepseek')
            sysp = SYS_COMMON + (D2_CONTRACT if delivery else '')
            userp = node_prompt(task, node, upstream)
            if delivery:
                ru = node.get('reference_upstream') or {}
                nup = n_upstream_facts(upstream, ru.get('from_nodes', []))
                mt = min(D1_CAP, MAXTOK_BASE + D1_PER_FACT * nup)
            else:
                nup, mt = 0, MAXTOK_BASE
            text, rec = self.call(cell, task, rep, node['node_id'], 'base',
                                  base_model, sysp, userp, mt)
            node_recs.append(rec)
            ok, facts, unk = parse_facts(text)
            base_out = dict(ok=ok, facts=facts, unknown=unk,
                            score=score_node(facts), model=base_model,
                            max_tokens=mt, n_upstream_facts=nup)
            sig = signals(node, ok, facts)
            chosen = dict(model=base_model, facts=facts, unknown=unk,
                          rerolled=False)
            reroll_out = None
            if sig['exec'] or sig['prod'] or sig['cite']:
                text2, rec2 = self.call(cell, task, rep, node['node_id'],
                                        'reroll', base_model, sysp, userp, mt)
                node_recs.append(rec2)
                ok2, facts2, unk2 = parse_facts(text2)
                reroll_out = dict(ok=ok2, facts=facts2, unknown=unk2,
                                  score=score_node(facts2), model=base_model,
                                  max_tokens=mt)
                if score_node(facts2) > score_node(facts):
                    chosen = dict(model=base_model, facts=facts2,
                                  unknown=unk2, rerolled=True)
            adopted = 'reroll' if chosen.get('rerolled') else 'base'
            upstream[node['node_id']] = chosen['facts']
            node_recs.append(dict(node_id=node['node_id'], kind=kind,
                                  delivery=delivery, signals=sig,
                                  chosen=chosen, base_output=base_out,
                                  reroll_output=reroll_out, adopted=adopted))
        record = dict(exec_id=exec_id, cell=cell, task=task, rep=rep,
                      nodes=node_recs, budget_left=self.gb.left())
        self.store.commit(record)
        return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq3_stat_v1_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq3_stat_v1_runs'))
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--reps', type=int, default=5)
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED: STAGE_D_REAL_CALLS_AUTHORIZED=1 required')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                raise SystemExit(f'REFUSED: {k} not set')
        print('REAL MODE — caps:', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE — zero real calls')
    r = R3Runner(cfg, a.out, a.real)
    done = skipped = 0
    stopped = False
    for task in TASKS:
        for rep in range(1, a.reps + 1):
            for cell in CELLS:
                exec_id = f"{cell}|{task}|r{rep}"
                if r.store.completed(exec_id):
                    skipped += 1
                    continue
                left = r.gb.left()
                if left['calls_left'] < 10:
                    print(f'STOP before {exec_id}: calls_left='
                          f'{left["calls_left"]} < 10')
                    stopped = True
                    break
                rec = r.run_exec(cell, task, rep)
                if rec is not None:
                    done += 1
                    print(f'  {exec_id} done, calls_left='
                          f'{r.gb.left()["calls_left"]}')
            if stopped:
                break
        if stopped:
            break
    print(f'BATCH DONE: executed={done} skipped={skipped} '
          f'stopped_early={stopped} budget={r.gb.left()}')


if __name__ == '__main__':
    main()
