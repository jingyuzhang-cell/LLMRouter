"""Collect the Node Capability Benchmark: all four models on every node.

Reuses the v1 local vLLM layer (medium/large/coder) and the dashscope R1
client. One call per (extraction task | non-extraction node) per model;
transport failures stay missing. Two frozen amendments from the approval are
recorded in PROTOCOL.json before generation: transformation is an exploratory
stratum, and R1 is measured for capability data only — the frozen router pool
stays {medium, large, coder}; no post-hoc pool changes from this round.
"""
import argparse
import fcntl
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import core
from . import run as engine
from . import tool_aware_v1 as v

OUT = v.OUT / 'node_benchmark'
SLOTS = ['medium', 'large', 'coder', 'reasoning']
ALLOWED_OPS = ('add', 'subtract', 'multiply', 'divide')
TRANS_PROMPT = ('You are verifying a unit conversion for a financial analysis. {instruction} '
                'Return ONLY JSON {{"value": number}}.\nQUESTION (context only, do not re-answer it): {question}')
VERIF_PROMPT = ('Check this financial computation. Given the question, extracted facts, a proposed arithmetic '
                'expression, and its computed value, decide whether it correctly answers the question using '
                'accurate facts. If any fact value is wrong, reject and name its index. '
                'Return ONLY JSON {{"verdict":"yes"|"no","wrong_fact":<fact index or null>}}.\n'
                'QUESTION: {question}\nFACTS: {facts}\nEXPRESSION: {expression}\nVALUE: {value}')


def resolve(tok, env, facts):
    if tok.startswith('#'):
        return env.get(int(tok[1:]))
    if tok.startswith('const_'):
        return {'const_1': 1.0, 'const_2': 2.0, 'const_3': 3.0, 'const_4': 4.0, 'const_5': 5.0,
                'const_10': 10.0, 'const_100': 100.0, 'const_1000': 1000.0}.get(tok)
    if tok.startswith('v') and tok[1:].isdigit():
        idx = int(tok[1:])
        return facts['facts'][idx]['value'] if idx < len(facts['facts']) else None
    try:
        return float(tok)
    except ValueError:
        return None


def interpret(program, facts):
    env = {}
    for step_i, (op, args) in enumerate(re.findall(r'(add|subtract|multiply|divide)\(([^()]*)\)', program)):
        parts = [p.strip() for p in args.split(',')] if args.count(',') == 1 else None
        if parts is None:
            return None
        a, b = resolve(parts[0], env, facts), resolve(parts[1], env, facts)
        if a is None or b is None:
            return None
        try:
            env[step_i] = dict(add=a + b, subtract=a - b, multiply=a * b, divide=(a / b if b else None))[op]
            if env[step_i] is None:
                return None
        except Exception:
            return None
    return env[len(env) - 1] if env else None


def to_vref_expression(program, index_of_value):
    text = program
    for value, idx in index_of_value.items():
        text = re.sub(r'(?<![\w.#])(-?' + re.escape(str(value)) + r')(?![\w.])', f'v{idx}', text)
    return text


def build_calls(nodes, contexts):
    calls = {}
    for n in nodes:
        t = dict(question=n['question'], context=contexts[n['task_uid']])
        if n['node_type'] == 'extraction':
            key = n['shares_model_call']
            if key not in calls:
                calls[key] = dict(call_key=key, task_uid=n['task_uid'], node_type='extraction',
                                  node_ids=[], prompt=v.eprompt(t))
            calls[key]['node_ids'].append(n['node_id'])
        elif n['node_type'] == 'transformation':
            calls[n['node_id']] = dict(call_key=n['node_id'], task_uid=n['task_uid'],
                                       node_type='transformation', node_ids=[n['node_id']],
                                       prompt=TRANS_PROMPT.format(instruction=n['instruction'], question=n['question']))
        elif n['node_type'] == 'reasoning':
            calls[n['node_id']] = dict(call_key=n['node_id'], task_uid=n['task_uid'],
                                       node_type='reasoning', node_ids=[n['node_id']],
                                       prompt=v.sprompt(t, n['gold_facts']))
        elif n['node_type'] == 'verification':
            facts = n['gold_facts']
            index_of_value = {f['value']: i for i, f in enumerate(facts['facts'])}
            expr = to_vref_expression(n['program'], index_of_value)
            value = interpret(expr, facts)
            if value is None:
                continue
            calls[n['node_id']] = dict(call_key=n['node_id'], task_uid=n['task_uid'],
                                       node_type='verification', node_ids=[n['node_id']],
                                       prompt=VERIF_PROMPT.format(question=n['question'], facts=json.dumps(facts),
                                                                  expression=expr, value=value),
                                       expression=expr, computed_value=value)
    return list(calls.values())


def collect(slot):
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    if core.sha(OUT / 'NODES.json') != protocol['bindings'][str(OUT / 'NODES.json')]:
        raise ValueError('Frozen node set changed')
    file = OUT / (slot + '_RESPONSES.jsonl')
    ledger = OUT / (slot + '_REQUESTS.jsonl')
    if ledger.exists():
        raise RuntimeError('No generation replay')
    nodes = json.loads((OUT / 'NODES.json').read_text())
    rows = json.loads(v.SOURCE.read_text())
    contexts = {r['uid']: v.context(r) for r in rows}
    calls = build_calls(nodes, contexts)
    engine.OUT = OUT
    with (core.ROOT / 'collect/logs' / ('reasoning.lock' if slot == 'reasoning' else 'local_gpu.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        started = time.time()
        try:
            if slot != 'reasoning':
                proc, log, _ = engine.start_model(slot)
            done = 0
            with ThreadPoolExecutor(max_workers=4) as pool, ledger.open('a') as intents, file.open('a') as out:
                def submit_block():
                    futures = {}
                    for c in calls:
                        intents.write(json.dumps(dict(call_key=c['call_key'], model=slot,
                                                      prompt=c['prompt'], unix_time=time.time()),
                                                 ensure_ascii=False) + '\n')
                        intents.flush()
                        fn = v.request_r1 if slot == 'reasoning' else (lambda txt: engine.call_model(slot, txt))
                        futures[pool.submit(fn, c['prompt'])] = c
                    return futures
                futures = submit_block()
                for future in as_completed(futures):
                    c = futures[future]
                    raw = future.result()
                    out.write(json.dumps(dict(**raw, call_key=c['call_key'], task_uid=c['task_uid'],
                                              node_type=c['node_type'], node_ids=c['node_ids'], model=slot,
                                              expression=c.get('expression'), computed_value=c.get('computed_value')),
                                         ensure_ascii=False) + '\n')
                    out.flush()
                    done += 1
                    if done % 40 == 0:
                        core.write(OUT / (slot + '_STATUS.json'),
                                   dict(phase='COLLECTING', slot=slot, done=done, total=len(calls)))
            core.write(OUT / (slot + '_STATUS.json'),
                       dict(phase='COMPLETE', slot=slot, records=done, total=len(calls),
                            missing=0, total_seconds=time.time() - started))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)
    print(slot, 'complete', done, '/', len(calls))


def freeze_amendments():
    protocol = json.loads((OUT / 'PROTOCOL.json').read_text())
    if 'amendments' in protocol:
        raise FileExistsError('Amendments already frozen')
    protocol['amendments'] = dict(
        adopted_unix_time=time.time(),
        transformation='exploratory stratum: 11 natural dev nodes, no train top-up this round; main conclusions '
                       'rest on extraction/reasoning/verification',
        r1_role='measured on every node for capability data only; frozen router candidate pool stays '
                '{medium, large, coder}; any pool expansion is a separate preregistered experiment',
        gates=dict(gate1='node GAP exists: OracleNode>BestFixed on a major type, not driven by 1-2 nodes',
                   gate2='Node Router beats Query Router on quality, or matches quality at lower cost',
                   gate3='recovery=(Q_NodeRouter-Q_BestFixed)/(Q_OracleNode-Q_BestFixed) reported per type'),
        post_collection_order=['node gap audit first', 'then 5-arm router comparison', 'stop and report'])
    protocol['prompt_templates'] = dict(transformation=TRANS_PROMPT, verification=VERIF_PROMPT,
                                        extraction='v1 eprompt verbatim', reasoning='v1 sprompt verbatim with gold facts')
    protocol['bindings'] = {str(p): core.sha(p) for p in
                            [OUT / 'NODES.json', Path(__file__).with_name('node_benchmark_build.py'),
                             Path(__file__).with_name('node_benchmark_collect.py')]}
    core.write(OUT / 'PROTOCOL.json', protocol)
    print('amendments frozen')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['freeze', 'collect'])
    ap.add_argument('slot', nargs='?', choices=SLOTS)
    args = ap.parse_args()
    if args.stage == 'freeze':
        freeze_amendments()
    else:
        collect(args.slot)


if __name__ == '__main__':
    main()
