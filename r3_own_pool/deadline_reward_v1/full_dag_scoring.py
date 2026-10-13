"""Terminal Q/C/L evaluator for the full-DAG experiment (zero calls).

Settles each (task, arm) from the versioned execution chain:
  per-node scores (INDEPENDENT, length-neutral):
    fe  coverage(silver atoms in answer) x precision(atom-bearing
        items / all items) — longer outputs only help if the added
        items carry atoms; fabrication lowers precision
    tl  date coverage x ordering factor (dates in item order must be
        non-decreasing)
    er  entity coverage x precision
    xc  contract (verdict/claim fields) is recorded SEPARATELY;
        semantic = verdict-consistency with the ACTUAL tl/er source
        content (a SUPPORTED claim must carry an atom present in both
        sources; UNSUPPORTED in <2) — self-verifiable, no gold needed
  terminal q = mean of available node semantics (None-skipped);
        if none evaluable -> q=None (denominator never forced)
  C/L   real tokens, incremental cash, sequential task time T,
        deadline met, U = 1(T<=D)q - 0.5 C/C0 - (T-D)+/D - 2*1(T>D)
        (frozen; C0=60K)

Silver atoms are CANDIDATE evidence (doc-derived), not gold — every
score carries grade='SILVER-candidate'. Contract failures recorded
per node and NEVER equal semantic success. Settlement runs only on
completed chains (never feeds DD decisions).

Run (fake-response demonstration over 15 tasks x 3 arms):
  python3 -m deadline_reward_v1.full_dag_scoring
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from deadline_reward_v1 import full_dag_tasks
from deadline_reward_v1.full_dag_executor import (
    GlobalBudget, RealRunner, TaskClock, topo_order, _ok)
from deadline_reward_v1.full_dag_protocol import (
    TUNED_THETA, utility, C0_PER_TASK)

HERE = Path(__file__).resolve().parent
DATE_RE = re.compile(r'\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日')


def _items(answer):
    try:
        obj = json.loads((answer or '').strip())
    except (ValueError, TypeError):
        return None
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ('facts', 'timeline', 'relations', 'claims', 'data'):
            if isinstance(obj.get(k), list):
                return obj[k]
    return []


def _norm(s):
    return re.sub(r'\s+', '', str(s or ''))


def _coverage(atoms, text):
    if not atoms:
        return None
    hit = sum(1 for a in atoms if _norm(a) in _norm(text))
    return hit / len(atoms)


def _precision(items, atoms):
    """Fraction of items carrying at least one atom (length-neutral:
    padding items lower precision)."""
    if items is None:
        return None
    if not items:
        return None
    text_items = [json.dumps(i, ensure_ascii=False) for i in items]
    if not atoms:
        return None
    n = sum(1 for t in text_items
            if any(_norm(a) in _norm(t) for a in atoms))
    return n / len(text_items)


def score_node(node, answer, finish, silver_task, sources=None):
    """One node's contract + semantic scores. Contract failure ->
    q_sem=0.0 (the node delivered nothing verifiable — counted, not
    excluded, so accepting a fault never shrinks the denominator).
    None is reserved for 'silver atoms not evaluable for this node'
    (e.g. a document with no extractable atoms)."""
    items = _items(answer)
    contract_ok = (items is not None
                   and (answer or '').strip() != ''
                   and finish in ('stop', 'end_turn'))
    if not contract_ok:
        return dict(contract_ok=False, q_sem=0.0,
                    n_items=0 if items is None else len(items),
                    note='contract failure (parse/finish): semantic '
                         'quality counted as 0, recorded separately '
                         'from semantic errors')
    fe_atoms = (silver_task['fe']['atom_dates']
                + silver_task['fe']['atom_amounts']
                + silver_task['fe']['atom_penalties'])
    if node == 'fe':
        cov = _coverage(fe_atoms, answer)
        prec = _precision(items, fe_atoms)
        q = (round(cov * prec, 4)
             if cov is not None and prec is not None else None)
        return dict(contract_ok=True, q_sem=q,
                    coverage=cov, precision=prec,
                    n_items=len(items))
    if node == 'tl':
        dates = silver_task['tl']['ordered_dates']
        cov = _coverage(dates, answer)
        prec = _precision(items, dates)
        # ordering: dates extracted from items in order must be
        # non-decreasing
        seq = []
        for it in items:
            m = DATE_RE.findall(json.dumps(it, ensure_ascii=False))
            seq.extend(d for d in m)
        seq_n = [_norm(d) for d in seq]
        ordered = (all(seq_n[i] <= seq_n[i + 1]
                       for i in range(len(seq_n) - 1))
                   if len(seq_n) > 1 else True)
        q = (round(cov * prec * (1.0 if ordered else 0.5), 4)
             if cov is not None and prec is not None else None)
        return dict(contract_ok=True, q_sem=q, coverage=cov,
                    precision=prec, chronology_ok=ordered,
                    n_items=len(items))
    if node == 'er':
        ents = silver_task['er']['entity_atoms']
        cov = _coverage(ents, answer)
        prec = _precision(items, ents)
        q = (round(cov * prec, 4)
             if cov is not None and prec is not None else None)
        return dict(contract_ok=True, q_sem=q, coverage=cov,
                    precision=prec, n_items=len(items))
    # xc: verdict-consistency with ACTUAL source content
    if not items:
        return dict(contract_ok=True, q_sem=None, n_items=0,
                    note='empty verdict list')
    tl_text = _norm((sources or {}).get('tl', ''))
    er_text = _norm((sources or {}).get('er', ''))
    atoms = silver_task['fe']['atom_dates'] \
        + silver_task['fe']['atom_amounts']
    consistent = 0
    verdicts = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        v = str(it.get('verdict', '')).upper()
        claim = _norm(it.get('claim', ''))
        if v not in ('SUPPORTED', 'UNSUPPORTED', 'CONFLICT'):
            continue
        verdicts += 1
        claim_atoms = [a for a in atoms if _norm(a) in claim]
        if not claim_atoms:
            # unverifiable claim text: cannot credit consistency
            continue
        in_both = all(_norm(a) in tl_text and _norm(a) in er_text
                      for a in claim_atoms)
        in_one = any(_norm(a) in tl_text or _norm(a) in er_text
                     for a in claim_atoms)
        if (v == 'SUPPORTED' and in_both) or \
                (v in ('UNSUPPORTED', 'CONFLICT') and not in_both
                 and in_one):
            consistent += 1
    q = round(consistent / verdicts, 4) if verdicts else None
    return dict(contract_ok=True, q_sem=q,
                verdicts=verdicts, consistent=consistent,
                n_items=len(items),
                note='verdict-consistency vs actual tl/er content')


def settle_task(task, chain, clock, silver_map, usage_sum, cash_sum):
    silver_task = silver_map[task['task_id']]
    sources = dict(
        tl=(chain.current('tl') or {}).get('answer', ''),
        er=(chain.current('er') or {}).get('answer', ''))
    nodes = {}
    for n in ('fe', 'tl', 'er', 'xc'):
        o = chain.current(n) or dict(answer='', finish_reason=None)
        nodes[n] = score_node(n, o.get('answer', ''),
                              o.get('finish_reason'), silver_task,
                              sources if n == 'xc' else None)
    sems = [nodes[n]['q_sem'] for n in ('fe', 'tl', 'er', 'xc')
            if nodes[n]['q_sem'] is not None]
    q = round(sum(sems) / len(sems), 4) if sems else None
    T = clock.t
    D = clock.D
    tokens = usage_sum
    U = (utility(q if q is not None else 0.0, tokens, T, D)
         if q is not None else None)
    return dict(
        task_id=task['task_id'], event=task['event'],
        deadline_s=D, nodes=nodes,
        terminal_q=q, q_available=(q is not None),
        total_tokens=tokens, incremental_cash_cny=round(cash_sum, 6),
        normalized_cost=round(tokens / C0_PER_TASK, 4),
        task_time_s=round(T, 3), sequential=True,
        deadline_met=(T <= D),
        utility_U=U,
        U_with_q_none_note=('q not evaluable for this task; U '
                            'reported as None and excluded from '
                            'paired stats') if q is None else '',
        grade='SILVER-candidate (doc-derived atoms, not gold)')


# ---- fake-response demonstration over 15 x 3 ------------------------------
def _fake_transport_factory(silver_map):
    """Deterministic fake that behaves like an extractor: it pulls the
    atoms present in the RENDERED PROMPT and echoes the first half as
    JSON facts (coverage ~0.5, precision 1.0, length-neutral). Fault
    paths follow the frozen injection semantics."""

    from deadline_reward_v1.full_dag_silver import doc_atoms

    def fake(model_id, theta, prompt, creds, force_max_tokens=None):
        if force_max_tokens == 64:
            return dict(answer='{"facts":[{"fact":"cut',
                        finish_reason='max_tokens', tokens_in=800,
                        tokens_out=64, cash_cny=0.0, latency_s=2.0)
        atoms = doc_atoms(prompt)
        if '## 任务类型：fact_extraction' in prompt:
            half = (atoms['dates'] + atoms['amounts'])[:max(
                1, (len(atoms['dates']) + len(atoms['amounts'])) // 2)]
            ans = json.dumps(
                [dict(fact=f'事实{a}', date='', entities=[],
                      evidence_doc_id='d') for a in half],
                ensure_ascii=False)
            return dict(answer=ans, finish_reason='stop',
                        tokens_in=900, tokens_out=200, cash_cny=0.0,
                        latency_s=20.0)
        if '## 任务类型：timeline' in prompt:
            ds = sorted(set(atoms['dates']))[:max(1, len(
                set(atoms['dates'])) // 2)] or ['2026年1月1日']
            ans = json.dumps([dict(date=d, event=f'事件{i+1}',
                                   evidence='d')
                              for i, d in enumerate(ds)],
                             ensure_ascii=False)
            return dict(answer=ans, finish_reason='stop',
                        tokens_in=700, tokens_out=150, cash_cny=0.0,
                        latency_s=18.0)
        if '## 任务类型：entity_relations' in prompt:
            ents = atoms['entities'] or ['某公司']
            ans = json.dumps([dict(entity=e, role='涉事主体',
                                   relation='处罚对象',
                                   evidence_doc_id='d') for e in ents],
                             ensure_ascii=False)
            return dict(answer=ans, finish_reason='stop',
                        tokens_in=700, tokens_out=150,
                        cash_cny=0.002, latency_s=12.0)
        # xc: one SUPPORTED claim on a date present in BOTH source
        # sections, else UNSUPPORTED on a source-A-only date
        a_sec = prompt.split('## 来源A事实')[1].split('## 来源B事实')[0] \
            if '## 来源A事实' in prompt else ''
        b_sec = prompt.split('## 来源B事实')[1] \
            if '## 来源B事实' in prompt else ''
        shared = [d for d in atoms['dates']
                  if d in a_sec and d in b_sec]
        if shared:
            ans = json.dumps([dict(claim=f'于{shared[0]}发生',
                                   source_a='d', source_b='d',
                                   verdict='SUPPORTED')],
                             ensure_ascii=False)
        else:
            only_a = [d for d in atoms['dates'] if d in a_sec][:1]
            ans = json.dumps([dict(
                claim=f'于{only_a[0] if only_a else "某日"}发生',
                source_a='d', source_b='d',
                verdict='UNSUPPORTED')], ensure_ascii=False)
        return dict(answer=ans, finish_reason='stop', tokens_in=600,
                    tokens_out=120, cash_cny=0.003, latency_s=15.0)

    return fake


def run_fake_scoring():
    tasks = full_dag_tasks.build_tasks()
    silver_map = {s['task_id']: s for s in json.loads(
        (HERE / 'FULL_DAG_SILVER_V1.json').read_text())['tasks']}
    docs = full_dag_tasks.load_docs()
    import tempfile
    results = {}
    for arm in ('SS-Tuned', 'Fixed-Tuned', 'DD-Online'):
        with tempfile.TemporaryDirectory() as td:
            runner = RealRunner(arm, {}, GlobalBudget(),
                                Path(td) / 'led.jsonl',
                                transport=_fake_transport_factory(
                                    silver_map))
            rows = []
            for t in tasks:
                chain, clock = runner.run_task(
                    t, docs[t['doc_slot']]['text'])
                usage = sum(r.get('tokens', 0) for r in [])
                # recompute usage/cash from chain versions (current)
                usage = sum(
                    (chain.current(n) or {}).get('tokens_in', 0)
                    + (chain.current(n) or {}).get('tokens_out', 0)
                    for n in ('fe', 'tl', 'er', 'xc'))
                cash = sum(
                    (chain.current(n) or {}).get('cash_cny', 0.0)
                    for n in ('fe', 'tl', 'er', 'xc'))
                rows.append(settle_task(t, chain, clock, silver_map,
                                        usage, cash))
            results[arm] = rows
    report = dict(version='FULL_DAG_FAKE_SCORING_DEMO_v1',
                  zero_model_calls=True, arms=results,
                  note='mechanics demonstration: fake answers carry '
                       'no real atoms; scores are structurally valid '
                       'but NOT evidence')
    (HERE / 'FULL_DAG_FAKE_SCORING_DEMO.json').write_text(
        json.dumps(report, indent=1, ensure_ascii=False))
    for arm, rows in results.items():
        q = [r['terminal_q'] for r in rows if r['q_available']]
        U = [r['utility_U'] for r in rows if r['utility_U'] is not None]
        print(f'{arm:14s} q_available={len(q)}/{len(rows)} '
              f'mean_q={sum(q)/len(q) if q else float("nan"):.3f} '
              f'mean_U={sum(U)/len(U) if U else float("nan"):.3f} '
              f'deadline_met={sum(1 for r in rows if r["deadline_met"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(run_fake_scoring())
