"""Pre-run integrity tests (zero model calls).

1. Replay the RD arm of multidag_ablation_120 from cached responses only and
   assert per-task ok/keys/events match the frozen RAW_TAIL exactly. This
   validates the stage/detection semantics the FG arm is built on.
2. FG key-mapping audit: map every planned FG adaptation key to the RD/base key
   that (by determinism at temperature 0) must produce the same prompt, and
   assert prompt + model equality between the mapped pairs. This checks, before
   any new execution, that FG feeds each node exactly the same inputs as RD —
   i.e. FG differs from RD only in scope, not in content.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from static_dag_v0.multidag_dynamic import (OUT, close, json_value,
                                            parse_facts_safe, value_of)
from static_dag_v0.multidag_ablation import ABL
from static_dag_v0 import tool_aware_v1 as v

from static_dag_v0.multidag_fullgraph import FG, PLANNED


def load_cache():
    cache = {}
    for folder in (OUT, ABL):
        p = folder / 'RESPONSES.jsonl'
        for l in p.read_text().splitlines():
            r = json.loads(l)
            cache[r['key']] = r
    return cache


def replay_rd(cache):
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    init = {}
    for t in tasks:
        uid = t['uid']
        f1, _ = parse_facts_safe(cache[f'e1:{uid}']['response']['answer'])
        f2, _ = parse_facts_safe(cache[f'e2:{uid}']['response']['answer'])
        init[uid] = dict(f1=f1, f2=f2)
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
        assert key in cache, 'missing cached key: ' + key
        if node in ('e1', 'e2'):
            fnew, _ = parse_facts_safe(cache[key]['response']['answer'])
            st[node] = fnew
        elif node == 'r':
            pass
        st['keys'].append(key)

    def r_value(st):
        return value_of(cache[latest(st, 'r')]['response']['answer'], merged(st))

    def refresh_expr(st):
        val, err = r_value(st)
        st['expr_text'] = 'UNPARSEABLE' if err else v.decode(cache[latest(st, 'r')]['response']['answer'])['expression']
        return (not err) and close(val, st['gold'])

    # stage 1: extraction failures (rd memory rule)
    n_ext_fail_seen = 0
    e_events = []
    for t in tasks:
        uid = t['uid']; st = armstate[uid]
        for node in ('e1', 'e2'):
            if st[node]['facts']:
                continue
            model = 'medium' if n_ext_fail_seen > 0 else 'coder'
            n_ext_fail_seen += 1
            e_events.append((t, st, node, model))
    for t, st, node, m in e_events:
        key = f'{node}:rd:{t["uid"]}:fb'
        call_into(st, node, m, key)
        st['events'].append(dict(node=node, kind='fb', model=m, key=key))
    affected = {id(st) for _, st, _, _ in e_events}
    for t in tasks:
        st = armstate[t['uid']]
        if id(st) in affected:
            key = f'r:rd:{t["uid"]}:fb-d'
            call_into(st, 'r', 'medium', key)
            st['events'].append(dict(node='r', kind='refresh', model='medium', key=key))
            refresh_expr(st)
    # stage 2: r failure adaptation (deployable only)
    r_events = []
    for t in tasks:
        st = armstate[t['uid']]
        if r_value(st)[1]:
            r_events.append((t, st, 'large', 'esc'))
        refresh_expr(st)
    for t, st, m, kind in r_events:
        key = f'r:rd:{t["uid"]}:{kind}'
        call_into(st, 'r', m, key)
        st['events'].append(dict(node='r', kind=kind, model=m, key=key))
        refresh_expr(st)
    # stage 3: v refresh for tasks whose r changed
    for t in tasks:
        st = armstate[t['uid']]
        rks = [k for k in st['keys'] if k.split(':')[0] == 'r']
        if len(rks) > 1:
            key = f'v:rd:{t["uid"]}:fb-d'
            call_into(st, 'v', 'coder', key)
            st['events'].append(dict(node='v', kind='refresh', model='coder', key=key))
    # stage 4: v failure adaptation
    v_events = []
    for t in tasks:
        uid = t['uid']; st = armstate[uid]
        vval = json_value(cache[latest(st, 'v')]['response']['answer'])
        if close(vval, t['answer']):
            st['ok'] = True
            continue
        rval, rerr = r_value(st)
        v_deployable_fail = (vval is None) or (not rerr and not close(vval, rval))
        if v_deployable_fail:
            v_events.append((t, st, 'large', 'esc'))
        else:
            st['ok'] = False
    for t, st, m, kind in v_events:
        key = f'v:rd:{t["uid"]}:{kind}'
        call_into(st, 'v', m, key)
        st['events'].append(dict(node='v', kind=kind, model=m, key=key))
        vval = json_value(cache[key]['response']['answer'])
        st['ok'] = close(vval, t['answer'])
    for t in tasks:
        st = armstate[t['uid']]
        if st['ok'] is None:
            vval = json_value(cache[latest(st, 'v')]['response']['answer'])
            st['ok'] = close(vval, t['gold'])
    return armstate


def check_rd_replay(cache):
    raw = json.loads((ABL / 'RAW_TAIL.json').read_text())
    pol = json.loads((OUT / 'POLICY.json').read_text())
    replay = replay_rd(cache)
    bad = []
    for t in pol['tasks']:
        u = t['uid']
        a, b = replay[u], raw['rd'][u]
        if a['ok'] != b['ok'] or a['keys'] != b['keys'] or a['events'] != b['events']:
            bad.append(dict(uid=u, ok=(a['ok'], b['ok']), keys_eq=a['keys'] == b['keys'],
                            events_eq=a['events'] == b['events']))
    print('RD replay: tasks matched =', 120 - len(bad), '/ 120')
    if bad:
        for x in bad[:5]:
            print('  mismatch', x)
    return not bad


def rd_events_per_task(cache):
    raw = json.loads((ABL / 'RAW_TAIL.json').read_text())
    pol = json.loads((OUT / 'POLICY.json').read_text())
    out = {}
    for t in pol['tasks']:
        u = t['uid']
        evs = raw['rd'][u]['events']
        out[u] = dict(
            e_failed=[e['node'] for e in evs if e['node'] in ('e1', 'e2') and e['kind'] == 'fb'],
            r_esc=any(e['node'] == 'r' and e['kind'] == 'esc' for e in evs),
            v_esc=any(e['node'] == 'v' and e['kind'] == 'esc' for e in evs),
            r_refresh=any(e['kind'] == 'refresh' and e['node'] == 'r' for e in evs),
            v_refresh=any(e['kind'] == 'refresh' and e['node'] == 'v' for e in evs))
    return out


def check_fg_mapping(cache):
    """Map every FG adaptation key to the RD/base key that must share its prompt
    and model (deterministic equivalence). Assert the mapping is coherent:
    models agree and (for keys present in the FG REQUESTS log) prompts agree."""
    pol = json.loads((OUT / 'POLICY.json').read_text())
    rd = rd_events_per_task(cache)
    reqs = {}
    for folder in (OUT, ABL):
        for l in (folder / 'REQUESTS.jsonl').read_text().splitlines():
            r = json.loads(l)
            reqs[r['key']] = r
    problems = []
    n_checked = 0
    for t in pol['tasks']:
        u = t['uid']
        e_failed = set(rd[u]['e_failed'])
        # stage E mapping (tasks with any e failure)
        if e_failed:
            mapping = {}
            for node in ('e1', 'e2'):
                fg_key = f'{node}:fg:{u}:e'
                mapping[fg_key] = f'{node}:rd:{u}:fb' if node in e_failed else f'{node}:{u}'
            mapping[f'r:fg:{u}:e'] = f'r:rd:{u}:fb-d'
            # when r esc also fires, RD's single v refresh uses the esc expression;
            # FG's stage-E v uses the medium-r expression, so it is an EXTRA
            # intermediate call with no RD counterpart (its output is later
            # overwritten by the stage-R v). Only map when no r esc.
            if not rd[u]['r_esc']:
                mapping[f'v:fg:{u}:e'] = f'v:rd:{u}:fb-d'
        else:
            mapping = {}
        # stage R mapping
        if rd[u]['r_esc']:
            for node in ('e1', 'e2'):
                mapping[f'{node}:fg:{u}:r'] = f'{node}:rd:{u}:fb' if node in e_failed else f'{node}:{u}'
            mapping[f'r:fg:{u}:r'] = f'r:rd:{u}:esc'
            mapping[f'v:fg:{u}:r'] = f'v:rd:{u}:fb-d'
        # stage V mapping
        if rd[u]['v_esc']:
            for node in ('e1', 'e2'):
                mapping[f'{node}:fg:{u}:v'] = f'{node}:rd:{u}:fb' if node in e_failed else f'{node}:{u}'
            if rd[u]['r_esc']:
                mapping[f'r:fg:{u}:v'] = f'r:rd:{u}:esc'
            elif rd[u]['r_refresh']:
                mapping[f'r:fg:{u}:v'] = f'r:rd:{u}:fb-d'
            else:
                mapping[f'r:fg:{u}:v'] = f'r:{u}'
            mapping[f'v:fg:{u}:v'] = f'v:rd:{u}:esc'
        for fg_key, src_key in mapping.items():
            n_checked += 1
            if fg_key in reqs and src_key in reqs:
                if reqs[fg_key]['prompt'] != reqs[src_key]['prompt'] or reqs[fg_key]['model'] != reqs[src_key]['model']:
                    problems.append(dict(fg_key=fg_key, src_key=src_key))
            if src_key not in reqs:
                problems.append(dict(fg_key=fg_key, missing_src=src_key))
    print(f'FG mapping: {n_checked} mapped key pairs; problems = {len(problems)}')
    for p in problems[:5]:
        print('  problem', p)
    return n_checked, problems


if __name__ == '__main__':
    cache = load_cache()
    ok1 = check_rd_replay(cache)
    n, problems = check_fg_mapping(cache)
    print('REPLAY_OK' if ok1 else 'REPLAY_FAIL',
          'MAPPING_OK' if not problems else 'MAPPING_FAIL')
    sys.exit(0 if (ok1 and not problems) else 1)
