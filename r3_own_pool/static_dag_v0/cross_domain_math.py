"""P3 cross-domain: Math500 six-arm panel — zero-call audit + freeze (no model calls).

RQs (pre-registered):
  RQ1 stage-wise complementarity: does the best staged DAG assignment exceed BOTH
     single-model baselines (paired, per-task)?
  RQ2 node/type routing > query routing: staged assignment vs frozen length-based
     query router (paired per-task)?
  RQ3 Dynamic-Real vs Static: does deployable-feedback dynamic improve at least
     one of Q / C / L (with paired CI + McNemar for Q)?

Six arms (all share frozen prompts, models, generation, deployable failure
detection — NO gold answer is ever used at runtime):
  always_medium      mono, medium
  always_large       mono, large
  query_router       mono, model = large iff tokenized problem length > frozen
                     panel median (threshold computed at freeze time)
  type_node_router   DAG extract(large)->solve(medium)->verify(coder), one call
                     per node, no recovery (pure assignment quality)
  static_dag         same DAG + frozen fallbacks (extract->coder, solve->coder,
                     verify->medium) + descendant refresh, deployable detection
  dynamic_real       same DAG + failure-memory extraction switch (coder then
                     medium), solve/verify escalate to large, budget-gated
                     (per-task budget = 1.2 x static realized), selective refresh
Oracle: finite candidate oracle = per-task max over the six arms' outcomes;
never presented as a global optimum.

Scoring: answer normalizer (LaTeX-tolerant float or safe arithmetic eval) and
tolerance max(1e-4, 1e-4*|gold|); task success = final node (verify for DAG
arms, mono answer otherwise) close to gold.
"""
import ast
import hashlib
import json
import re
import time
from pathlib import Path

from . import core

BASE = core.ROOT / 'static_dag_v0'
OUT = BASE / 'cross_domain_math'
DATA_GLOB = '/root/autodl-tmp/llmrouterbench_r2_data/bench-release/math500/test/*/*.json'
N_TASKS = 200
HEADROOM = 1.2
GATE = 200

MONO = ('Solve the math problem. Think as needed, then give ONLY the final numeric answer on the last line '
        'in the format: Answer: <number>\nPROBLEM:\n{q}')
EXTRACT = ('Extract every explicit numeric quantity in the problem that is relevant to solving it, with its '
           'meaning. Return ONLY JSON {{"facts":[{{"value":<number>,"evidence":"<short description>"}}]}} with '
           'at most 12 facts; values as plain numbers (convert percentages and units to plain numbers).\nPROBLEM:\n{q}')
SOLVE = ('Choose the arithmetic computation that answers the math problem using the extracted facts. Return ONLY '
         'JSON {{"expression":"..."}}. Reference fact values as v0,v1,... in their listed order. Allowed operators: '
         '+ - * / and parentheses; any explicit numeric constants are permitted. Do not do the arithmetic.\n'
         'PROBLEM: {q}\nFACTS: {facts}')
VERIFY = ('You are verifying a computed answer for a math problem. Given the extracted facts and a proposed '
          'expression, check that every referenced value binds to the correct fact and that the arithmetic is '
          'right, recompute independently, then return ONLY JSON {{"value": <number>}} with the corrected final '
          'numeric value.\nQUESTION: {q}\nFACTS: {facts}\nPROPOSED EXPRESSION: {expr}')


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def latex_to_expr(s):
    s = re.sub(r'\\left|\\right|\\!|\\,|\$|\\%|\^\\circ|\\circ', '', s or '')
    s = re.sub(r'\\text\{[^}]*\}', '', s)
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'((\1)/(\2))', s)
    return s.replace('{', '(').replace('}', ')').replace(',', '').replace('^', '**').strip()


_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Add,
            ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd)


def normalize_answer(gt):
    """Frozen scorer-side normalizer: LaTeX-tolerant float or safe arithmetic eval."""
    s = latex_to_expr(gt)
    try:
        v = float(s)
        return v if v == v and abs(v) != float('inf') else None
    except ValueError:
        pass
    try:
        tree = ast.parse(s, mode='eval')
        for n in ast.walk(tree):
            if not isinstance(n, _ALLOWED):
                return None
        v = eval(compile(tree, '<gt>', 'eval'))
        return float(v) if isinstance(v, (int, float)) and float(v) == float(v) and abs(float(v)) != float('inf') else None
    except Exception:
        return None


def extract_mono_value(text):
    m = re.findall(r'Answer:\s*(-?[\d,]+(?:\.\d+)?)', text or '') or \
        re.findall(r'(-?[\d,]+(?:\.\d+)?)\s*$', (text or '').strip())
    if not m:
        return None
    try:
        return float(m[-1].replace(',', ''))
    except Exception:
        return None


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def load_records():
    import glob as g
    files = sorted(g.glob(DATA_GLOB))
    d = json.load(open(files[0]))
    return files[0], hashlib.sha256(Path(files[0]).read_bytes()).hexdigest(), d['records']


def audit_and_freeze():
    f, fsha, records = load_records()
    seen = set()
    rows = []
    for r in records:
        gold = normalize_answer(r['ground_truth'])
        if gold is None:
            continue
        q = re.sub(r'\s+', ' ', r['origin_query']).strip().lower()
        if q in seen:
            continue
        seen.add(q)
        rows.append(dict(index=r['index'], question=r['origin_query'],
                         gold=gold, gold_raw=r['ground_truth']))
    OUT.mkdir(parents=True, exist_ok=True)
    audit = dict(
        generated_unix=time.time(),
        source_file=str(f), source_sha256=fsha, dataset='math500', split='test',
        total_records=len(records), numeric_normalizable=len(rows),
        duplicates_removed=len(records) - len(rows),
        exposure=('bench-release math500 contains third-party model response collections from an earlier '
                  'router-benchmark project; the present 3-model pool (Qwen2.5 7B/14B/coder) has never been '
                  'run on these tasks, and no component of this paper was tuned on math500'),
        normalizer='strip LaTeX spacing/degree markers/text; \\frac{a}{b} -> (a)/(b); float parse else '
                   'whitelisted-AST arithmetic eval; rejects symbolic (pi, sqrt, i), tuples, text, equations')
    (OUT / 'CROSS_DOMAIN_MATH_AUDIT.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))

    # frozen panel: sha256("xmath:"+index) ascending, first N_TASKS
    rows.sort(key=lambda t: sha('xmath:' + str(t['index'])))
    panel = rows[:N_TASKS]
    assert len(panel) == N_TASKS
    # query-router threshold: median tokenized length computed at freeze time
    from . import run as engine
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'], local_files_only=True)
    lens = [len(tok.apply_chat_template([dict(role='user', content=t['question'])], tokenize=True,
                                        add_generation_prompt=True)) for t in panel]
    lens_sorted = sorted(lens)
    median = lens_sorted[len(lens) // 2]
    json.dump([dict(index=t['index'], question=t['question'], gold=t['gold'], gold_raw=t['gold_raw'],
                    tok_len=l) for t, l in zip(panel, lens)],
              open(OUT / 'frozen_math_tasks.json', 'w'), ensure_ascii=False, indent=1)
    protocol = dict(
        role='cross_domain_math_six_arm_one_shot', n_tasks=N_TASKS,
        panel='sha256("xmath:"+index) ascending over numeric-normalizable deduped tasks',
        models=dict(medium='Qwen2.5-7B-Instruct', large='Qwen2.5-14B-Instruct-GPTQ-Int8',
                    coder='Qwen2.5-Coder-7B-Instruct'),
        generation='temperature 0, top_p 1, max_tokens 512, vLLM local',
        prompts=dict(mono=MONO, extract=EXTRACT, solve=SOLVE, verify=VERIFY),
        arms=dict(
            always_medium='mono medium; success = Answer: <number> close to gold',
            always_large='mono large',
            query_router=f'mono; model = large iff tok_len > {median} (frozen panel median at freeze time) else medium',
            type_node_router='DAG extract(large)->solve(medium)->verify(coder), one call per node, NO recovery; success = verify value close to gold',
            static_dag='same DAG; deployable failure detection; fallbacks extract->coder, solve->coder, verify->medium; descendant closure refresh',
            dynamic_real='same DAG; deployable detection; extraction memory switch (first failure->coder, later->medium in task order); solve/verify escalate to large, budget-gated (B_rem<200 skip+record); budget = 1.2 x static realized; selective refresh'),
        failure_detection_deployable=dict(
            extract='facts unparseable or empty', solve='expression unparseable or unexecutable on facts',
            verify='value unparseable or disagrees with solve value (tolerance 1e-4 rel)'),
        no_gold_runtime=True,
        oracle='finite candidate oracle: per-task max over the six arms; not a global optimum',
        metrics=['accuracy', 'tokens', 'observed service latency', 'help/harm (dynamic vs static)',
                 'paired dQ with task bootstrap CI (B=10000, seed 20260918)', 'McNemar exact',
                 'budget violations', 'dynamic intervention rate'],
        rq_operationalization=dict(
            RQ1='staged DAG assignment (best of type_node/static) exceeds BOTH always_medium and always_large (paired CI)',
            RQ2='type_node_router (and static_dag) exceed query_router (paired CI)',
            RQ3='dynamic_real improves static_dag on >=1 of Q/C/L; Q compared with paired CI + McNemar'),
        one_shot='no threshold, prompt, task, or detector change after any result is seen')
    (OUT / 'CROSS_DOMAIN_MATH_PROTOCOL.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, n=N_TASKS, numeric_pool=len(rows), median_len=median,
                          source_sha=fsha[:12])))


if __name__ == '__main__':
    audit_and_freeze()
