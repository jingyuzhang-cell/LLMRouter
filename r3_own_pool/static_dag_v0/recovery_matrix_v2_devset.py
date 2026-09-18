"""Build the frozen dev failure set for the Local Subgraph Replan pilot (~40 nodes).
Criterion-pure: task final answer (original reasoning expression executed on ACTUAL extracted
facts) verifiably wrong; node disjoint from the frozen 116/pool-148/pilot-20/decompose-40.
Labels: evidence = extraction node with ER<1; reasoning = rs with <=2 ops; structural = rs with >=3 ops."""
import hashlib
import json
from collections import Counter
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .tatqa_benchmark_build import literals
from .recovery_matrix_v2_snapshot import BASE, Sources, build_snapshot, offline_payload

DEV = BASE / 'recovery_matrix_v2/dev_replan_pilot'

def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))

def er(facts, required):
    return sum(any(close(f['value'], x) for f in facts['facts']) for x in required) / len(required) if required else 1.

def build_dev():
    used = set()
    used |= {n['node_id'] for n in json.loads((BASE / 'recovery_matrix_v2_pool_final.json').read_text())}
    used |= {r['node_id'] for r in json.loads((BASE / 'scale_up/decompose_at_scale/RESULTS.json').read_text())['rows']}
    src = Sources()
    # --- multihiertt (fresh_static_confirmation) ---
    mh_tasks = {t['uid']: t for t in json.loads((BASE / 'fresh_static_confirmation/TASKS.json').read_text())}
    mh_nodes = json.loads((BASE / 'fresh_static_confirmation/NODES.json').read_text())
    mh_resp = list(map(json.loads, (BASE / 'fresh_static_confirmation/medium_RESPONSES.jsonl').open()))
    mh_ext = {r['task_uid']: r for r in mh_resp if r['node_type'] == 'extraction'}
    mh_rs = {r['task_uid']: r for r in mh_resp if r['node_type'] == 'reasoning'}
    # --- tatqa benchmark (40) ---
    tq_tasks = {t['uid']: t for t in json.loads((BASE / 'tatqa_benchmark/TASKS.json').read_text())}
    tq_nodes = json.loads((BASE / 'tatqa_benchmark/NODES.json').read_text())
    tq_resp = list(map(json.loads, (BASE / 'tatqa_benchmark/medium_RESPONSES.jsonl').open()))
    tq_ext = {r['task_uid']: r for r in tq_resp if r['node_type'] == 'extraction'}
    tq_rs = {r['task_uid']: r for r in tq_resp if r['node_type'] == 'reasoning'}
    # --- tatqa scale_up (160) ---
    su_tasks = {t['uid']: t for t in json.loads((BASE / 'scale_up/TQ_TASKS.json').read_text())}
    su_resp = {r['key']: r for r in map(json.loads, (BASE / 'scale_up/RESPONSES.jsonl').open())}

    def required_operands(dom, task):
        if dom == 'multihiertt':
            import re
            prog = task['program']; vals = []
            for args in re.findall(r'\(([^()]*)\)', prog):
                for x in args.split(','):
                    x = x.strip()
                    if x.startswith('#') or x.startswith('const_'): continue
                    try: vals.append(float(x))
                    except ValueError: pass
            return sorted(set(vals))
        return sorted({x for x in literals(task['derivation']) if x not in (0., 1., 100.)})

    def n_ops(dom, task):
        import re
        if dom == 'multihiertt':
            return len(re.findall(r'(?:add|subtract|multiply|divide)\(', task['program']))
        return len(re.findall(r'[+\-*/]', task['derivation']))

    candidates = []
    def add(dom, uid, task):
        # task-level final wrongness on ACTUAL facts
        if dom == 'multihiertt':
            ext, rsn = mh_ext.get(uid), mh_rs.get(uid)
        elif (uid in tq_ext) and (uid in tq_rs):
            ext, rsn = tq_ext[uid], tq_rs[uid]
        else:
            ext, rsn = su_resp.get('tq:' + uid + ':ext'), su_resp.get('tq:' + uid + ':rsn')
        if ext is None or rsn is None or ext.get('status') != 'delivered': return
        try: facts = v.parse_facts(ext['answer'])
        except Exception: facts = {'facts': []}
        try:
            expr = v.decode(rsn['answer'])['expression']
            val = exec_calc(expr, facts)
            wrong = not close(val, task['answer'])
        except Exception:
            wrong = True
        if not wrong: return
        req = required_operands(dom, task); nops = n_ops(dom, task)
        # failure nodes of this task
        nid_rs = uid + ':rs'
        if nid_rs not in used:
            label = 'structural' if nops >= 3 else 'reasoning'
            candidates.append(dict(node_id=nid_rs, task_uid=uid, domain=dom, label=label,
                                   n_ops=nops, ER_before=er(facts, req)))
        if dom == 'multihiertt':
            for exn in ['ex0', 'ex1']:
                nid = uid + ':' + exn
                if nid in used: continue
                if er(facts, req) < 1:
                    candidates.append(dict(node_id=nid, task_uid=uid, domain=dom, label='evidence',
                                           n_ops=nops, ER_before=er(facts, req)))
        elif (uid + ':ex0') not in used and er(facts, req) < 1:
            candidates.append(dict(node_id=uid + ':ex0', task_uid=uid, domain=dom, label='evidence',
                                   n_ops=nops, ER_before=er(facts, req)))

    for uid, t in mh_tasks.items(): add('multihiertt', uid, t)
    for uid, t in tq_tasks.items(): add('tatqa', uid, t)
    for uid, t in su_tasks.items(): add('tatqa', uid, t)
    # dedupe (benchmark tatqa tasks may double as scale_up tasks) and order deterministically
    seen = set(); dedup = []
    for c in candidates:
        if c['node_id'] in seen: continue
        seen.add(c['node_id']); dedup.append(c)
    dedup.sort(key=lambda c: hashlib.sha256(c['node_id'].encode()).hexdigest())
    # snapshot-validity filter (build_snapshot requires records; scale_up tasks need tasks entry too)
    valid = []
    for c in dedup:
        node = dict(node_id=c['node_id'], task_uid=c['task_uid'], domain=c['domain'])
        try:
            snap = build_snapshot(node, src)
            if snap['valid']: valid.append(c)
        except Exception: pass
    selected = valid[:40]
    counts = Counter(c['label'] for c in selected)
    DEV.mkdir(parents=True, exist_ok=True)
    (DEV / 'runtime').mkdir(exist_ok=True); (DEV / 'offline').mkdir(exist_ok=True)
    for c in selected:
        node = dict(node_id=c['node_id'], task_uid=c['task_uid'], domain=c['domain'], label=c['label'])
        name = hashlib.sha256(c['node_id'].encode()).hexdigest() + '.json'
        (DEV / 'runtime' / name).write_text(json.dumps(build_snapshot(node, src), ensure_ascii=False, indent=2))
        (DEV / 'offline' / name).write_text(json.dumps(offline_payload(node, src), ensure_ascii=False, indent=2))
    (DEV / 'dev_failure_set.json').write_text(json.dumps(dict(
        frozen_116_disjoint=True, criterion='task final answer wrong on actual extraction facts',
        labels=dict(counts), n=len(selected), nodes=selected,
        n_available_before_cap=len(valid)), ensure_ascii=False, indent=2))
    print(json.dumps(dict(n_selected=len(selected), labels=dict(counts),
                          n_available=len(valid), total_candidates=len(dedup),
                          domains=dict(Counter(c['domain'] for c in selected))), indent=1))
    return selected

if __name__ == '__main__':
    build_dev()
