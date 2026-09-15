"""Build the Node Capability Benchmark for Phase 1 (node-level routing).

Zero generation. Mines nodes from MultiHiertt dev (excluding the frozen
tool-aware v1 tasks) into four types, reusing the v1 prompt builders and
scoring semantics verbatim where they exist. Reasoning nodes are CONDITIONAL:
they receive gold facts, isolating intrinsic reasoning from upstream extraction
failures. Verification nodes come in gold/perturbed pairs. Writes NODES.json
and a frozen PROTOCOL.json; generation runs only after explicit budget approval.
"""
import argparse
import hashlib
import json
import re
import time

from . import core
from . import tool_aware_v1 as v

SOURCE = v.SOURCE
OUT = v.OUT / 'node_benchmark'
SEED = '20260915'
TARGET_EXTRACTION_TASKS = 60
TARGET_REASONING_TASKS = 120
TARGET_VERIFICATION_TASKS = 60
MAX_OPERANDS_PER_TASK = 2
MAX_TRANSFORM_PER_TASK = 2
CONSTS = ('const_100', 'const_1000', 'const_10')


def operand_values(program):
    vals = []
    for args in re.findall(r'\(([^()]*)\)', program):
        for x in args.split(','):
            x = x.strip()
            if x.startswith('#') or x in CONSTS or re.fullmatch(r'-?\d+', x) is None:
                continue
            vals.append(float(x))
    return sorted(set(vals))


def uid_hash(uid, salt):
    return hashlib.sha256(f'{salt}:{uid}'.encode()).hexdigest()


ALLOWED_OPS = ('add', 'subtract', 'multiply', 'divide')


def eligible_tasks():
    frozen = {t['task_id'] for t in json.loads((v.OUT / 'fresh/TASKS.json').read_text())}
    rows = json.loads(SOURCE.read_text())
    out = []
    for row in rows:
        qa = row['qa']
        prog = qa.get('program', '')
        if qa.get('question_type') != 'arithmetic' or prog.count('(') < 2:
            continue
        if row['uid'] in frozen:
            continue
        if any(op not in ALLOWED_OPS for op in re.findall(r'([a-z_]+)\(', prog)):
            continue  # v1 expression language supports only + - * /; exp() etc. are unscorable
        out.append(dict(uid=row['uid'], question=qa['question'], program=prog,
                        answer=float(qa['answer']), context=v.context(row)))
    return out


def build():
    if OUT.exists():
        raise FileExistsError('node_benchmark already exists')
    tasks = eligible_tasks()
    ordered = sorted(tasks, key=lambda t: uid_hash(t['uid'], SEED + ':a'))
    nodes = []

    extraction_tasks = []
    for t in ordered:
        ops = operand_values(t['program'])
        if not ops:
            continue
        extraction_tasks.append(t)
        if sum(min(len(operand_values(x['program'])), MAX_OPERANDS_PER_TASK) for x in extraction_tasks) >= 120:
            break
    extraction_calls = 0
    for t in extraction_tasks:
        ops = operand_values(t['program'])[:MAX_OPERANDS_PER_TASK]
        extraction_calls += 1
        for k, val in enumerate(ops):
            nodes.append(dict(node_id=f'{t["uid"]}:ex{k}', task_uid=t['uid'], node_type='extraction',
                              question=t['question'], program=t['program'], answer=t['answer'],
                              gold_operand=val, shares_model_call=f'{t["uid"]}:extraction'))
    n_extraction = sum(n['node_type'] == 'extraction' for n in nodes)

    def resolve(tok, env):
        if tok.startswith('#'):
            return env.get(int(tok[1:]))
        if re.fullmatch(r'-?\d+(\.\d+)?', tok):
            return float(tok)
        return None

    transform_nodes = 0
    for t in tasks:
        made = 0
        env = {}
        for step_i, (op, args) in enumerate(re.findall(r'(add|subtract|multiply|divide)\(([^()]*)\)', t['program'])):
            parts = [p.strip() for p in args.split(',')] if args.count(',') == 1 else None
            if parts is None:
                break
            a, b = (resolve(parts[0], env), resolve(parts[1], env))
            if a is not None and b is not None:
                try:
                    env[step_i] = dict(add=lambda: a + b, subtract=lambda: a - b,
                                       multiply=lambda: a * b, divide=lambda: a / b)[op]()
                except ZeroDivisionError:
                    break
            if op not in ('multiply', 'divide') or made >= MAX_TRANSFORM_PER_TASK:
                continue
            const = [p for p in parts if p in ('const_100', 'const_1000', 'const_1000000')]
            if not const:
                continue  # const_2..5 are averaging (arithmetic/tool territory), 1e4/1e5 have no natural unit name
            value_tok = [p for p in parts if p != const[0]]
            x = resolve(value_tok[0], env) if value_tok else None
            if x is None:
                continue
            scale = {'const_100': 100, 'const_1000': 1000, 'const_1000000': 1000000}[const[0]]
            unit = {100: 'percent', 1000: 'thousands', 1000000: 'millions'}[scale]
            gold = x * scale if op == 'multiply' else x / scale
            instruction = (f'Express the value {x:g} in {unit} by multiplying by {scale}.' if op == 'multiply'
                           else f'Convert the value {x:g} from {unit} by dividing by {scale}.')
            transform_nodes += 1
            made += 1
            nodes.append(dict(node_id=f'{t["uid"]}:tr{made}', task_uid=t['uid'], node_type='transformation',
                              question=t['question'], raw_value=x, direction=unit,
                              instruction=instruction, gold_value=gold))

    reasoning_tasks = [t for t in sorted(tasks, key=lambda t: uid_hash(t['uid'], SEED + ':b'))
                       if operand_values(t['program'])][:TARGET_REASONING_TASKS]
    for t in reasoning_tasks:
        ops = operand_values(t['program'])
        facts = dict(facts=[dict(value=val, evidence='gold') for val in ops])
        nodes.append(dict(node_id=f'{t["uid"]}:rs', task_uid=t['uid'], node_type='reasoning',
                          question=t['question'], program=t['program'], answer=t['answer'],
                          gold_facts=facts))

    verification_tasks = [t for t in sorted(tasks, key=lambda t: uid_hash(t['uid'], SEED + ':c'))
                          if operand_values(t['program'])][:TARGET_VERIFICATION_TASKS]
    for t in verification_tasks:
        ops = operand_values(t['program'])
        for variant, perturb in [('pos', None), ('neg', None)]:
            facts = [dict(value=val, evidence='gold') for val in ops]
            if variant == 'neg':
                idx = int(uid_hash(t['uid'], SEED + ':n')[:8], 16) % len(facts)
                facts[idx]['value'] = facts[idx]['value'] * 3 + 7
            nodes.append(dict(node_id=f'{t["uid"]}:vf{variant}', task_uid=t['uid'],
                              node_type='verification', question=t['question'], program=t['program'],
                              answer=t['answer'], gold_facts=dict(facts=facts), expect_accept=variant == 'pos'))

    counts = {t: sum(n['node_type'] == t for n in nodes) for t in ['extraction', 'transformation', 'reasoning', 'verification']}
    calls_per_model = extraction_calls + sum(n['node_type'] != 'extraction' for n in nodes)
    OUT.mkdir()
    core.write(OUT / 'NODES.json', nodes)
    core.write(OUT / 'TASK_POOL.json', dict(eligible=len(tasks), frozen_excluded=40,
                                            extraction_tasks=len(extraction_tasks),
                                            reasoning_tasks=len(reasoning_tasks),
                                            verification_tasks=len(verification_tasks)))
    core.write(OUT / 'PROTOCOL.json', dict(
        role='Phase 1 Node Capability Benchmark (construction only; generation pending budget approval)',
        source=str(SOURCE), seed=SEED,
        sampling='UID-hash order under seed 20260915 with disjoint salts; frozen tool-aware v1 tasks excluded; overlap between type samples allowed and reported',
        node_types=dict(
            extraction=dict(n=counts['extraction'],
                            prompt='v1 eprompt verbatim (one call per task; both operand nodes score the same response)',
                            quality='v1 operand recall: target operand recovered among parsed fact values (tolerance 1e-4 relative)'),
            transformation=dict(n=counts['transformation'],
                                prompt='unit/scale conversion of a single raw value (percent/millions), frozen instruction in builder',
                                quality='numeric closeness to gold conversion'),
            reasoning=dict(n=counts['reasoning'],
                           prompt='v1 sprompt verbatim with GOLD facts (conditional quality; no upstream contamination)',
                           quality='executed expression on gold facts equals reference answer (v1 tolerance)'),
            verification=dict(n=counts['verification'],
                              prompt='facts + candidate program + value; verdict yes/no (+ wrong operand index); gold/perturbed pairs',
                              quality='verdict matches expect_accept')),
        runner=dict(models=['medium', 'large', 'coder', 'reasoning'], temperature=0, max_tokens=512,
                    concurrency=4, retries=0, api_timeout_seconds=600,
                    transport_failure='kept as missing, never scored as zero',
                    calls_per_model=calls_per_model, total_calls=4 * calls_per_model,
                    local_calls=3 * calls_per_model, r1_dashscope_calls=calls_per_model),
        router_experiment=dict(
            features='deployment-observable only: node_type one-hot, task-question GTE embedding, input context token length, node position hints; gold programs/operands never used as features',
            arms=['Always Large', 'Query Router (question embedding only)', 'Static Capability Router (per-type model means)', 'Node Router', 'Node Oracle'],
            splits='3 folds grouped by task_uid (no task crosses folds), seed frozen',
            utility='alpha*Q - beta*C_tokens/1000 - gamma*L_seconds/10 with v1 frozen weights',
            comparisons='paired bootstrap over tasks (10000, frozen seed); success = Node Router beats Query Router on utility with CI95 lower>0'),
        constraints=['No generation in this step', 'No router retrained yet', 'No Dynamic DAG/feedback',
                     'Reasoning/verification nodes conditional on gold inputs by design'],
        created_unix=time.time()))
    print(json.dumps(dict(eligible_pool=len(tasks), node_counts=counts, calls_per_model=calls_per_model,
                          total_calls=4 * calls_per_model), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['build'])
    ap.parse_args()
    build()


if __name__ == '__main__':
    main()
