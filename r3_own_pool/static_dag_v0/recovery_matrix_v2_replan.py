"""Local Subgraph Replan (dev pilot method, new prompts; frozen 116 untouched).
Unlike local_decompose (align + single expression), replan produces a small sub-DAG of
atomic arithmetic steps s1..sk executed deterministically in order, plus a final expression;
on step failure it performs ONE evidence repair (frozen RETRIEVE prompt) and re-plans once.
Scored offline; runtime snapshots contain no gold."""
import copy
import hashlib
import json
import re
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_pilot import parse_retrieval, RETRIEVE
from .recovery_matrix_v2_snapshot import assert_runtime, digest

PLAN = ('Re-plan the remaining computation as a small graph of atomic arithmetic steps. '
        'Available facts are v0,v1,... in order. Write 1-4 steps; each step is ONE atomic '
        'operation (a single +,-,*,/ or negation) referencing facts v* or earlier steps s*. '
        'Then give the final answer as one expression over v*/s*. Use numeric constants only '
        'for counting (divide by count), scaling (percent, thousands, millions) or sign changes. '
        'Return ONLY JSON {{"steps":[{{"id":"s1","expr":"..."}},...],"final":"..."}}. '
        'Do not compute anything; write expressions only.\n'
        'QUESTION: {q}\nREPORT:\n{ctx}\nFACT VALUES: {vals}')

MAX_STEPS = 4

def _sub_step_refs(expr, n_facts):
    """Rewrite sK refs to v{n_facts+K-1} so exec_calc can evaluate against a flat facts list."""
    def repl(m):
        idx = int(m.group(1)) - 1
        return f'v{n_facts + idx}'
    return re.sub(r'\bs([0-9]+)\b', repl, expr)

def execute_replan(runtime_snapshot, call):
    """Signature-compatible with frozen execute_action: (snapshot, action, call(model,prompt,stage,sh))."""
    assert_runtime(runtime_snapshot)
    snap = copy.deepcopy(runtime_snapshot); sh = digest(snap)
    calls = []
    def invoke(model, prompt, stage):
        result = call(model, prompt, stage, sh)
        calls.append(dict(model=model, prompt=prompt,
                          prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                          response=result, stage=stage))
        return result

    def try_plan(facts):
        vals = [f['value'] for f in facts['facts']]
        n = len(vals)
        r = invoke('medium', PLAN.format(q=snap['question'], ctx=snap['context'][:14000],
                                         vals=json.dumps(vals)), 'plan')
        plan = v.decode(r['answer'])
        steps = plan.get('steps') or []
        assert isinstance(steps, list) and 0 < len(steps) <= MAX_STEPS and isinstance(plan.get('final'), str)
        env = dict(vals=vals, computed=[])
        for st in steps:
            expr = _sub_step_refs(st['expr'], n)
            flat = {'facts': [dict(value=x, evidence='computed') for x in env['vals'] + env['computed']]}
            env['computed'].append(round(exec_calc(expr, flat), 6))
        final = _sub_step_refs(plan['final'], n)
        flat = {'facts': [dict(value=x, evidence='computed') for x in env['vals'] + env['computed']]}
        return exec_calc(final, flat), len(steps) + 1
    result = dict(action='local_replan', snapshot_hash=sh, facts_source=snap['facts_source'],
                  facts_before=copy.deepcopy(snap['facts_before']),
                  facts_after=copy.deepcopy(snap['facts_before']), gold_leak_check=False,
                  plans_made=0, evidence_repaired=False)
    try:
        value, nodes = try_plan(snap['facts_before'])
        result.update(value=value, expression=None, executor_error=None,
                      affected_nodes=nodes, plans_made=1)
    except Exception as first_err:
        # one evidence repair + one re-plan
        try:
            r = invoke('medium', RETRIEVE.format(q=snap['question'], ctx=snap['context'][:14000]), 'retrieve')
            new = parse_retrieval(r['answer'])
            vals = list({round(f['value'], 6) for f in snap['facts_before']['facts']} |
                        {round(f['value'], 6) for f in new['facts']})
            merged = {'facts': [dict(value=x, evidence='merged') for x in vals]}
            result['facts_after'] = merged; result['evidence_repaired'] = True
            value, nodes = try_plan(merged)
            result.update(value=value, expression=None, executor_error=None,
                          affected_nodes=nodes, plans_made=2)
        except Exception as second_err:
            result.update(value=None, expression=None, executor_error=type(second_err).__name__,
                          plans_made=result['plans_made'] or 2, first_error=type(first_err).__name__,
                          affected_nodes=None)
    result.update(calls=calls, executed=True,
                  tokens=sum(c['response']['usage']['total_tokens'] for c in calls) if all((c['response'].get('usage') or {}).get('total_tokens') is not None for c in calls) else None,
                  dt_s=sum(c['response']['latency_s'] for c in calls) if all(c['response'].get('latency_s') is not None for c in calls) else None)
    assert sh == digest(snap)
    return result
