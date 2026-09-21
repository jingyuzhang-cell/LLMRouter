"""Offline audit of DEPLOYABLE failure-detection signals (P2, zero model calls).

Question: at runtime, without the evaluation answer, how well can cheap
parser/execution signals detect that a node failed? Evaluated on the frozen
confirmation corpora (500 + 200 tasks x 3 models x 2 nodes), zero new calls.

Deployable signals (computable without gold):
  ext_invalid      : EXT answer does not parse as a facts object
  ext_empty        : no fact extracted
  rsn_schema_invalid : RSN answer does not decode to {"expression": ...}
  rsn_exec_fail    : expression does not execute on the consumed facts
  detector_fire    : none of the above four is clean (any fires)
Label (offline only): node failure = task_q == 0 under the frozen scorer.
Metrics: precision/recall/F1 for "detect failure".
Limitation: parser/execution signals catch interface failures only; value
errors need a verifier or cross-model consistency (live experiments).
"""
import json
import random
import subprocess
import time

import numpy as np

from . import core, tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .capability_profiling import POOL
from .conf500_eval import load_conf500
from .preference_router_eval import load_confirmation
from .confirmation_500 import OUT as CONF5
from .confirmation_200 import OUT as CONF1

OUT = BASE / 'failure_detector_offline'


def commit():
    return subprocess.run(['git', '-C', str(core.ROOT), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def evaluate(rows, corpus):
    folder = CONF5 if corpus == 'conf500' else CONF1
    resp = {}
    for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
        rr = json.loads(l); resp[rr['key']] = rr
    out = []
    for r in rows:
        uid = r['uid']; gold = r['gold']
        for m in POOL:
            e = resp[f'EXT:{m}:{uid}']['response']; rs = resp[f'RSN:{m}:{uid}']['response']
            try:
                facts = v.parse_facts(e['answer']); ext_valid = True
            except Exception:
                facts = {'facts': []}; ext_valid = False
            try:
                expr = v.decode(rs['answer'])['expression']; schema = True
            except Exception:
                expr = None; schema = False
            exec_ok = False
            if schema:
                try:
                    exec_calc(expr, facts); exec_ok = True
                except Exception:
                    exec_ok = False
            out.append(dict(uid=uid, model=m, fail=int(r['per_model'][m]['task_q'] == 0),
                            ext_invalid=int(not ext_valid), ext_empty=int(len(facts['facts']) == 0),
                            rsn_schema_invalid=int(not schema), rsn_exec_fail=int(not exec_ok),
                            detector_fire=int(not (ext_valid and len(facts['facts']) > 0 and schema and exec_ok))))
    return out


def prf(rows, signal):
    tp = sum(1 for r in rows if r[signal] == 1 and r['fail'] == 1)
    fp = sum(1 for r in rows if r[signal] == 1 and r['fail'] == 0)
    fn = sum(1 for r in rows if r[signal] == 0 and r['fail'] == 1)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return dict(precision=round(prec, 4), recall=round(rec, 4), f1=round(f1, 4), tp=tp, fp=fp, fn=fn)


def run():
    out = {}
    for corpus, loader in (('conf500', load_conf500), ('conf200', load_confirmation)):
        rows = evaluate(loader(), corpus)
        out[corpus] = dict(
            n_instances=len(rows), failure_rate=round(sum(r['fail'] for r in rows) / len(rows), 4),
            signals={name: prf(rows, name) for name in
                     ['ext_invalid', 'ext_empty', 'rsn_schema_invalid', 'rsn_exec_fail', 'detector_fire']})
    report = dict(generated_unix=time.time(), commit_hash=commit(),
                  evidence_tier='offline audit of frozen outputs; zero model calls',
                  label='node failure = task_q==0 under frozen scorer (ideal label, evaluation only)',
                  deployability='all signals computable at runtime without the evaluation answer',
                  corpora=out,
                  limitation='parser/execution signals only catch interface failures; value errors need a verifier or cross-model consistency (measured live in the multinode DAG verification node)',
                  sources='conf500/conf200 RESPONSES.jsonl + policy gold answers')
    OUT.mkdir(exist_ok=True)
    (OUT / 'FAILURE_DETECTOR_OFFLINE.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for corpus, d in out.items():
        print(corpus, 'n=%d fail_rate=%.3f' % (d['n_instances'], d['failure_rate']),
              {k: (v['precision'], v['recall'], v['f1']) for k, v in d['signals'].items()})


if __name__ == '__main__':
    run()
