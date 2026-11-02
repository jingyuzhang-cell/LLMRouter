"""DD-V5.1 C_info experiment: 3 arms × 5 blocks. Tests whether C_info-based
joint scheduling improves terminal quality vs original C_norm and pi_only.

Arms:
  JointCnorm: Joint with original C_norm (baseline from v6)
  JointCinfo: Joint with C_info (information completeness fix)
  pi_only: Model reassignment only (best quality from v6)

Only difference between JointCnorm and JointCinfo: the C computation in
joint_select_action(). Everything else frozen.
"""
import json, re, sys, time, hashlib, random
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import Meter, BudgetExceeded

from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location('ag', '/root/r3_own_pool/deadline_reward_v1/auth_gate.py')
ag = module_from_spec(spec); sys.modules['ag'] = ag; spec.loader.exec_module(ag)
ag.require('dd_v51_cinfo')

OUT = B / 'dd_v51_cinfo_results'
OUT.mkdir(exist_ok=True)

MAX_CALLS = 150
MAX_TOKENS = 350_000
DEADLINE_S = 120
MODELS = {'strong': 'glm53', 'weak': 'glm53flash'}
SILVER = json.load(open(B / 'dd_v51_silver_facts.json'))

BLOCK_ORDER = [
    (1,'pi_only'),(1,'JointCinfo'),(1,'JointCnorm'),
    (2,'JointCinfo'),(2,'JointCnorm'),(2,'pi_only'),
    (3,'JointCnorm'),(3,'pi_only'),(3,'JointCinfo'),
    (4,'JointCinfo'),(4,'JointCnorm'),(4,'pi_only'),
    (5,'JointCnorm'),(5,'pi_only'),(5,'JointCinfo'),
]

# DAG — AUTHORITATIVE D_R1 spec
NODES = {
    'n1': dict(role='extraction',      deps=[]),
    'n2': dict(role='extraction',      deps=[]),
    'n3': dict(role='timeline',        deps=['n1']),
    'n4': dict(role='amounts',         deps=['n1']),
    'n5': dict(role='penalties',       deps=['n1','n2']),
    'n6': dict(role='entity_graph',    deps=['n1','n2']),
    'n7': dict(role='timeline_deep',   deps=['n3','n6']),
    'n8': dict(role='amounts_check',   deps=['n4']),
    'n9': dict(role='cross_check',     deps=['n5','n7','n8']),
    'n10':dict(role='synthesis',       deps=['n9']),
}
TOPO = ['n1','n2','n3','n4','n5','n6','n7','n8','n9','n10']
ANOMALIES = {'n3': 'transport', 'n5': 'evidence_fail'}

EXPECTED_OUTPUT_KEYS = {
    'extraction': ['facts'], 'timeline': ['timeline'], 'amounts': ['amounts'],
    'penalties': ['penalties'], 'entity_graph': ['entities'],
    'timeline_deep': ['stages'], 'amounts_check': ['amounts_checked'],
    'cross_check': ['verified_facts'], 'synthesis': ['report'],
}

# C_info frozen slots and scoring rules
N9_INFO_SLOTS = {
    'penalties_data':  dict(source='n5', weight=0.3),
    'timeline_stages': dict(source='n7', weight=0.3),
    'amounts_checked': dict(source='n8', weight=0.4),
}

zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV = {d['doc_id']: d['text'][:4000] for d in zeda['docs']}

def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))

SYS = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'

def build_prompt(nid, role, upstream, docs):
    if role == 'extraction':
        ds = '\n\n'.join(f'## 文档 {k}\n{v}' for k, v in docs.items())
        return f'{SYS}\n从下列处罚决定书文档中抽取关键事实（日期/金额/主体/违规行为/处罚）：\n{ds}\n输出JSON，字段 facts，数组。'
    if role == 'timeline':
        return f'{SYS}\n根据以下抽取事实整理时间线（按日期排序）：\n{str(upstream.get("n1",""))[:3000]}\n输出JSON，字段 timeline。'
    if role == 'amounts':
        return f'{SYS}\n汇总所有金额数据：\n{str(upstream.get("n1",""))[:3000]}\n输出JSON，字段 amounts。'
    if role == 'penalties':
        return f'{SYS}\n梳理处罚决定（种类/对象/金额/依据）：\n{str(upstream.get("n2",""))[:2500]}\n输出JSON，字段 penalties。'
    if role == 'entity_graph':
        return f'{SYS}\n识别涉事主体及关系：\n{str(upstream.get("n2",""))[:3000]}\n输出JSON，字段 entities。'
    if role == 'timeline_deep':
        t = str(upstream.get('n3',''))[:2000]; e = str(upstream.get('n6',''))[:1500]
        return f'{SYS}\n时间线阶段复核：\n时间线:{t}\n主体:{e}\n输出JSON，字段 stages。'
    if role == 'amounts_check':
        return f'{SYS}\n金额交叉核验：\n{str(upstream.get("n4",""))[:2500]}\n输出JSON，字段 amounts_checked。'
    if role == 'cross_check':
        p = str(upstream.get('n5',''))[:1500]; s = str(upstream.get('n7',''))[:1500]; a = str(upstream.get('n8',''))[:1000]
        return f'{SYS}\n跨来源核验：\n处罚:{p}\n阶段:{s}\n核验:{a}\n输出JSON，字段 verified_facts。'
    return f'{SYS}\n综合全部核验事实，输出完整调查报告（含全部日期、金额、主体、处罚）：\n{str(upstream.get("n9",""))[:3000]}\n输出JSON，字段 report。'

def downstream_closure(nid):
    result = set(); queue = [nid]
    while queue:
        cur = queue.pop(0); result.add(cur)
        for n, info in NODES.items():
            if cur in info['deps'] and n not in result:
                queue.append(n)
    return result

def strip_fences(txt):
    clean = txt.strip()
    if clean.startswith('```'):
        lines = clean.split('\n')[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        clean = '\n'.join(lines).strip()
    return clean

def evaluate_q_f1(report_text):
    nr = norm(report_text)
    tp, fn = 0, 0
    for fact in SILVER:
        nv = norm(fact['value'])
        if fact['kind'] == 'date':
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})', fact['value'])
            if m:
                alt = norm(f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日")
                if nv in nr or alt in nr: tp += 1
                else: fn += 1
        else:
            if nv in nr: tp += 1
            else: fn += 1
    report_claims = re.findall(r'[\u4e00-\u9fa5]{4,}(?:万元|亿元|元|日|公司|处罚)', report_text)
    evidence_norm = norm(' '.join(EV.values()))
    fp = min(sum(1 for c in report_claims if norm(c) not in evidence_norm and len(c) > 8), 50)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(0.001, precision + recall)
    return dict(tp=tp, fp=fp, fn=fn, precision=round(precision,4), recall=round(recall,4), f1=round(f1,4))

# ============================================================
# C_info computation (frozen)
# ============================================================
def compute_c_info(node_status, upstream_data):
    """Terminal required information completeness for n9's input slots."""
    total_w = sum(s['weight'] for s in N9_INFO_SLOTS.values())
    score = 0.0
    for slot_name, slot in N9_INFO_SLOTS.items():
        src = slot['source']
        status = node_status.get(src, 'PENDING')
        data = upstream_data.get(src, '')
        if status in ('SKIPPED', 'PENDING'):
            continue  # 0 credit
        elif status == 'DEGRADED':
            score += slot['weight'] * 0.5
        elif status == 'OK' and len(data.strip()) > 50:
            score += slot['weight'] * 1.0
        elif status == 'OK' and data.strip():
            score += slot['weight'] * 0.5
        else:  # OK but empty
            score += slot['weight'] * 0.25
    return score / total_w

def compute_c_norm(node_status):
    """Original C_norm: binary reachability of n9."""
    inputs = {'n9'}
    filled = sum(1 for d in inputs if node_status.get(d) in ('OK','DEGRADED'))
    return filled / len(inputs)

# ============================================================
# Joint action selection with selectable C function
# ============================================================
def joint_select_action(failed_nid, node_status, upstream, executed, remaining, tokens_used, time_used, use_c_info):
    best_score = -1; best = None
    fn = failed_nid
    dclosure = downstream_closure(fn)

    for z in ('Z_NONE','Z_FALLBACK','Z_MERGE'):
        if z == 'Z_MERGE' and fn == 'n10': continue
        if z == 'Z_MERGE':
            downstream = [n for n in TOPO if fn in NODES[n]['deps'] and n not in executed]
            if not downstream: continue
        for r in ('R_EMPTY','R_FAILED','R_DOWNSTREAM'):
            if r == 'R_EMPTY' and fn == 'n9': continue
            closure = {fn} if r == 'R_FAILED' else dclosure if r == 'R_DOWNSTREAM' else set()
            for pi in ('PI_KEEP','PI_SWAP_FAILED','PI_SWAP_REMAINING'):
                if pi == 'PI_SWAP_REMAINING' and len(executed) > 7: continue

                # C computation — THE ONLY DIFFERENCE between arms
                if use_c_info:
                    # Simulate: what happens to n9's info slots after this action?
                    sim_status = dict(node_status)
                    for cn in closure:
                        if cn not in executed:
                            sim_status[cn] = 'OK'  # will be re-executed
                    if z == 'Z_FALLBACK':
                        sim_status[fn] = 'DEGRADED'
                    c_val = compute_c_info(sim_status, upstream)
                else:
                    # Original C_norm: binary reachability
                    sim_status = dict(node_status)
                    for cn in closure:
                        if cn not in executed:
                            sim_status[cn] = 'OK'
                    if z == 'Z_FALLBACK':
                        sim_status[fn] = 'DEGRADED'
                    c_val = compute_c_norm(sim_status)

                nodes_to_execute = len(closure) + len(remaining - closure)
                est_cost = nodes_to_execute * 1200
                k_val = max(0.0, 1.0 - est_cost / MAX_TOKENS)
                est_ms = time_used + nodes_to_execute * 8
                l_val = max(0.0, 1.0 - est_ms / DEADLINE_S)

                if est_cost + tokens_used > MAX_TOKENS: continue
                if est_ms > DEADLINE_S: continue

                score = 0.5 * min(1.0, max(0.0, c_val)) + 0.3 * k_val + 0.2 * l_val
                if score > best_score:
                    best_score = score; best = (z, r, pi)
                elif score == best_score:
                    zo = {'Z_NONE':0,'Z_FALLBACK':1,'Z_MERGE':2}
                    ro = {'R_EMPTY':0,'R_FAILED':1,'R_DOWNSTREAM':2}
                    po = {'PI_KEEP':0,'PI_SWAP_FAILED':1,'PI_SWAP_REMAINING':2}
                    if best and (zo[z]+ro[r]+po[pi]) < (zo[best[0]]+ro[best[1]]+po[best[2]]):
                        best = (z, r, pi)
    return best if best else ('Z_NONE','R_FAILED','PI_KEEP')

# ============================================================
# Run single experiment
# ============================================================
def run_single(meter, run_id, arm, block):
    t0 = time.time()
    upstream = {}
    node_status = {}
    node_model = {n: MODELS['strong'] for n in TOPO}
    node_latencies = {}
    anomaly_fired = set()
    anomaly_events = []
    degraded_nodes = set()
    actions_taken = []
    tokens_used = 0
    executed = set()
    remaining = set(TOPO)
    use_c_info = (arm == 'JointCinfo')

    def call_node(nid, model_override=None):
        nonlocal tokens_used
        role = NODES[nid]['role']
        model = model_override or node_model[nid]
        ud = {d: upstream.get(d, '') for d in NODES[nid]['deps']}
        ud_effective = dict(ud)
        if nid in ANOMALIES and nid not in anomaly_fired:
            anomaly_fired.add(nid)
            if ANOMALIES[nid] == 'evidence_fail':
                ud_effective = {d: '' for d in ud}

        prompt = build_prompt(nid, role, ud_effective, EV)
        rec, txt = meter.call(model, SYS, prompt, 768, f'{run_id}:{nid}', 30)
        tokens_used += rec['usage'].get('input_tokens',0) + rec['usage'].get('output_tokens',0)

        if nid in ANOMALIES and ANOMALIES.get(nid) == 'transport' and \
           not any(e['node']==nid and e['type']=='injection_transport' for e in anomaly_events):
            txt = txt[:10]
            anomaly_events.append(dict(node=nid, type='injection_transport', truncated_len=10))

        clean = strip_fences(txt)
        response_usable = False
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict) and len(parsed) > 0:
                ek = EXPECTED_OUTPUT_KEYS.get(role, [])
                response_usable = any(k in parsed for k in ek) if ek else True
        except: pass
        empty_inputs = [d for d in NODES[nid]['deps'] if not ud_effective.get(d, '').strip()]
        input_contract_ok = len(empty_inputs) == 0
        anomaly_detected = (not response_usable) or (not input_contract_ok)

        if anomaly_detected:
            anomaly_events.append(dict(node=nid, type='anomaly_detected',
                                       response_usable=response_usable, input_contract_ok=input_contract_ok))
        return txt, rec, anomaly_detected

    def execute(nid):
        nonlocal upstream, node_status, executed, remaining, degraded_nodes

        if arm == 'pi_only':
            txt, rec, anomaly_detected = call_node(nid)
            node_latencies[nid] = rec['latency_s']
            if anomaly_detected:
                node_model[nid] = MODELS['weak']
                txt2, rec2, _ = call_node(nid)
                node_latencies[nid] += rec2['latency_s']
                if txt2 and len(txt2) >= 30:
                    upstream[nid] = txt2; node_status[nid] = 'OK'
                else:
                    node_status[nid] = 'SKIPPED'; upstream[nid] = ''
                for rn in remaining:
                    if rn not in executed: node_model[rn] = MODELS['weak']
                executed.add(nid); remaining.discard(nid); return
            upstream[nid] = txt; node_status[nid] = 'OK'
            executed.add(nid); remaining.discard(nid); return

        # Joint arms (JointCnorm and JointCinfo share this logic)
        txt, rec, anomaly_detected = call_node(nid)
        node_latencies[nid] = rec['latency_s']
        if anomaly_detected:
            elapsed = time.time() - t0
            z, r, pi = joint_select_action(nid, node_status, upstream, executed, remaining, tokens_used, elapsed, use_c_info)
            actions_taken.append(dict(node=nid, action=f'{z}|{r}|{pi}'))

            if z == 'Z_FALLBACK':
                raw = ' '.join(str(upstream.get(d, ''))[:500] for d in NODES[nid]['deps'])
                upstream[nid] = raw; node_status[nid] = 'DEGRADED'
                degraded_nodes.add(nid); executed.add(nid); remaining.discard(nid)
            elif z == 'Z_MERGE':
                ds = [n for n in TOPO if nid in NODES[n]['deps'] and n not in executed]
                if ds:
                    target = ds[0]
                    NODES[target] = dict(role=NODES[target]['role'], deps=NODES[target]['deps']+[nid])
                node_status[nid] = 'SKIPPED'; upstream[nid] = ''
                executed.add(nid); remaining.discard(nid)

            if r == 'R_FAILED':
                if z == 'Z_NONE':
                    node_model[nid] = MODELS['weak'] if pi in ('PI_SWAP_FAILED','PI_SWAP_REMAINING') else node_model[nid]
                    txt2, rec2, _ = call_node(nid)
                    node_latencies[nid] += rec2['latency_s']
                    if txt2 and len(txt2) >= 30:
                        upstream[nid] = txt2; node_status[nid] = 'OK'
                    else:
                        node_status[nid] = 'SKIPPED'; upstream[nid] = ''
                    executed.add(nid); remaining.discard(nid)
            elif r == 'R_DOWNSTREAM':
                closure = downstream_closure(nid)
                for cn in sorted(closure):
                    if cn == nid and z == 'Z_NONE':
                        node_model[nid] = MODELS['weak'] if pi in ('PI_SWAP_FAILED','PI_SWAP_REMAINING') else node_model[nid]
                        txt2, rec2, _ = call_node(cn)
                        node_latencies[cn] = node_latencies.get(cn,0) + rec2['latency_s']
                        if txt2 and len(txt2) >= 30:
                            upstream[cn] = txt2; node_status[cn] = 'OK'
                        else:
                            node_status[cn] = 'SKIPPED'; upstream[cn] = ''
                        executed.add(cn); remaining.discard(cn)
                    elif cn not in executed and cn in remaining:
                        txt3, rec3, _ = call_node(cn)
                        node_latencies[cn] = rec3['latency_s']
                        if txt3 and len(txt3) >= 30:
                            upstream[cn] = txt3; node_status[cn] = 'OK'
                        else:
                            node_status[cn] = 'SKIPPED'; upstream[cn] = ''
                        executed.add(cn); remaining.discard(cn)

            if pi == 'PI_SWAP_REMAINING':
                for rn in remaining: node_model[rn] = MODELS['weak']

            # Always set status (prevents PENDING cascade)
            if node_status.get(nid) not in ('OK','DEGRADED','SKIPPED'):
                if txt and len(txt.strip()) > 10:
                    upstream[nid] = txt; node_status[nid] = 'OK'
                else:
                    upstream[nid] = ''; node_status[nid] = 'SKIPPED'
                executed.add(nid); remaining.discard(nid)
            return
        else:
            upstream[nid] = txt; node_status[nid] = 'OK'
            executed.add(nid); remaining.discard(nid)

    for nid in TOPO:
        if node_status.get(nid) in ('OK','DEGRADED','SKIPPED'): continue
        deps_ok = all(node_status.get(d) in ('OK','DEGRADED','SKIPPED') for d in NODES[nid]['deps'])
        if not deps_ok:
            node_status[nid] = 'SKIPPED'; upstream[nid] = ''
            executed.add(nid); remaining.discard(nid); continue
        execute(nid)

    makespan = time.time() - t0
    report = upstream.get('n10', '')
    q = evaluate_q_f1(report)
    return dict(
        run_id=run_id, arm=arm, block=block,
        status='COMPLETE' if node_status.get('n10') in ('OK','DEGRADED') else 'INCOMPLETE',
        q_f1=q['f1'], q_precision=q['precision'], q_recall=q['recall'],
        tp=q['tp'], fp=q['fp'], fn=q['fn'],
        cost_tokens=tokens_used, makespan_s=round(makespan,1),
        on_time=makespan <= DEADLINE_S,
        degraded_nodes=list(degraded_nodes), actions_taken=actions_taken,
        anomaly_events=anomaly_events,
        node_status={n: node_status.get(n,'PENDING') for n in TOPO},
        node_models={n: node_model.get(n,'?') for n in TOPO},
    )

def main():
    meter = Meter(ledger_path=OUT/'LEDGER.jsonl', max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    results = []
    for block, arm in BLOCK_ORDER:
        rid = f'CI-{arm}-B{block}'
        try:
            r = run_single(meter, rid, arm, block)
            results.append(r)
            print(f"  {arm:12s} B{block}: Q_F1={r['q_f1']:.3f} cost={r['cost_tokens']} "
                  f"ms={r['makespan_s']}s {'ON_TIME' if r['on_time'] else 'LATE'} {r['status']}")
        except BudgetExceeded:
            print(f"  BUDGET STOP at {rid}"); break
        except Exception as e:
            results.append(dict(run_id=rid, arm=arm, block=block, status=f'ERROR:{e}'))
            print(f"  ERROR {rid}: {e}")

    json.dump(results, open(OUT/'RESULTS.json','w'), ensure_ascii=False, indent=1)
    print(f"\nDone: {len(results)} runs")
    if results:
        print(f"\n{'='*70}")
        print(f"{'Arm':<14} {'Q_F1(mean)':<12} {'Cost(mean)':<12} {'Makespan(mean)':<15} {'OnTime'}")
        for arm in ('JointCnorm','JointCinfo','pi_only'):
            rs = [r for r in results if r.get('arm')==arm and 'q_f1' in r]
            if rs:
                mq = sum(r['q_f1'] for r in rs)/len(rs)
                mc = sum(r.get('cost_tokens',0) for r in rs)/len(rs)
                mm = sum(r.get('makespan_s',0) for r in rs)/len(rs)
                ot = sum(1 for r in rs if r.get('on_time'))/len(rs)
                print(f"{arm:<14} {mq:<12.4f} {mc:<12.0f} {mm:<15.1f} {ot:.0%}")
        print(f"{'='*70}")

if __name__ == '__main__':
    main()
