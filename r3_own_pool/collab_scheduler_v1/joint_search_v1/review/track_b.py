"""Track B v2: cross-state production closed loop (clean + fault30) with FULL-IDENTITY
cache prediction. Supersedes v1 (single-state loop, node+model cache approximation)
IN THIS SAME FILE — no parallel test suite.

Admission-gap fixes mandated by review (2026-10-09):
  GAP-1 "incremental cost deducted by same-node+same-model": WRONG because r/v
  full inputs depend on upstream outputs. v2 predictor verifies the COMPLETE
  cache identity chain per (state, task):
      e1/e2 prompt = f(task, node)                -> identity (node, m_ei)
      r    prompt = f(task, facts_e1, facts_e2)   -> identity (m_e1, m_e2, m_r)
      v    prompt = f(task, facts, r output)      -> identity (m_e1, m_e2, m_r, m_v)
  Unknown successors are NEVER predicted as hits (conditional-conservative).
  Predicted hits are verified against the executor's own TRAJECTORY.jsonl
  (alias_of records). Recovery calls are charged CONDITIONALLY:
  E[new tokens] = overhead x P_fire(state), frozen calibration parameters,
  with the measured fire rate reported alongside.

  GAP-2 "closed loop covers clean only": the SAME production loop now evaluates
  every selected config on BOTH states per step (SearchSession.step with a REAL
  fault panel: r-corruption on task 1, empty-e2-facts on task 2), so Q/C/L are
  state- and Z-dependent inside one loop; the state ablation runs WITHIN this
  loop (state feature bits on/off), not in a separate suite.

  GAP-3 "C/L attached as deterministic": evaluated (config,state) units use
  ACTUAL evaluator C/L; only CANDIDATES use frozen ex-ante predictions; all six
  methods share the identical information boundary (public config space + state
  list + public fault rate + returned observations); ablations toggle only the
  declared bits (state features / incremental divisor).

Zero real LLM calls. The stub chain is output-coupled (v recomputes from r's
expression over parsed facts) and model-tagged (facts evidence and expression
spacing vary by model), so the cache-identity structure matches real
deployments; r corruption propagates to Q exactly as a real broken node would.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/review'

from collab_scheduler_v1.joint_search_v1.evaluator import (
    JointEvaluator, MeteredExecutor, SearchSession, space, NODES)
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget, StopRun
from collab_scheduler_v1.fault30_protocol import Ledger
from collab_scheduler_v1.fault30_cache_accounting_tests import make_task
from collab_scheduler_v1.joint_search_v1.review.exact_qnehvi_test import (
    JointPosteriorGP)
from collab_scheduler_v1.joint_search_v1.review.track_a import (
    botorch_qnehvi_scores)

STATES = ('clean', 'fault30')
RHO_FAULT30 = 0.3  # public protocol knowledge: corrupted-node injection rate
# frozen conditional-recovery calibration (documented; revisable only with new
# measured data recorded in the evidence manifest)
RECOVERY_FIRE_E = {'clean': {'NONE': 0.0, 'LOCAL': 0.0, 'FULL': 0.0},
                   'fault30': {'NONE': 0.0, 'LOCAL': RHO_FAULT30, 'FULL': RHO_FAULT30}}

NODE_EST_TOKENS = {'e1': 700, 'e2': 700, 'r': 200, 'v': 100}
MODEL_MULTIPLIER = {'medium': 0.9, 'large': 1.1, 'coder': 1.0}
RECOVERY_COST = {'LOCAL': 150, 'FULL': 1200}


def deployment_cost(config):
    x = config['X']
    total = sum(NODE_EST_TOKENS[nd] * MODEL_MULTIPLIER[x[nd]] for nd in NODES)
    if config['Z'] in RECOVERY_COST:
        total += RECOVERY_COST[config['Z']]
    return float(total)


# ============ GAP-1 fix: full-identity cache predictor ============

class CacheIdentityPredictor:
    """Per (state-scope, task) signature sets mirroring the executor's cache
    identity (model_binding, sha256(full_prompt), task, node, scope).

    Prompts are chained: r consumes the e-outputs, v consumes the facts and
    r's output. A node therefore hits only when its FULL upstream signature
    already executed in the same scope:
      e_i : (node, m_ei)
      r   : (m_e1, m_e2, m_r)
      v   : (m_e1, m_e2, m_r, m_v)
    Unknown successors are charged as new — predicted-hit => actual hit by
    construction (prompt-identical chain); verified against TRAJECTORY.jsonl.
    """

    def __init__(self, task_uids):
        self.task_uids = list(task_uids)
        self.sigs = {st: {u: dict(e=set(), r=set(), v=set()) for u in self.task_uids}
                     for st in STATES}

    def _v_sig(self, config, state):
        """v identity: (m_e1, m_e2, m_r, m_v) + Z-context in fault30 only.
        In clean the realized chain is recovery-independent (recovery never
        fires), so v prompts are identical across Z for the same tuple. In
        fault30, e-node faults are rerouted at extraction stage, so v may
        consume RECOVERED facts under LOCAL/FULL — the realized chain, and
        hence the v prompt, depends on Z there."""
        x = config['X']
        sig = (x['e1'], x['e2'], x['r'], x['v'])
        return sig + (('z', config['Z']),) if state == 'fault30' else sig

    def predict(self, config, state):
        x = config['X']
        per_task = {}
        est_total = 0.0
        for u in self.task_uids:
            s = self.sigs[state][u]
            nodes = {}
            for nd in ('e1', 'e2'):
                nodes[nd] = 'hit' if (nd, x[nd]) in s['e'] else 'new'
            nodes['r'] = 'hit' if (x['e1'], x['e2'], x['r']) in s['r'] else 'new'
            nodes['v'] = 'hit' if self._v_sig(config, state) in s['v'] else 'new'
            per_task[u] = nodes
            est_total += sum(NODE_EST_TOKENS[nd] * MODEL_MULTIPLIER[x[nd]]
                             for nd in NODES if nodes[nd] == 'new')
        est = est_total / len(self.task_uids)
        est += RECOVERY_COST.get(config['Z'], 0) * RECOVERY_FIRE_E[state][config['Z']]
        return dict(per_task=per_task, est_new_tokens=float(max(est, 100.0)))

    def register(self, config, state):
        x = config['X']
        for u in self.task_uids:
            s = self.sigs[state][u]
            s['e'].add(('e1', x['e1']))
            s['e'].add(('e2', x['e2']))
            s['r'].add((x['e1'], x['e2'], x['r']))
            s['v'].add(self._v_sig(config, state))


def extract_features(config, state_bit=None):
    """7 public config features (+optional state bit). One constructor for ALL
    methods; ablations toggle only the state bit / cost divisor."""
    x, z = config['X'], config['Z']
    models = [x[nd] for nd in NODES]
    f = [float(len(set(models))),
         1.0 if 'coder' in models else 0.0,
         1.0 if 'large' in models else 0.0,
         1.0 if x['e1'] != x['e2'] else 0.0,
         float({'NONE': 0, 'LOCAL': 1, 'FULL': 2}[z]),
         deployment_cost(config) / 2500.0,
         RECOVERY_COST.get(z, 0) / 1200.0]
    if state_bit is not None:
        f.append(float(state_bit))
    return f


def _ranks(v):
    v = np.asarray(v, float)
    r = np.empty(len(v))
    r[np.argsort(v)] = np.arange(len(v))
    return r


def spearman(a, b):
    ra, rb = _ranks(a), _ranks(b)
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float('nan')
    return float(np.corrcoef(ra, rb)[0, 1])


USE_STATE = {'proposed_state_incremental': True,
             'official_qnehvi_same_state': True,
             'proposed_without_state': False,
             'proposed_without_incremental_cost': True,
             'scalarized_bo': False,
             'random': False}
USE_COST = {'proposed_state_incremental': True,
            'official_qnehvi_same_state': False,
            'proposed_without_state': True,
            'proposed_without_incremental_cost': False,
            'scalarized_bo': False,
            'random': False}


class ProductionSearcher:
    """Cross-state searcher. Observation unit = (config, state); one GP over
    all units (state bit on/off IS the use_state ablation, evaluated in this
    loop); state-aware candidates are scored per state and averaged,
    state-blind pooled; the incremental divisor uses the full-identity
    predictor per state (identical information for every method)."""

    def __init__(self, method, all_configs, task_uids, rng_seed=42):
        self.method = method
        self.rng = np.random.default_rng(rng_seed)
        self.configs = all_configs
        self.cfg_by_id = {c['id']: c for c in all_configs}
        self.use_state = USE_STATE[method]
        self.use_cost = USE_COST[method]
        self.predictor = CacheIdentityPredictor(task_uids)
        self.observations = []
        self.revealed_ids = set()
        self.predictions = []
        self.n_cost_preds = 0
        self.n_gp_calls = 0
        self.acquisition_scores = []
        dep = np.array([deployment_cost(c) for c in all_configs])
        self.Cmax, self.Lmax = dep.max(), dep.max() / 1000.0

    def _feats(self, cfg, state):
        bit = (1.0 if state == 'fault30' else 0.0) if self.use_state else None
        return extract_features(cfg, bit)

    def _obs_units(self):
        X = np.array([self._feats(self.cfg_by_id[o['config_id']], o['state'])
                      for o in self.observations])
        y = np.array([o['Q'] for o in self.observations])
        C = np.array([o['C_norm'] for o in self.observations])
        L = np.array([o['L_norm'] for o in self.observations])
        return X, y, C, L

    def _record_predictions(self, pick):
        """Record full-identity predictions for the chosen config BEFORE any
        register, on every selection path (including random)."""
        cfg = self.cfg_by_id[pick]
        for st in STATES:
            pred = self.predictor.predict(cfg, st)
            self.predictions.append(dict(cid=pick, state=st,
                                         per_task=pred['per_task'],
                                         est_new_tokens=pred['est_new_tokens']))

    def select(self, candidates):
        unrevealed = [c for c in candidates if c['id'] not in self.revealed_ids]
        if not unrevealed:
            return candidates[0]['id']
        if len(self.observations) < 2 * len(STATES) or self.method == 'random':
            pick = unrevealed[int(self.rng.integers(len(unrevealed)))]['id']
            self._record_predictions(pick)
            return pick

        X_tr, y_tr, obs_C, obs_L = self._obs_units()
        un_cfgs = [self.cfg_by_id[c['id']] for c in unrevealed]
        un_ids = [c['id'] for c in unrevealed]
        self.n_cost_preds += 1

        def cand_arrays(state):
            X_te = np.array([self._feats(c, state) for c in un_cfgs])
            dep = np.array([deployment_cost(c) for c in un_cfgs])
            return X_te, 1 - dep / self.Cmax, 1 - dep / self.Cmax

        div = np.mean([np.array([self.predictor.predict(c, st)['est_new_tokens']
                                 for c in un_cfgs]) / self.Cmax
                       for st in STATES], axis=0)

        self.n_gp_calls += 1
        if self.method == 'scalarized_bo':
            weights = [(0.6, 0.2, 0.2), (0.4, 0.3, 0.3),
                       (1/3, 1/3, 1/3), (0.2, 0.4, 0.4)]
            w = weights[len(self.observations) % len(weights)]
            gp = JointPosteriorGP(X_tr, y_tr)
            X_te, cand_C, cand_L = cand_arrays(STATES[0])  # state-blind features
            mu = gp.joint_posterior(X_te)[0]
            scores = w[0] * mu + w[1] * cand_C + w[2] * cand_L
            self.acquisition_scores.append({'pooled': scores.tolist()})
        elif self.use_state:
            per_state = {}
            for st in STATES:
                idx = [i for i, o in enumerate(self.observations) if o['state'] == st]
                X_te, cand_C, cand_L = cand_arrays(st)
                per_state[st] = botorch_qnehvi_scores(
                    X_tr[idx], y_tr[idx], X_te, obs_C[idx], obs_L[idx],
                    cand_C, cand_L, n_mc=64,
                    seed=10000 + 13 * len(self.observations) + STATES.index(st))
            self.acquisition_scores.append({st: per_state[st].tolist()
                                            for st in STATES})
            scores = np.mean([per_state[st] for st in STATES], axis=0)
        else:
            X_te, cand_C, cand_L = cand_arrays(STATES[0])
            scores = botorch_qnehvi_scores(X_tr, y_tr, X_te, obs_C, obs_L,
                                           cand_C, cand_L, n_mc=64,
                                           seed=10000 + 13 * len(self.observations))
            self.acquisition_scores.append({'pooled': scores.tolist()})

        if self.use_cost:
            scores = np.asarray(scores) / (div + 1e-9)
        pick = un_ids[int(np.argmax(scores))]
        self._record_predictions(pick)
        return pick

    def observe_evaluator_result(self, result):
        cid = result['config_id']
        cfg = self.cfg_by_id[cid]
        state = result.get('state', 'clean')
        self.revealed_ids.add(cid)
        self.predictor.register(cfg, state)
        self.observations.append(dict(
            config_id=cid, state=state,
            Q=result['objectives']['Q'],
            C_actual=result['objectives']['C'],
            L_actual=result['objectives']['L'],
            C_norm=max(0.0, 1 - result['objectives']['C'] / self.Cmax),
            L_norm=max(0.0, 1 - result['objectives']['L'] / self.Lmax)))


# ============ output-coupled, model-tagged stub chain ============
STUB_MULT = {'medium': 0.8, 'large': 1.2, 'coder': 1.0}
EXPR_BY_MODEL = {'medium': 'v0 + v1', 'large': 'v0+v1', 'coder': 'v0 + v1'}


def _usage(model, prompt_toks, base_completion):
    comp = int(base_completion * STUB_MULT[model])
    return dict(prompt_tokens=prompt_toks, completion_tokens=comp,
                total_tokens=prompt_toks + comp)


def dispatch_correct(model, prompt):
    pl = prompt.lower()
    if 'read the financial' in pl:
        # e-node: extract the number from its own REPORT section (task-specific);
        # evidence carries a model tag -> different models emit different fact
        # JSON -> downstream prompts inherit exact model-chain identity
        report = pl.split('report:', 1)[1]
        m = re.search(r'(\d+(?:\.\d+)?)', report)
        val = float(m.group(1))
        return dict(status='delivered',
                    answer=json.dumps({'facts': [dict(value=val, evidence=f'{model}-extract')]}),
                    usage=_usage(model, 500, 200))
    if 'choose the arithmetic' in pl:
        return dict(status='delivered',
                    answer=json.dumps({'expression': EXPR_BY_MODEL[model]}),
                    usage=_usage(model, 150, 50))
    if 'you are verifying' in pl:
        # v-node: recompute from the prompt's own FACTS + PROPOSED EXPRESSION —
        # output-coupled, so an r corruption propagates to v's answer and Q
        try:
            facts = json.loads(re.search(r'FACTS: (\[.*?\])\n', prompt).group(1))
            expr = re.search(r'PROPOSED EXPRESSION: (.+)', prompt).group(1).strip()
            e = expr
            for i, f in enumerate(facts):
                e = re.sub(rf'\bv{i}\b', repr(float(f['value'])), e)
            value = eval(e, {'__builtins__': {}})
            return dict(status='delivered', answer=json.dumps({'value': value}),
                        usage=_usage(model, 70, 30))
        except Exception:
            return dict(status='delivered', answer='{"value": null}',
                        usage=_usage(model, 70, 30))
    raise AssertionError('unroutable prompt: ' + pl[:80])


def make_panel():
    """2-task panel; fault30 corrupts r on task 1 and empties e2 facts on task 2."""
    t1 = make_task()
    t2 = dict(t1, uid='cross-state-panel-uid-2', question='What is 2.5 + 1.5?',
              derivation='2.5+1.5', answer=4.0,
              ctx_table='TABLE: | val | 2.5 |', ctx_text='PASSAGES: value is 1.5')
    return [t1, t2]


def fault30_panel(panel):
    # t1: detectable r corruption (references missing fact v9 -> value_of errors
    # -> output-consistency detector fires; a CONSISTENT-but-wrong corruption
    # like v0*v1 legitimately evades the detector and scores only against gold —
    # realistic, but it would not exercise the recovery paths under test here).
    # t2: e2 emits no facts -> r/v chain unresolved -> detected.
    return {panel[0]['uid']: ('r', '{"expression": "v0*v9"}'),
            panel[1]['uid']: ('e2', '{"facts": []}')}


def make_pipeline(tmp_path, panel):
    Path(tmp_path).mkdir(parents=True, exist_ok=True)
    budget = Budget(tmp_path, dict(
        new_request_attempts=10000, new_total_tokens=81920000,
        request_token_reservation=8192, max_output_tokens=512,
        wall_seconds=3600, logical_calls_per_task_config_state=12))
    ex = MeteredExecutor(tmp_path, budget, dispatch_correct, lambda m: None,
                         dict(medium='m', large='l', coder='c'))
    return JointEvaluator(ex, Ledger(), panel)


def parse_trajectory(traj_path):
    """Actual planned-node outcomes {(scope, cid, uid, node): 'hit'/'new'} and
    the recovery-call count.

    TRAJECTORY records embed scope/cid in event_id='{scope}:{cid}:{key}'. Keys:
    planned base calls are 5-part f30:{topo}:{fam=base}:{node}:{uid}; recovery
    reroutes carry a 6th kind field; FULL replay uses fam='replay'."""
    planned, n_recovery = {}, 0
    for line in Path(traj_path).read_text().splitlines():
        rec = json.loads(line)
        state, cid, key = rec['event_id'].split(':', 2)
        parts = key.split(':')
        fam, node = parts[2], parts[3]
        is_planned = len(parts) == 5 and fam == 'base'
        if not is_planned:
            n_recovery += 1
            continue
        k = (state, cid, parts[4], node)
        if k not in planned:
            planned[k] = 'hit' if 'alias_of' in rec else 'new'
    return planned, n_recovery


def run():
    checks = {}
    sp = space()
    panel = make_panel()
    task_uids = [t['uid'] for t in panel]
    faults30 = fault30_panel(panel)
    states = [('clean', {}), ('fault30', faults30)]
    tmp = Path(tempfile.mkdtemp())

    # ---- predictor structural checks (the reviewed counter-examples) ----
    pred = CacheIdentityPredictor(task_uids)
    c0 = sp[0]
    pred.register(c0, 'clean')
    p_repeat = pred.predict(c0, 'clean')['per_task'][task_uids[0]]
    checks['cp_exact_repeat_all_hit'] = all(v == 'hit' for v in p_repeat.values())
    c_diff_r = next(c for c in sp if c['X']['e1'] == c0['X']['e1']
                    and c['X']['e2'] == c0['X']['e2']
                    and c['X']['r'] != c0['X']['r'] and c['Z'] == 'NONE')
    p_dr = pred.predict(c_diff_r, 'clean')['per_task'][task_uids[0]]
    checks['cp_same_e_new_r_charged'] = (p_dr['e1'] == 'hit' and p_dr['e2'] == 'hit'
                                         and p_dr['r'] == 'new')
    c_diff_v = next(c for c in sp if c['X']['e1'] == c0['X']['e1']
                    and c['X']['e2'] == c0['X']['e2'] and c['X']['r'] == c0['X']['r']
                    and c['X']['v'] != c0['X']['v'] and c['Z'] == 'NONE')
    p_dv = pred.predict(c_diff_v, 'clean')['per_task'][task_uids[0]]
    checks['cp_r_chain_new_v_charged'] = (p_dv['r'] == 'hit' and p_dv['v'] == 'new')
    p_f30 = pred.predict(c0, 'fault30')['per_task'][task_uids[0]]
    checks['cp_scope_isolated'] = all(v == 'new' for v in p_f30.values())
    c_local = next(c for c in sp if c['Z'] == 'LOCAL'
                   and (c['X']['e1'], c['X']['e2'], c['X']['r'], c['X']['v'])
                   == (c0['X']['e1'], c0['X']['e2'], c0['X']['r'], c0['X']['v']))
    checks['cp_recovery_conditional'] = (
        pred.predict(c_local, 'fault30')['est_new_tokens']
        > pred.predict(c_local, 'clean')['est_new_tokens'])

    # ---- cross-state closed loop, all 6 methods, same pipeline ----
    methods = ['random', 'scalarized_bo', 'official_qnehvi_same_state',
               'proposed_state_incremental', 'proposed_without_state',
               'proposed_without_incremental_cost']

    import random as stdlib_random
    method_data, searchers = {}, {}
    pooled_act = {}
    for method in methods:
        mdir = tmp / f'x_{method}'
        evaluator = make_pipeline(mdir, panel)
        session = SearchSession(evaluator, method, max_configurations=5)
        searcher = ProductionSearcher(method, sp, task_uids, rng_seed=42)
        searchers[method] = searcher

        init_ids = stdlib_random.Random(42).sample([c['id'] for c in sp], 2)
        for cid in init_ids:
            for r in session.step(lambda c, o, cid=cid: cid, states):
                searcher.observe_evaluator_result(r)
        picks = list(init_ids)
        while len(session.selected) < 5:
            try:
                results = session.step(lambda c, o, s=searcher: s.select(c), states)
                for r in results:
                    searcher.observe_evaluator_result(r)
                picks.append(results[0]['config_id'])
            except (StopRun, ValueError):
                break

        actual, recovery_calls = parse_trajectory(mdir / 'TRAJECTORY.jsonl')
        rows = []
        for pr in searcher.predictions:
            for uid, nodes in pr['per_task'].items():
                for nd, flag in nodes.items():
                    rows.append((pr['state'], uid, nd, flag,
                                 actual.get((pr['state'], pr['cid'], uid, nd))))
        n_ph = sum(1 for r in rows if r[3] == 'hit')
        n_ph_ah = sum(1 for r in rows if r[3] == 'hit' and r[4] == 'hit')
        n_ah = sum(1 for r in rows if r[4] == 'hit')
        precision = n_ph_ah / n_ph if n_ph else float('nan')
        recall = n_ph_ah / n_ah if n_ah else float('nan')
        per_node_recall = {}
        for nd in NODES:
            ah = [r for r in rows if r[2] == nd and r[4] == 'hit']
            ph_ah = [r for r in rows if r[2] == nd and r[3] == 'hit' and r[4] == 'hit']
            per_node_recall[nd] = (len(ph_ah) / len(ah)) if ah else float('nan')

        last = searcher.acquisition_scores[-1] if searcher.acquisition_scores else {}
        score_stats = {}
        for st, arr in last.items():
            a = np.array(arr)
            score_stats[st] = dict(n=len(a), distinct=int(len(set(np.round(a, 10)))),
                                   nonzero=int(np.sum(a > 1e-12)),
                                   std=float(np.std(a)))

        method_data[method] = dict(
            n_selected=len(session.selected), picks=picks,
            n_observations=len(searcher.observations),
            states_covered=sorted({o['state'] for o in searcher.observations}),
            Q_by_state={st: [o['Q'] for o in searcher.observations if o['state'] == st]
                        for st in STATES},
            C_by_state={st: [round(o['C_actual'], 1) for o in searcher.observations
                             if o['state'] == st] for st in STATES},
            n_gp_calls=searcher.n_gp_calls, n_cost_preds=searcher.n_cost_preds,
            use_state=searcher.use_state, use_cost=searcher.use_cost,
            cache_precision=precision, cache_recall=recall,
            cache_recall_per_node=per_node_recall,
            n_prediction_rows=len(rows), n_recovery_calls=recovery_calls,
            last_round_scores=score_stats)
        for o in searcher.observations:
            pooled_act[(o['config_id'], o['state'])] = o['C_actual']

    # ---- cross-state loop checks ----
    checks['x_all_methods_complete'] = all(
        v['n_selected'] == 5 for v in method_data.values())
    checks['x_both_states_per_selection'] = all(
        v['n_observations'] == 10 and v['states_covered'] == ['clean', 'fault30']
        for v in method_data.values())
    qnehvi = method_data['official_qnehvi_same_state']
    checks['x_fault30_q_z_dependent'] = (
        len(set(qnehvi['Q_by_state']['fault30'])) > 1
        and len(set(qnehvi['Q_by_state']['clean'])) == 1)
    for st in ('clean', 'fault30'):
        s = qnehvi['last_round_scores'].get(st, {})
        checks[f'x_scores_nondegen_{st}'] = (
            s.get('distinct', 0) > 1 and s.get('nonzero', 0) > 0
            and s.get('std', 0) > 1e-10)
    aware = method_data['proposed_state_incremental']['picks']
    blind = method_data['proposed_without_state']['picks']
    checks['x_state_ablation_diverges_in_loop'] = aware != blind

    # state-blind label invariance at a real decision point (after 4 selections)
    blind_s = searchers['proposed_without_state']
    obs8 = blind_s.observations[:8]
    revealed4 = {o['config_id'] for o in obs8}
    cands4 = [dict(c) for c in sp if c['id'] not in revealed4]

    def make_twin(swap):
        tw = ProductionSearcher('proposed_without_state', sp, task_uids, rng_seed=42)
        tw.observations = [
            dict(o, state=('clean' if o['state'] == 'fault30' else 'fault30'))
            if swap else dict(o) for o in obs8]
        tw.revealed_ids = set(revealed4)
        for cid in revealed4:
            for st in STATES:
                tw.predictor.register(tw.cfg_by_id[cid], st)
        return tw

    checks['x_state_blind_label_invariant'] = (
        make_twin(False).select(cands4) == make_twin(True).select(cands4))

    # ---- cache prediction vs executor ground truth ----
    # Precision MUST be exactly 1.0: a predicted hit is a guaranteed identity
    # match, so the incremental estimate never underestimates new search tokens
    # (budget-safe direction). Recall < 1 is expected and conservative: the
    # executor's cache is also populated by recovery-driven executions
    # (v/r escalation, FULL replay chains) whose firing depends on outputs and
    # is NOT knowable inside the searcher's information boundary — those hits
    # are unpredicted and charged as new. Recall is measured and attributed.
    checks['x_cache_precision_1'] = all(
        v['cache_precision'] == 1.0 for v in method_data.values())
    checks['x_cache_recall_measured'] = all(
        0.0 <= v['cache_recall'] <= 1.0 for v in method_data.values())

    # ---- calibration: deployment estimate vs actual C (both states pooled) ----
    uniq = list(pooled_act)
    est = [deployment_cost(next(c for c in sp if c['id'] == i)) for i, _ in uniq]
    act = [pooled_act[k] for k in uniq]
    rho = spearman(est, act)
    checks['x_calibration_rank_corr_positive'] = (not np.isnan(rho)) and rho > 0.3

    all_pass = all(v for v in checks.values() if isinstance(v, bool))
    results = dict(checks=checks, all_pass=all_pass,
                   calibration=dict(spearman=rho, n_units=len(uniq)),
                   recovery_calibration=dict(
                       params=RECOVERY_FIRE_E,
                       note='E[new recovery tokens] = overhead x P_fire(state), '
                            'frozen; measured recovery-call counts reported per method'),
                   cache_identity_rule=dict(
                       e='(node, model) — prompt depends only on task+node',
                       r='(m_e1, m_e2, m_r) — prompt consumes e outputs; planned '
                         'r runs before any recovery',
                       v='(m_e1, m_e2, m_r, m_v, Z) — prompt consumes facts and r '
                         'output; Z-conditioned because e-node faults are rerouted '
                         'at extraction stage, so v may consume recovered facts',
                       scope='state scopes are separate caches (executor identity '
                             'includes scope)'),
                   method_data=method_data,
                   notes=['GAP-1 fixed: full identity chain; predicted hits '
                          'verified against TRAJECTORY.jsonl (precision must be 1.0)',
                          'GAP-2 fixed: same loop evaluates clean+fault30 with a real '
                          'fault panel; state ablation inside this loop',
                          'GAP-3: evaluated units use ACTUAL C/L; candidates frozen '
                          'ex-ante predictions; identical boundary for all methods'])
    (OUT / 'TRACK_B_EVIDENCE.json').write_text(json.dumps(results, indent=1, default=str))
    print(json.dumps(checks, indent=1))
    print(json.dumps({m: dict(sel=v['n_selected'],
                              prec=v['cache_precision'], rec=v['cache_recall'],
                              Qf30=v['Q_by_state']['fault30'],
                              nrec=v['n_recovery_calls'])
                      for m, v in method_data.items()}, indent=1))
    print('ALL PASS' if all_pass else 'FAIL PRESENT')
    return all_pass


if __name__ == '__main__':
    run()
