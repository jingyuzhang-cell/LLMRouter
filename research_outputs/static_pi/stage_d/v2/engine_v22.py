"""Phase Pi V2.2.1 engine: R0 / Z split / pi / L1 / six arms. Offline only (mock provider).

Execution order is FROZEN: detect -> R0 -> Z -> recompute U -> pi -> reschedule.
No network. Every call is recorded; no key is read.
"""
import json, hashlib

MODEL_BASE = ('E1', 'E2', 'E3', 'E4', 'J1', 'J2', 'SINK')
ARMS = ('Static-GLM', 'Static-DS', 'Retry-only', 'Z-only', 'pi-only', 'Joint')
FACTORIAL = ('Retry-only', 'Z-only', 'pi-only', 'Joint')

def base_dag():
    return {
      'E1': dict(kind='model', ups=[], downs=['J1'], spec='E_POS', doc='D1', deleted=False),
      'E2': dict(kind='model', ups=[], downs=['J1'], spec='E_POS', doc='D2', deleted=False),
      'E3': dict(kind='model', ups=[], downs=['J2'], spec='E',     doc='D3', deleted=False),
      'E4': dict(kind='model', ups=[], downs=['J2'], spec='E',     doc='D4', deleted=False),
      'J1': dict(kind='model', ups=['E1','E2'], downs=['J2'], spec='J1', deleted=False),
      'J2': dict(kind='model', ups=['J1','E3','E4'], downs=['SINK'], spec='J2', deleted=False),
      'SINK': dict(kind='model', ups=['J2'], downs=[], spec='SINK', deleted=False),
    }

def _rewire(nodes, old, new):
    for up in nodes[old]['ups']:
        if not nodes[up]['deleted']:
            nodes[up]['downs'] = [new if d == old else d for d in nodes[up]['downs']]
    for dn in nodes[old]['downs']:
        if not nodes[dn]['deleted']:
            nodes[dn]['ups'] = [new if u == old else u for u in nodes[dn]['ups']]

class DAG:
    def __init__(self):
        self.nodes = base_dag()
        self.version = 0
        self.edits = []
    def active_models(self):
        return [n for n, s in self.nodes.items() if s['kind'] == 'model' and not s['deleted']]
    def split(self, node):
        assert node in ('E1', 'E2'), 'Z split defined for E nodes only'
        assert not self.nodes.get(node, {}).get('deleted'), 'already split'
        src = self.nodes[node]
        pos, rest, mrg = f'{node}_pos', f'{node}_rest', f'{node}_merge'
        # contracts DERIVED for the new sub-tasks (allowed by the Z definition)
        self.nodes[pos] = dict(kind='model', ups=list(src['ups']), downs=[mrg],
                               spec='E_POS_ONLY', doc=src['doc'], deleted=False, derived_from=node)
        self.nodes[rest] = dict(kind='model', ups=list(src['ups']), downs=[mrg],
                                spec='E_NO_POS', doc=src['doc'], deleted=False, derived_from=node)
        self.nodes[mrg] = dict(kind='code', ups=[pos, rest], downs=list(src['downs']),
                               deleted=False, derived_from=node)
        _rewire(self.nodes, node, mrg)
        self.nodes[node]['deleted'] = True
        self.version += 1
        self.edits.append(dict(op='split', node=node, added=[pos, rest, mrg], version=self.version))
        return pos, rest, mrg

# ── fixed R0: one function object shared by all four factorial arms ──
def R0(dag, node, states, versions, audit):
    versions[node] = versions.get(node, 0) + 1
    states[node] = 'READY'
    stack = list(dag.nodes[node]['downs'])
    invalidated = []
    while stack:
        d = stack.pop()
        if d not in dag.nodes or dag.nodes[d]['deleted']:
            continue
        if states.get(d) in ('COMPLETED', 'READY'):
            states[d] = 'READY'
            invalidated.append(d)
        stack.extend(dag.nodes[d]['downs'])
    audit.append(dict(step='R0', node=node, invalidated=invalidated))
    return invalidated

def compute_U(dag, states):
    return sorted(n for n in dag.active_models()
                  if states.get(n, 'PENDING') in ('PENDING', 'READY'))

def pi_apply(dag, U, alt='deepseek'):
    scope = []
    for n in U:
        dag.nodes[n]['model'] = alt
        scope.append(n)
    return scope

# ── L1: deterministic normalization ONLY (never invents facts) ──
def _norm_dates(o, path, fixed):
    """Normalize YYYY/MM/DD -> YYYY-MM-DD anywhere. Never adds or removes facts."""
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if isinstance(v, str) and len(v) == 10 and v[4] == '/' and v[7] == '/':
                o[k] = v.replace('/', '-'); fixed.append(f'date:{path}.{k}')
            else:
                _norm_dates(v, f'{path}.{k}', fixed)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            _norm_dates(v, f'{path}[{i}]', fixed)
    return o

def L1(raw_obj, required_fields):
    obj = json.loads(json.dumps(raw_obj)) if raw_obj else {}
    fixed, residual = [], []
    if isinstance(obj, dict):
        _norm_dates(obj, '$', fixed)
        for f in required_fields:
            if f not in obj: residual.append(f'missing:{f}')
            elif obj[f] is None: residual.append(f'null:{f}')
            elif f in ('answers', 'abstentions') and not isinstance(obj[f], list):
                residual.append(f'type:{f}')
            elif f == 'answers':
                for i, a in enumerate(obj[f]):
                    if not isinstance(a, dict): residual.append(f'type:answers[{i}]'); continue
                    if not a.get('fact_id'): residual.append(f'missing:answers[{i}].fact_id')
                    if a.get('value') in (None, ''): residual.append(f'null:answers[{i}].value')
    else:
        residual.append('not_object')
    return obj, fixed, residual

# ─────────────── mock provider (deterministic; NO network) ───────────────
class MockProvider:
    """Returns schema-valid JSON per node; honours spec-level defects so the fault persists."""
    def __init__(self, scenario, timeout_once=(), sink_missing=None):
        self.scenario = scenario
        self.timeout_once = set(timeout_once)
        self.sink_missing = sink_missing
        self.calls = []
    def call(self, node, spec, doc, ups_out, defective=False, model=None):
        self.calls.append(dict(node=node, spec=spec))
        if node in self.timeout_once:
            self.timeout_once.discard(node)
            raise TimeoutError('mock timeout')
        if spec == 'E_POS_ONLY':
            return {'positions': [{'field': '任职状况', 'value': '董事长', 'quote': 'q', 'page': 1}]}
        if spec == 'E_NO_POS':          # contract derived WITHOUT positions -> by definition no positions
            return {'subjects': ['泽达易盛'], 'notice_numbers': ['A1'], 'dates': ['2020-01-01'], 'cause': ['c'], 'quotes': ['q']}
        if spec == 'E_POS':
            return {'subjects': ['泽达易盛'], 'notice_numbers': ['A1'], 'dates': ['2020/01/01'],
                    'cause': ['c'], 'quotes': ['q'],
                    'positions': [{'field': '任职状况', 'value': '董事长', 'quote': 'q', 'page': 1}]}
        if spec == 'E_POS_DEFECTIVE':   # contract omits the positions requirement (persistent)
            return {'subjects': ['泽达易盛'], 'notice_numbers': ['A1'], 'dates': ['2020/01/01'],
                    'cause': ['c'], 'quotes': ['q']}
        if spec == 'E':
            return {'subjects': ['西王食品'], 'notice_numbers': ['B1'], 'dates': ['2020/02/02'], 'cause': ['c'], 'quotes': ['q']}
        if spec == 'J1':
            return {'judgments': [{'kind': 'person_identity', 'verdict': 'SAME_PERSON'}], 'dates_relay': {'D1': {}}}
        if spec == 'J2':
            return {'subject_binding': [], 'notice_binding': [], 'cause_specificity': [],
                    'counts': {'personal': 1, 'announcing': 2}}
        if spec == 'SINK':
            ans = {'answers': [{'fact_id': 'F1', 'value': '2020-01-01'},
                               {'fact_id': 'F2', 'value': '1'},
                               {'fact_id': 'F3', 'value': '2'}],
                   'abstentions': []}
            if self.scenario == 'S4p' and self.sink_missing:
                ans['answers'] = [a for a in ans['answers'] if a['fact_id'] != self.sink_missing]
            return ans
        return {'ok': True}

def merge_code(dag, node, states, outputs):
    """Deterministic merge of the two sub-task outputs. Key sets are disjoint by construction."""
    ups = dag.nodes[node]['ups']
    merged = {}
    for u in ups:
        o = outputs.get(u) or {}
        for k in o:
            assert k not in merged, f'merge key collision: {k}'
            merged[k] = o[k]
    return merged

DETECT_POS_NODES = ('E1', 'E2')

def detect(node, parsed, spec):
    sig = {}
    if node in DETECT_POS_NODES and not (parsed or {}).get('positions'):
        sig['D2'] = 'structure'
    return sig

def run_execution(arm, scenario, cap_calls=16, provider=None, sink_missing=None,
                  fail_nodes=(), max_reruns=2, simulated=True):
    """One execution. Returns a full record incl. per-node audit trail."""
    dag = DAG()
    states = {n: 'PENDING' for n in dag.nodes}
    versions = {}
    outputs, calls, audit, pi_scope, z_actions = {}, [], [], [], []
    snaps = []
    reruns = {}
    degraded_fields = {}
    p = provider or MockProvider(scenario, timeout_once=set(fail_nodes), sink_missing=sink_missing)
    # S1/S1b: spec-level defect on the original E node (PERSISTENT)
    if scenario == 'S1':
        dag.nodes['E2']['spec'] = 'E_POS_DEFECTIVE'      # persistent CONTRACT defect
    if scenario == 'S1b':
        dag.nodes['E1']['spec'] = 'E_POS_DEFECTIVE'
    init_model = 'deepseek' if arm == 'Static-DS' else 'glm53flash'
    for n, s in dag.nodes.items():
        if s['kind'] == 'model': s['model'] = init_model
    stop_reason = 'completed'
    snaps.append(dict(phase='init', states=dict(states), dag_version=dag.version))

    def node_ready(n):
        s = dag.nodes[n]
        return all(states.get(u) in ('COMPLETED', 'COMPLETED_DEGRADED')
                   for u in s['ups'] if not dag.nodes[u]['deleted'])

    while True:
        done = [n for n in dag.nodes if not dag.nodes[n]['deleted']]
        if all(states.get(n) in ('COMPLETED', 'COMPLETED_DEGRADED', 'DELETED', 'FAILED') for n in done):
            break
        # code nodes execute automatically
        ran_code = False
        for n in [x for x in dag.nodes if dag.nodes[x]['kind'] == 'code' and not dag.nodes[x]['deleted']]:
            if states.get(n) != 'COMPLETED' and node_ready(n):
                outputs[n] = merge_code(dag, n, states, outputs)
                states[n] = 'COMPLETED'; ran_code = True
        if ran_code: continue
        ready = [n for n in dag.active_models() if states.get(n) in ('PENDING', 'READY') and node_ready(n)]
        if not ready:
            pending = [x for x in dag.active_models() if states.get(x) not in ('COMPLETED','FAILED')]
            failed = [x for x in dag.active_models() if states.get(x) == 'FAILED']
            stop_reason = 'incomplete' if (pending or failed) else 'deadlock'
            break
        n = ready[0]
        if len(calls) >= cap_calls:
            stop_reason = 'budget'
            break
        states[n] = 'RUNNING'
        spec = dag.nodes[n]['spec']
        defective = dag.nodes[n].get('defective', False)
        prov = p
        try:
            parsed = prov.call(n, spec, dag.nodes[n].get('doc'),
                               {u: outputs.get(u) for u in dag.nodes[n]['ups']}, defective,
                               dag.nodes[n].get('model'))
        except TimeoutError:
            calls.append(dict(node=n, model=dag.nodes[n].get('model'), status='timeout', charged=True))
            if len(calls) >= cap_calls: stop_reason = 'budget'; break
            parsed = prov.call(n, spec, dag.nodes[n].get('doc'),
                               {u: outputs.get(u) for u in dag.nodes[n]['ups']}, defective,
                               dag.nodes[n].get('model'))
            calls.append(dict(node=n, model=dag.nodes[n].get('model'), status='retry_ok', charged=True))
        else:
            calls.append(dict(node=n, model=dag.nodes[n].get('model'), status='ok', charged=True))
        outputs[n] = parsed
        states[n] = 'COMPLETED'
        sig = detect(n, parsed, spec)
        snaps.append(dict(phase='detect', node=n, states=dict(states), dag_version=dag.version))
        audit.append(dict(step='detect', node=n, sig=sig, state=states.get(n)))
        if not sig:
            continue
        fam = next(iter(sig.values()))
        # ── Static arms: no recovery at all ──
        if arm in ('Static-GLM', 'Static-DS'):
            # Same partial-input contract: missing field marked UNKNOWN, downstream proceeds.
            if isinstance(parsed, dict) and 'positions' not in parsed:
                parsed['positions'] = []           # explicit UNKNOWN marker
                degraded_fields[n] = ['positions']
                states[n] = 'COMPLETED_DEGRADED'
                audit.append(dict(step='degraded', node=n, missing=['positions'], reason='static'))
            else:
                states[n] = 'COMPLETED'
            audit.append(dict(step='policy', node=n, action='none', reason='static'))
            continue
        # 1) R0
        R0(dag, n, states, versions, audit)
        snaps.append(dict(phase='R0', node=n, states=dict(states), dag_version=dag.version))
        reruns[n] = reruns.get(n, 0) + 1
        if reruns[n] > max_reruns:
            # V2 degraded semantics: keep the last parseable output, mark missing
            # fields UNKNOWN, let downstream continue under the partial-input contract.
            # Hard-fail only when there is NO parseable output at all.
            last = outputs.get(n)
            if isinstance(last, dict):
                missing = ['positions'] if 'positions' not in last else []
                if missing:
                    last['positions'] = []      # explicit UNKNOWN marker; never a fabricated fact
                    degraded_fields[n] = missing
                states[n] = 'COMPLETED_DEGRADED'
                audit.append(dict(step='degraded', node=n, missing=missing))
            else:
                states[n] = 'FAILED'; audit.append(dict(step='rerun_cap_hard_fail', node=n))
            continue
        # 2) Z
        if arm in ('Z-only', 'Joint') and fam == 'structure' and n in ('E1', 'E2'):
            pos, rest, mrg = dag.split(n)
            states[n] = 'DELETED'
            for x in (pos, rest, mrg): states[x] = 'PENDING'
            for x in (pos, rest, mrg): dag.nodes[x]['model'] = init_model
            z_actions.append(dict(node=n, added=[pos, rest, mrg], version=dag.version))
            audit.append(dict(step='Z', node=n, added=[pos, rest, mrg], version=dag.version))
        elif arm in ('Z-only', 'Joint'):
            z_actions.append(dict(node=n, action='z_not_applicable', fam=fam))
            audit.append(dict(step='Z', node=n, action='z_not_applicable', fam=fam))
        # 3) recompute U AFTER R0 and Z
        snaps.append(dict(phase='Z', node=n, states=dict(states), dag_version=dag.version))
        U = compute_U(dag, states)
        snaps.append(dict(phase='U', node=n, U=list(U), states=dict(states), dag_version=dag.version))
        audit.append(dict(step='U', U=list(U)))
        # 4) pi
        if arm in ('pi-only', 'Joint'):
            scope = pi_apply(dag, U)
            pi_scope.extend(scope)
            snaps.append(dict(phase='pi', node=n, scope=list(scope), states=dict(states), dag_version=dag.version))
            audit.append(dict(step='pi', scope=list(scope), dag_version=dag.version))
    # ── L1 (all six arms) ──
    sink = outputs.get('SINK') or {}
    required = ('answers', 'abstentions')
    obj, fixed, residual = L1(sink, required)
    l1_fixed = bool(fixed) and not residual
    # residual can only trigger a policy if a policy exists and nothing is left to do
    return dict(arm=arm, scenario=scenario, calls=calls, call_count=len(calls),
                stop_reason=stop_reason, z_actions=z_actions, pi_scope=sorted(set(pi_scope)),
                dag_version=dag.version, edits=dag.edits, outputs=outputs,
                l1_fixed=l1_fixed, l1_normalized=fixed, residual=residual,
                audit=audit, states=dict(states), versions=dict(versions), snapshots=snaps,
                simulated=simulated, degraded_fields=dict(degraded_fields),
                sink_text=(outputs.get('SINK') if isinstance(outputs.get('SINK'), str) else None),
                )
