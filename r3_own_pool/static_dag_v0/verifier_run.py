"""Dynamic + Verifier (DV) arm execution (frozen protocol: VERIFIER_SUBSET_PROTOCOL.md).

DV = RD (deployable Dynamic-Real, corrected v-stage) + r-node second opinion
(coder, same prompt/facts). Signal: both r executions parse+execute and their values
disagree -> r escalates to large (same recovery target as RD), v refresh, standard RD
v stage. All calls real; identical (model,prompt) pairs reused at temperature 0.
Verifier cost fully counted. Zero prompt/model/budget advantage anywhere.
"""
import fcntl
import hashlib
import json
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .multidag_dynamic import OUT, VPROMPT, close, json_value, parse_facts_safe, value_of
from .multidag_ablation import ABL
from .multidag_fullgraph import FG

DV = OUT.parent / 'adaptive_benchmark' / 'verifier_ablation'


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')
        f.flush()


class Caller:
    def __init__(self, folder):
        self.folder = folder
        self.by_key = {}
        self.by_mp = {}
        self.proc = self.log = None
        self.current = None
        for f in (OUT, ABL, FG, OUT.parent / 'adaptive_benchmark' / 'router_clean'):
            p = f / 'RESPONSES.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_key[r['key']] = r
        for f in (OUT, ABL, FG, OUT.parent / 'adaptive_benchmark' / 'router_clean'):
            p = f / 'REQUESTS.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l)
                    self.by_mp[(r['model'], sha(r['prompt']))] = r['key']
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(self, key, model, prompt):
        if key in self.by_key:
            rec = self.by_key[key]
            if rec['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return rec
        mp = (model, sha(prompt))
        if mp in self.by_mp:
            src = self.by_key[self.by_mp[mp]]
            rec = dict(key=key, model=model, response=src['response'], alias_of=self.by_mp[mp])
            self.by_key[key] = rec
            return rec
        if model != self.current:
            if self.proc is not None:
                engine.stop_model(self.proc, self.log)
                self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model)
            self.current = model
        append(self.folder / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp)
        append(self.folder / 'RESPONSES.jsonl', rec)
        self.by_key[key] = rec
        self.by_mp[mp] = key
        if resp.get('status') != 'delivered':
            raise RuntimeError('Infrastructure failure: ' + key)
        return rec

    def cost(self, key):
        return float((self.by_key[key]['response'].get('usage') or {}).get('total_tokens') or 0)

    def lat(self, key):
        return self.by_key[key]['response'].get('latency_s') or 0

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
    DV.mkdir(parents=True, exist_ok=True)
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    engine.OUT = DV
    caller = Caller(DV)
    t0 = time.time()
    try:
        init = {}
        for t in tasks:
            uid = t['uid']
            f1, _ = parse_facts_safe(caller.by_key[f'e1:{uid}']['response']['answer'])
            f2, _ = parse_facts_safe(caller.by_key[f'e2:{uid}']['response']['answer'])
            init[uid] = dict(f1=f1, f2=f2)
        state = {}
        for t in tasks:
            uid = t['uid']
            state[uid] = dict(e1=init[uid]['f1'], e2=init[uid]['f2'], ok=None, events=[], keys=[],
                              question=t['question'], gold=t['answer'],
                              ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None,
                              second_called=False, signal=None)

        def merged(st):
            return {'facts': st['e1']['facts'] + st['e2']['facts']}

        def call_into(st, node, model, key):
            if node in ('e1', 'e2'):
                caller.call(key, model, v.eprompt(dict(question=st['question'], context=st['ctx'][node])))
                fnew, _ = parse_facts_safe(caller.by_key[key]['response']['answer'])
                st[node] = fnew
            elif node == 'r':
                caller.call(key, model, v.sprompt(dict(question=st['question']), merged(st)))
            else:
                caller.call(key, model, VPROMPT.format(q=st['question'], facts=json.dumps(merged(st)['facts']),
                                                       expr=st['expr_text'] or 'UNPARSEABLE'))
            st['keys'].append(key)

        def latest_v(st):
            return [k for k in st['keys'] if k.split(':')[0] == 'v'][-1]

        def r_ans(st):
            return caller.by_key[[k for k in st['keys'] if k.split(':')[0] == 'r'][-1]]['response']['answer']

        def r_value(st):
            return value_of(r_ans(st), merged(st))

        def refresh_expr(st):
            val, err = r_value(st)
            st['expr_text'] = 'UNPARSEABLE' if err else v.decode(r_ans(st))['expression']
            return (not err) and close(val, st['gold'])

        # initial passes are the shared cached keys
        for t in tasks:
            u = t['uid']
            state[u]['keys'] = [f'e1:{u}', f'e2:{u}', f'r:{u}', f'v:{u}']
        # ---- stage 1: e failures (RD memory rule) ----
        n_ext_fail_seen = 0
        e_events = []
        for t in tasks:
            u = t['uid']
            st = state[u]
            for node in ('e1', 'e2'):
                if st[node]['facts']:
                    continue
                model = 'medium' if n_ext_fail_seen > 0 else 'coder'
                n_ext_fail_seen += 1
                e_events.append((u, st, node, model))
        for u, st, node, m in e_events:
            key = f'{node}:dv:{u}:fb'
            call_into(st, node, m, key)
            st['events'].append(dict(node=node, kind='fb', model=m, key=key))
        affected = {id(st) for _, st, _, _ in e_events}
        for t in tasks:
            u = t['uid']
            st = state[u]
            if id(st) in affected:
                key = f'r:dv:{u}:fb-d'
                call_into(st, 'r', 'medium', key)
                st['events'].append(dict(node='r', kind='refresh', model='medium', key=key))
                refresh_expr(st)
        # ---- stage 2: r failure = unexecutable (RD) OR second-opinion disagreement (NEW) ----
        r_esc = []
        signal_stats = dict(fired=0, both_exec=0, correct_initial=0, wrong_initial=0, new_fired=0)
        for t in tasks:
            u = t['uid']
            st = state[u]
            rval, rerr = r_value(st)
            fail = rerr
            reason = 'execution'
            if not rerr:
                # second opinion (coder, same facts) — the verifier
                key = f'r2:dv:{u}'
                caller.call(key, 'coder', v.sprompt(dict(question=st['question']), merged(st)))
                st['keys'].append(key)
                st['second_called'] = True
                sval, serr = value_of(caller.by_key[key]['response']['answer'], merged(st))
                if not serr and not close(rval, sval):
                    fail = True
                    reason = 'disagreement'
                signal_stats['both_exec'] += int(not serr)
                # post-hoc label of the initial r's actual correctness (value on its own facts vs gold)
                signal_stats['wrong_initial'] += int(not close(rval, st['gold']))
                signal_stats['correct_initial'] += int(close(rval, st['gold']))
            if fail:
                st['signal'] = reason
                if reason == 'disagreement':
                    signal_stats['fired'] += 1
                    if not close(rval, st['gold']):
                        signal_stats['new_fired'] += 1
                r_esc.append((u, st))
            refresh_expr(st)
        for u, st in r_esc:
            key = f'r:dv:{u}:esc'
            call_into(st, 'r', 'large', key)
            st['events'].append(dict(node='r', kind='esc', model='large', key=key,
                                     signal=st['signal']))
            refresh_expr(st)
        # ---- stage 3: v refresh for r-changed tasks ----
        for t in tasks:
            u = t['uid']
            st = state[u]
            rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
            if len(rks) > 1:
                key = f'v:dv:{u}:fb-d'
                call_into(st, 'v', 'coder', key)
                st['events'].append(dict(node='v', kind='refresh', model='coder', key=key))
        # ---- stage 4: v failure (RD deployable) ----
        v_esc = []
        for t in tasks:
            u = t['uid']
            st = state[u]
            vval = json_value(caller.by_key[latest_v(st)]['response']['answer'])
            if close(vval, t['answer']):
                st['ok'] = True
                continue
            rval, rerr = r_value(st)
            v_fail = (vval is None) or (not rerr and not close(vval, rval))
            if v_fail:
                v_esc.append((u, st))
            else:
                st['ok'] = False
        for u, st in v_esc:
            key = f'v:dv:{u}:esc'
            call_into(st, 'v', 'large', key)
            st['events'].append(dict(node='v', kind='esc', model='large', key=key))
            vval = json_value(caller.by_key[key]['response']['answer'])
            st['ok'] = close(vval, st['gold'])
        results = {}
        for t in tasks:
            u = t['uid']
            st = state[u]
            if st['ok'] is None:
                vval = json_value(caller.by_key[latest_v(st)]['response']['answer'])
                st['ok'] = close(vval, st['gold'])
            results[u] = dict(ok=st['ok'], keys=st['keys'], events=st['events'],
                              used=sum(caller.cost(k) for k in st['keys']),
                              lat=sum(caller.lat(k) for k in st['keys']),
                              signal=st['signal'])
        rep = dict(wall_seconds=time.time() - t0, signal_stats=signal_stats,
                   dv=results, calls=len(caller.by_key))
        core.write(DV / 'DV_RESULT.json', rep)
        q = sum(1 for u in results if results[u]['ok']) / len(tasks)
        print(json.dumps(dict(done=True, Q_dv=round(q, 4), signal_stats=signal_stats,
                              calls=len(caller.by_key), wall=round(rep['wall_seconds'])), ensure_ascii=False))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
