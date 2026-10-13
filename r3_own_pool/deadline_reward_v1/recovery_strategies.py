"""Four fair-comparison strategies over a replay world seeded ONLY by
real observations (SS-Original / SS-Tuned / Fixed-Recovery /
DD-Enhanced), for joint action a = (Z, R, pi, theta).

Fairness rules (operator ruling 2026-10-13, Phase 2):
  - all four strategies share the same legal model pool, the
    theta-legality table (theta_actions.MODEL_THETA_SUPPORT), the same
    budget guard and the same scorer;
  - Fixed-Recovery applies a PRE-COMMITTED parameter-repair rule;
  - DD-Enhanced decides recovery scope/model/theta from the observed
    fault feedback at run time;
  - nobody keeps a known-bad config on purpose to manufacture DD's
    win (SS-Tuned exists to remove that confound).

Honesty rules (Phase 3):
  - ReplayWorld settles quality ONLY from real observations of the
    same (sample, model, theta) — the FE paired ledgers. Historical
    calls under different prompts inform PRIORS, never settle quality.
  - Unobserved actions return status=UNOBSERVED with quality=None;
    the scorer gives them NO quality credit (proposals awaiting the
    Phase-4 real parameter experiment, not gains).

Closure rule implemented: R must contain the failed node plus every
downstream node that ALREADY consumed its output. In the FE replay
no downstream node has executed, so R = {failed} is complete.

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
    DEFAULT_THETA, MODEL_THETA_SUPPORT, budget_reservation,
    enumerate_legal_thetas, theta_legal)

HERE = Path(__file__).resolve().parent
FE_ORIG = HERE / 'fe_screening_runs' / 'fe_20261013_211741' / 'FE_LEDGER.jsonl'
FE_REC = sorted((HERE / 'fe_screening_runs').glob(
    'fe_recovery_*/FE_LEDGER.jsonl'))[-1]
SAMPLES = json.loads((HERE / 'FACT_EXTRACTION_SAMPLES_V2.json').read_text())
RATES = json.loads(
    (HERE / 'REVERSE_ENGINEERED_RATES_V2.json').read_text())['rates']

MODEL_MENU = ['GLM-5.3', 'GLM-5.3-Flash', 'deepseek-flash', 'qwen-plus']
LEDGER_MODEL_IDS = {'glm53': 'GLM-5.3', 'glm53flash': 'GLM-5.3-Flash',
                    'deepseek': 'deepseek-flash', 'qwen': 'qwen-plus'}
RATE_KEYS = {'deepseek-flash': 'deepseek_flash', 'qwen-plus': 'qwen_plus'}

# Tuned static theta (SS-Tuned): legal, capability-preserving where
# possible. GLM: reasoning_effort=low + wider budget. deepseek:
# thinking disabled (its only legal intensity control). qwen: default.
SS_TUNED_THETA = {
    'GLM-5.3': dict(DEFAULT_THETA, reasoning_effort='low',
                    max_tokens=8192),
    'GLM-5.3-Flash': dict(DEFAULT_THETA, reasoning_effort='low',
                          max_tokens=8192),
    'deepseek-flash': dict(DEFAULT_THETA, thinking='disabled'),
    'qwen-plus': dict(DEFAULT_THETA),
}

# Fixed-Recovery pre-committed rule (decided BEFORE seeing outcomes):
# on F_TRUNCATED -> retry same model with its first legal theta
# repair; if that record still fails -> switch to qwen-plus default.
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
    """R must contain the failed node plus downstream nodes that
    already consumed its output (M5 rule)."""
    return {failed_node} | (downstream_of(failed_node) & executed)


# ---- observed anchors (measured on the FE paired runs) -------------------
# format: strict-JSON pass on the FE contract (real, 5 calls each)
OBSERVED_FORMAT = {}
for _sid in ('FE1', 'FE2', 'FE3', 'FE4', 'FE5'):
    OBSERVED_FORMAT[(_sid, 'GLM-5.3')] = 0.0
    OBSERVED_FORMAT[(_sid, 'GLM-5.3-Flash')] = 0.0
    OBSERVED_FORMAT[(_sid, 'deepseek-flash')] = 0.0
    OBSERVED_FORMAT[(_sid, 'qwen-plus')] = 1.0
# recall: Silver sets FE3(17)/FE4(4)/FE5(1); FE1/FE2 not evaluable.
# Truncated-model values are diagnostic lower bounds and are NEVER
# given credit because their format factor is 0.
OBSERVED_RECALL = {
    ('FE3', 'GLM-5.3'): 7 / 17, ('FE3', 'GLM-5.3-Flash'): 9 / 17,
    ('FE3', 'deepseek-flash'): 0.0, ('FE3', 'qwen-plus'): 6 / 17,
    ('FE4', 'GLM-5.3'): 2 / 4, ('FE4', 'GLM-5.3-Flash'): 0.0,
    ('FE4', 'deepseek-flash'): 0.0, ('FE4', 'qwen-plus'): 2 / 4,
    ('FE5', 'GLM-5.3'): 1.0, ('FE5', 'GLM-5.3-Flash'): 1.0,
    ('FE5', 'deepseek-flash'): 0.0, ('FE5', 'qwen-plus'): 1.0,
}


def _load_observations() -> Dict[tuple, dict]:
    """Real outcomes keyed by (sample, model, theta_bucket). Only
    'default' (the FE contract) was ever really executed on FE."""
    obs = {}
    for path in (FE_ORIG, FE_REC):
        for line in Path(path).read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if e['status'] != 'delivered':
                continue
            key = (e['sample_id'],
                   LEDGER_MODEL_IDS.get(e['model_key'], e['model_id']),
                   'default')
            obs[key] = dict(
                answer=e['answer'],
                finish_reason=e.get('finish_reason'),
                tokens_in=e['usage']['prompt_tokens'],
                tokens_out=e['usage']['completion_tokens'],
                cash_cny=e.get('cash_cny', 0.0),
                latency_s=e['latency_s'])
    return obs


class ReplayWorld:
    """Settles actions from real observations only; anything else is
    an UNOBSERVED proposal with no quality credit."""

    def __init__(self):
        self.obs = _load_observations()
        self.audit: List[dict] = []

    def outcome_for(self, sample_id: str, model_id: str,
                    theta: dict, prompt_tokens: int) -> dict:
        bucket = 'default' if theta == dict(DEFAULT_THETA) else \
            json.dumps(theta, sort_keys=True)
        key = (sample_id, model_id, bucket)
        entry = dict(sample=sample_id, model=model_id, theta=bucket)
        if key in self.obs:
            e = self.obs[key]
            out = dict(status='OBSERVED', **e)
        else:
            res = budget_reservation(model_id, theta, prompt_tokens)
            out = dict(status='UNOBSERVED', answer=None,
                       finish_reason=None, cash_cny=None,
                       latency_s=None,
                       tokens_in=res['tokens_in'],
                       tokens_out=res['tokens_out_reserved'],
                       note='awaiting Phase-4 real execution; '
                            'NO quality credit')
        self.audit.append({**entry, **{k: out.get(k) for k in
                                       ('status', 'finish_reason',
                                        'tokens_in', 'tokens_out',
                                        'cash_cny')}})
        return out


# ---- shared budget & scorer ----------------------------------------------
class Budget:
    """Charges executed actions: observed at real cost, unobserved
    proposals at full reservation (parameter changes are not free)."""

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
                    if r else 0.0)  # GLM subscription: cash 0
        self.cash += cash
        self.wall += (o.get('latency_s') or
                      budget_reservation(model_id, DEFAULT_THETA,
                                         0)['latency_s_reserved'])

    def over(self) -> Optional[str]:
        checks = (('attempts', self.attempts),
                  ('tokens', self.tokens),
                  ('cash_cny', self.cash),
                  ('wall_s', self.wall))
        for k, v in checks:
            if v > self.caps[f'max_{k}']:
                return k
        return None


def score(outcome: dict, sample_id: str, model_id: str) -> dict:
    """Shared scorer: quality credit ONLY from observed outcomes."""
    tokens = outcome['tokens_in'] + outcome['tokens_out']
    if outcome['status'] != 'OBSERVED':
        return dict(quality=0.0, credit='none/unobserved-proposal',
                    cost_cny=outcome.get('cash_cny'), tokens=tokens)
    fmt = OBSERVED_FORMAT.get((sample_id, model_id), 0.0)
    rec = OBSERVED_RECALL.get((sample_id, model_id))
    quality = fmt * rec if rec is not None else 0.0
    return dict(quality=round(quality, 4),
                credit=f'observed format={fmt} recall={rec}',
                cost_cny=outcome.get('cash_cny', 0.0), tokens=tokens)


# ---- the four strategies -------------------------------------------------
class Strategy:
    name = 'BASE'
    planned_model = 'GLM-5.3'   # natural default (subscription, cash 0)

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
        s = score(o, sid, self.planned_model)
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
        s = score(o, sid, self.planned_model)
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
        s1 = score(o1, sid, self.planned_model)
        self._record(sid, (self.planned_model, 'default'), o1, s1)
        if s1['quality'] > 0:
            return s1
        fault = classify_entry(
            dict(status='delivered', answer=o1.get('answer') or '',
                 finish_reason=o1.get('finish_reason'),
                 usage=dict(completion_tokens=o1['tokens_out']),
                 max_output_tokens=DEFAULT_THETA['max_tokens']))
        if fault['fault'] == F_TRUNCATED:
            # pre-committed rule #1: first legal theta repair
            repairs = enumerate_legal_thetas(self.planned_model)
            if repairs:
                o2 = self.world.outcome_for(
                    sid, self.planned_model, repairs[0]['theta'],
                    self._prompt_tokens(sample))
                self.budget.charge(o2, self.planned_model)
                s2 = score(o2, sid, self.planned_model)
                self._record(sid, (self.planned_model,
                                   f'FIXED:{repairs[0]["repair"]}'),
                             o2, s2, rule='pre-committed rule #1')
                if s2['quality'] > 0:
                    return s2
        # pre-committed rule #2: fallback switch
        target = FIXED_RULE['fallback_switch']
        o3 = self.world.outcome_for(sid, target, dict(DEFAULT_THETA),
                                    self._prompt_tokens(sample))
        self.budget.charge(o3, target)
        s3 = score(o3, sid, target)
        self._record(sid, (target, 'FIXED:fallback'), o3, s3,
                     rule='pre-committed rule #2')
        return s3


class DDEnhanced(Strategy):
    name = 'DD-Enhanced'

    def run_task(self, sample):
        sid = sample['sample_id']
        o1 = self.world.outcome_for(sid, self.planned_model,
                                    dict(DEFAULT_THETA),
                                    self._prompt_tokens(sample))
        self.budget.charge(o1, self.planned_model)
        s1 = score(o1, sid, self.planned_model)
        self._record(sid, (self.planned_model, 'default'), o1, s1)
        if s1['quality'] > 0:
            return s1
        fault = classify_entry(
            dict(status='delivered', answer=o1.get('answer') or '',
                 finish_reason=o1.get('finish_reason'),
                 usage=dict(completion_tokens=o1['tokens_out']),
                 max_output_tokens=DEFAULT_THETA['max_tokens']))
        # candidate evaluation is FREE (ledger lookups / priors); only
        # the CHOSEN action is charged
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
                assert ok, f'DD emitted illegal theta: {why}'
                probe = self.world.outcome_for(
                    sid, other, th, self._prompt_tokens(sample))
                s = score(probe, sid, other)
                observed_bonus = 0.1 if probe['status'] == 'OBSERVED' \
                    else 0.0
                util = round(s['quality'] + observed_bonus
                             - 0.001 * s['tokens'] / 100.0, 6)
                cands.append(dict(model=other, theta=th, util=util,
                                  probe=probe, sc=s))
        cands.sort(key=lambda c: -c['util'])
        best = cands[0]
        self.budget.charge(best['probe'], best['model'])
        # closure: no downstream node executed yet -> R={failed}
        assert closure_required('fact_extraction', set()) == \
            {'fact_extraction'}
        self._record(sid, (best['model'],
                           json.dumps(best['theta'], sort_keys=True)),
                     best['probe'], best['sc'],
                     rule=f'fault={fault["fault"]}; argmax util='
                          f'{best["util"]}')
        return best['sc']


STRATEGIES = (SSOriginal, SSTuned, FixedRecovery, DDEnhanced)


def run_all() -> dict:
    report = dict(
        version='FOUR_STRATEGY_REPLAY_v1', zero_model_calls=True,
        fairness=dict(
            shared_pool=MODEL_MENU,
            shared_theta_table='theta_actions.MODEL_THETA_SUPPORT',
            shared_budget=True, shared_scorer=True,
            fixed_rule=FIXED_RULE, ss_tuned_theta=SS_TUNED_THETA,
            planned_model='GLM-5.3'),
        samples=[], summaries={})
    for sample in SAMPLES['samples']:
        row = dict(sample=sample['sample_id'])
        for cls in STRATEGIES:
            world, budget = ReplayWorld(), Budget()
            strat = cls(world, budget)
            s = strat.run_task(sample)
            last = strat.log[-1]
            row[cls.name] = dict(
                quality=s['quality'], credit=s['credit'],
                outcome=last['outcome'], action=last['action'],
                rule=last.get('rule', ''))
            assert budget.over() is None, \
                f'{cls.name} exceeded budget: {budget.over()}'
        report['samples'].append(row)

    for cls in STRATEGIES:
        world, budget = ReplayWorld(), Budget()
        strat = cls(world, budget)
        for sample in SAMPLES['samples']:
            strat.run_task(sample)
        report['summaries'][cls.name] = dict(
            total_quality=round(sum(e['quality'] for e in strat.log), 4),
            attempts=budget.attempts, tokens=budget.tokens,
            cash_cny=round(budget.cash, 6),
            unobserved_actions=sum(
                1 for e in strat.log if e['outcome'] == 'UNOBSERVED'),
            audit_entries=len(world.audit))
    return report


if __name__ == '__main__':
    rep = run_all()
    (HERE / 'FOUR_STRATEGY_REPLAY.json').write_text(
        json.dumps(rep, indent=1, ensure_ascii=False, default=str))
    for name, s in rep['summaries'].items():
        print(f"{name:16s} quality={s['total_quality']:.3f} "
              f"attempts={s['attempts']} tokens={s['tokens']} "
              f"cash=CNY{s['cash_cny']:.4f} "
              f"unobserved_actions={s['unobserved_actions']}")
    print('\nper-sample final decisions:')
    for row in rep['samples']:
        print(f"  {row['sample']}:")
        for k in ('SS-Original', 'SS-Tuned', 'Fixed-Recovery',
                  'DD-Enhanced'):
            d = row[k]
            print(f"    {k:15s} q={d['quality']:.3f} "
                  f"[{d['outcome']}] {d['action']}")
    print('\nzero_model_calls=true')
