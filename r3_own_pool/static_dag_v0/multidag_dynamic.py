"""Multi-node live DAG: Static vs Dynamic — branch, join, and tail (pre-registered).

Motivation (P1): prior live Dynamic evidence used 2-node chains (extraction ->
reasoning). This experiment builds a real 4-node DAG per task with a structural
branch, a join, and a tail node:

    e1 (table facts, large)  ->  r (join expression, medium)  ->  v (verify, coder)
    e2 (text facts, large)   ->  r

Branch is structurally non-degenerate: only tasks whose gold answer requires
BOTH the table and the text region (TAT-QA answer_from == 'table-text'), so a
failure in e1 leaves e2's output just as necessary and vice versa.

Dynamic vs Static: identical initial assignment, prompts, generation, and
per-task budget rule (1.2 x Static realized). Both arms re-execute ONLY the
descendant closure of any node whose output changed (selective update; the
unaffected branch is never re-run). Arms differ only in the frozen adaptation
rules:
  static : one local fallback per failed node (e: large->coder; r: medium->coder;
           v: coder->medium); descendant closure re-executed with planned models.
  dynamic: extraction fallback follows failure memory (first primary extraction
           failure -> coder, later ones -> medium, task order); r failure
           escalates to large; v failure escalates to large; escalations are
           budget-gated (skip + record when B_rem < 200 tokens).
Failure detection is IDEAL (evaluation answer), matching the stated regime of
the 48/250-task panels; a deployable detector is a separate experiment (P2).

Preregistered readout: paired delta-Q task bootstrap CI, McNemar exact,
Help/Harm, tokens, latency, budget violations, selective-update audit
(re-executed set == descendant closure on every event), propagation length.
One-shot; no threshold may be changed after results are seen.
"""
import fcntl
import hashlib
import json
import os
import re
import time

from . import core, run as engine
from . import tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .confirm_dynamic_v2 import used_uids
from .tatqa_benchmark_build import literals

BASE = core.ROOT / 'static_dag_v0'
OUT = BASE / 'multidag_dynamic_120'
N_TASKS = 120
HEADROOM = 1.2
GATE = 200
FROZEN_REF = 'live_static_dynamic 8417776 semantics extended to a 4-node DAG'

VPROMPT = ('You are verifying a computed answer for a financial question. Given the extracted facts and a '
           'proposed expression, check that every referenced value binds to the correct fact and that the '
           'arithmetic is right, recompute independently, then return ONLY JSON {{"value": <number>}} with the '
           'corrected final value (preserve reported units; percentages as ratios x100).\n'
           'QUESTION: {q}\nFACTS: {facts}\nPROPOSED EXPRESSION: {expr}')

CLOSURE = {'e1': ['r', 'v'], 'e2': ['r', 'v'], 'r': ['v'], 'v': []}


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def close(a, b):
    return a is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def ctx_table(para):
    txt = []
    for row in para['table']['table']:
        cells = [str(c).replace('\n', ' ').strip() for c in row]
        if any(cells):
            txt.append(' | '.join(cells))
    return 'TABLE:\n' + '\n'.join(txt)


def ctx_text(para):
    return 'PASSAGES:\n' + '\n'.join(f'[{i}] ' + (x.get('text', str(x)) if isinstance(x, dict) else str(x)) for i, x in enumerate(para['paragraphs']))


def hybrid_pool():
    rows = json.loads((core.ROOT / 'data/tatqa/tatqa_dataset_train.json').read_text())
    seen = used_uids()
    out = []
    for para in rows:
        for q in para['questions']:
            d = (q.get('derivation') or '').strip()
            if q.get('answer_from') != 'table-text': continue
            if q.get('answer_type') != 'arithmetic' or not d or not re.search(r'[+\-*/]', d): continue
            lits = [x for x in literals(d) if x not in (0.0, 1.0, 100.0)]
            if len(set(lits)) < 2 or q['uid'] in seen: continue
            try: gold = eval(d, {'__builtins__': {}}, {})
            except Exception: continue
            if not isinstance(gold, (int, float)): continue
            out.append(dict(uid=q['uid'], question=q['question'], derivation=d, answer=float(gold), para=para))
    return out


def freeze():
    pool = hybrid_pool()
    from . import run as eng
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(eng.MODELS['medium']['path'], local_files_only=True)
    sized = []
    for t in pool:
        blob = t['question'] + json.dumps(t['para']['table']['table']) + ' '.join(x.get('text', str(x)) if isinstance(x, dict) else str(x) for x in t['para']['paragraphs'])
        if len(tok.apply_chat_template([dict(role='user', content=blob)], tokenize=True, add_generation_prompt=True)) + 512 <= 8192:
            sized.append(t)
    sized.sort(key=lambda t: sha('multidag:' + t['uid']))
    assert len(sized) >= N_TASKS, len(sized)
    sel = sized[:N_TASKS]
    for t in sel:
        t['ctx_table'] = ctx_table(t['para'])
        t['ctx_text'] = ctx_text(t['para'])
        del t['para']
    policy = dict(role='multinode_dag_static_vs_dynamic_one_shot', frozen_ref=FROZEN_REF,
                  n_tasks=len(sel), fresh_pool=len(sized),
                  selection='sha256("multidag:"+uid) ascending; fresh TAT-QA train; answer_from=table-text; zero overlap with any workspace artifact (UUID superset scan, includes confirm_250)',
                  dag='e1(table facts,large) + e2(text facts,large) -> r(join expression, medium) -> v(verify value, coder); task success = v value close to gold (1e-4 rel)',
                  failure_detection='IDEAL (evaluation answer); deployable detector is a separate pre-registered experiment',
                  static_rules='per failed node one local fallback: e large->coder, r medium->coder, v coder->medium; descendant closure re-executed with planned models',
                  dynamic_rules='e fallback: first primary failure -> coder, later ones -> medium (task-order memory); r failure -> escalate large; v failure -> escalate large; escalations budget-gated (B_rem<200 skip+record); descendant closure only',
                  budget='per-task = 1.2 x Static arm realized tokens; recomputed after every dynamic-arm call',
                  generation='temperature 0, top_p 1, max_tokens 512 via run.call_model',
                  metrics_preregistered='paired dQ bootstrap CI, McNemar exact, Help/Harm, tokens, latency, budget violations, selective-update audit, propagation length',
                  tasks=sel)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, n=len(sel), fresh_pool=len(sized)), ensure_ascii=False))


def append(path, obj):
    with path.open('a') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n'); f.flush(); os.fsync(f.fileno())


class Caller:
    def __init__(self):
        self.proc = self.log = None; self.current = None; self.cache = {}
        if (OUT / 'RESPONSES.jsonl').exists():
            for l in (OUT / 'RESPONSES.jsonl').read_text().splitlines():
                r = json.loads(l); self.cache[r['key']] = r
        self.lock = (core.ROOT / 'collect/logs/local_gpu.lock').open('a+')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def call(self, key, model, prompt):
        if key in self.cache:
            if self.cache[key]['response'].get('status') != 'delivered':
                raise RuntimeError('cached infra failure: ' + key)
            return self.cache[key]
        if model != self.current:
            if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = self.log = None
            self.proc, self.log, _ = engine.start_model(model); self.current = model
        append(OUT / 'REQUESTS.jsonl', dict(key=key, model=model, prompt=prompt))
        resp = engine.call_model(model, prompt)
        rec = dict(key=key, model=model, response=resp); append(OUT / 'RESPONSES.jsonl', rec)
        self.cache[key] = rec
        if resp.get('status') != 'delivered': raise RuntimeError('Infrastructure failure: ' + key)
        return rec

    def close(self):
        if self.proc is not None: engine.stop_model(self.proc, self.log); self.proc = None
        try: fcntl.flock(self.lock, fcntl.LOCK_UN)
        except Exception: pass
        self.lock.close()


def parse_facts_safe(ans):
    try: return v.parse_facts(ans), False
    except Exception: return {'facts': []}, True


def value_of(ans, facts):
    try: return exec_calc(v.decode(ans)['expression'], facts), False
    except Exception: return None, True


def json_value(ans):
    try: return float(json.loads(ans)['value'])
    except Exception:
        try: return float(json.loads(v.decode(ans))['value'])
        except Exception: return None


def cost_of(cache, key):
    r = cache.get(key)
    return float((r['response'].get('usage') or {}).get('total_tokens') or 0) if r else 0.0


def run():
    if not (OUT / 'POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    if (OUT / 'DONE.json').exists(): raise FileExistsError('multidag run complete')
    engine.OUT = OUT
    caller = Caller()
    t0 = time.time()
    try:
        # ---------- shared initial passes ----------
        for t in tasks:
            for node, ctx in (('e1', t['ctx_table']), ('e2', t['ctx_text'])):
                k = f'{node}:{t["uid"]}'
                if k not in caller.cache:
                    caller.call(k, 'large', v.eprompt(dict(question=t['question'], context=ctx)))
        init = {}
        for t in tasks:
            uid = t['uid']
            f1, bad1 = parse_facts_safe(caller.cache[f'e1:{uid}']['response']['answer'])
            f2, bad2 = parse_facts_safe(caller.cache[f'e2:{uid}']['response']['answer'])
            init[uid] = dict(f1=f1, f2=f2, bad1=bad1, bad2=bad2)
        for t in tasks:
            uid = t['uid']
            if f'r:{uid}' not in caller.cache:
                merged = {'facts': init[uid]['f1']['facts'] + init[uid]['f2']['facts']}
                caller.call(f'r:{uid}', 'medium', v.sprompt(dict(question=t['question']), merged))
        for t in tasks:
            uid = t['uid']
            if f'v:{uid}' not in caller.cache:
                merged = {'facts': init[uid]['f1']['facts'] + init[uid]['f2']['facts']}
                val, err = value_of(caller.cache[f'r:{uid}']['response']['answer'], merged)
                expr = 'UNPARSEABLE' if err else v.decode(caller.cache[f'r:{uid}']['response']['answer'])['expression']
                caller.call(f'v:{uid}', 'coder', VPROMPT.format(q=t['question'], facts=json.dumps(merged['facts']), expr=expr))
        # ---------- per-arm adaptation ----------
        state = {'static': {}, 'dynamic': {}}
        for arm in state:
            for t in tasks:
                uid = t['uid']
                state[arm][uid] = dict(e1=init[uid]['f1'], e2=init[uid]['f2'],
                                       keys=[f'e1:{uid}', f'e2:{uid}', f'r:{uid}', f'v:{uid}'],
                                       events=[], expr_text=None)
        FALLBACK = {'static': {'e': 'coder', 'r': 'coder', 'v': 'medium'},
                    'dynamic': {'e': 'coder', 'r': 'large', 'v': 'large'}}
        for arm in ('static', 'dynamic'):
            n_ext_fail_seen = 0
            for t in tasks:
                uid = t['uid']; st = state[arm][uid]

                def merged():
                    return {'facts': st['e1']['facts'] + st['e2']['facts']}

                def latest(prefix):
                    ks = [k for k in st['keys'] if k.split(':')[0] == prefix]
                    return ks[-1]

                def do(node, model, kind, gate_info=None):
                    """Re-execute node with model; then re-execute descendant closure.
                    Returns the list of executed keys (node first, then closure)."""
                    executed = []
                    k = f'{node}:{arm}:{uid}:{kind}'
                    if node in ('e1', 'e2'):
                        ctx = t['ctx_table'] if node == 'e1' else t['ctx_text']
                        caller.call(k, model, v.eprompt(dict(question=t['question'], context=ctx)))
                        fnew, _ = parse_facts_safe(caller.cache[k]['response']['answer'])
                        st[node] = fnew
                    elif node == 'r':
                        caller.call(k, model, v.sprompt(dict(question=t['question']), merged()))
                    else:
                        caller.call(k, model, VPROMPT.format(q=t['question'], facts=json.dumps(merged()['facts']),
                                                             expr=st['expr_text'] or 'UNPARSEABLE'))
                    st['keys'].append(k); executed.append(k)
                    ev = dict(node=node, kind=kind, model=model, attempted=True,
                              closure=CLOSURE[node], gate=gate_info)
                    for dn in CLOSURE[node]:
                        if dn == 'r':
                            dk = f'r:{arm}:{uid}:{kind}-d'
                            caller.call(dk, 'medium', v.sprompt(dict(question=t['question']), merged()))
                            val, err = value_of(caller.cache[dk]['response']['answer'], merged())
                            st['expr_text'] = 'UNPARSEABLE' if err else v.decode(caller.cache[dk]['response']['answer'])['expression']
                        else:
                            dk = f'v:{arm}:{uid}:{kind}-d'
                            caller.call(dk, 'coder', VPROMPT.format(q=t['question'], facts=json.dumps(merged()['facts']),
                                                                    expr=st['expr_text'] or 'UNPARSEABLE'))
                        st['keys'].append(dk); executed.append(dk)
                    ev['executed'] = executed
                    st['events'].append(ev)

                # --- extraction failures (topological order e1 -> e2) ---
                for node in ('e1', 'e2'):
                    if st[node]['facts']:
                        continue
                    if arm == 'dynamic':
                        model = 'medium' if n_ext_fail_seen > 0 else FALLBACK['dynamic']['e']
                        n_ext_fail_seen += 1
                    else:
                        model = FALLBACK['static']['e']
                    do(node, model, 'fb')
                # --- r failure ---
                rval, rerr = value_of(caller.cache[latest('r')]['response']['answer'], merged())
                rok = (not rerr) and close(rval, t['answer'])
                st['expr_text'] = 'UNPARSEABLE' if rerr else v.decode(caller.cache[latest('r')]['response']['answer'])['expression']
                if not rok:
                    if arm == 'dynamic':
                        budget = sum(cost_of(caller.cache, k) for k in state['static'][uid]['keys']) * HEADROOM
                        rem = budget - sum(cost_of(caller.cache, k) for k in st['keys'])
                        if rem < GATE:
                            st['events'].append(dict(node='r', kind='escalation', model='large',
                                                     attempted=False, closure=CLOSURE['r'], gate=dict(rem=rem, reason='budget')))
                        else:
                            do('r', 'large', 'esc')
                    else:
                        do('r', FALLBACK['static']['r'], 'fb')
                    rval, rerr = value_of(caller.cache[latest('r')]['response']['answer'], merged())
                    st['expr_text'] = 'UNPARSEABLE' if rerr else v.decode(caller.cache[latest('r')]['response']['answer'])['expression']
                # --- v failure ---
                vval = json_value(caller.cache[latest('v')]['response']['answer'])
                vok = close(vval, t['answer'])
                if not vok:
                    if arm == 'dynamic':
                        budget = sum(cost_of(caller.cache, k) for k in state['static'][uid]['keys']) * HEADROOM
                        rem = budget - sum(cost_of(caller.cache, k) for k in st['keys'])
                        if rem < GATE:
                            st['events'].append(dict(node='v', kind='escalation', model='large',
                                                     attempted=False, closure=CLOSURE['v'], gate=dict(rem=rem, reason='budget')))
                        else:
                            do('v', 'large', 'esc')
                    else:
                        do('v', FALLBACK['static']['v'], 'fb')
                    vval = json_value(caller.cache[latest('v')]['response']['answer'])
                    vok = close(vval, t['answer'])
                st['r_ok'] = bool(rok)
                st['ok'] = bool(vok)
                st['used'] = sum(cost_of(caller.cache, k) for k in st['keys'])
        raw = dict(wall_seconds=time.time() - t0,
                   static={u: {k: v for k, v in s.items() if k != 'expr_text'} for u, s in state['static'].items()},
                   dynamic={u: {k: v for k, v in s.items() if k != 'expr_text'} for u, s in state['dynamic'].items()},
                   init_bad={t['uid']: dict(bad1=init[t['uid']]['bad1'], bad2=init[t['uid']]['bad2']) for t in tasks})
        core.write(OUT / 'RAW_TAIL.json', raw)
        core.write(OUT / 'DONE.json', dict(unix_time=time.time(), wall_seconds=time.time() - t0, calls=len(caller.cache)))
        print(json.dumps(dict(done=True, calls=len(caller.cache), wall_seconds=round(time.time() - t0)), ensure_ascii=False))
    finally:
        caller.close()


if __name__ == '__main__':
    run()
