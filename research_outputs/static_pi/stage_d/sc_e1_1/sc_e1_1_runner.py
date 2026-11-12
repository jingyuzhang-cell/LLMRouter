#!/usr/bin/env python3
"""SC-E1.1 runner: plumbing repair of sc_e1_runner.py (three-arm canary only).

E/J1/J2/SINK system prompts are reused byte-identically from sc_e1_runner.py. The default is a
dry run on the offline mock. Real calls need --real, SC_E1_1_CANARY_GO=1 and --freeze <sha256 of
FREEZE.json>, and only Stage A may run for real: Stage B and the formal experiment are on HOLD
(P2_AMENDMENT_SC_E1_1.md). Stage B exists here only to test arm logic on the mock.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent), '/root/capital_opinion_pilot']
import sc_e1_runner as OLD  # noqa: E402
import sc_e1_scorer as SC  # noqa: E402
import transport as DS_TRANSPORT  # noqa: E402

E_SYS, J1_SYS, J2_SYS, SINK_SYS = OLD.E_SYS, OLD.J1_SYS, OLD.J2_SYS, OLD.SINK_SYS
E_SYS_DEGRADED = (E_SYS.replace('name, penalty_amount, penalty_type, position, quote', 'name, position, quote')
                  .replace(', "quotes": [...]', ''))
J1_REPAIR_SYS = J1_SYS + '\n请务必输出完整JSON。'

ARMS = ('Static', 'Fixed-Recovery', 'Joint-Dynamic')
J1_DEFAULT_BACKEND, J1_ALT_BACKEND = 'glm', 'ds'
MAX_TOKENS = {'E': 8000, 'J1': 8000, 'J2': 4000, 'SINK': 4000}
REQUIRED_KEYS = {'E': ('parties',), 'J1': ('party_matrix',), 'J2': ('verified',), 'SINK': ('answers',)}
PRICE_IN, PRICE_OUT = 0.8e-6, 2.8e-6
GLM_MODEL = 'GLM-5.3-Flash'
DS_MODEL, DS_BASE, DS_KEY_ENV = DS_TRANSPORT.OPENAI_MODELS['deepseek']
MODEL_FAMILY = {'ds': 'deepseek', 'glm': 'glm'}
# Anthropic-format usage reports cached input outside input_tokens, and J1 repeats one prompt across arms.
GLM_INPUT_USAGE_KEYS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
# Far below any Chinese-dominant prompt: a lower count means the provider dropped input silently.
MIN_INPUT_TOKENS_PER_CHAR = 0.25
# Pessimistic: the pre-flight must overestimate input so a cap cannot be crossed.
PREFLIGHT_TOKENS_PER_CHAR = 0.8
REAL_STAGES = ('A',)

# Caps equal the authorized limits. Stage A takes no recovery action, so 11 calls is its maximum in
# practice; 13 stays the hard limit the operator set.
STAGES = {
    'A': dict(conditions=('normal',), calls=13, tokens=230_000, yuan=0.30, allow_recovery=False),
    'B': dict(conditions=('exec_anomaly', 'info_anomaly'), calls=23, tokens=380_000, yuan=0.60, allow_recovery=True),
}

NONE, RETRY, SWAP, REEXTRACT = 'none', 'repair_retry', 'swap_model', 'reextract_upstream'
MIN_FINAL_COVERAGE = 0.25
Obs = namedtuple('Obs', 'j1_fault final_coverage e_d2_penalty_signal')


class Stop(Exception):
    """Infrastructure or natural-fault stop: keep the scene, no retry, no backfill."""


class RealTransport:
    """Request bodies match transport.openai_call (DS) and glm_low (GLM) byte for byte; unlike those it
    returns the raw response so the ledger can keep it."""

    @staticmethod
    def _request(backend, system, user, max_tokens):
        if backend == 'ds':
            body = {'model': DS_MODEL, 'max_tokens': max_tokens,
                    'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                    'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}, 'temperature': 0}
            return DS_BASE + '/chat/completions', body, json.dumps(body).encode()
        body = {'model': GLM_MODEL, 'max_tokens': max_tokens, 'system': system,
                'messages': [{'role': 'user', 'content': user}], 'reasoning_effort': 'low'}
        return OLD.GLM_URL, body, json.dumps(body, ensure_ascii=False).encode()

    def describe(self, backend, system, user, max_tokens):
        url, body, _ = self._request(backend, system, user, max_tokens)
        return url, body

    def call(self, backend, system, user, max_tokens):
        url, _, data = self._request(backend, system, user, max_tokens)
        req = urllib.request.Request(url, data=data, method='POST')
        if backend == 'ds':
            req.add_header('Content-Type', 'application/json')
            req.add_header('Authorization', 'Bearer ' + os.environ[DS_KEY_ENV])
        else:
            key = os.environ['STAGE_D_GLM_KEY'].strip()
            for name, val in (('content-type', 'application/json'), ('x-api-key', key),
                              ('authorization', 'Bearer ' + key), ('anthropic-version', '2023-06-01')):
                req.add_header(name, val)
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.loads(r.read().decode())
        lat = round(time.monotonic() - t0, 2)
        usage = raw.get('usage') or {}
        if backend == 'ds':
            choice = raw['choices'][0]
            text = choice['message'].get('content') or ''
            if isinstance(text, list):
                text = ''.join(x.get('text', '') for x in text if isinstance(x, dict))
            stop, tin, tout = choice.get('finish_reason', ''), usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0)
        else:
            blocks = raw.get('content', [])
            text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            stop, tin, tout = raw.get('stop_reason'), sum(usage.get(k) or 0 for k in GLM_INPUT_USAGE_KEYS), usage.get('output_tokens', 0)
        return dict(text=text, stop=stop, lat=lat, response_model=raw.get('model'), usage_raw=usage,
                    raw_response=raw, **{'in': tin, 'out': tout})


class Budget:
    """Costs are booked at the accounting price on every backend; GLM's marginal subscription cost is ¥0."""

    def __init__(self, calls, tokens, yuan):
        self.caps = dict(calls=calls, tokens=tokens, yuan=yuan)
        self.calls, self.tokens, self.yuan, self.yuan_marginal = 0, 0, 0.0, 0.0

    def preflight(self, backend, system, user, max_tokens):
        est_in = int((len(system) + len(user)) * PREFLIGHT_TOKENS_PER_CHAR)
        if self.calls + 1 > self.caps['calls']:
            raise Stop(f'call cap {self.caps["calls"]} reached')
        if self.tokens + est_in + max_tokens > self.caps['tokens']:
            raise Stop(f'token pre-flight: {self.tokens}+{est_in}+{max_tokens} > {self.caps["tokens"]}')
        if self.yuan + est_in * PRICE_IN + max_tokens * PRICE_OUT > self.caps['yuan']:
            raise Stop(f'yuan pre-flight exceeds {self.caps["yuan"]}')

    def book(self, backend, tin, tout):
        cost = tin * PRICE_IN + tout * PRICE_OUT
        self.calls += 1
        self.tokens += tin + tout
        self.yuan += cost
        if backend == 'ds':
            self.yuan_marginal += cost
        return round(cost, 8)

    def reached(self):
        for name, used in (('calls', self.calls), ('tokens', self.tokens), ('yuan', self.yuan)):
            if used >= self.caps[name]:
                return f'{name} cap reached: {used} >= {self.caps[name]}'
        return None


class Ledger:
    """Append-only. A 'sent' row with the full payload is on disk before each request leaves, and a
    'done' row with the response, usage, model identity, cost and node output follows it."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, rec):
        with self.path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')


def read_ledger(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text('utf-8').splitlines()] if path.exists() else []


def ledger_integrity(path):
    rows = read_ledger(path)
    key = lambda r: (r['condition'], r['arm'], r['node'], r['user_sha256'])
    sent = [r for r in rows if r['phase'] == 'sent']
    done = [r for r in rows if r['phase'] == 'done' and not r['injected']]
    if not sent or [key(r) for r in sent] != [key(r) for r in done]:
        return False
    answered = [r for r in done if r['stop'] != 'transport_error']
    return all(r.get('request_body') for r in done) and all(
        r.get('raw_response') is not None and r.get('usage_raw') is not None and 'response_model' in r
        and r.get('yuan_accounting') is not None and 'text' in r for r in answered)


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def guard(node, res):
    """Contract guard: returns (fault_kind | None, parsed)."""
    text = res.get('text') or ''
    if res.get('stop') in ('length', 'max_tokens'):
        return 'truncated', None
    if res.get('stop') not in ('stop', 'end_turn'):
        return 'abnormal_stop', None
    if not text.strip():
        return 'empty_text', None
    parsed = OLD.extract_json(text)
    if parsed is None:
        return 'json_invalid', None
    base = node.split('_')[0]
    if any(k not in parsed for k in REQUIRED_KEYS[base]):
        return 'schema_invalid', None
    return None, parsed


NodeOut = namedtuple('NodeOut', 'text parsed fault')


def frozen_request(condition, node):
    """(backend, system prompt, max_tokens) the frozen configuration allows for a node."""
    e_d2 = E_SYS_DEGRADED if condition == 'info_anomaly' else E_SYS
    route = {'E_D1': ('ds', E_SYS), 'E_D2': ('ds', e_d2), 'J1': (J1_DEFAULT_BACKEND, J1_SYS), 'J2': ('ds', J2_SYS),
             'SINK': ('ds', SINK_SYS), 'J1_retry': (J1_DEFAULT_BACKEND, J1_REPAIR_SYS),
             'J1_swap': (J1_ALT_BACKEND, J1_SYS), 'E_D2_reextract': ('ds', E_SYS),
             'J1_rerun': (J1_DEFAULT_BACKEND, J1_SYS)}
    backend, system = route[node]
    return backend, system, MAX_TOKENS[node.split('_')[0]]


class Env:
    """Execution environment. It alone knows the injected condition; policies only see Obs."""

    def __init__(self, transport, ledger, budget, condition, rep):
        self.transport, self.ledger, self.budget = transport, ledger, budget
        self.condition, self.rep = condition, rep
        self.arm = 'shared'

    def call(self, node, backend, system, user):
        max_tokens = MAX_TOKENS[node.split('_')[0]]
        if (backend, system, max_tokens) != frozen_request(self.condition, node):
            raise Stop(f'{node}: request differs from the frozen configuration (backend={backend}, '
                       f'max_tokens={max_tokens}, system_sha256={_sha(system)[:16]})')
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), condition=self.condition, rep=self.rep, arm=self.arm,
                   node=node, backend=backend, max_tokens=max_tokens, system_sha256=_sha(system),
                   user_sha256=_sha(user), chars_in=len(system) + len(user))
        if self.condition == 'exec_anomaly' and node == 'J1':
            self.ledger.write({**rec, 'phase': 'done', 'injected': True, 'request_body': None, 'raw_response': None,
                               'text': '', 'stop': 'injected_empty', 'in': 0, 'out': 0, 'yuan_accounting': 0.0,
                               'fault': 'empty_text'})
            return NodeOut('', None, 'empty_text')

        self.budget.preflight(backend, system, user, max_tokens)
        url, body = self.transport.describe(backend, system, user, max_tokens)
        rec.update(injected=False, url=url, request_body=body)
        self.ledger.write({**rec, 'phase': 'sent'})
        try:
            res = self.transport.call(backend, system, user, max_tokens)
        except Exception as exc:
            self.budget.book(backend, 0, 0)
            detail = f'{type(exc).__name__}: {exc}'[:300]
            error_body = getattr(exc, 'read', lambda: b'')()
            self.ledger.write({**rec, 'phase': 'done', 'raw_response': None, 'text': '', 'stop': 'transport_error',
                               'error': detail, 'error_body': error_body.decode('utf-8', 'replace')[:2000] if error_body else None})
            raise Stop(f'{node}/{backend} transport error: {detail}') from exc

        cost = self.budget.book(backend, res['in'], res['out'])
        fault, parsed = guard(node, res)
        self.ledger.write({**rec, 'phase': 'done', 'raw_response': res.get('raw_response'),
                           'response_model': res.get('response_model'), 'usage_raw': res.get('usage_raw'),
                           'text': res.get('text', ''), 'stop': res.get('stop'), 'in': res['in'], 'out': res['out'],
                           'lat': res.get('lat'), 'yuan_accounting': cost,
                           'yuan_marginal': cost if backend == 'ds' else 0.0, 'fault': fault})
        if fault:
            raise Stop(f'{node}/{backend} natural fault: {fault} (stop={res.get("stop")})')
        reported = res.get('response_model')
        if reported and MODEL_FAMILY[backend] not in str(reported).lower():
            raise Stop(f'{node}/{backend}: provider reports model {reported!r}')
        if res['in'] < MIN_INPUT_TOKENS_PER_CHAR * rec['chars_in']:
            raise Stop(f'{node}/{backend}: {res["in"]} input tokens for {rec["chars_in"]} chars; input looks truncated')
        reached = self.budget.reached()
        if reached:
            raise Stop(reached)
        return NodeOut(res['text'], parsed, None)


def load_task(contract):
    docs = {d: v['pages']['1']['text'] for d, v in contract['source_pages'].items()}
    slots = []
    for f in contract['required_facts']:
        slot = {'fact_id': f['fact_id'], 'subject': f.get('subject', ''), 'predicate': f.get('predicate', '')}
        if f.get('unit'):
            slot['unit'] = f['unit']
        slots.append(slot)
    return docs, json.dumps(slots, ensure_ascii=False)


def e_user(doc_text):
    return f'请从以下文书中抽取全部信息：\n\n{doc_text}'


def j1_user(e_texts):
    return f"告知书(D1)抽取：\n{e_texts['E_D1']}\n\n决定书(D2)抽取：\n{e_texts['E_D2']}"


def j2_user(j1_text, slots_json):
    return f'上游配对结果：\n{j1_text}\n\n槽位：{slots_json}'


def _iter_quotes(node, label='', key=None):
    if isinstance(node, dict):
        lab = str(node.get('name') or node.get('item') or label)
        for k, v in node.items():
            yield from _iter_quotes(v, lab or k, k)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_quotes(item, label, key)
    elif isinstance(node, str) and (key in ('quote', 'quotes') or len(SC.norm_text(node)) >= 15):
        yield label, node


def evidence_rows(e_texts, docs_norm):
    """Rows keep only the quote and a label: an amount the E model attached to a quote is not
    carried, because the value must be readable from the verbatim sentence itself."""
    kept, rejected, seen = [], 0, set()
    for node, doc in (('E_D1', 'D1'), ('E_D2', 'D2')):
        obj = OLD.extract_json(e_texts[node]) or {}
        for label, quote in _iter_quotes(obj):
            q = SC.norm_text(quote)
            if (doc, q) in seen:
                continue
            seen.add((doc, q))
            if len(q) >= SC.MIN_QUOTE_CHARS and q in docs_norm[doc]:
                kept.append(dict(row=f'R{len(kept) + 1}', doc=doc, label=label,
                                 quote=re.sub(r'\s+', ' ', quote).strip()))
            else:
                rejected += 1
    return kept, rejected


def evidence_block(rows):
    lines = ['已核验证据表（程序已与原文逐字核对；doc 为文书编号）：']
    lines += [f"{r['row']} | doc={r['doc']} | {r['label']} | quote={r['quote']}" for r in rows]
    lines.append('复用规则：answers 的 doc 与 quote 必须从上表同一行逐字复制，不得改写或拼接；'
                 '上表没有依据的槽位写入 unknown_slots。')
    return '\n'.join(lines)


def sink_user(j2_text, rows, slots_json):
    return f'核验结果：\n{j2_text}\n\n{evidence_block(rows)}\n\n槽位：{slots_json}'


def _backed_by_d2(row):
    # A final amount counts only with a D2 sentence naming an amount: a proposed amount that
    # J1 copied over from D1 must not hide a deficient E_D2.
    if not re.search(r'\d', str(row.get('final_penalty') or '')):
        return False
    evidence = row.get('evidence')
    evidence = evidence if isinstance(evidence, list) else [evidence]
    return any(isinstance(e, dict) and ('D2' in str(e.get('doc')) or '决定书' in str(e.get('doc')))
               and '万元' in str(e.get('quote')) for e in evidence)


def observe(j1_out, e_d2_text):
    matrix = (j1_out.parsed or {}).get('party_matrix') or []
    rows = [r for r in matrix if isinstance(r, dict)]
    coverage = sum(_backed_by_d2(r) for r in rows) / len(rows) if rows else 0.0
    signal = len(re.findall(r'万元罚款|"penalty_amount":\s*"?\d', e_d2_text))
    return Obs(j1_out.fault, round(coverage, 4), signal)


def policy_static(obs):
    return NONE


def policy_fixed(obs):
    return RETRY if obs.j1_fault or obs.final_coverage < MIN_FINAL_COVERAGE else NONE


def policy_joint(obs):
    if obs.j1_fault in ('empty_text', 'truncated'):
        return SWAP
    if obs.j1_fault:
        return RETRY
    if obs.final_coverage < MIN_FINAL_COVERAGE:
        return REEXTRACT if obs.e_d2_penalty_signal == 0 else RETRY
    return NONE


POLICY = {'Static': policy_static, 'Fixed-Recovery': policy_fixed, 'Joint-Dynamic': policy_joint}


def run_execution(arm, env, task, e_texts, allow_recovery):
    docs, docs_norm, slots_json = task
    env.arm = arm
    trace = []
    j1 = env.call('J1', J1_DEFAULT_BACKEND, J1_SYS, j1_user(e_texts))
    obs = observe(j1, e_texts['E_D2'])
    action = POLICY[arm](obs)
    trace.append(dict(obs=obs._asdict(), action=action))
    if action != NONE and not allow_recovery:
        raise Stop(f'{arm}: recovery action {action} in a stage that allows none ({obs})')

    if action == RETRY:
        j1 = env.call('J1_retry', J1_DEFAULT_BACKEND, J1_REPAIR_SYS, j1_user(e_texts))
    elif action == SWAP:
        j1 = env.call('J1_swap', J1_ALT_BACKEND, J1_SYS, j1_user(e_texts))
    elif action == REEXTRACT:
        e2 = env.call('E_D2_reextract', 'ds', E_SYS, e_user(docs['D2']))
        e_texts = {**e_texts, 'E_D2': e2.text}
        j1 = env.call('J1_rerun', J1_DEFAULT_BACKEND, J1_SYS, j1_user(e_texts))

    if j1.fault:
        return dict(status='INCOMPLETE_NO_RECOVERY', trace=trace, sink=None, evidence_rows=0, evidence_rejected=0)

    j2 = env.call('J2', 'ds', J2_SYS, j2_user(j1.text, slots_json))
    rows, rejected = evidence_rows(e_texts, docs_norm)
    sink = env.call('SINK', 'ds', SINK_SYS, sink_user(j2.text, rows, slots_json))
    return dict(status='COMPLETE', trace=trace, sink=sink.parsed, evidence_rows=len(rows), evidence_rejected=rejected)


def run_condition(condition, rep, transport, ledger, budget, contract, records, allow_recovery):
    SC.verify_pins()
    docs, slots_json = load_task(contract)
    task = (docs, SC.doc_index(contract), slots_json)
    env = Env(transport, ledger, budget, condition, rep)
    e_d1 = env.call('E_D1', 'ds', E_SYS, e_user(docs['D1']))
    e_d2 = env.call('E_D2', 'ds', frozen_request(condition, 'E_D2')[1], e_user(docs['D2']))
    e_texts = {'E_D1': e_d1.text, 'E_D2': e_d2.text}

    for arm in ARMS:
        out = run_execution(arm, env, task, e_texts, allow_recovery)
        try:
            metrics = SC.score(out['sink'], contract)
        except Exception as exc:
            raise Stop(f'{arm}: scoring failed: {type(exc).__name__}: {exc}') from exc
        records.append(dict(arm=arm, condition=condition, rep=rep, **out, metrics=metrics))
        if out['status'] == 'COMPLETE':
            if metrics['Q_all'] is None:
                raise Stop(f'{arm}: Q_all is NULL for a complete execution')
            if metrics['asserted'] == 0:
                raise Stop(f'{arm}: SINK returned no answers')


def canary_acceptance(records, stopped, ledger_ok=True):
    """Infrastructure acceptance only: no arm comparison, and a zero-answer run can never pass."""
    complete = [r for r in records if r['status'] == 'COMPLETE']
    checks = {
        'C1_no_stop': stopped is None,
        'C2_answers_present': bool(complete) and all(r['metrics']['asserted'] > 0 for r in complete),
        'C3_ids_in_contract': bool(complete) and all(not r['metrics']['out_of_contract'] for r in complete),
        'C4_q_all_not_null': bool(records) and all(r['metrics']['Q_all'] is not None for r in records),
        'C5_evidence_path_alive': bool(complete) and all(r['metrics']['tp'] >= 1 for r in complete),
        'C6_incomplete_only_by_design': all(r['status'] == 'COMPLETE' or (r['arm'] == 'Static' and
                                            r['condition'] == 'exec_anomaly') for r in records),
        'C7_no_recovery_in_normal': all(r['trace'][0]['action'] == NONE for r in records
                                        if r['condition'] == 'normal'),
        'C8_ledger_complete': ledger_ok,
    }
    return dict(checks=checks, verdict='PASS' if all(checks.values()) else 'FAIL')


def run_stage(stage, transport, out_dir, rep=1, contract=None):
    cfg = STAGES[stage]
    contract = contract or SC.load_contract()
    out_dir = Path(out_dir)
    ledger = Ledger(out_dir / 'LEDGER.jsonl')
    budget = Budget(cfg['calls'], cfg['tokens'], cfg['yuan'])
    records, stopped = [], None
    try:
        for condition in cfg['conditions']:
            run_condition(condition, rep, transport, ledger, budget, contract, records, cfg['allow_recovery'])
    except Stop as stop:
        stopped = str(stop)
    except Exception as exc:
        stopped = f'internal error: {type(exc).__name__}: {exc}'
    done = [r for r in read_ledger(ledger.path) if r['phase'] == 'done' and not r['injected']]
    summary = dict(stage=stage, contract_sha256=SC.CONTRACT_SHA256, stopped=stopped,
                   used=dict(calls=budget.calls, tokens=budget.tokens, yuan_accounting=round(budget.yuan, 6),
                             yuan_marginal=round(budget.yuan_marginal, 6)),
                   caps=budget.caps, models_reported=sorted({f"{r['backend']}:{r.get('response_model')}" for r in done}),
                   acceptance=canary_acceptance(records, stopped, ledger_integrity(ledger.path)), records=records)
    (out_dir / 'RESULTS.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), 'utf-8')
    return summary


def rescore(out_dir, contract=None):
    """Recompute SINK scores from the ledger alone: rows are ordered by content hash and the arm label
    is joined only after scoring."""
    contract = contract or SC.load_contract()
    sinks = [r for r in read_ledger(Path(out_dir) / 'LEDGER.jsonl')
             if r['phase'] == 'done' and r['node'] == 'SINK' and r['stop'] != 'transport_error' and not r.get('fault')]
    scored = [(r, SC.score(OLD.extract_json(r['text']), contract)) for r in sorted(sinks, key=lambda r: _sha(r['text']))]
    return {f"{r['condition']}|{r['rep']}|{r['arm']}": m for r, m in scored}


def freeze_inputs():
    files = [Path(__file__).resolve(), HERE / 'sc_e1_scorer.py', Path(OLD.__file__).resolve(), SC.CONTRACT_PATH,
             Path(DS_TRANSPORT.__file__).resolve(), HERE / 'P2_AMENDMENT_SC_E1_1.md',
             *(Path(p) for p in SC.PINNED_SHA256)]
    return dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                contract_sha256=SC.CONTRACT_SHA256,
                prompts={name: _sha(val) for name, val in (('E_SYS', E_SYS), ('E_SYS_DEGRADED', E_SYS_DEGRADED),
                                                           ('J1_SYS', J1_SYS), ('J1_REPAIR_SYS', J1_REPAIR_SYS),
                                                           ('J2_SYS', J2_SYS), ('SINK_SYS', SINK_SYS))},
                real_stages=REAL_STAGES, stage_a=STAGES['A'], max_tokens=MAX_TOKENS,
                route={n: frozen_request('normal', n)[0] for n in ('E_D1', 'E_D2', 'J1', 'J2', 'SINK')},
                models=dict(ds=DS_MODEL, glm=GLM_MODEL), endpoints=dict(ds=DS_BASE + '/chat/completions', glm=OLD.GLM_URL),
                min_final_coverage=MIN_FINAL_COVERAGE, min_input_tokens_per_char=MIN_INPUT_TOKENS_PER_CHAR)


def check_real_gate(stage, freeze_sha):
    if stage not in REAL_STAGES:
        raise SystemExit(f'REFUSED: Stage {stage} is on HOLD; only {REAL_STAGES} may run for real')
    if os.environ.get('SC_E1_1_CANARY_GO') != '1':
        raise SystemExit('REFUSED: requires SC_E1_1_CANARY_GO=1')
    freeze_path = HERE / 'FREEZE.json'
    if not freeze_path.exists() or hashlib.sha256(freeze_path.read_bytes()).hexdigest() != freeze_sha:
        raise SystemExit('REFUSED: --freeze does not match FREEZE.json')
    SC.verify_pins()
    SC.load_contract()
    if json.loads(freeze_path.read_text('utf-8')) != json.loads(json.dumps(freeze_inputs())):
        raise SystemExit('REFUSED: frozen inputs changed since FREEZE.json was written')
    for key in (DS_KEY_ENV, 'STAGE_D_GLM_KEY'):
        if not os.environ.get(key, '').strip():
            raise SystemExit(f'REFUSED: {key} not set')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=sorted(STAGES), default='A')
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--freeze', default='')
    ap.add_argument('--write-freeze', action='store_true')
    ap.add_argument('--rescore', default='')
    args = ap.parse_args()

    if args.rescore:
        out_dir = Path(args.rescore)
        scores = rescore(out_dir)
        online = {f"{r['condition']}|{r['rep']}|{r['arm']}": r['metrics']
                  for r in json.loads((out_dir / 'RESULTS.json').read_text('utf-8'))['records'] if r['status'] == 'COMPLETE'}
        out = dict(matches_online=scores == online, scores=scores)
        (out_dir / 'RESCORE.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), 'utf-8')
        print('rescored', len(scores), 'SINK outputs from the ledger; matches online scores:', out['matches_online'])
        return

    if args.write_freeze:
        path = HERE / 'FREEZE.json'
        path.write_text(json.dumps(freeze_inputs(), ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE sha256:', hashlib.sha256(path.read_bytes()).hexdigest())
        return

    if args.real:
        check_real_gate(args.stage, args.freeze)
        out_dir = HERE / f'canary_{args.stage}'
        if out_dir.exists():
            raise SystemExit(f'REFUSED: {out_dir} exists; a canary stage is never rerun over its scene')
        transport = RealTransport()
    else:
        import sc_e1_1_mock as MOCK
        out_dir = HERE / f'dry_run_{args.stage}'
        if (out_dir / 'LEDGER.jsonl').exists():
            (out_dir / 'LEDGER.jsonl').unlink()
        transport = MOCK.MockTransport()

    summary = run_stage(args.stage, transport, out_dir)
    for r in summary['records']:
        m = r['metrics']
        print(f"[{r['arm']}|{r['condition']}] {r['status']} Q_all={m['Q_all']} Q_terminal={m['Q_terminal']} "
              f"E_literal={m['E_literal']} asserted={m['asserted']} tp={m['tp']} wrong={m['wrong']} "
              f"action={r['trace'][0]['action']}")
    print('stopped:', summary['stopped'], '| used:', summary['used'], '| acceptance:', summary['acceptance']['verdict'])


if __name__ == '__main__':
    main()
