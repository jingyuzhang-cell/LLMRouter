"""FG (Full-Graph re-execution) control arm on the frozen multidag 120-task panel.

Supplementary experiment (see FULLGRAPH_PROTOCOL.md). Identical to the RD
(Dynamic-RealDetector) arm of multidag_ablation_120 in initial DAG, model
assignment, deployable detection, recovery targets, budget rule and stopping
(one recovery attempt per failed node, single detection pass per stage) — the
ONLY difference is execution scope: every feedback-triggered recovery
re-executes the ENTIRE graph (e1, e2, r, v) instead of the failed node plus its
descendant closure. The triggering node uses its recovery model; all other
nodes keep their current model (planned unless previously recovered), so
recoveries persist across rounds and clean-node re-executions are deterministic
pure cost at temperature 0.

Initial-pass calls are the same cached keys as the base panel (same initial DAG
by design). Every adaptation call is a REAL execution under a new arm-prefixed
key. Budget is NOT enforced at execution time (like RD); violations are
post-hoc statistics against 1.2 x Static-arm realized tokens.
"""
import fcntl
import hashlib
import json
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .multidag_dynamic import (OUT, VPROMPT, close, json_value,
                               parse_facts_safe, value_of, cost_of, append)
from .multidag_ablation import ABL

FG = OUT.parent / 'multidag_fullgraph_120'
HEADROOM = 1.2
PLANNED = {'e1': 'large', 'e2': 'large', 'r': 'medium', 'v': 'coder'}


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def freeze():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    import os
    here = os.path.dirname(__file__)
    bindings = {}
    for p in [os.path.join(here, 'multidag_fullgraph.py'),
              os.path.join(here, 'multidag_ablation.py'),
              os.path.join(here, 'multidag_dynamic.py'),
              str(OUT / 'POLICY.json')]:
        try:
            bindings[p] = sha(open(p).read())
        except Exception:
            pass
    policy = dict(
        role='multidag_fullgraph_control_arm_one_shot',
        base_panel='multidag_dynamic_120 (frozen, unchanged)',
        base_controls='multidag_ablation_120 sm (Static-Matched) and rd (Dynamic-Real, local)',
        n_tasks=pol['n_tasks'],
        question='how much computation does dependency-aware local recovery save vs feedback-triggered full-graph re-execution, at what quality difference?',
        arm_fg=dict(
            semantics='IDENTICAL to RD arm rules except execution scope: every feedback-triggered recovery re-executes ALL nodes e1,e2,r,v',
            shared_with_rd=['initial DAG execution (cached base-panel keys)',
                            'model assignment (planned e=large,r=medium,v=coder)',
                            'deployable detection: e=facts unparseable/empty; r=expression unparseable/unexecutable; v=value unparseable or disagrees with r value; gold NEVER triggers recovery',
                            'recovery targets: e first failure->coder later->medium (cross-task memory, frozen task order); r->large; v->large',
                            'one recovery attempt per failed node; single detection pass per stage; stages e->r->v',
                            'budget rule per-task = 1.2 x Static-arm realized tokens; NOT enforced at execution (ungated like RD); violations reported post-hoc for both arms',
                            'generation temperature 0, top_p 1, max_tokens 512; same prompts'],
            scope_difference='each feedback round re-executes the whole graph; triggering node gets its recovery model, other nodes keep their CURRENT model (recoveries persist)',
            rounds='per task at most 3 rounds (e round handles all e failures at once, r round, v round); 4 real calls per round'),
        budget_accounting='post-hoc violation statistics against 1.2 x static realized; no hard limit at execution; same口径 for RD and FG',
        all_tasks_kept=True,
        supplementary_not_confirmatory=True,
        generation='temperature 0, top_p 1, max_tokens 512; initial-pass keys shared with base panel (cache reuse)',
        one_shot=True,
        code_sha256=bindings)
    FG.mkdir(parents=True, exist_ok=True)
    (FG / 'POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, n=pol['n_tasks'])))


class Caller:
    def __init__(self):
        self.proc = self.log = None
        self.current = None
        self.cache = {}
        for folder in (OUT, ABL, FG):
            p = folder / 'RESPONSES.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.cache[r['key']] = r
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(self, key, model, prompt):
        if key in self.cache:
            if self.cache[key]['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return self.cache[key]
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
                self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model
        append(FG / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp)
        append(FG / 'RESPONSES.jsonl', rec)
        self.cache[key] = rec
        if resp.get('status') != 'delivered':
            raise RuntimeError('Infrastructure failure: ' + key)
        return rec

    def close(self):
        if self.proc is not None:
            engine.stop_model(self.proc, self.log)
            self.proc = None
        try:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception:
            pass
        self.lock.close()


def run():
    if not (FG / 'POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    if (FG / 'DONE.json').exists():
        raise FileExistsError('fullgraph run complete')
    engine.OUT = FG
    caller = Caller()
    t0 = time.time()
    try:
        # shared initial state (same cached initial passes as base panel and RD)
        init = {}
        for t in tasks:
            uid = t['uid']
            f1, _ = parse_facts_safe(caller.cache[f'e1:{uid}']['response']['answer'])
            f2, _ = parse_facts_safe(caller.cache[f'e2:{uid}']['response']['answer'])
            init[uid] = dict(f1=f1, f2=f2)
        armstate = {}
        for t in tasks:
            uid = t['uid']
            armstate[uid] = dict(e1=init[uid]['f1'], e2=init[uid]['f2'], ok=None, events=[], rounds=[],
                                 keys=[f'e1:{uid}', f'e2:{uid}', f'r:{uid}', f'v:{uid}'],
                                 node_model=dict(PLANNED),
                                 question=t['question'], gold=t['answer'],
                                 ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)

        def merged(st):
            return {'facts': st['e1']['facts'] + st['e2']['facts']}

        def latest(st, prefix):
            return [k for k in st['keys'] if k.split(':')[0] == prefix][-1]

        def r_value(st):
            return value_of(caller.cache[latest(st, 'r')]['response']['answer'], merged(st))

        def refresh_expr(st):
            val, err = r_value(st)
            st['expr_text'] = 'UNPARSEABLE' if err else v.decode(caller.cache[latest(st, 'r')]['response']['answer'])['expression']
            return (not err) and close(val, st['gold'])

        def call_node(st, node, model, key):
            if node in ('e1', 'e2'):
                caller.call(key, model, v.eprompt(dict(question=st['question'], context=st['ctx'][node])))
                fnew, _ = parse_facts_safe(caller.cache[key]['response']['answer'])
                st[node] = fnew
            elif node == 'r':
                caller.call(key, model, v.sprompt(dict(question=st['question']), merged(st)))
            else:
                caller.call(key, model, VPROMPT.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                                       expr=st['expr_text'] or 'UNPARSEABLE'))
            st['keys'].append(key)
            st['node_model'][node] = model

        def exec_round(ts, round_tag, override, round_index):
            # e1/e2 (independent) -> r -> refresh expr -> v (v prompt needs the new expr).
            # Calls are batched by model within each node pass so the vLLM server
            # is not restarted per task (decisions are task-local; call order does
            # not affect any decision, only wall-clock cost).
            for node in ('e1', 'e2', 'r', 'v'):
                by_model = {}
                for t in ts:
                    st = armstate[t['uid']]
                    m = override(t, node) if override else None
                    m = m or st['node_model'][node]
                    by_model.setdefault(m, []).append((t, st))
                for m in sorted(by_model):
                    for t, st in by_model[m]:
                        key = f'{node}:fg:{t["uid"]}:{round_tag}'
                        call_node(st, node, m, key)
                        rd_ = st['rounds'][round_index]
                        rd_['executed'].append(key)
                        rd_['models'][node] = m
                if node == 'r':
                    for t in ts:
                        st = armstate[t['uid']]
                        st['expr_text'] = None
                        refresh_expr(st)

        # ---- stage E: extraction failures -> one full-graph round per affected task ----
        n_ext_fail_seen = 0
        e_models = {}
        for t in tasks:
            uid = t['uid']
            st = armstate[uid]
            trig = []
            for node in ('e1', 'e2'):
                if st[node]['facts']:
                    continue
                model = 'medium' if n_ext_fail_seen > 0 else 'coder'
                n_ext_fail_seen += 1
                e_models[(uid, node)] = model
                trig.append(node)
                st['events'].append(dict(node=node, kind='fb', model=model, attempted=True, stage='e'))
            if trig:
                st['rounds'].append(dict(round='e', triggered=trig,
                                         models={n: e_models.get((uid, n), PLANNED[n]) for n in ('e1', 'e2', 'r', 'v')},
                                         executed=[]))
        affected = [t for t in tasks if armstate[t['uid']]['rounds']]
        if affected:
            exec_round(affected, 'e', lambda t, node: e_models.get((t['uid'], node), PLANNED[node]), 0)

        # ---- stage R: r failure (deployable) -> one full-graph round per task ----
        r_tasks = []
        for t in tasks:
            st = armstate[t['uid']]
            if r_value(st)[1]:  # unparseable or unexecutable (deployable signal)
                r_tasks.append(t)
                st['events'].append(dict(node='r', kind='esc', model='large', attempted=True, stage='r'))
                st['rounds'].append(dict(round='r', triggered=['r'],
                                         models={n: st['node_model'][n] for n in ('e1', 'e2', 'r', 'v')},
                                         executed=[]))
        if r_tasks:
            exec_round(r_tasks, 'r', lambda t, node: {'r': 'large'}.get(node), -1)

        # ---- stage V: v failure (deployable) -> one full-graph round per task ----
        v_tasks = []
        for t in tasks:
            uid = t['uid']
            st = armstate[uid]
            vval = json_value(caller.cache[latest(st, 'v')]['response']['answer'])
            if close(vval, t['answer']):
                st['ok'] = True
                continue
            rval, rerr = r_value(st)
            v_deployable_fail = (vval is None) or (not rerr and not close(vval, rval))
            if v_deployable_fail:
                v_tasks.append(t)
                st['events'].append(dict(node='v', kind='esc', model='large', attempted=True, stage='v'))
                st['rounds'].append(dict(round='v', triggered=['v'],
                                         models={n: st['node_model'][n] for n in ('e1', 'e2', 'r', 'v')},
                                         executed=[]))
            else:
                st['ok'] = False
        if v_tasks:
            exec_round(v_tasks, 'v', lambda t, node: {'v': 'large'}.get(node), -1)

        results = {}
        for t in tasks:
            st = armstate[t['uid']]
            if st['ok'] is None:
                vval = json_value(caller.cache[latest(st, 'v')]['response']['answer'])
                st['ok'] = close(vval, t['answer'])
            rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
            val, err = value_of(caller.cache[rks[-1]]['response']['answer'], merged(st))
            st['r_ok'] = int((not err) and close(val, t['answer']))
            st['used'] = sum(cost_of(caller.cache, k) for k in st['keys'])
            results[t['uid']] = dict(ok=st['ok'], r_ok=st['r_ok'], used=st['used'],
                                     keys=st['keys'], events=st['events'], rounds=st['rounds'])
        core.write(FG / 'RAW_TAIL.json', dict(wall_seconds=time.time() - t0, fg=results))
        core.write(FG / 'DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0,
                                          calls=len(caller.cache)))
        print(json.dumps(dict(done=True, calls=len(caller.cache), wall_seconds=round(time.time() - t0)), ensure_ascii=False))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
