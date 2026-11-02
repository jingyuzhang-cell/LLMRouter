"""DD-V5.1 Joint experiment: 4 arms × 5 blocks, zeda penalty DAG, dual anomaly.

Pre-registered v1.2. Zero model calls during design; execution authorized by operator.
"""
import json, re, sys, time, hashlib, random
from pathlib import Path
from decimal import Decimal

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, '/root/capital_opinion_pilot')

from pilot_common import Meter, BudgetExceeded

# Auth gate
from importlib.util import spec_from_file_location, module_from_spec
spec = spec_from_file_location('ag', '/root/r3_own_pool/deadline_reward_v1/auth_gate.py')
ag = module_from_spec(spec); sys.modules['ag'] = ag; spec.loader.exec_module(ag)
ag.require('dd_v51_joint_v2')

OUT = B / 'dd_v51_results'
OUT.mkdir(exist_ok=True)

# ============================================================
# Frozen experiment parameters
# ============================================================
MODELS = {'strong': 'glm53', 'weak': 'glm53flash'}
DEADLINE_S = 120
MAX_CALLS = 200
MAX_TOKENS = 500_000
SILVER = json.load(open(B / 'dd_v51_silver_facts.json'))
BLOCK_ORDER = [  # seed-42 randomized, frozen
    (1,'pi_only'),(1,'R_only'),(1,'Joint'),(1,'Static'),
    (2,'Joint'),(2,'pi_only'),(2,'Static'),(2,'R_only'),
    (3,'Static'),(3,'Joint'),(3,'R_only'),(3,'pi_only'),
    (4,'R_only'),(4,'Static'),(4,'pi_only'),(4,'Joint'),
    (5,'pi_only'),(5,'Static'),(5,'Joint'),(5,'R_only'),
]

# DAG structure — AUTHORITATIVE: D_R1 frozen spec (aligned 2026-11-01)
# n1: extraction (root)
# n2: extraction (root, independent of n1 per D_R1)
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

# Expected output JSON keys per role (for generic detector)
EXPECTED_OUTPUT_KEYS = {
    'extraction': ['facts'],
    'timeline': ['timeline'],
    'amounts': ['amounts'],
    'penalties': ['penalties'],
    'entity_graph': ['entities'],
    'timeline_deep': ['stages'],
    'amounts_check': ['amounts_checked'],
    'cross_check': ['verified_facts'],
    'synthesis': ['report'],
}

# Evidence docs
zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV = {d['doc_id']: d['text'][:4000] for d in zeda['docs']}

def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))

# ============================================================
# Prompt builders
# ============================================================
SYS = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'

def build_prompt(nid, role, upstream, docs, degraded=None):
    if role == 'extraction':
        ds = '\n\n'.join(f'## 文档 {k}\n{v}' for k, v in docs.items())
        return f'{SYS}\n从下列处罚决定书文档中抽取关键事实（日期/金额/主体/违规行为/处罚）：\n{ds}\n输出JSON，字段 facts，数组，每条含 date/amount/entity/violation/penalty 字段。'
    if role == 'timeline':
        ud = str(upstream.get('n2', ''))[:3000]
        return f'{SYS}\n根据以下抽取事实整理时间线（按日期排序）：\n{ud}\n输出JSON，字段 timeline，数组，每条含 date/event。'
    if role == 'amounts':
        ud = str(upstream.get('n2', ''))[:3000]
        return f'{SYS}\n汇总所有金额数据（虚增金额、罚款金额、募集资金等）：\n{ud}\n输出JSON，字段 amounts，数组，每条含 item/value。'
    if role == 'penalties':
        ud = str(upstream.get('n2', ''))[:2500]
        return f'{SYS}\n梳理处罚决定（处罚种类、对象、金额、依据）：\n{ud}\n输出JSON，字段 penalties，数组，每条含 type/target/amount/basis。'
    if role == 'entity_graph':
        ud = str(upstream.get('n2', ''))[:3000]
        return f'{SYS}\n识别涉事主体及关系（公司、责任人、中介机构）：\n{ud}\n输出JSON，字段 entities，数组，每条含 name/role/relation。'
    if role == 'timeline_deep':
        t = str(upstream.get('n3', ''))[:2000]; e = str(upstream.get('n6', ''))[:1500]
        return f'{SYS}\n时间线阶段复核与划分：\n时间线:{t}\n主体:{e}\n输出JSON，字段 stages。'
    if role == 'amounts_check':
        ud = str(upstream.get('n4', ''))[:2500]
        return f'{SYS}\n金额交叉核验（比对各来源金额数据）：\n{ud}\n输出JSON，字段 amounts_checked。'
    if role == 'cross_check':
        p = str(upstream.get('n5',''))[:1500]; s = str(upstream.get('n7',''))[:1500]; a = str(upstream.get('n8',''))[:1000]
        return f'{SYS}\n跨来源核验（核对处罚、时间线、金额的一致性）：\n处罚:{p}\n阶段:{s}\n核验:{a}\n输出JSON，字段 verified_facts。'
    return f'{SYS}\n综合分析全部核验事实，输出完整调查报告（含全部日期、金额、主体、处罚、违规事实）：\n{str(upstream.get("n9",""))[:3000]}\n输出JSON，字段 report。'

# ============================================================
# Anomaly injection
# ============================================================
def inject_anomaly(nid, kind, response_text):
    if nid == 'n3' and kind == 'transport':
        return response_text[:20] if response_text else ''  # truncate to garbage
    if nid == 'n5' and kind == 'evidence_fail':
        return ''  # empty upstream
    return response_text

# ============================================================
# Joint action selection (frozen formula, pre-execution info only)
# ============================================================
def downstream_closure(nid):
    """All nodes that transitively depend on nid."""
    result = set(); queue = [nid]
    while queue:
        cur = queue.pop(0)
        result.add(cur)
        for n, info in NODES.items():
            if cur in info['deps'] and n not in result:
                queue.append(n)
    return result

def terminal_input_contracts():
    """n10's required input ports."""
    return {'n9'}  # n10 depends on n9

def joint_select_action(failed_nodes, executed, remaining, tokens_used, time_used, current_dag):
    """Enumerate Z×R×π, apply semantic guard, score with normalized formula, select best."""
    best_score = -1; best = None
    fn = failed_nodes[0] if failed_nodes else None
    if fn is None: return ('Z_NONE','R_EMPTY','PI_KEEP')

    dclosure = downstream_closure(fn)
    n10_inputs = terminal_input_contracts()

    for z in ('Z_NONE','Z_FALLBACK','Z_MERGE'):
        # Semantic guard for Z
        if z == 'Z_MERGE' and fn == 'n10': continue
        if z == 'Z_MERGE':
            downstream = [n for n, info in current_dag.items() if fn in info['deps']]
            if not downstream: continue
        for r in ('R_EMPTY','R_FAILED','R_DOWNSTREAM'):
            # Semantic guard for R
            if r == 'R_EMPTY' and fn in n10_inputs: continue
            closure = {fn} if r == 'R_FAILED' else dclosure if r == 'R_DOWNSTREAM' else set()
            for pi in ('PI_KEEP','PI_SWAP_FAILED','PI_SWAP_REMAINING'):
                # Semantic guard for π
                if pi == 'PI_SWAP_REMAINING' and len(executed) > 7: continue

                # C_norm: terminal input contract satisfaction
                # After action, which of n10's inputs can be effectively filled?
                c_norm = 0.0
                for inp in n10_inputs:
                    if inp in executed and inp not in closure:
                        c_norm += 1.0  # already done, not re-executed
                    elif inp in closure and z != 'Z_FALLBACK':
                        c_norm += 1.0  # will be re-executed with model
                    elif inp in closure and z == 'Z_FALLBACK':
                        c_norm += 0.5  # degraded fill (half credit)
                    elif inp in remaining:
                        c_norm += 1.0  # will be executed
                c_norm = min(1.0, c_norm / max(1, len(n10_inputs)))

                # K_norm: cost utility
                nodes_to_execute = len(closure) + len(remaining - closure)
                est_cost = nodes_to_execute * 1200  # frozen estimate: 1200 tok/node
                k_norm = max(0.0, 1.0 - est_cost / MAX_TOKENS)

                # L_norm: latency utility
                est_makespan = time_used + nodes_to_execute * 8  # frozen: 8s/node
                l_norm = max(0.0, 1.0 - est_makespan / DEADLINE_S)

                # Budget/deadline exclusion
                if est_cost + tokens_used > MAX_TOKENS: continue
                if est_makespan > DEADLINE_S: continue

                score = 0.5 * c_norm + 0.3 * k_norm + 0.2 * l_norm
                if score > best_score:
                    best_score = score
                    best = (z, r, pi)
                elif score == best_score:
                    # Tie-breaker: prefer minimal action
                    order = {'Z_NONE':0,'Z_FALLBACK':1,'Z_MERGE':2}
                    ro = {'R_EMPTY':0,'R_FAILED':1,'R_DOWNSTREAM':2}
                    po = {'PI_KEEP':0,'PI_SWAP_FAILED':1,'PI_SWAP_REMAINING':2}
                    if best and (order[z]+ro[r]+po[pi]) < (order[best[0]]+ro[best[1]]+po[best[2]]):
                        best = (z, r, pi)

    return best if best else ('Z_NONE','R_FAILED','PI_KEEP')

# ============================================================
# Q_F1 evaluation (frozen criteria)
# ============================================================
def evaluate_q_f1(report_text, degraded_nodes):
    """Deterministic evaluation against frozen Silver facts."""
    nr = norm(report_text)
    tp, fn = 0, 0
    for fact in SILVER:
        nv = norm(fact['value'])
        if fact['kind'] == 'date':
            m = re.match(r'(\d{4})-(\d{2})-(\d{2})', fact['value'])
            if m:
                alt = norm(f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日")
                if nv in nr or alt in nr:
                    tp += 1
                else:
                    fn += 1
        else:
            if nv in nr:
                tp += 1
            else:
                fn += 1
    # FP: sentences in report containing specific claims not in evidence
    report_claims = re.findall(r'[\u4e00-\u9fa5]{4,}(?:万元|亿元|元|日|公司|处罚)', report_text)
    evidence_norm = norm(' '.join(EV.values()))
    fp = sum(1 for c in report_claims if norm(c) not in evidence_norm and len(c) > 8)
    # Cap FP to avoid extreme outliers from long reports
    fp = min(fp, 50)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(0.001, precision + recall)
    return dict(tp=tp, fp=fp, fn=fn, precision=round(precision,4), recall=round(recall,4), f1=round(f1,4))

# ============================================================
# Run single experiment
# ============================================================
def run_single(meter, run_id, arm, block):
    t0 = time.time()
    upstream = {}          # nid -> response text
    node_status = {}       # nid -> 'OK'|'FAILED'|'DEGRADED'|'SKIPPED'
    node_model = {n: MODELS['strong'] for n in TOPO}  # all start with strong
    node_latencies = {}
    dag = {n: dict(role=info["role"], deps=list(info["deps"])) for n, info in NODES.items()}  # working DAG
    anomaly_fired = set()
    anomaly_events = []  # structured log of actual injection events
    degraded_nodes = set()
    actions_taken = []
    tokens_used = 0
    executed = set()
    remaining = set(TOPO)

    def call_node(nid, model_override=None):
        nonlocal tokens_used
        role = NODES[nid]['role']
        model = model_override or node_model[nid]
        # Build upstream dict for this node
        ud = {d: upstream.get(d, '') for d in NODES[nid]['deps']}
        # === INJECTOR (only creates the anomaly; does NOT signal controller) ===
        ud_effective = dict(ud)
        if nid in ANOMALIES and nid not in anomaly_fired:
            anomaly_fired.add(nid)
            if ANOMALIES[nid] == 'transport':
                pass  # truncation will be applied to response below
            elif ANOMALIES[nid] == 'evidence_fail':
                ud_effective = {d: '' for d in ud}  # empty upstream BEFORE model call

        degraded_input = any(node_status.get(d) == 'DEGRADED' for d in NODES[nid]['deps'])
        prompt = build_prompt(nid, role, ud_effective, EV, degraded=degraded_input)
        rec, txt = meter.call(model, SYS if role != 'synthesis' else '', prompt,
                              max_tokens=768, purpose=f'{run_id}:{nid}', timeout_s=30)
        tokens_used += rec['usage'].get('input_tokens',0) + rec['usage'].get('output_tokens',0)

        # === INJECTOR: apply transport truncation to response ===
        if nid in ANOMALIES and ANOMALIES.get(nid) == 'transport' and len(anomaly_events) == 0 or \
           (nid in ANOMALIES and ANOMALIES.get(nid) == 'transport' and
            not any(e['node'] == nid and e['type'] == 'injection_transport' for e in anomaly_events)):
            txt = txt[:10]
            anomaly_events.append(dict(node=nid, type='injection_transport',
                                       original_len=len(txt) + 10, truncated_len=10,
                                       parser_received=txt))

        # === GENERIC DETECTOR (independent of injector; examines actual execution state) ===
        # Strip markdown code fences before JSON parsing (model outputs wrapped in ```json ... ```)
        clean = txt.strip()
        if clean.startswith('```'):
            fence_lines = clean.split('\n')
            fence_lines = fence_lines[1:]  # remove ```json or ```
            if fence_lines and fence_lines[-1].strip() == '```':
                fence_lines = fence_lines[:-1]  # remove closing ```
            clean = '\n'.join(fence_lines).strip()
        # Signal 1: response unusable — JSON parse + expected key check (not just length)
        response_usable = False
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict) and len(parsed) > 0:
                # Check at least one expected output key for this role exists
                expected_keys = EXPECTED_OUTPUT_KEYS.get(role, [])
                response_usable = any(k in parsed for k in expected_keys) if expected_keys else True
        except (json.JSONDecodeError, ValueError):
            response_usable = False
        # Signal 2: upstream input contract violation (model received empty required input)
        empty_inputs = [d for d in NODES[nid]['deps'] if not ud_effective.get(d, '').strip()]
        input_contract_ok = len(empty_inputs) == 0

        anomaly_detected = (not response_usable) or (not input_contract_ok)

        if anomaly_detected:
            anomaly_events.append(dict(
                node=nid, type='anomaly_detected',
                detection_method='generic_detector',
                response_usable=response_usable,
                input_contract_ok=input_contract_ok,
                empty_inputs=empty_inputs,
                response_preview=txt[:50]))

        return txt, rec, anomaly_detected

    def execute_with_arm_logic(nid):
        """Execute node, handle anomaly according to arm's action set."""
        role = NODES[nid]['role']
        ud = {d: upstream.get(d, '') for d in NODES[nid]['deps']}

        # Anomaly check (FIXED: use returned anomaly flag + input-contract, not output length)
        is_anomaly = nid in ANOMALIES

        if arm == 'Static':
            txt, rec, anomaly_detected = call_node(nid)
            node_latencies[nid] = rec['latency_s']
            if anomaly_detected:
                # Retry once with same model
                txt2, rec2, _ = call_node(nid)
                node_latencies[nid] += rec2['latency_s']
                if not txt2 or len(txt2) < 30:
                    node_status[nid] = 'SKIPPED'
                    upstream[nid] = ''
                    return
            upstream[nid] = txt
            node_status[nid] = 'OK'
            executed.add(nid); remaining.discard(nid)

        elif arm == 'R_only':
            txt, rec, anomaly_detected = call_node(nid)
            node_latencies[nid] = rec['latency_s']
            if anomaly_detected:
                # Recovery closure: failed node + all downstream
                closure = downstream_closure(nid)
                for cn in sorted(closure):
                    if cn == nid:
                        txt2, rec2, _ = call_node(cn)
                        node_latencies[cn] = node_latencies.get(cn,0) + rec2['latency_s']
                        if txt2 and len(txt2) >= 30:
                            upstream[cn] = txt2; node_status[cn] = 'OK'
                            executed.add(cn); remaining.discard(cn)
                        else:
                            node_status[cn] = 'SKIPPED'; upstream[cn] = ''
                    elif cn not in executed:
                        txt3, rec3, _ = call_node(cn)
                        node_latencies[cn] = rec3['latency_s']
                        upstream[cn] = txt3; node_status[cn] = 'OK'
                        executed.add(cn); remaining.discard(cn)
                return
            upstream[nid] = txt; node_status[nid] = 'OK'
            executed.add(nid); remaining.discard(nid)

        elif arm == 'pi_only':
            txt, rec, anomaly_detected = call_node(nid)
            node_latencies[nid] = rec['latency_s']
            if anomaly_detected:
                # Switch model and retry
                new_model = MODELS['weak'] if node_model[nid] == MODELS['strong'] else MODELS['strong']
                node_model[nid] = new_model
                txt2, rec2, _ = call_node(nid)
                node_latencies[nid] += rec2['latency_s']
                if txt2 and len(txt2) >= 30:
                    upstream[nid] = txt2; node_status[nid] = 'OK'
                else:
                    node_status[nid] = 'SKIPPED'; upstream[nid] = ''
                # Reassign remaining nodes
                for rn in remaining:
                    if rn not in executed and rn not in NODES[nid]['deps']:
                        node_model[rn] = MODELS['weak']
                executed.add(nid); remaining.discard(nid)
                return
            upstream[nid] = txt; node_status[nid] = 'OK'
            executed.add(nid); remaining.discard(nid)

        elif arm == 'Joint':
            txt, rec, anomaly_detected = call_node(nid)
            node_latencies[nid] = rec['latency_s']
            if anomaly_detected:
                # Joint: enumerate Z×R×π, select best
                elapsed = time.time() - t0
                action = joint_select_action([nid], executed, remaining, tokens_used, elapsed, dag)
                z, r, pi = action
                actions_taken.append(dict(node=nid, anomaly=ANOMALIES.get(nid), action=f'{z}|{r}|{pi}'))

                # Apply Z
                if z == 'Z_FALLBACK':
                    # Use upstream raw data directly
                    raw = ' '.join(str(upstream.get(d, ''))[:500] for d in NODES[nid]['deps'])
                    upstream[nid] = raw
                    node_status[nid] = 'DEGRADED'
                    degraded_nodes.add(nid)
                    executed.add(nid); remaining.discard(nid)
                elif z == 'Z_MERGE':
                    # Merge into downstream
                    downstream = [n for n in TOPO if nid in NODES[n].get('deps', []) and n not in executed]
                    if downstream:
                        target = downstream[0]
                        # Append failed node's task to target's prompt
                        merged_role = NODES[target]['role']
                        merged_deps = NODES[target]['deps'] + [nid]
                        NODES[target] = dict(role=merged_role, deps=merged_deps)
                        node_status[nid] = 'SKIPPED'
                        upstream[nid] = ''
                    executed.add(nid); remaining.discard(nid)

                # Apply R (recovery closure)
                if r == 'R_FAILED':
                    if z == 'Z_NONE':
                        # Just retry failed node
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
                            txt2, rec2, _ = call_node(cn)
                            node_latencies[cn] = node_latencies.get(cn,0) + rec2['latency_s']
                            if txt2 and len(txt2) >= 30:
                                upstream[cn] = txt2; node_status[cn] = 'OK'
                            else:
                                node_status[cn] = 'SKIPPED'; upstream[cn] = ''
                            executed.add(cn); remaining.discard(cn)
                        elif cn not in executed:
                            if cn in remaining:
                                txt3, rec3, _ = call_node(cn)
                                node_latencies[cn] = rec3['latency_s']
                                if txt3 and len(txt3) >= 30:
                                    upstream[cn] = txt3; node_status[cn] = 'OK'
                                else:
                                    node_status[cn] = 'SKIPPED'; upstream[cn] = ''
                                executed.add(cn); remaining.discard(cn)

                # Apply π
                if pi == 'PI_SWAP_FAILED':
                    new_model = MODELS['weak'] if node_model.get(nid, MODELS['strong']) == MODELS['strong'] else MODELS['strong']
                    node_model[nid] = new_model
                elif pi == 'PI_SWAP_REMAINING':
                    for rn in remaining:
                        node_model[rn] = MODELS['weak']

                # CRITICAL FIX: always set node status after action (prevents PENDING cascade)
                if node_status.get(nid) not in ('OK', 'DEGRADED', 'SKIPPED'):
                    if txt and len(txt.strip()) > 10:
                        upstream[nid] = txt
                        node_status[nid] = 'OK'
                    else:
                        upstream[nid] = ''
                        node_status[nid] = 'SKIPPED'
                    executed.add(nid); remaining.discard(nid)

                return
            else:
                upstream[nid] = txt; node_status[nid] = 'OK'
                executed.add(nid); remaining.discard(nid)

    # Execute DAG in topological order
    for nid in TOPO:
        if node_status.get(nid) in ('OK', 'DEGRADED', 'SKIPPED'):
            continue
        # Check deps
        deps_ok = all(node_status.get(d) in ('OK', 'DEGRADED', 'SKIPPED') for d in NODES[nid]['deps'])
        if not deps_ok:
            node_status[nid] = 'SKIPPED'
            upstream[nid] = ''
            continue
        execute_with_arm_logic(nid)

    makespan = time.time() - t0
    report = upstream.get('n10', '')
    q = evaluate_q_f1(report, degraded_nodes)
    on_time = makespan <= DEADLINE_S

    return dict(
        run_id=run_id, arm=arm, block=block,
        status='COMPLETE' if node_status.get('n10') in ('OK','DEGRADED') else 'INCOMPLETE',
        q_f1=q['f1'], q_precision=q['precision'], q_recall=q['recall'],
        tp=q['tp'], fp=q['fp'], fn=q['fn'],
        cost_tokens=tokens_used, makespan_s=round(makespan,1), on_time=on_time,
        degraded_nodes=list(degraded_nodes), actions_taken=actions_taken,
        anomaly_events=anomaly_events,
        node_status={n: node_status.get(n, 'PENDING') for n in TOPO},
        node_models={n: node_model.get(n, '?') for n in TOPO},
    )

# ============================================================
# Main
# ============================================================
def main():
    meter = Meter(ledger_path=OUT/'LEDGER.jsonl', max_calls=MAX_CALLS, max_guaranteed_actual=MAX_TOKENS)
    results = []
    for block, arm in BLOCK_ORDER:
        rid = f'V51-{arm}-B{block}'
        try:
            r = run_single(meter, rid, arm, block)
            results.append(r)
            print(f"  {arm:10s} B{block}: Q_F1={r['q_f1']:.3f} cost={r['cost_tokens']} "
                  f"ms={r['makespan_s']}s {'ON_TIME' if r['on_time'] else 'LATE'} {r['status']}")
        except BudgetExceeded:
            print(f"  BUDGET STOP at {rid}")
            break
        except Exception as e:
            results.append(dict(run_id=rid, arm=arm, block=block, status=f'ERROR:{e}'))
            print(f"  ERROR {rid}: {e}")

    json.dump(results, open(OUT/'RESULTS.json','w'), ensure_ascii=False, indent=1)
    print(f"\nDone: {len(results)} runs")

    # Summary table
    if results:
        print(f"\n{'='*70}")
        print(f"{'Arm':<12} {'Q_F1(mean)':<12} {'Cost(mean)':<12} {'Makespan(mean)':<15} {'OnTime':<8}")
        for arm in ('Static','R_only','pi_only','Joint'):
            rs = [r for r in results if r.get('arm')==arm and 'q_f1' in r]
            if rs:
                mq = sum(r['q_f1'] for r in rs)/len(rs)
                mc = sum(r.get('cost_tokens',0) for r in rs)/len(rs)
                mm = sum(r.get('makespan_s',0) for r in rs)/len(rs)
                ot = sum(1 for r in rs if r.get('on_time'))/len(rs)
                print(f"{arm:<12} {mq:<12.4f} {mc:<12.0f} {mm:<15.1f} {ot:.0%}")
        print(f"{'='*70}")

if __name__ == '__main__':
    main()
