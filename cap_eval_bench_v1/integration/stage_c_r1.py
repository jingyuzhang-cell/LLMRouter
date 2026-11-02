"""Stage-C-R1 production executor (zero-call testable; real path FAIL-CLOSED).

ONE executor drives all six arms. The only seam is the model adapter:
  --adapter deterministic (default)  frozen deterministic stand-in, zero API
  --adapter meter --authorize        pilot Meter, requires the seven-field
                                     auth record 'stage_c_r1_v1' (HOLD)

Everything else is shared and frozen per task: DAG (from
stage_c_evidence/tasks.json), evidence texts, silver scorer (verbatim
stage_c_v2.score), anomaly injection points, K_m slots, budget.

Mechanics implemented here that the invalid v2 runner lacked:
  * per-DAG parent prompt assembly (multi-parent inputs by node id)
  * K_m resource-constrained parallel kernel with virtual clock (queuing,
    makespan, deadline)
  * healthy cache (done nodes outside a recovery set are never re-billed)
  * version propagation (children read the parent version in their inputs)
  * transport/evidence anomalies feed BACK into the arm's next decision
    (bounded continuous feedback, not a hard break)
"""
import argparse
import json
import re
import sys
import time
import heapq
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
for p in (P, B, B / 'integration'):
    sys.path.insert(0, str(p))

from six_arm_scheduler import (
    ARMS, ARM_META, ARM_DECIDERS, DAGState, NodeState, TOKENS_PRIOR,
    LATENCY_PRIOR)

SC = B / 'stage_c_evidence'
OUT = B / 'stage_c_r1_runs'

PORT_KEYS = {'index': 'evidence_index', 'extracts': 'doc_extracts',
             'timeline': 'timeline', 'entity_facts': 'entity_facts',
             'factcheck_full': 'verified_facts', 'report': 'report',
             'reasoning': 'reasoned_facts', 'verification': 'verified_facts'}
SYS = ('你是调查DAG节点。严格执行subtask。只使用给定证据。'
       '无法确认标注UNRESOLVED。输出极其简洁的JSON——每字段值不超过50字，'
       '不要生成详细分析、重复内容或长篇解释。')
K_M = {'glm53': 2, 'glm53flash': 2}     # frozen parallelism ceiling per model
# π₀ frozen initial allocation, Stage-B static-opt direction: evidence-
# critical kinds on the strong model, mid-pipeline kinds on flash. Applied
# IDENTICALLY to all six arms (paired fairness); post-anomaly divergence
# comes only from each arm's decisions.
INITIAL_PI = {'index': 'glm53', 'extracts': 'glm53', 'timeline': 'glm53flash',
              'entity_facts': 'glm53flash', 'factcheck_full': 'glm53',
              'report': 'glm53', 'reasoning': 'glm53flash',
              'verification': 'glm53'}
MAX_RECOVERY_ROUNDS = 3
PER_PARENT_CAP = 2000                    # chars per parent in prompts (v2: 2000)
DOC_CAP = 500                            # chars per doc (v2: 500)


# ---------------------------------------------------------------------------
# frozen scorer — verbatim copy of the stage_c_v2.py score function (audit: silver fact coverage)
# ---------------------------------------------------------------------------
def score(text, silver):
    def norm(s): return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))
    nt = norm(text); covered = []
    for f in silver:
        a, typ = f['answer'], f.get('answer_type', 'text')
        na = norm(a)
        hit = na in nt
        if not hit and typ == 'date':
            dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', a)
            if dm:
                hit = norm(f'{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日') in nt
        if hit: covered.append(f['fact_id'])
    return round(len(covered) / max(1, len(silver)), 4), covered


# ---------------------------------------------------------------------------
# evidence / task loading
# ---------------------------------------------------------------------------
def load_tasks():
    tasks = json.load(open(SC / 'tasks.json'))
    deadlines = {}
    fz = B / 'tasks' / 'tasks_frozen.jsonl'
    if fz.exists():
        for l in open(fz):
            if l.strip():
                r = json.loads(l)
                deadlines[r['task_id']] = r.get('deadline_s', 1800)
    out = {}
    for t in tasks:
        texts = {}
        for did in t['doc_ids']:
            p = SC / 'text' / f'{did}.txt'
            if p.exists():
                texts[did] = p.read_text()
        silver = json.load(open(SC / f"{t['event']}_silver.json"))['facts']
        out[t['task_id']] = dict(task=t, texts=texts, silver=silver,
                                 deadline=deadlines.get(t['task_id'], 1800))
    return out


def build_state(data, budget_tokens=60000, deadline_s=None):
    dag = data['task']['dag']
    nodes = {n['id']: NodeState(n['id'], n['kind'], n.get('subtask', ''),
                                model=INITIAL_PI.get(n['kind'], 'glm53'))
             for n in dag['nodes']}
    deps = {n['id']: list(n.get('deps', [])) for n in dag['nodes']}
    return DAGState(nodes=nodes, deps=deps,
                    kinds={n['id']: n['kind'] for n in dag['nodes']},
                    subtasks={n['id']: n.get('subtask', '') for n in dag['nodes']},
                    deadline_s=deadline_s or data['deadline'],
                    budget_remaining=budget_tokens)


def build_prompt(state: DAGState, nid: str, data) -> str:
    kind, sub = state.kinds[nid], state.subtasks[nid]
    pk = PORT_KEYS.get(kind, kind)
    prompt = (f'subtask: {sub}\n输出JSON对象，只有一个顶层键 "{pk}"，'
              f'值为数组或对象。\n')
    for p in state.parents(nid):
        node = state.nodes[p]
        val = json.dumps(node.output, ensure_ascii=False)[:PER_PARENT_CAP]
        prompt += f'{PORT_KEYS.get(state.kinds[p], state.kinds[p])}@v{node.version}: {val}\n'
    if kind in ('index', 'extracts'):
        for did, txt in data['texts'].items():
            prompt += f'文档 {did}（仅前{DOC_CAP}字）: {txt[:DOC_CAP]}\n'
        prompt += '要求：仅索引/抽取最核心的3-5条事实，每条不超过30字。不要生成详细分析。\n'
    if kind == 'report':
        prompt += ('\n输出JSON：{"investigation_timeline":"...",'
                   '"fraud_nature":"...","report":"...","unknown_marks":[...]}\n')
    return prompt


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------
class DeterministicAdapter:
    """Frozen deterministic stand-in model. Declared SYNTHETIC: its outputs
    are excerpts of the REAL evidence texts (quality differentiation comes
    from excerpt length per model), used only for zero-call mechanics
    acceptance — never for scientific quality claims."""

    def __init__(self, anomalies=None):
        self.anomalies = dict(anomalies or {})   # node_id -> {type, left}
        self.calls = []
        self.prompts = []                        # (node, prompt) for tests

    def call(self, nid, kind, model, prompt):
        self.calls.append(dict(node=nid, kind=kind, model=model,
                               prompt_chars=len(prompt)))
        self.prompts.append((nid, prompt))
        lat = LATENCY_PRIOR[model] * (1.1 if kind == 'report' else 1.0)
        toks = {'in': min(len(prompt), 4000), 'out': 400 if model == 'glm53' else 260}
        # NOTE: fault injection is NOT here anymore — it lives in the executor
        # (inject_result) so the REAL Meter path has identical fault semantics.
        # healthy: excerpt of the real evidence embedded in the prompt
        pk = PORT_KEYS.get(kind, kind)
        depth = 800 if model == 'glm53' else 300
        m = sorted(set(re.findall(r'[\u4e00-\u9fa5][\u4e00-\u9fa5\d,，.。;；:-]{8,}',
                                  prompt)))
        body = '；'.join(m[-12:])[:depth] if m else sub_safe(kind)
        return dict(success=True, failure=None, usage=toks, latency_s=lat,
                    output={pk: body})


def sub_safe(kind):
    return {'index': '文档已索引', 'extracts': '事实抽取完成',
            'timeline': '时间线整理完成', 'entity_facts': '主体事实完成',
            'factcheck_full': '交叉核查完成', 'report': '调查报告完成',
            'reasoning': '推理完成', 'verification': '核验完成'}.get(
        kind, 'done')


class MeterAdapter:
    """Real path — FAIL-CLOSED behind the auth gate. Shares the executor,
    scheduler, kernel and fault-injection semantics with the deterministic
    path; only the model transport differs (pilot Meter)."""

    OUT_CAPS = {'report': 768}       # v2 parity: report 768, others 1024
    OUT_DEFAULT = 1024

    def __init__(self, meter, run_id):
        self.meter = meter
        self.run_id = run_id
        self._ver = {}               # node -> attempt counter (purpose suffix)

    def call(self, nid, kind, model, prompt):
        from pilot_common import fenced_json
        self._ver[nid] = self._ver.get(nid, 0) + 1
        rec, txt = self.meter.call(
            model, SYS, prompt, self.OUT_CAPS.get(kind, self.OUT_DEFAULT),
            purpose=f'{self.run_id}:{nid}:v{self._ver[nid]}', timeout_s=60)
        usage = {'in': rec['usage']['input_tokens'],
                 'out': rec['usage']['output_tokens']}
        try:
            obj = fenced_json(txt)
            pk = PORT_KEYS.get(kind, kind)
            if isinstance(obj, dict) and pk in obj:
                return dict(success=True, failure=None, usage=usage,
                            latency_s=rec['latency_s'], output={pk: obj[pk]})
        except Exception:
            pass
        return dict(success=False, failure='parse', usage=usage,
                    latency_s=rec['latency_s'], output=None)


def inject_result(anomalies, nid, result):
    """Executor-level fault injection, shared by BOTH adapter paths.
    Persistent 'contract': the node's merged-scope port contract keeps
    failing (narrower split successors use different node ids and are not
    injected). 'transport': transient, consumes one 'left' unit.
    Real usage/latency of the underlying call are preserved (failures are
    billed — operator item 5)."""
    inj = anomalies.get(nid)
    if not inj:
        return result
    if inj['type'] == 'contract':
        return dict(result, success=False, failure='contract', output=None)
    if inj.get('left', 0) > 0:
        inj['left'] -= 1
        if inj['type'] == 'transport':
            return dict(result, success=False, failure='transport', output=None)
        if inj['type'] == 'evidence_fail':
            pk = PORT_KEYS.get(result.get('_kind', ''), '') if False else None
            out = dict(result.get('output') or {})
            if out:
                out[next(iter(out))] = []
            return dict(result, success=True, failure=None, output=out)
    return result


# ---------------------------------------------------------------------------
# K_m resource-constrained parallel kernel (virtual clock)
# ---------------------------------------------------------------------------
class Kernel:
    def __init__(self, k=K_M):
        self.k = dict(k)
        self.free_at = {m: [0.0] * n for m, n in k.items()}

    def run_batch(self, assignments, adapter, state, data, t_now,
                  anomalies=None):
        """Execute (node, model) assignments in parallel under K_m slots.
        Returns (t_end, records). Nodes whose slot frees earlier start
        earlier; per-node wait and finish times are recorded."""
        events = []
        for nid, model in assignments:
            heap = self.free_at[model]
            slot_free = heapq.heappop(heap)
            start = max(t_now, slot_free)
            res = adapter.call(nid, state.kinds[nid], model,
                               build_prompt(state, nid, data))
            res = inject_result(anomalies or {}, nid, res)
            heapq.heappush(heap, start + res['latency_s'])
            events.append(dict(node=nid, model=model, start=round(start, 2),
                               wait=round(start - t_now, 2),
                               finish=round(start + res['latency_s'], 2),
                               result=res))
        t_end = max((e['finish'] for e in events), default=t_now)
        return t_end, events


# ---------------------------------------------------------------------------
# Z application (structure ops that passed legality)
# ---------------------------------------------------------------------------
def apply_z(state, z_op, z_detail):
    if z_op == 'ADJUST_DEP':
        m = re.search(r'drop redundant edge (\w+)->(\w+)', z_detail)
        if m:
            u, v = m.group(1), m.group(2)
            state.active_deps[v] = [p for p in state.active_deps[v] if p != u]
            state.z_ops_applied.append(f'ADJUST_DEP:{u}->{v}')
            return True
    if z_op == 'SPLIT_VERIFY':
        target = z_detail.split(' -> ')[0]
        if target in state.nodes:
            ps = state.parents(target)
            child = next((c for c, cds in state.active_deps.items()
                          if target in cds), None)
            for suffix, p in zip(('_a', '_b'), ps[:2]):
                nid = target + suffix
                state.nodes[nid] = NodeState(
                    nid, state.nodes[target].kind,
                    f'验证分支 {p}: ' + state.nodes[target].subtask,
                    model='glm53')
                state.kinds[nid] = state.nodes[target].kind
                state.subtasks[nid] = state.subtasks.get(target, '')
                state.active_deps[nid] = [p]
                if child:
                    state.active_deps[child] = state.active_deps.get(child, []) + [nid]
            state.nodes.pop(target)
            state.active_deps.pop(target, None)
            if child:
                state.active_deps[child] = [p for p in state.active_deps[child]
                                            if p != target]
            state.z_ops_applied.append(f'SPLIT_VERIFY:{target}')
            return True
    return False


def run_prefix(data, anomalies, budget_tokens=60000, adapter=None,
               deadline_s=None):
    """Shared paid prefix (paired design): execute under frozen pi0 with NO
    recovery until the injected fault fires, then snapshot. All six arms
    fork from the IDENTICAL post-fault state — cross-arm identical initial
    fault and frozen inputs by construction (operator item 6)."""
    from copy import deepcopy
    state = build_state(data, budget_tokens, deadline_s)
    kernel = Kernel()
    anomalies = dict(anomalies or {})
    adapter = adapter or DeterministicAdapter()
    spent, calls = 0.0, []
    while True:
        ready = state.ready_nodes()
        if not ready:
            break
        t_end, events = kernel.run_batch(
            [(n, state.nodes[n].model) for n in ready], adapter, state, data,
            state.t_now, anomalies)
        state.t_now = t_end
        fired = False
        for e in events:
            n, r = state.nodes[e['node']], e['result']
            n.attempts += 1
            n.version += 1
            n.usage, n.latency_s, n.wait_s = r['usage'], r['latency_s'], e['wait']
            spent += r['usage']['in'] + r['usage']['out']
            state.budget_remaining -= (r['usage']['in'] + r['usage']['out'])
            if r['success']:
                n.status, n.output, n.failure_type = 'done', r['output'], None
            else:
                n.status, n.output = 'failed', None
                n.failure_type = r['failure']
                fired = True
            calls.append(dict(node=e['node'], model=e['model'],
                              attempt=n.attempts, version=n.version,
                              wait_s=e['wait'], start=e['start'],
                              finish=e['finish'], latency_s=r['latency_s'],
                              usage=r['usage'], success=r['success'],
                              failure=r['failure'], shared=True))
        for nid in state.blocked_nodes():
            state.nodes[nid].status = 'blocked'
        if fired:
            break
    return dict(state=state, spent=spent, calls=calls, anomalies=anomalies,
                t_now=state.t_now)


# ---------------------------------------------------------------------------
# the run loop: decide -> execute -> feedback (bounded)
# ---------------------------------------------------------------------------
def run_arm(arm, data, anomalies=None, budget_tokens=60000, adapter=None,
            deadline_s=None, fork=None):
    from copy import deepcopy
    if fork is not None:
        state = deepcopy(fork['state'])
        state.budget_remaining = budget_tokens - fork['spent']
        anomalies = dict(fork['anomalies'])
        recovery_rounds = 1 if state.failed_nodes() else 0
    else:
        state = build_state(data, budget_tokens, deadline_s)
        anomalies = dict(anomalies or {})
        recovery_rounds = 0
    if deadline_s:
        state.deadline_s = deadline_s
    kernel = Kernel()
    adapter = adapter or DeterministicAdapter()
    meta = ARM_META[arm]
    rounds, spent, calls = [], 0.0, []
    if fork is not None:
        spent, calls = fork['spent'], list(fork['calls'])
    status = 'RUNNING'
    terminal = state.terminal()

    while status == 'RUNNING':
        failed_before = bool(state.failed_nodes())
        if failed_before:
            recovery_rounds += 1
        dec = ARM_DECIDERS[arm](state)
        rounds.append(dict(round=len(rounds) + 1, action=dec.action_type,
                           z_op=dec.z_op, z_detail=dec.z_detail,
                           recovery_set=sorted(dec.recovery_set),
                           reoptimize=dec.reoptimize,
                           assignments=[list(a) for a in dec.assignments],
                           rationale=dec.rationale))
        if dec.action_type == 'terminate' or not dec.assignments:
            status = ('COMPLETE' if state.nodes[terminal].status == 'done' else
                      'INCOMPLETE_NO_RECOVERY'
                      if (state.failed_nodes() and not meta['recovers']) else
                      'INCOMPLETE_RECOVERY_EXHAUSTED'
                      if state.failed_nodes() else 'STALLED')
            break
        if dec.z_op != 'KEEP':
            apply_z(state, dec.z_op, dec.z_detail)
        for nid, model in dec.reoptimize:
            if nid in state.nodes:
                state.nodes[nid].model = model
        # static arm must not recover: drop failed-node assignments
        if not meta['recovers']:
            dec.assignments = [(n, m) for n, m in dec.assignments
                               if state.nodes[n].status != 'failed']
        t_end, events = kernel.run_batch(dec.assignments, adapter, state,
                                         data, state.t_now, anomalies)
        state.t_now = t_end
        for e in events:
            n, r = state.nodes[e['node']], e['result']
            n.attempts += 1
            n.version += 1
            n.model = e['model']
            n.wait_s = e['wait']
            n.latency_s = r['latency_s']
            n.usage = r['usage']
            spent += r['usage']['in'] + r['usage']['out']
            state.budget_remaining -= (r['usage']['in'] + r['usage']['out'])
            if r['success']:
                n.status, n.output, n.failure_type = 'done', r['output'], None
            else:
                n.status, n.output = 'failed', None
                n.failure_type = r['failure']
            calls.append(dict(node=e['node'], model=e['model'],
                              attempt=n.attempts, version=n.version,
                              wait_s=e['wait'], start=e['start'],
                              finish=e['finish'], latency_s=r['latency_s'],
                              usage=r['usage'], success=r['success'],
                              failure=r['failure']))
        for nid in state.blocked_nodes():
            state.nodes[nid].status = 'blocked'
        # unblock nodes whose parents all became done (post-recovery)
        for nid, n in state.nodes.items():
            if n.status == 'blocked' and all(
                    state.nodes[p].status == 'done' for p in state.parents(nid)):
                n.status = 'pending'
        if state.nodes[terminal].status == 'done':
            status = 'COMPLETE'
        elif state.budget_remaining <= 0:
            status = 'BUDGET_STOP'
        elif (state.failed_nodes() and meta['recovers']
              and recovery_rounds >= MAX_RECOVERY_ROUNDS):
            status = 'INCOMPLETE_RECOVERY_EXHAUSTED'

    ports = {}
    for n in sorted(state.nodes):
        if state.nodes[n].status != 'done':
            continue
        pk = PORT_KEYS.get(state.kinds[n], state.kinds[n])
        val = (state.nodes[n].output or {}).get(pk)
        if val is None:
            continue
        # port-collision-safe: split successors share one port key; every
        # done node's value must reach the scorer (operator item 3)
        ports[pk] = (ports[pk] + ' ' + json.dumps(val, ensure_ascii=False)
                     if pk in ports else json.dumps(val, ensure_ascii=False))
    raw = json.dumps(ports, ensure_ascii=False)
    q, covered = score(raw, data['silver'])
    return dict(
        arm=arm, task=data['task']['task_id'], status=status, Q=q,
        covered=len(covered), n_silver=len(data['silver']),
        tokens=int(spent), makespan=round(state.t_now, 2),
        deadline_s=state.deadline_s,
        deadline_met=bool(state.t_now <= state.deadline_s),
        baseline_type=meta.get('baseline_type',
                               'adaptive') if arm == 'Static-Parallel' else 'adaptive',
        attribution_note=meta.get('attribution_note', ''),
        z_ops_applied=state.z_ops_applied, rounds=rounds, calls=calls,
        wait_total=round(sum(c['wait_s'] for c in calls), 2),
        node_versions={n: state.nodes[n].version for n in state.nodes})


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--adapter', default='deterministic',
                    choices=['deterministic', 'meter'])
    ap.add_argument('--authorize', action='store_true')
    ap.add_argument('--arm')
    ap.add_argument('--task')
    ap.add_argument('--anomaly', default='transport',
                    choices=['transport', 'evidence_fail', 'contract', 'none'])
    args = ap.parse_args()

    tasks = load_tasks()
    if args.adapter == 'meter':
        if not args.authorize:
            raise SystemExit('real path requires --authorize (HOLD: seven-field '
                             'auth record stage_c_r1_v1 required)')
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location('ag', '/root/r3_own_pool/'
                                       'deadline_reward_v1/auth_gate.py')
        ag = module_from_spec(spec)
        sys.modules['ag'] = ag
        spec.loader.exec_module(ag)
        ag.require('stage_c_r1_v1')

    arms = [args.arm] if args.arm else ARMS
    task_ids = [args.task] if args.task else sorted(tasks)
    results = []
    for tid in task_ids:
        data = tasks[tid]
        for arm in arms:
            # anomaly at the task's timeline node (same injection point
            # class as the frozen v2 protocol: first timeline-kind node)
            tl = next((n['id'] for n in data['task']['dag']['nodes']
                       if n['kind'] == 'timeline'), None)
            anomalies = {tl: dict(type=args.anomaly, left=1)} \
                if (args.anomaly != 'none' and tl) else {}
            r = run_arm(arm, data, anomalies)
            results.append(r)
            print(f"{tid} {arm:16s} {r['status']:28s} Q={r['Q']:.3f} "
                  f"tok={r['tokens']} mk={r['makespan']}s "
                  f"wait={r['wait_total']}s z={r['z_ops_applied'] or 'KEEP'}")
    OUT.mkdir(exist_ok=True)
    (OUT / 'deterministic_results.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=1))
    print(f"\n{len(results)} runs -> {OUT / 'deterministic_results.json'}")


if __name__ == '__main__':
    main()
