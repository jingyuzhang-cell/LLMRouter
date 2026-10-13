"""Fair-comparison strategies over a replay world seeded ONLY by real
observations, for joint action a = (Z, R, pi, theta).

Two DD variants (operator ruling 2026-10-13, information boundary):

  DD-Oracle  DIAGNOSTIC ONLY. Reads real same-sample candidate
             outcomes before choosing — information an online
             scheduler cannot have. Its numbers are offline
             constructions, NOT performance evidence vs Fixed.
  DD-Online  Honest variant. Decisions use ONLY leave-one-sample-out
             priors (observations on OTHER samples), the theta
             support table, the current sample's own fault feedback,
             and remaining budget. Same-sample candidate outcomes are
             never consulted pre-choice; real outcomes are used only
             for post-hoc settlement.

Two knowledge stages:
  Stage A  observation pool = original FE paired runs only
           (pre-Phase-4 knowledge).
  Stage B  pool additionally includes the 8 Phase-4 parameter-recovery
           cells (FE3/FE4 only; using FE4's cell to inform FE3's
           decision is cross-sample LOO — legitimate; the reverse
           likewise).

Honesty rules: quality credit ONLY from real observations of the
same (sample, model, theta-bucket); UNOBSERVED actions get zero
credit; historical different-prompt calls are discounted priors,
never settlement.

Run: python3 -m deadline_reward_v1.recovery_strategies
Zero real model calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from deadline_reward_v1 import theta_actions
from deadline_reward_v1.contract_fault import F_TRUNCATED, classify_entry
from deadline_reward_v1.theta_actions import (
    DEFAULT_THETA, REAL_OUTCOME_ANCHORS, budget_reservation,
    enumerate_legal_thetas, theta_legal)

HERE = Path(__file__).resolve().parent
FE_ORIG = HERE / 'fe_screening_runs' / 'fe_20261013_211741' / 'FE_LEDGER.jsonl'
FE_REC = sorted((HERE / 'fe_screening_runs').glob(
    'fe_recovery_*/FE_LEDGER.jsonl'))[-1]
PR4_LEDGER = sorted((HERE / 'fe_screening_runs').glob(
    'param_recovery_*/PR_LEDGER.jsonl'))[-1]
PR4_RESULTS = HERE / 'PARAM_RECOVERY_RESULTS.json'
SAMPLES = json.loads((HERE / 'FACT_EXTRACTION_SAMPLES_V2.json').read_text())
RATES = json.loads(
    (HERE / 'REVERSE_ENGINEERED_RATES_V2.json').read_text())['rates']

MODEL_MENU = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']
LEDGER_MODEL_IDS = {'glm53': 'GLM-5.3', 'glm53flash': 'GLM-5.3-Flash',
                    'deepseek': 'deepseek-flash', 'qwen': 'qwen-plus'}
RATE_KEYS = {'deepseek-flash': 'deepseek_flash', 'qwen-plus': 'qwen_plus'}

SS_TUNED_THETA = {
    'GLM-5.3': dict(DEFAULT_THETA, reasoning_effort='low',
                    max_tokens=8192),
    'GLM-5.3-Flash': dict(DEFAULT_THETA, reasoning_effort='low',
                          max_tokens=8192),
    'deepseek-flash': dict(DEFAULT_THETA, thinking='disabled'),
    'qwen-plus': dict(DEFAULT_THETA),
}
FIXED_RULE = dict(retry_theta='first_legal_repair',
                  fallback_switch='qwen-plus')

DAG_EDGES = {'fact_extraction': ['timeline', 'entity_relations'],
             'timeline': ['cross_verification'],
             'entity_relations': ['cross_verification'],
             'cross_verification': []}


def downstream_of(node: str) -> set:
    seen, stack = set(), [node]
    while stack:
        n = stack.pop()
        for m in DAG_EDGES.get(n, []):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def closure_required(failed_node: str, executed: set) -> set:
    return {failed_node} | (downstream_of(failed_node) & executed)


def bucket_of(theta: dict) -> str:
    """Canonical theta bucket: DEFAULT merged with non-None overrides."""
    full = dict(DEFAULT_THETA)
    full.update({k: v for k, v in (theta or {}).items()
                 if v is not None})
    return json.dumps(full, sort_keys=True)


BUCKET_DEFAULT = bucket_of(DEFAULT_THETA)


def _strict(text) -> bool:
    if not text or not text.strip():
        return False
    c = text.strip()
    if c.startswith('```'):
        parts = c.split('\n', 1)
        if len(parts) == 2:
            c = parts[1].rsplit('```', 1)[0].strip()
    try:
        json.loads(c)
        return True
    except json.JSONDecodeError:
        return False


# ---- observation pools ----------------------------------------------------
def load_fe_pool() -> Dict[tuple, dict]:
    """Original FE paired runs (default theta only). fmt/recall are the
    measured values (FE3/4/5 Silver; FE1/FE2 recall None)."""
    recall = {  # measured: qwen full-output; thinking models 0 (empty)
        ('FE3', 'qwen-plus'): 6 / 17, ('FE4', 'qwen-plus'): 2 / 4,
        ('FE5', 'qwen-plus'): 1.0}
    pool = {}
    for path in (FE_ORIG, FE_REC):
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e['status'] != 'delivered':
                continue
            model = LEDGER_MODEL_IDS.get(e['model_key'], e['model_id'])
            sid = e['sample_id']
            fmt = 1.0 if (model == 'qwen-plus'
                          and _strict(e['answer'])) else 0.0
            pool[(sid, model, BUCKET_DEFAULT)] = dict(
                answer=e['answer'], finish_reason=e.get('finish_reason'),
                tokens_in=e['usage']['prompt_tokens'],
                tokens_out=e['usage']['completion_tokens'],
                cash_cny=e.get('cash_cny', 0.0),
                latency_s=e['latency_s'],
                fmt=fmt, recall=recall.get((sid, model)))
    return pool


def load_pr4_pool() -> Dict[tuple, dict]:
    """Phase-4 parameter-recovery cells (FE3/FE4, real observations
    under repaired thetas)."""
    res = {r['cell']: r for r in
           json.loads(PR4_RESULTS.read_text())['results']}
    pool = {}
    for line in PR4_LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        r = res[e['cell']]
        rec = (r['recall_hit'] / r['recall_total']
               if r['recall_hit'] is not None and r['recall_total']
               else None)
        pool[(e['sample'], e['model_id'], bucket_of(e['theta']))] = dict(
            answer=e['answer'], finish_reason=e['finish_reason'],
            tokens_in=e['usage']['prompt_tokens'],
            tokens_out=e['usage']['completion_tokens'],
            cash_cny=e['cash_cny'], latency_s=e['latency_s'],
            fmt=1.0 if (r['json_ok'] and r['complete']) else 0.0,
            recall=rec)
    return pool


class ReplayWorld:
    """Settles actions from the real observation pool of its stage;
    anything else is an UNOBSERVED proposal with no quality credit."""

    def __init__(self, stage: str):
        self.stage = stage
        self.obs = load_fe_pool()
        if stage == 'B':
            self.obs.update(load_pr4_pool())
        self.audit: List[dict] = []

    def outcome_for(self, sample_id: str, model_id: str, theta: dict,
                    prompt_tokens: int) -> dict:
        key = (sample_id, model_id, bucket_of(theta))
        if key in self.obs:
            e = self.obs[key]
            out = dict(status='OBSERVED', **e)
        else:
            res = budget_reservation(model_id, theta, prompt_tokens)
            out = dict(status='UNOBSERVED', answer=None,
                       finish_reason=None, cash_cny=None,
                       latency_s=None, fmt=0.0, recall=None,
                       tokens_in=res['tokens_in'],
                       tokens_out=res['tokens_out_reserved'],
                       note='unobserved proposal; NO quality credit')
        self.audit.append(dict(sample=sample_id, model=model_id,
                               bucket=key[2], status=out['status'],
                               tokens_in=out['tokens_in'],
                               tokens_out=out['tokens_out'],
                               cash_cny=out.get('cash_cny')))
        return out


# ---- shared budget & scorer ----------------------------------------------
class Budget:
    def __init__(self, max_attempts=40, max_tokens=400000,
                 max_cash_cny=2.0, max_wall_s=3600.0):
        self.caps = dict(max_attempts=max_attempts, max_tokens=max_tokens,
                         max_cash_cny=max_cash_cny, max_wall_s=max_wall_s)
        self.attempts = 0
        self.tokens = 0
        self.cash = 0.0
        self.wall = 0.0

    def charge(self, o: dict, model_id: str):
        self.attempts += 1
        self.tokens += o['tokens_in'] + o['tokens_out']
        cash = o.get('cash_cny')
        if cash is None:
            rk = RATE_KEYS.get(model_id)
            r = RATES[rk] if rk else None
            cash = ((o['tokens_in'] * r['input_cny_per_mtok']
                     + o['tokens_out'] * r['output_cny_per_mtok']) / 1e6
                    if r else 0.0)
        self.cash += cash
        self.wall += (o.get('latency_s')
                      or budget_reservation(model_id, DEFAULT_THETA,
                                            0)['latency_s_reserved'])

    def over(self) -> Optional[str]:
        for k, v in (('attempts', self.attempts),
                     ('tokens', self.tokens),
                     ('cash_cny', self.cash), ('wall_s', self.wall)):
            if v > self.caps[f'max_{k}']:
                return k
        return None


def score(outcome: dict) -> dict:
    """Shared scorer: quality credit ONLY from real observations of
    the settled (sample, model, theta-bucket) cell."""
    tokens = outcome['tokens_in'] + outcome['tokens_out']
    if outcome['status'] != 'OBSERVED':
        return dict(quality=0.0, credit='none/unobserved-proposal',
                    cost_cny=outcome.get('cash_cny'), tokens=tokens)
    quality = outcome['fmt'] * outcome['recall'] \
        if outcome.get('recall') is not None else 0.0
    return dict(quality=round(quality, 4),
                credit=f"observed fmt={outcome['fmt']} "
                       f"recall={outcome.get('recall')}",
                cost_cny=outcome.get('cash_cny', 0.0), tokens=tokens)


# ---- strategies -----------------------------------------------------------
class Strategy:
    name = 'BASE'
    planned_model = 'GLM-5.3'

    def __init__(self, world: ReplayWorld, budget: Budget):
        self.world, self.budget = world, budget
        self.log: List[dict] = []

    def _prompt_tokens(self, sample) -> int:
        return max(1, len(sample['evidence_full_text']) // 2)

    def _record(self, sample_id, action, outcome, s, rule=''):
        self.log.append(dict(strategy=self.name, sample=sample_id,
                             action=action, outcome=outcome['status'],
                             rule=rule, **s))


class SSOriginal(Strategy):
    name = 'SS-Original'

    def run_task(self, sample):
        sid = sample['sample_id']
        o = self.world.outcome_for(sid, self.planned_model,
                                   dict(DEFAULT_THETA),
                                   self._prompt_tokens(sample))
        self.budget.charge(o, self.planned_model)
        s = score(o)
        self._record(sid, (self.planned_model, 'default'), o, s)
        return s


class SSTuned(Strategy):
    name = 'SS-Tuned'

    def run_task(self, sample):
        sid = sample['sample_id']
        theta = SS_TUNED_THETA[self.planned_model]
        ok, why = theta_legal(self.planned_model, theta)
        assert ok, f'SS-Tuned emitted illegal theta: {why}'
        o = self.world.outcome_for(sid, self.planned_model, theta,
                                   self._prompt_tokens(sample))
        self.budget.charge(o, self.planned_model)
        s = score(o)
        self._record(sid, (self.planned_model, 'SS_TUNED'), o, s)
        return s


class FixedRecovery(Strategy):
    name = 'Fixed-Recovery'

    def run_task(self, sample):
        sid = sample['sample_id']
        o1 = self.world.outcome_for(sid, self.planned_model,
                                    dict(DEFAULT_THETA),
                                    self._prompt_tokens(sample))
        self.budget.charge(o1, self.planned_model)
        s1 = score(o1)
        self._record(sid, (self.planned_model, 'default'), o1, s1)
        if s1['quality'] > 0:
            return s1
        fault = classify_entry(
            dict(status='delivered', answer=o1.get('answer') or '',
                 finish_reason=o1.get('finish_reason'),
                 usage=dict(completion_tokens=o1['tokens_out']),
                 max_output_tokens=DEFAULT_THETA['max_tokens']))
        if fault['fault'] == F_TRUNCATED:
            repairs = enumerate_legal_thetas(self.planned_model)
            if repairs:
                o2 = self.world.outcome_for(
                    sid, self.planned_model, repairs[0]['theta'],
                    self._prompt_tokens(sample))
                self.budget.charge(o2, self.planned_model)
                s2 = score(o2)
                self._record(sid, (self.planned_model,
                                   f'FIXED:{repairs[0]["repair"]}'),
                             o2, s2, rule='pre-committed rule #1')
                if s2['quality'] > 0:
                    return s2
        target = FIXED_RULE['fallback_switch']
        o3 = self.world.outcome_for(sid, target, dict(DEFAULT_THETA),
                                    self._prompt_tokens(sample))
        self.budget.charge(o3, target)
        s3 = score(o3)
        self._record(sid, (target, 'FIXED:fallback'), o3, s3,
                     rule='pre-committed rule #2')
        return s3


class DDEnhanced(Strategy):
    """ORACLE / DIAGNOSTIC ONLY — same-sample candidate lookups before
    choosing (an online scheduler cannot have this). Not admissible
    as DD-vs-Fixed performance evidence."""
    name = 'DD-Oracle'
    diagnostic_only = True

    def run_task(self, sample):
        sid = sample['sample_id']
        o1 = self.world.outcome_for(sid, self.planned_model,
                                    dict(DEFAULT_THETA),
                                    self._prompt_tokens(sample))
        self.budget.charge(o1, self.planned_model)
        s1 = score(o1)
        self._record(sid, (self.planned_model, 'default'), o1, s1)
        if s1['quality'] > 0:
            return s1
        fault = classify_entry(
            dict(status='delivered', answer=o1.get('answer') or '',
                 finish_reason=o1.get('finish_reason'),
                 usage=dict(completion_tokens=o1['tokens_out']),
                 max_output_tokens=DEFAULT_THETA['max_tokens']))
        cands = []
        for other in MODEL_MENU:
            if other == self.planned_model:
                thetas = [a['theta'] for a in
                          enumerate_legal_thetas(other)]
            else:
                thetas = ([dict(DEFAULT_THETA)] +
                          [a['theta'] for a in
                           enumerate_legal_thetas(other)])
            for th in thetas:
                ok, why = theta_legal(other, th)
                assert ok, f'DD-Oracle emitted illegal theta: {why}'
                probe = self.world.outcome_for(
                    sid, other, th, self._prompt_tokens(sample))
                s = score(probe)
                bonus = 0.1 if probe['status'] == 'OBSERVED' else 0.0
                util = round(s['quality'] + bonus
                             - 0.001 * s['tokens'] / 100.0, 6)
                cands.append(dict(model=other, theta=th, util=util,
                                  probe=probe, sc=s))
        cands.sort(key=lambda c: -c['util'])
        best = cands[0]
        self.budget.charge(best['probe'], best['model'])
        assert closure_required('fact_extraction', set()) == \
            {'fact_extraction'}
        self._record(sid, (best['model'], bucket_of(best['theta'])),
                     best['probe'], best['sc'],
                     rule=f'ORACLE fault={fault["fault"]} '
                          f'util={best["util"]}')
        return best['sc']


class DDOnline(Strategy):
    """Honest online DD: LOO cross-sample priors + support table +
    own fault feedback + budget. Settlement post-choice only."""
    name = 'DD-Online'

    def _prior(self, model, theta, sid):
        bucket = bucket_of(theta)
        obs = [o for (s, m, b), o in self.world.obs.items()
               if m == model and b == bucket and s != sid]
        if obs:
            pr = sum(o['fmt'] for o in obs) / len(obs)
            recs = [o['recall'] for o in obs
                    if o.get('recall') is not None]
            mr = sum(recs) / len(recs) if recs else 0.35
            return pr, mr, f'LOO cross-sample n={len(obs)}'
        # prior-only anchors, discounted (different prompts)
        if (model == 'deepseek-flash'
                and theta.get('thinking') == 'disabled'):
            a = REAL_OUTCOME_ANCHORS['deepseek-flash|thinking=disabled']
            pr = 0.5 * a['strict_json'] / a['n']  # 17/17 discounted
            return pr, 0.35, 'historical prior (discounted)'
        if theta == dict(DEFAULT_THETA):
            a = REAL_OUTCOME_ANCHORS.get(f'{model}|default')
            if a and a.get('strict_json') == 0:
                return 0.15, 0.35, 'mechanism-family (default fails)'
        return 0.5, 0.35, 'uninformed'

    def run_task(self, sample):
        sid = sample['sample_id']
        o1 = self.world.outcome_for(sid, self.planned_model,
                                    dict(DEFAULT_THETA),
                                    self._prompt_tokens(sample))
        self.budget.charge(o1, self.planned_model)
        s1 = score(o1)
        self._record(sid, (self.planned_model, 'default'), o1, s1)
        if s1['quality'] > 0:
            return s1
        fault = classify_entry(
            dict(status='delivered', answer=o1.get('answer') or '',
                 finish_reason=o1.get('finish_reason'),
                 usage=dict(completion_tokens=o1['tokens_out']),
                 max_output_tokens=DEFAULT_THETA['max_tokens']))
        budget_cut = fault['fault'] == F_TRUNCATED
        cands = []
        for other in MODEL_MENU:
            if other == self.planned_model:
                thetas = [a['theta'] for a in
                          enumerate_legal_thetas(other)]
            else:
                thetas = ([dict(DEFAULT_THETA)] +
                          [a['theta'] for a in
                           enumerate_legal_thetas(other)])
            for th in thetas:
                ok, why = theta_legal(other, th)
                assert ok, f'DD-Online emitted illegal theta: {why}'
                pr, mr, src = self._prior(other, th, sid)
                res = budget_reservation(other, th,
                                         self._prompt_tokens(sample))
                cost = (res['tokens_in']
                        + res['tokens_out_reserved']) / 1000.0
                align = 0.05 if (
                    (budget_cut and th != dict(DEFAULT_THETA))
                    or (not budget_cut
                        and th == dict(DEFAULT_THETA))) else 0.0
                util = round(pr * mr + align - 0.001 * cost, 6)
                cands.append(dict(model=other, theta=th, util=util,
                                  prior=(round(pr, 3), round(mr, 3)),
                                  src=src))
        cands.sort(key=lambda c: -c['util'])
        best = cands[0]
        settle = self.world.outcome_for(sid, best['model'],
                                        best['theta'],
                                        self._prompt_tokens(sample))
        self.budget.charge(settle, best['model'])
        s = score(settle)
        assert closure_required('fact_extraction', set()) == \
            {'fact_extraction'}
        self._record(sid, (best['model'], bucket_of(best['theta'])),
                     settle, s,
                     rule=f'ONLINE fault={fault["fault"]} prior='
                          f'{best["prior"]} src={best["src"]} '
                          f'util={best["util"]}')
        return s


STRATEGIES = (SSOriginal, SSTuned, FixedRecovery, DDEnhanced, DDOnline)
LABELS = {'SS-Original': 'baseline (replay of real failures)',
          'SS-Tuned': 'fair tuned-static baseline',
          'Fixed-Recovery': 'pre-committed rule',
          'DD-Oracle': 'DIAGNOSTIC ONLY (oracle leak, labeled)',
          'DD-Online': 'honest online DD (LOO priors)'}


def run_stage(stage: str) -> dict:
    report = dict(
        stage=stage,
        knowledge_pool='original FE paired runs'
        if stage == 'A' else
        'original FE + Phase-4 parameter-recovery cells (FE3/FE4)',
        samples=[], summaries={})
    for sample in SAMPLES['samples']:
        row = dict(sample=sample['sample_id'])
        for cls in STRATEGIES:
            world, budget = ReplayWorld(stage), Budget()
            strat = cls(world, budget)
            strat.run_task(sample)
            last = strat.log[-1]
            row[cls.name] = dict(
                quality=last['quality'], credit=last['credit'],
                outcome=last['outcome'], action=last['action'],
                rule=last.get('rule', ''))
            assert budget.over() is None, \
                f'{cls.name} exceeded budget: {budget.over()}'
        report['samples'].append(row)
    for cls in STRATEGIES:
        world, budget = ReplayWorld(stage), Budget()
        strat = cls(world, budget)
        for sample in SAMPLES['samples']:
            strat.run_task(sample)
        report['summaries'][cls.name] = dict(
            total_quality=round(sum(e['quality'] for e in strat.log), 4),
            attempts=budget.attempts, tokens=budget.tokens,
            cash_cny=round(budget.cash, 6),
            unobserved_actions=sum(
                1 for e in strat.log if e['outcome'] == 'UNOBSERVED'),
            label=LABELS[cls.name],
            diagnostic_only=getattr(cls, 'diagnostic_only', False))
    return report


def run_all() -> dict:
    return dict(version='FOUR_STRATEGY_REPLAY_v2',
                zero_model_calls=True,
                fairness=dict(
                    shared_pool=MODEL_MENU,
                    shared_theta_table=(
                        'theta_actions.MODEL_THETA_SUPPORT'),
                    shared_budget=True, shared_scorer=True,
                    fixed_rule=FIXED_RULE,
                    ss_tuned_theta=SS_TUNED_THETA,
                    planned_model='GLM-5.3'),
                information_boundary=dict(
                    dd_oracle='ORACLE/DIAGNOSTIC — reads same-sample '
                              'candidate outcomes pre-choice; NOT '
                              'admissible as DD-vs-Fixed evidence',
                    dd_online='LOO cross-sample priors only; '
                              'settlement post-choice',
                    stages=dict(
                        A='pre-Phase-4 knowledge',
                        B='post-Phase-4 knowledge (cross-sample LOO '
                          'only; FE4 cells inform FE3 and vice versa)')),
                stage_A=run_stage('A'), stage_B=run_stage('B'))


if __name__ == '__main__':
    rep = run_all()
    (HERE / 'FOUR_STRATEGY_REPLAY.json').write_text(
        json.dumps(rep, indent=1, ensure_ascii=False, default=str))
    for stage in ('stage_A', 'stage_B'):
        print(f"== {stage} ({rep[stage]['knowledge_pool']}) ==")
        for name, s in rep[stage]['summaries'].items():
            tag = ' [DIAGNOSTIC-ONLY]' if s['diagnostic_only'] else ''
            print(f"  {name:15s}{tag} q={s['total_quality']:.3f} "
                  f"attempts={s['attempts']} tokens={s['tokens']} "
                  f"cash=CNY{s['cash_cny']:.4f} "
                  f"unobs={s['unobserved_actions']}")
        print('  decisions:')
        for row in rep[stage]['samples']:
            dd = row['DD-Online']
            print(f"    {row['sample']}: DD-Online -> "
                  f"{dd['action'][0]} q={dd['quality']:.3f} "
                  f"[{dd['outcome']}] {dd['rule'][:60]}")
    print('\nzero_model_calls=true')
