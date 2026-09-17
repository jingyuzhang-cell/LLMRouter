"""TAT-QA second-domain node benchmark: build nodes from arithmetic derivations.

Reuses the frozen DAG template (extraction/reasoning/verification) verbatim on
TAT-QA dev (table+text hybrid; never used in any prior experiment). Operands
are the numeric literals in each derivation; the gold reasoning value is the
exact evaluation of the derivation expression; verification pos/neg pairs are
built from the v-ref program. Success rules identical to the MultiHiertt
benchmark. Zero generation in this step.
"""
import argparse
import hashlib
import json
import re

from . import core
from . import tool_aware_v1 as v

DATA = core.ROOT / 'data/tatqa/tatqa_dataset_dev.json'
OUT = core.ROOT / 'static_dag_v0/tatqa_benchmark'
SEED = '20260916'
TARGET_TASKS = 40
OPS = {'+': 'add', '-': 'subtract', '*': 'multiply', '/': 'divide'}
CONST_ALLOWED = {0.0, 1.0, 100.0}


def context(para):
    table = para['table']['table']
    txt = []
    for r in table:
        cells = [str(c).replace('\n', ' ').strip() for c in r]
        if any(cells):
            txt.append(' | '.join(cells))
    body = '\n'.join(f'[{i}] {p}' for i, p in enumerate(para['paragraphs']))
    return 'TABLE:\n' + '\n'.join(txt) + '\n\nPASSAGES:\n' + body


def literals(expr):
    """Numeric literals outside of v-references."""
    out = []
    for m in re.finditer(r'(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])', expr):
        out.append(float(m.group(1)))
    return out


def run():
    if OUT.exists():
        raise FileExistsError('tatqa_benchmark already exists')
    paras = json.loads(DATA.read_text())
    eligible = []
    for para in paras:
        for q in para['questions']:
            d = (q.get('derivation') or '').strip()
            if q.get('answer_type') != 'arithmetic' or not d or not re.search(r'[+\-*/]', d):
                continue
            lits = [x for x in literals(d) if x not in CONST_ALLOWED]
            if len(set(lits)) < 2:
                continue
            try:
                gold = eval(d, {'__builtins__': {}}, {})
            except Exception:
                continue
            if not isinstance(gold, (int, float)):
                continue
            eligible.append(dict(uid=q['uid'], question=q['question'], derivation=d,
                                 answer=float(gold), context=context(para)))
    eligible.sort(key=lambda t: hashlib.sha256(f'{SEED}:{t["uid"]}'.encode()).hexdigest())
    tasks = eligible[:TARGET_TASKS]
    nodes = []
    for t in tasks:
        ops = sorted({x for x in literals(t['derivation']) if x not in CONST_ALLOWED})
        for k, val in enumerate(ops[:2]):
            nodes.append(dict(node_id=f'{t["uid"]}:ex{k}', task_uid=t['uid'], node_type='extraction',
                              question=t['question'], derivation=t['derivation'], answer=t['answer'],
                              gold_operand=val, shares_model_call=f'{t["uid"]}:extraction'))
        facts = dict(facts=[dict(value=x, evidence='gold') for x in ops])
        nodes.append(dict(node_id=f'{t["uid"]}:rs', task_uid=t['uid'], node_type='reasoning',
                          question=t['question'], derivation=t['derivation'], answer=t['answer'],
                          gold_facts=facts, gold_expr=t['derivation']))
        expr = t['derivation']
        for i, val in enumerate(sorted(set(ops), key=lambda x: -len(str(x)))):
            expr = re.sub(r'(?<![\w.])(-?' + re.escape(str(val)) + r')(?![\w.])', f'v{i}', expr)
        facts_v = dict(facts=[dict(value=x, evidence='gold') for x in sorted(set(ops), key=lambda x: -len(str(x)))])
        pert = dict(facts=[dict(value=f['value'], evidence='gold') for f in facts_v['facts']])
        idx = int(hashlib.sha256(f'{SEED}:n:{t["uid"]}'.encode()).hexdigest()[:8], 16) % len(pert['facts'])
        pert['facts'][idx]['value'] = pert['facts'][idx]['value'] * 3 + 7
        for variant, fv in [('pos', facts_v), ('neg', pert)]:
            nodes.append(dict(node_id=f'{t["uid"]}:vf{variant}', task_uid=t['uid'], node_type='verification',
                              question=t['question'], derivation=t['derivation'], answer=t['answer'],
                              gold_facts=fv, gold_expr=expr, expect_accept=variant == 'pos'))
    counts = {t: sum(n['node_type'] == t for n in nodes) for t in ['extraction', 'reasoning', 'verification']}
    OUT.mkdir()
    core.write(OUT / 'NODES.json', nodes)
    core.write(OUT / 'TASKS.json', tasks)
    core.write(OUT / 'PROTOCOL.json', dict(
        role='second-domain node-level routing validation (TAT-QA dev, never used in any prior experiment)',
        source=str(DATA), seed=SEED, tasks=len(tasks), node_counts=counts,
        eligibility='answer_type=arithmetic, derivation parseable, >=2 non-constant literals',
        gold='exact evaluation of the dataset derivation expression (tolerance 1e-4 relative)',
        prompts='identical frozen templates as the MultiHiertt benchmark (eprompt/sprompt/verification)',
        calls_per_model=len(tasks) + sum(n['node_type'] != 'extraction' for n in nodes),
        constraints=['No overlap with any prior workspace data', 'Models and decoding identical to main benchmark']))
    print(json.dumps(dict(eligible=len(eligible), tasks=len(tasks), node_counts=counts,
                          calls_per_model=len(tasks) + sum(n['node_type'] != 'extraction' for n in nodes)), indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
