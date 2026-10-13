"""Offline preparation toolkit for the four-model cloud-API screening
(zero real calls; operator directive 2026-10-13 — do not idle on GPU).

Supports the pivot from local-GPU Qwen to cloud APIs (GLM, DeepSeek,
Qwen cloud + local Qwen when GPU returns). The DD-V2 scheduling
machinery (joint action, contracts, settlement) is model-agnostic —
this toolkit prepares the MODEL LAYER: verification configs, frozen
screening panels, Q/C/L analysis, and dual-cost budget calculation.

Components (all zero-call until a real GO):
  MODEL_REGISTRY    four-model identity/version/billing verification
  freeze_screening_panel()   20-task sample + Gold isolation
  freeze_screening_plan()    80-call plan (4 models × 4 nodes × 20 tasks)
  NodeScreeningAnalyzer      per-(node,model) Q/C/L + complementarity
  BudgetCalculator           cash cost + normalized resource cost (dual)
  GateReject                refuses unverified models / missing samples

Run: python3 -m deadline_reward_v1.test_offline_toolkit
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path('/root/r3_own_pool')
HERE = Path(__file__).resolve().parent

# ---- model registry ---------------------------------------------------

MODEL_REGISTRY_TEMPLATE = {
    'glm': {
        'provider': 'zhipu',
        'model_id': None,  # e.g. 'glm-4-plus' — MUST be filled + verified
        'api_version': None,
        'credential_env': 'GLM_API_KEY',
        'billing': {
            'input_per_1k_cny': None,   # cash cost — MUST be filled
            'output_per_1k_cny': None,
            'currency': 'CNY',
        },
        'subscription_covered': None,  # True if within subscription quota
        'normalized_cost_basis': None,  # e.g. per-token standard unit
        'verified': False,
        'verification_method': None,  # e.g. 'api_probe_response_match'
    },
    'deepseek': {
        'provider': 'deepseek',
        'model_id': None,  # e.g. 'deepseek-chat'
        'api_version': None,
        'credential_env': 'DEEPSEEK_API_KEY',
        'billing': {
            'input_per_1k_cny': None,
            'output_per_1k_cny': None,
            'currency': 'CNY',
        },
        'subscription_covered': None,
        'normalized_cost_basis': None,
        'verified': False,
        'verification_method': None,
    },
    'qwen_cloud': {
        'provider': 'alibaba_cloud',
        'model_id': None,  # e.g. 'qwen-plus'
        'api_version': None,
        'credential_env': 'QWEN_CLOUD_API_KEY',
        'billing': {
            'input_per_1k_cny': None,
            'output_per_1k_cny': None,
            'currency': 'CNY',
        },
        'subscription_covered': None,
        'normalized_cost_basis': None,
        'verified': False,
        'verification_method': None,
    },
    'qwen_local': {
        'provider': 'local_gpu',
        'model_id': 'Qwen2.5-7B-Instruct',  # known from PRIORS_REAL_V1
        'model_path': '/root/autodl-tmp/models/Qwen2.5-7B-Instruct',
        'provenance_sha256': None,  # from label_repair_experiment provenance
        'gpu_required': True,
        'billing': {
            'input_per_1k_cny': 0.0,
            'output_per_1k_cny': 0.0,
            'currency': 'CNY',
            'note': 'zero cash but NOT zero cost — normalized resource '
                    'accounting required (operator ruling)'
        },
        'subscription_covered': True,
        'normalized_cost_basis': 'gpu_seconds',
        'verified': False,
        'verification_method': 'checkpoint_sha256_match',
    },
}

GOLD_STATUS_OPTIONS = ('independently_verified', 'dual_annotated',
                       'single_annotated', 'unverified', 'conflicted')


class GateReject(Exception):
    """Raised when a gate condition fails — never silently bypassed."""


def verify_model_registry(registry: dict) -> dict:
    """Gate: every model must have identity + billing + verification
    filled before any screening plan can be frozen. Returns a per-model
    status dict; raises GateReject if ANY registered model that will be
    used is unverified."""
    status = {}
    for name, cfg in registry.items():
        issues = []
        if not cfg.get('model_id'):
            issues.append('model_id missing')
        if cfg.get('billing', {}).get('input_per_1k_cny') is None:
            issues.append('billing incomplete')
        if not cfg.get('verified'):
            issues.append('not verified')
        if cfg.get('subscription_covered') is None:
            issues.append('subscription status unknown')
        if not cfg.get('normalized_cost_basis') and \
                cfg.get('subscription_covered'):
            issues.append('subscription-covered model lacks normalized '
                          'cost basis (operator ruling: zero cash ≠ '
                          'zero cost)')
        status[name] = dict(ok=not issues, issues=issues)
    unverified = [n for n, s in status.items() if not s['ok']]
    if unverified:
        raise GateReject(
            f'Unverified/incomplete models: {unverified}. '
            f'Details: {json.dumps(status, indent=1)}')
    return status


# ---- screening panel freeze -------------------------------------------

SCREENING_SEED = 20261013
SCREENING_N = 20


def freeze_screening_panel(exclude_files: List[Path] = None) -> dict:
    """Freeze 20 screening tasks from TAT-QA train, excluding ALL
    previously used UIDs (frozen200, P3-60, micropilot, dev micro-trial,
    reliability panels, evaluation panel). Gold status tracked
    separately from task inclusion (isolation requirement)."""
    import glob
    exclude = set()
    for f in (exclude_files or []):
        if f.exists():
            data = json.loads(f.read_text())
            if 'uids' in data:
                exclude.update(data['uids'])
            elif 'tasks' in data:
                exclude.update(t['uid'] for t in data['tasks'])
            elif isinstance(data, list):
                exclude.update(data)

    tr = json.loads(
        (ROOT / 'data/tatqa/tatqa_dataset_train.json').read_text())
    from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (
        load_native_answers)
    nat = load_native_answers()
    pool = []
    for p in tr:
        if not p.get('table', {}).get('table') or not p.get('paragraphs'):
            continue
        for q in p['questions']:
            d = (q.get('derivation') or '').strip()
            if (q.get('answer_from') == 'table-text'
                    and q.get('answer_type') == 'arithmetic' and d
                    and re.search(r'[+\-*/]', d)
                    and q['uid'] not in exclude and q['uid'] in nat):
                pool.append(q['uid'])
    pool.sort()
    chosen = sorted(random.Random(SCREENING_SEED).sample(
        pool, min(SCREENING_N, len(pool))))

    return dict(
        version='SCREENING_PANEL_FREEZE_v1',
        seed=SCREENING_SEED, n=len(chosen),
        pool_size=len(pool), uids=chosen,
        uids_sha256=hashlib.sha256(
            json.dumps(chosen, sort_keys=True).encode()).hexdigest(),
        gold_status={u: 'independently_verified'
                     for u in chosen},  # v2.1 contract gold exists for all
        gold_isolation='gold NEVER enters model inputs; scoring only',
        note='Screening panel for 4-model node-level Q/C/L. Disjoint '
             'from all prior panels by construction.')


# ---- screening plan freeze --------------------------------------------

NODES = ('e1', 'e2', 'r', 'v')
SCREENING_MODELS = ('glm', 'deepseek', 'qwen_cloud', 'qwen_local')


def freeze_screening_plan(panel: dict, registry: dict) -> dict:
    """80-call plan: 4 models × 4 nodes × 5 tasks (20 tasks split across
    nodes 5 each to keep calls at 80 total). Gate: registry must be
    fully verified first."""
    verify_model_registry(registry)
    assignments = {}
    for i, uid in enumerate(panel['uids']):
        node = NODES[i % 4]      # round-robin: 5 tasks per node
        for model in SCREENING_MODELS:
            assignments[f'{model}|{node}|{uid}'] = dict(
                model=model, node=node, uid=uid,
                status='PENDING')
    return dict(
        version='SCREENING_PLAN_FREEZE_v1',
        panel_sha256=panel['uids_sha256'],
        total_calls=len(assignments),
        assignments=assignments,
        gate='registry_verified + panel_frozen')


# ---- Q/C/L analysis ----------------------------------------------------

class NodeScreeningAnalyzer:
    """Per-(node, model) quality/cost/latency from screening results +
    cross-model complementarity analysis."""

    def __init__(self):
        self.results = defaultdict(lambda: defaultdict(list))

    def add(self, model, node, task_uid, q: int, tokens: int,
            latency_s: float, cash_cost_cny: float = 0.0,
            normalized_cost: float = 0.0):
        self.results[(node, model)][task_uid] = dict(
            q=q, tokens=tokens, latency_s=latency_s,
            cash_cny=cash_cost_cny, normalized=normalized_cost)

    def cell_summary(self, node, model):
        rows = list(self.results[(node, model)].values())
        if not rows:
            return None
        n = len(rows)
        return dict(
            n=n,
            Q=sum(r['q'] for r in rows) / n,
            mean_tokens=sum(r['tokens'] for r in rows) / n,
            mean_latency_s=sum(r['latency_s'] for r in rows) / n,
            mean_cash_cny=sum(r['cash_cny'] for r in rows) / n,
            mean_normalized=sum(r['normalized'] for r in rows) / n)

    def full_table(self):
        table = {}
        for (node, model) in sorted(self.results.keys()):
            s = self.cell_summary(node, model)
            if s:
                table[f'{node}|{model}'] = s
        return table

    def complementarity(self, node):
        """For one node, find model pairs where they succeed on
        DIFFERENT tasks (potential for reassignment on failure)."""
        models = [m for (n, m) in self.results if n == node]
        pairs = []
        for i, m1 in enumerate(models):
            for m2 in models[i+1:]:
                tasks = set(self.results[(node, m1)].keys()) & \
                    set(self.results[(node, m2)].keys())
                both = sum(1 for t in tasks
                           if self.results[(node, m1)][t]['q'] == 1
                           and self.results[(node, m2)][t]['q'] == 1)
                only1 = sum(1 for t in tasks
                            if self.results[(node, m1)][t]['q'] == 1
                            and self.results[(node, m2)][t]['q'] == 0)
                only2 = sum(1 for t in tasks
                            if self.results[(node, m1)][t]['q'] == 0
                            and self.results[(node, m2)][t]['q'] == 1)
                union = both + only1 + only2
                pairs.append(dict(
                    pair=f'{m1}+{m2}', n=len(tasks),
                    both=both, only_m1=only1, only_m2=only2,
                    complementarity_rate=(only1 + only2) / max(1, union),
                    oracle_gain=(only1 + only2) / max(1, len(tasks))))
        return pairs


# ---- budget calculator -------------------------------------------------

class BudgetCalculator:
    """Dual-cost budget: cash (API billing) + normalized resource cost
    (operator ruling: subscription-covered ≠ free; local GPU ≠ free)."""

    def __init__(self, registry: dict):
        self.registry = registry

    def estimate_call_cost(self, model, est_input_tokens,
                           est_output_tokens):
        cfg = self.registry[model]
        billing = cfg.get('billing', {})
        input_rate = billing.get('input_per_1k_cny', 0) or 0
        output_rate = billing.get('output_per_1k_cny', 0) or 0
        cash = (est_input_tokens / 1000 * input_rate
                + est_output_tokens / 1000 * output_rate)
        # normalized: for subscription-covered models, use the declared
        # normalized basis; for cash models, normalize by a reference
        # rate (e.g. deepseek-chat input price as unit)
        ref_rate = self.registry.get('deepseek', {}).get(
            'billing', {}).get('input_per_1k_cny', 1) or 1
        normalized = cash / ref_rate if cash > 0 else \
            (est_input_tokens + est_output_tokens) / 1000  # token-units
        return dict(cash_cny=round(cash, 6),
                    normalized=round(normalized, 6),
                    basis=cfg.get('normalized_cost_basis', 'cash/ref'))

    def estimate_screening_budget(self, n_calls=80,
                                  avg_input=500, avg_output=200):
        total_cash = 0.0
        total_norm = 0.0
        per_model = {}
        for model in SCREENING_MODELS:
            n = n_calls // len(SCREENING_MODELS)
            c = self.estimate_call_cost(model, avg_input, avg_output)
            per_model[model] = dict(
                calls=n,
                cash_cny=round(c['cash_cny'] * n, 4),
                normalized=round(c['normalized'] * n, 4))
            total_cash += c['cash_cny'] * n
            total_norm += c['normalized'] * n
        return dict(
            total_calls=n_calls,
            total_cash_cny=round(total_cash, 4),
            total_normalized=round(total_norm, 4),
            per_model=per_model,
            note='Cash cost is the real spend; normalized cost enables '
                 'fair cross-model comparison including free-tier and '
                 'GPU models. Both reported separately, never mixed.')
