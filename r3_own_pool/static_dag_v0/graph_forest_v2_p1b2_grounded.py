"""P1b-2: Grounded Semantic Contract — typed operators + deterministic compiler.

Pipeline: Question/Facts -> TYPED contract (family + operand roles ONLY, no
free-form expression) -> deterministic compile -> Equivalent(., e_stored).

Typed semantics (the point: multiply-by-100 is decided by OPERATOR, not by
the model's convention):
    sum(t1..tk)                 = t1+..+tk
    average(t1..tk)             = (t1+..+tk)/k
    difference(minuend, sub)    = minuend - sub
    ratio(num, den)             = num/den               (NEVER x100)
    percentage(part, whole)     = 100*part/whole        (ALWAYS x100)
    percentage_change(new, old) = 100*(new-old)/old     (ALWAYS x100)
    product(a, b)               = a*b
num/den/whole may be a single fact id OR {"sum_of": [ids]} (denominator family).

Abstain policy (pre-registered): schema-inexpressible / invalid -> abstain ->
DO NOT intervene (Selective Intervention: uncertainty -> inaction); abstain
rate reported.

Protocol: dev = GFv2-20 (schema design, <=2 rounds, then FROZEN); test =
96-task P0-2 panel, primary metrics on the 76 non-overlapping tasks; single
model 'large', temperature 0, one call per task; policy utility replays
frozen P0-2 outcomes (zero workflow calls). Hypotheses:
    H1 Q_grounded > Q_freeform (14/76)
    H2 FPR on reuse-safe down (10/19 false interventions before)
    H3 recall on reuse-harm up (0/2 before)
"""
import fcntl
import json
import re
import time
from pathlib import Path

from . import core
from . import run as engine
from .decompose_v1 import exec_calc

ROOT = core.ROOT
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p1b2'
SRC = ROOT / 'static_dag_v0/fresh_static_confirmation'
V1DIR = ROOT / 'static_dag_v0/graph_forest_v1'
MODEL = 'large'
PROMPT_VERSION = 1

FAMILIES = {
    'sum': '{"family":"sum","terms":["f0","f1","f2"]}  // total of the listed facts',
    'average': '{"family":"average","terms":["f0","f1"]}  // mean of the listed facts',
    'difference': '{"family":"difference","minuend":"f1","subtrahend":"f0"}  // minuend minus subtrahend',
    'ratio': '{"family":"ratio","numerator":"f3","denominator":"f7"}  // numerator/denominator, NEVER x100; '
             'denominator may be {"sum_of":["f3","f7"]} for a share of a total',
    'percentage': '{"family":"percentage","part":"f3","whole":"f7"}  // 100*part/whole, ONLY when the question '
                  'explicitly asks for a percentage; whole may be {"sum_of":[...]}',
    'percentage_change': '{"family":"percentage_change","new":"f3","old":"f7"}  // 100*(new-old)/old, ONLY for '
                         '"by what percent did X increase/decrease"',
    'product': '{"family":"product","factors":["f0","f1"]}',
}
PROMPT = (
    'Classify the financial question into EXACTLY ONE operation family and assign its operand '
    'roles. The system compiles your choice into the exact formula — you do NOT write formulas. '
    'CRITICAL: ratio = a/b is NEVER multiplied by 100; percentage and percentage_change ALWAYS '
    'multiply by 100. If the question asks "the ratio of X to Y" or "how many times", choose '
    'ratio. Choose percentage/percentage_change ONLY if the question literally contains '
    '"percent" or "%". Choose difference only for an absolute amount difference.\n'
    'Allowed schemas:\n{schemas}\n'
    'Return ONLY the JSON object for ONE family, using fact ids f0..fk from the list. '
    'If none fits, return {{"family":"none"}}.\n'
    'QUESTION: {q}\nFACTS: {facts}')


def contract_prompt(question, facts):
    fs = ', '.join(f"f{k}={f['value']:g}" for k, f in enumerate(facts['facts']))
    schemas = '\n'.join(FAMILIES.values())
    return PROMPT.replace('{schemas}', schemas).replace('{q}', question).replace('{facts}', fs)


def _fid(tok, n):
    if isinstance(tok, str) and re.fullmatch(r'f\d+', tok) and int(tok[1:]) < n:
        return f'v{tok[1:]}'
    return None


def _comp(tok, n):
    """fact id OR {'sum_of': [...]} -> parenthesized v-expression."""
    f = _fid(tok, n)
    if f:
        return f
    if isinstance(tok, dict) and isinstance(tok.get('sum_of'), list):
        parts = [_fid(x, n) for x in tok['sum_of']]
        if parts and all(parts):
            return '(' + ') + ('.join(parts) + ')'
    return None


def compile_contract(c, n_facts):
    """Typed contract -> v-ref expression, or None if invalid."""
    try:
        fam = c['family']
        if fam == 'none':
            return None
        if fam in ('sum', 'average'):
            ts = [_fid(x, n_facts) for x in c['terms']]
            if not (ts and all(ts)) or len(ts) < 2:
                return None
            s = '(' + ') + ('.join(ts) + ')'
            return s if fam == 'sum' else f'({s}) / {len(ts)}'
        if fam == 'difference':
            a, b = _fid(c['minuend'], n_facts), _fid(c['subtrahend'], n_facts)
            return f'({a}) - ({b})' if a and b else None
        if fam == 'ratio':
            num, den = _comp(c['numerator'], n_facts), _comp(c['denominator'], n_facts)
            return f'({num}) / ({den})' if num and den else None
        if fam == 'percentage':
            p, w = _comp(c['part'], n_facts), _comp(c['whole'], n_facts)
            return f'(100 * ({p})) / ({w})' if p and w else None
        if fam == 'percentage_change':
            new, old = _comp(c['new'], n_facts), _comp(c['old'], n_facts)
            return f'(100 * (({new}) - ({old}))) / ({old})' if new and old else None
        if fam == 'product':
            fs = [_fid(x, n_facts) for x in c['factors']]
            if not (fs and all(fs)) or len(fs) < 2:
                return None
            return '(' + ') * ('.join(fs) + ')'
    except Exception:
        return None
    return None


def parse_contract(answer):
    try:
        text = (answer or '').strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        c = json.loads(text)
        assert c['family'] in (list(FAMILIES) + ['none'])
        return c
    except Exception:
        return None


def run(phase='dev'):
    OUT.mkdir(parents=True, exist_ok=True)
    nodes = json.loads((SRC / 'NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    dry = json.loads((ROOT / 'static_dag_v0/graph_forest_v2_p02/DRYRUN.json').read_text())
    rows = sorted([r for r in dry['fresh_rows'] if r['ok']], key=lambda r: r['uid'])
    dev = {r['task_uid'] for r in json.loads((V1DIR / 'RESULTS.json').read_text())['rows']}
    panel = [r for r in rows if r['uid'] in dev] if phase == 'dev' else rows

    engine.OUT = OUT
    path = OUT / 'RESPONSES.jsonl'
    cache = {}
    if path.exists():
        for l in path.read_text().splitlines():
            rec = json.loads(l)
            cache[rec['key']] = rec

    def call(key, prompt):
        if key in cache:
            return cache[key]['response']
        with (OUT / 'REQUESTS.jsonl').open('a') as f:
            f.write(json.dumps(dict(key=key, model=MODEL,
                                    prompt_sha256=__import__('hashlib').sha256(
                                        prompt.encode()).hexdigest(),
                                    unix_time=time.time())) + '\n')
        resp = engine.call_model(MODEL, prompt)
        rec = dict(key=key, model=MODEL, response=resp)
        with path.open('a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        cache[key] = rec
        return resp

    with (ROOT / 'collect/logs/local_gpu.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proc = log = None
        try:
            proc, log, _ = engine.start_model(MODEL)
            contracts = {}
            for r in panel:
                uid = r['uid']
                node = rs[uid]
                resp = call(f'p1b2:v{PROMPT_VERSION}:{phase}:{uid}',
                            contract_prompt(node['question'], node['gold_facts']))
                c = parse_contract(resp.get('answer'))
                expr = compile_contract(c, len(node['gold_facts']['facts'])) if c else None
                val = None
                if expr:
                    try:
                        val = exec_calc(expr, node['gold_facts'])
                    except Exception:
                        val = None
                contracts[uid] = dict(uid=uid, family=c['family'] if c else 'unparseable',
                                      contract=c, expr=expr, value=val,
                                      abstain=c is None or expr is None,
                                      tokens=float(resp.get('usage', {}).get('total_tokens', 0)),
                                      latency=float(resp.get('latency_s', 0)))
            out = dict(phase=phase, n=len(panel), model=MODEL, prompt=PROMPT, families=FAMILIES,
                       abstain=sum(c['abstain'] for c in contracts.values()),
                       contracts=contracts)
            (OUT / f'CONTRACTS_{phase}_v{PROMPT_VERSION}.json').write_text(json.dumps(out, indent=1))
            print(json.dumps(dict(phase=phase, n=len(panel), abstain=out['abstain'],
                                  executable=sum(c['expr'] is not None for c in contracts.values()))))
        finally:
            if proc is not None:
                engine.stop_model(proc, log)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('phase', choices=['dev', 'test'])
    a = ap.parse_args()
    run(a.phase)
