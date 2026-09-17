"""Error-propagation decomposition of live E2E failures (zero new calls).

For every Full-arm task failure: rebuild the live-extracted facts from the
call cache; classify the CAUSE - extraction-caused (gold operands not all
recovered), formula error (operands present but the expression executed on
GOLD facts still misses gold), input-value mismatch (operands present, gold-
facts execution matches gold, so the error entered via a corrupted extracted
value), tool error (impossible by construction, reported for completeness).
Separately count verifier-passed-wrong (verdict yes but answer wrong) over all
decided tasks - the paper's headline finding.
"""
import argparse
import json

import numpy as np

from . import core
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc

LIVE = core.ROOT / 'static_dag_v0/live_e2e'
SRC = core.ROOT / 'static_dag_v0/fresh_static_confirmation'
GOLD_TOL = 1e-4


def close(a, b):
    return a is not None and abs(a - b) <= max(GOLD_TOL, GOLD_TOL * abs(b))


def run():
    traces = [json.loads(l) for l in (LIVE / 'TRACES.jsonl').open()]
    cache = {}
    for line in (LIVE / 'CALL_CACHE.jsonl').open():
        row = json.loads(line)
        k = tuple(row['key'].split('/')) if '/' in row['key'] else row['key']
        cache[k] = row['response']
    nodes_all = json.loads((SRC / 'NODES.json').read_text())
    tasks = {t['uid']: t for t in json.loads((SRC / 'TASKS.json').read_text())}
    node_by_id = {n['node_id']: n for n in nodes_all}

    def gold_operands(r_node):
        import re
        vals = []
        for args in re.findall(r'\(([^()]*)\)', r_node['program']):
            for x in args.split(','):
                x = x.strip()
                if x.startswith('#') or x.startswith('const_'):
                    continue
                try:
                    vals.append(float(x))
                except ValueError:
                    pass
        return sorted(set(vals))

    decomposition = dict(extraction_caused=0, formula_error=0, input_value_mismatch=0,
                         tool_error=0, no_value=0, total_failures=0)
    cases = []
    verifier = dict(decided=0, passed_wrong=0, rejected_correct=0)
    for t in traces:
        full = t['arms']['Full']
        r_node = node_by_id[f"{t['task_uid']}:rs"]
        gold = tasks[t['task_uid']]['answer']
        if full.get('verdict') is not None:
            verifier['decided'] += 1
            if full['verdict'] and not full['task_success']:
                verifier['passed_wrong'] += 1
            if (not full['verdict']) and full['task_success']:
                verifier['rejected_correct'] += 1
        if full['task_success']:
            continue
        decomposition['total_failures'] += 1
        # live-extracted facts for the FULL arm's extraction model
        facts = None
        for k, resp in cache.items():
            if k[0].endswith(t['task_uid'] + ':ex0') or (isinstance(k, tuple) and k[0].startswith(t['task_uid']) and ':ex' in k[0]):
                try:
                    facts = v.parse_facts(resp['answer'])
                    break
                except Exception:
                    facts = None
        operands = gold_operands(r_node)
        got = [f['value'] for f in facts['facts']] if facts else []
        recall_ok = all(any(close(g, w) for g in got) for w in operands)
        if not recall_ok:
            decomposition['extraction_caused'] += 1
            cause = 'extraction_caused'
        elif full.get('final_value') is None:
            decomposition['no_value'] += 1
            cause = 'no_value'
        else:
            # execute the final expression on GOLD facts to isolate formula error
            expr = full.get('expression')
            try:
                on_gold = exec_calc(expr, r_node['gold_facts'])
            except Exception:
                on_gold = None
            if not close(on_gold, gold):
                decomposition['formula_error'] += 1
                cause = 'formula_error'
            else:
                decomposition['input_value_mismatch'] += 1
                cause = 'input_value_mismatch'
        cases.append(dict(task_uid=t['task_uid'], cause=cause, gold=gold,
                          final_value=full.get('final_value'), verdict=full.get('verdict')))
    result = dict(decomposition=decomposition, verifier=verifier,
                  note='tool_error is 0 by construction (deterministic executor, verified in benchmark); '
                       'input_value_mismatch = formula correct on gold facts, error entered via corrupted '
                       'extracted value; verifier.passed_wrong is the headline: adaptive gain is bounded by '
                       'verification reliability')
    core.write(LIVE / 'ERROR_PROPAGATION.json', dict(**result, cases=cases))
    print(json.dumps(result, indent=1))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()


if __name__ == '__main__':
    main()
