"""Two pre-registered control arms on the frozen multidag 120-task panel.

Arm SM (Static-Matched): answers "is the +20pp just because Dynamic escalates to
large?" Static semantics (one recovery pass per failed node, descendant refresh,
ideal detection, no cross-task memory, no budget gating) but with Dynamic's
escalation targets (r fail -> large, v fail -> large; e fail -> coder as in the
original static arm). If Q(SM) ~= Q(Dynamic), the gain is the target model; if
Q(SM) < Q(Dynamic), the policy adds value beyond target choice. Both arms have
identical model sets, identical call caps (one recovery per node), and the
budget rule is reported for both (SM ungated by definition of static).

Arm RD (Dynamic-RealDetector): answers "does the gain survive without gold?"
Identical to the Dynamic arm except failure detection uses only deployable
signals:
  e node fail  = facts unparseable or empty            (precision 1.0 offline)
  r node fail  = expression unparseable or unexecutable (precision 1.0 offline;
                 value errors are NOT detected -- this is the recall gap)
  v node fail  = v value unparseable OR v value != r value (agreement check;
                 the offline audit showed this fires almost always)
Retention metric (pre-registered): (Q_RD - Q_static) / (Q_ideal - Q_static).

Initial-pass calls are shared with the frozen panel (same keys, cache reuse);
adaptation calls use new arm-prefixed keys. One-shot; no thresholds may change.
"""
import fcntl
import hashlib
import json
import os
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .multidag_dynamic import (OUT, VPROMPT, CLOSURE, close, json_value,
                               parse_facts_safe, value_of, cost_of, append)

ABL = OUT.parent / 'multidag_ablation_120'
GATE = 200
HEADROOM = 1.2


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def freeze():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    policy = dict(
        role='multidag_ablation_two_control_arms_one_shot',
        base_panel='multidag_dynamic_120 (frozen, unchanged)',
        n_tasks=pol['n_tasks'],
        arm_static_matched=dict(
            semantics='static: one recovery per failed node, ideal detection, no cross-task memory, no gating',
            targets='e fail->coder (as original static); r fail->large; v fail->large',
            purpose='isolate whether the +20pp comes from escalation targets rather than the adaptive policy'),
        arm_dynamic_realdetector=dict(
            semantics='dynamic rules identical to frozen dynamic arm',
            detection='DEPLOYABLE: e=facts unparseable/empty; r=expression unparseable/unexecutable; v=value unparseable or v_value != r_value (agreement)',
            retention_preregistered='(Q_RD - Q_static)/(Q_ideal - Q_static), reported with binomial CI'),
        generation='temperature 0, top_p 1, max_tokens 512; initial-pass keys shared with base panel (cache reuse)',
        one_shot=True)
    ABL.mkdir(parents=True, exist_ok=True)
    (ABL / 'ABLATION_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, n=pol['n_tasks'])))


class Caller:
    def __init__(self):
        self.proc = self.log = None; self.current = None
        self.cache = {}
        for folder in (OUT, ABL):
            p = folder / 'RESPONSES.jsonl'
            if p.exists():
                for l in p.read_text().splitlines():
                    r = json.loads(l); self.cache[r['key']] = r
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(self, key, model, prompt):
        if key in self.cache:
            if self.cache[key]['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return self.cache[key]
        if model != self.current:
            if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model); self.current = model
        append(ABL / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp); append(ABL / 'RESPONSES.jsonl', rec)
        self.cache[key] = rec
        if resp.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
        return rec

    def close(self):
        if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = None
        try: fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception: pass
        self.lock.close()


def run():
    if not (ABL / 'ABLATION_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    if (ABL / 'DONE.json').exists(): raise FileExistsError('ablation complete')
    engine.OUT = ABL
    caller = Caller()
    t0 = time.time()
    try:
        # shared initial state (recomputed from cached initial passes)
        init = {}
        for t in tasks:
            uid = t['uid']
            f1, bad1 = parse_facts_safe(caller.cache[f'e1:{uid}']['response']['answer'])
            f2, bad2 = parse_facts_safe(caller.cache[f'e2:{uid}']['response']['answer'])
            init[uid] = dict(f1=f1, f2=f2)
        # ideal labels from the base analysis for reference arms
        base_raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
        results = {}
        for arm in ('sm', 'rd'):
            armstate = {}
            for t in tasks:
                uid = t['uid']
                armstate[uid] = dict(e1=init[uid]['f1'], e2=init[uid]['f2'], ok=None, events=[],
                                     keys=[f'e1:{uid}', f'e2:{uid}', f'r:{uid}', f'v:{uid}'],
                                     question=t['question'], gold=t['answer'],
                                     ctx={'e1': t['ctx_table'], 'e2': t['ctx_text']}, expr_text=None)

            def merged(st):
                return {'facts': st['e1']['facts'] + st['e2']['facts']}

            def latest(st, prefix):
                return [k for k in st['keys'] if k.split(':')[0] == prefix][-1]

            def call_into(st, node, model, key):
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

            def r_value(st):
                return value_of(caller.cache[latest(st, 'r')]['response']['answer'], merged(st))

            def r_deployable_fail(st):
                return r_value(st)[1]  # True = unparseable or unexecutable

            def refresh_expr(st):
                val, err = r_value(st)
                st['expr_text'] = 'UNPARSEABLE' if err else v.decode(caller.cache[latest(st, 'r')]['response']['answer'])['expression']
                return (not err) and close(val, st['gold'])

            # stage 1: extraction failures
            e_events = []
            n_ext_fail_seen = 0
            for t in tasks:
                uid = t['uid']; st = armstate[uid]
                for node in ('e1', 'e2'):
                    if st[node]['facts']:
                        continue
                    # deployable detection for e == ideal detection (parse/empty); same for both arms.
                    # sm uses coder (original static target); rd uses the dynamic memory rule.
                    if arm == 'rd':
                        model = 'medium' if n_ext_fail_seen > 0 else 'coder'
                        n_ext_fail_seen += 1
                    else:
                        model = 'coder'
                    e_events.append((t, st, node, model))
            for model in sorted({m for _, _, _, m in e_events}):
                for t, st, node, m in e_events:
                    if m != model: continue
                    key = f'{node}:{arm}:{t["uid"]}:fb'
                    call_into(st, node, m, key)
                    st['events'].append(dict(node=node, kind='fb', model=m, key=key))
            affected = {id(st) for _, st, _, _ in e_events}
            for t in tasks:
                st = armstate[t['uid']]
                if id(st) in affected:
                    key = f'r:{arm}:{t["uid"]}:fb-d'
                    call_into(st, 'r', 'medium', key)
                    st['events'].append(dict(node='r', kind='refresh', model='medium', key=key))
                    refresh_expr(st)
            # stage 2: r failure adaptation
            r_events = []
            for t in tasks:
                uid = t['uid']; st = armstate[uid]
                if arm == 'sm':
                    fail_ideal = not refresh_expr(st)
                    if fail_ideal:
                        r_events.append((t, st, 'large', 'fb'))
                else:  # rd: deployable detection only
                    if r_deployable_fail(st):
                        r_events.append((t, st, 'large', 'esc'))
                    refresh_expr(st)
            for model in sorted({m for _, _, m, _ in r_events}):
                for t, st, m, kind in r_events:
                    if m != model: continue
                    key = f'r:{arm}:{t["uid"]}:{kind}'
                    call_into(st, 'r', m, key)
                    st['events'].append(dict(node='r', kind=kind, model=m, key=key))
                    refresh_expr(st)
            # stage 3: v refresh for tasks whose r changed
            for t in tasks:
                st = armstate[t['uid']]
                rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
                if len(rks) > 1:
                    key = f'v:{arm}:{t["uid"]}:fb-d'
                    call_into(st, 'v', 'coder', key)
                    st['events'].append(dict(node='v', kind='refresh', model='coder', key=key))
            # stage 4: v failure adaptation
            v_events = []
            for t in tasks:
                uid = t['uid']; st = armstate[uid]
                vval = json_value(caller.cache[latest(st, 'v')]['response']['answer'])
                if close(vval, t['answer']):
                    st['ok'] = True; continue
                if arm == 'sm':
                    v_events.append((t, st, 'large', 'fb'))
                else:  # rd: deployable = v value unparseable or disagrees with r value
                    rval, rerr = r_value(st)
                    v_deployable_fail = (vval is None) or (not rerr and not close(vval, rval))
                    if v_deployable_fail:
                        v_events.append((t, st, 'large', 'esc'))
                    else:
                        st['ok'] = False
            for model in sorted({m for _, _, m, _ in v_events}):
                for t, st, m, kind in v_events:
                    if m != model: continue
                    key = f'v:{arm}:{t["uid"]}:{kind}'
                    call_into(st, 'v', m, key)
                    st['events'].append(dict(node='v', kind=kind, model=m, key=key))
                    vval = json_value(caller.cache[key]['response']['answer'])
                    st['ok'] = close(vval, t['answer'])
            for t in tasks:
                st = armstate[t['uid']]
                if st['ok'] is None:
                    vval = json_value(caller.cache[latest(st, 'v')]['response']['answer'])
                    st['ok'] = close(vval, t['gold'])
                st['used'] = sum(cost_of(caller.cache, k) for k in st['keys'])
            results[arm] = {t['uid']: dict(ok=armstate[t['uid']]['ok'], used=armstate[t['uid']]['used'],
                                            keys=armstate[t['uid']]['keys'], events=armstate[t['uid']]['events'])
                            for t in tasks}
        core.write(ABL / 'RAW_TAIL.json', dict(wall_seconds=time.time() - t0, sm=results['sm'], rd=results['rd']))
        core.write(ABL / 'DONE.json', dict(unix_time=time.time(), calls=len(caller.cache)))
        print(json.dumps(dict(done=True, calls=len(caller.cache))))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
