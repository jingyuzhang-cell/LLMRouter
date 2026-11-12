#!/usr/bin/env python3
"""QS (300216) independent confirmation executor: three arms forked from one shared checkpoint per replicate.

Implements PREREG_QS_CONFIRM_V2_1.md. Per replicate: shared E_D1, E_D2, J1 (DS) and J2 (GLM) form checkpoint CP_r;
evidence table, base total (base_total_v2), V5 M1/M2 and the coverage check are computed on CP_r. Arm A runs SINK on
CP_r (its output is the shared pre-recovery terminal); B applies the fixed recovery; C applies the graded policy.
Detector V5 is the only execution detector. Gold is read only by the scorer, after each arm is final.
Two blocks of four replicates; each block needs its own GO and the frozen manifest; block 2 needs block 1 PASS.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SD = HERE.parent
sys.path[:0] = [str(HERE), str(SD / 'sc_e1_1'), str(SD / 'sc_e1_1' / 'fork_t1'), str(SD)]
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_runner as OLD  # noqa: E402
import qs_scorer as Q  # noqa: E402
import detectors_v5 as D5  # noqa: E402
import base_total_v2 as BT  # noqa: E402
import safety_metrics as SM  # noqa: E402
import render_fork_t1 as TXT  # noqa: E402

OUT = HERE / 'run'
BLOCKS = {1: (1, 2, 3, 4), 2: (5, 6, 7, 8)}
BLOCK_CAPS = dict(calls=60, tokens=690_000, yuan=1.25)
ARM_CAPS = {'A': 2, 'B': 3, 'C': 5}
ROUTE = {'E_D1': ('ds', R.E_SYS, 8000), 'E_D2': ('ds', R.E_SYS, 8000), 'J1': ('ds', R.J1_SYS, 8000),
         'J2': ('glm', R.J2_SYS, 8000), 'J2_recheck': ('glm', R.J2_SYS, 8000), 'SINK': ('ds', R.SINK_SYS, 4000),
         'SINK_bypass': ('ds', R.SINK_SYS, 4000), 'SINK_after_recheck': ('ds', R.SINK_SYS, 4000), 'SINK_h': ('ds', R.SINK_SYS, 4000)}
BASE_LINE_NONE = '确定性派生值：{fact_id} 无法由程序确定计算（{reason}），请按证据表作答或写入 unknown_slots。'
ACTIONABLE = ('EXPLICIT_SUPPRESSION', 'UNKNOWN_LABEL', 'OMISSION_WITH_EVIDENCE')


class InfraStop(Exception):
    """Infrastructure-level anomaly: stop the whole block, keep the scene, no retry."""


class BlockBudget(R.Budget):
    def preflight(self, backend, system, user, max_tokens):
        try:
            super().preflight(backend, system, user, max_tokens)
        except R.Stop as stop:
            raise InfraStop(f'budget pre-flight: {stop}') from stop

    def reached(self):
        for name, used in (('tokens', self.tokens), ('yuan', self.yuan)):
            if used >= self.caps[name]:
                return f'{name} cap reached: {used} >= {self.caps[name]}'
        return None


class Ctx:
    def __init__(self, transport, ledger, budget, rep):
        self.transport, self.ledger, self.budget, self.rep = transport, ledger, budget, rep


def call(ctx, arm, node, user):
    """One model call with the write-ahead ledger. Node-level faults are returned; infrastructure faults raise."""
    backend, system, max_tokens = ROUTE[node]
    rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), condition='qs', rep=ctx.rep, arm=arm, node=node, backend=backend,
               max_tokens=max_tokens, system_sha256=R._sha(system), user_sha256=R._sha(user), chars_in=len(system) + len(user),
               injected=False)
    ctx.budget.preflight(backend, system, user, max_tokens)
    url, body = ctx.transport.describe(backend, system, user, max_tokens)
    ctx.ledger.write({**rec, 'phase': 'sent', 'url': url, 'request_body': body})
    try:
        res = ctx.transport.call(backend, system, user, max_tokens)
    except Exception as exc:
        ctx.budget.book(backend, 0, 0)
        detail = f'{type(exc).__name__}: {exc}'[:300]
        error_body = getattr(exc, 'read', lambda: b'')()
        ctx.ledger.write({**rec, 'phase': 'done', 'url': url, 'request_body': body, 'raw_response': None, 'text': '',
                          'stop': 'transport_error', 'error': detail,
                          'error_body': error_body.decode('utf-8', 'replace')[:2000] if error_body else None})
        raise InfraStop(f'{arm}/{node}/{backend} transport error: {detail}') from exc
    cost = ctx.budget.book(backend, res['in'], res['out'])
    fault, parsed = R.guard(node, res)
    ctx.ledger.write({**rec, 'phase': 'done', 'url': url, 'request_body': body, 'raw_response': res.get('raw_response'),
                      'response_model': res.get('response_model'), 'usage_raw': res.get('usage_raw'), 'text': res.get('text', ''),
                      'stop': res.get('stop'), 'in': res['in'], 'out': res['out'], 'lat': res.get('lat'), 'yuan_accounting': cost,
                      'yuan_marginal': cost if backend == 'ds' else 0.0, 'fault': fault})
    reported = res.get('response_model')
    if reported and R.MODEL_FAMILY[backend] not in str(reported).lower():
        raise InfraStop(f'{arm}/{node}: provider reports model {reported!r}')
    if res['in'] < R.MIN_INPUT_TOKENS_PER_CHAR * rec['chars_in']:
        raise InfraStop(f'{arm}/{node}: {res["in"]} input tokens for {rec["chars_in"]} chars; input looks truncated')
    reached = ctx.budget.reached()
    if reached:
        raise InfraStop(reached)
    return dict(text=res.get('text', ''), parsed=parsed, fault=fault, lat=res.get('lat') or 0.0, yuan=cost,
                tokens=res['in'] + res['out'], node=node)


class Arm:
    def __init__(self, name):
        self.name, self.cap = name, ARM_CAPS[name]
        self.calls, self.retry_used, self.lat, self.yuan, self.tokens = 0, False, 0.0, 0.0, 0
        self.trace, self.failures, self.budget_exhausted = [], [], False

    def run(self, ctx, node, user):
        """Arm-owned call with the arm's single retry. Returns the call result or None (no usable output)."""
        for attempt in (1, 2):
            if self.calls >= self.cap:
                self.budget_exhausted = True
                self.trace.append(dict(action='budget_exhausted', node=node))
                return None
            res = call(ctx, self.name, node, user)
            self.calls += 1
            self.lat += res['lat']
            self.yuan += res['yuan']
            self.tokens += res['tokens']
            self.trace.append(dict(action='call', node=node, attempt=attempt, fault=res['fault']))
            if not res['fault']:
                return res
            self.failures.append(dict(node=node, attempt=attempt, fault=res['fault']))
            if self.retry_used:
                return None
            self.retry_used = True
        return None


def load_task():
    ct = Q.load_contract()
    Q.verify_pins()
    D5.verify_pins()
    docs = {d: v['pages']['1']['text'] for d, v in ct['source_pages'].items()}
    slots = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'], **({'unit': f['unit']} if f.get('unit') else {}))
             for f in ct['required_facts']]
    return ct, docs, slots, json.dumps(slots, ensure_ascii=False), Q.doc_index(ct)


def base_line(base, slots):
    lines = []
    for s in slots:
        if D5.slot_type(s) != 'derived':
            continue
        if base.get('value') is not None:
            lines.append(TXT.BASE_LINE.format(fact_id=s['fact_id'], subject=s['subject'], predicate=s['predicate'],
                                              value=base['value'], parties=base['parties']))
        else:
            reason = '同一当事人出现不同金额' if base.get('conflicts') else '决定书抽取中没有可用金额'
            lines.append(BASE_LINE_NONE.format(fact_id=s['fact_id'], reason=reason))
    return '\n'.join(lines)


def slot_states(slots, j2_obj, rows):
    m1 = D5.detect_m1(slots, j2_obj, rows)
    out = {}
    for s in slots:
        fid, v = s['fact_id'], m1[s['fact_id']]
        if v['state'] == 'EXPLICIT_SUPPRESSION':
            st = 'EXPLICIT_SUPPRESSION'
        elif v['state'] == 'UNKNOWN_LABEL':
            st = 'UNKNOWN_LABEL'
        elif v['state'] == 'OMISSION':
            st = 'OMISSION_WITH_EVIDENCE'
        elif v['state'] == 'NOT_APPLICABLE':
            st = 'DERIVED'
        else:
            label = D5.classify(v['j2_status'])
            st = {None: 'MISSING_NO_EVIDENCE', 'suppressed': 'SUPPRESSED_NO_EVIDENCE', 'affirmed': 'CONFIRMED'}.get(label, 'UNKNOWN_NO_EVIDENCE')
        out[fid] = dict(state=st, j2_status=v['j2_status'], candidate_rows=v.get('candidate_rows', []))
    return out


def addendum(targets, states, rows, slots):
    by_row = {r['row']: r for r in rows}
    items = []
    for s in slots:
        fid = s['fact_id']
        if fid in targets and states[fid]['candidate_rows']:
            cand = '；'.join(TXT.A2_ROW.format(row=r, doc=by_row[r]['doc'], quote=by_row[r]['quote']) for r in states[fid]['candidate_rows'])
            items.append(TXT.A2_ITEM.format(fact_id=fid, subject=s['subject'], predicate=s['predicate'], rows=cand))
    return TXT.A2_HEADER + '\n' + '\n'.join(items)


def terminal_view(sink_obj, rows, base, slots):
    """Gold-blind view of a terminal output: answered, cited verbatim from the table, V5 M3 state."""
    table = {(r['doc'], Q.norm_text(r['quote'])) for r in rows}
    m3 = D5.detect_m3(slots, sink_obj or {}, rows, base)
    answers = {}
    for a in (sink_obj or {}).get('answers') or []:
        if isinstance(a, dict) and a.get('fact_id') and not Q.is_abstention(a.get('value')):
            answers.setdefault(a['fact_id'], a)
    view = {}
    for s in slots:
        a = answers.get(s['fact_id'])
        view[s['fact_id']] = dict(answered=bool(a), cited=bool(a) and (str(a.get('doc')), Q.norm_text(a.get('quote'))) in table,
                                  m3=(m3.get(s['fact_id']) or {}).get('state'))
    return view


def recovered(view, targets):
    # UNDETERMINED polarity is not a violation (V2.1 section 4); only an inconsistent answer blocks recovery.
    return all(view[f]['answered'] and view[f]['cited'] and view[f]['m3'] != 'SELF_EVIDENCE_INCONSISTENT' for f in targets)


def degraded(before, after, targets):
    if before is None:
        return []
    out = []
    for fid, b in before.items():
        if fid in targets:
            continue
        a = after[fid]
        if b['cited'] and not a['cited']:
            out.append((fid, 'citation lost'))
        elif b['m3'] == 'CONSISTENT' and a['m3'] == 'SELF_EVIDENCE_INCONSISTENT':
            out.append((fid, 'new M3 violation'))
    return out


def convert_to_unknown(sink_obj, fids):
    obj = json.loads(json.dumps(sink_obj, ensure_ascii=False))
    obj['answers'] = [a for a in obj.get('answers') or [] if not (isinstance(a, dict) and a.get('fact_id') in fids)]
    obj['unknown_slots'] = sorted(set(map(str, obj.get('unknown_slots') or [])) | set(fids), key=lambda x: int(x[1:]))
    return obj


def run_rep(ctx, task):
    ct, docs, slots, slots_json, docs_norm = task
    shared_calls = []
    texts = {}
    for node, user in (('E_D1', R.e_user(docs['D1'])), ('E_D2', R.e_user(docs['D2']))):
        res = call(ctx, 'shared', node, user)
        if res['fault']:
            raise InfraStop(f'shared-stage node fault at {node}: {res["fault"]}')
        texts[node] = res['text']
        shared_calls.append(res)
    j1 = call(ctx, 'shared', 'J1', R.j1_user(texts))
    if j1['fault']:
        raise InfraStop(f'shared-stage node fault at J1: {j1["fault"]}')
    j2 = call(ctx, 'shared', 'J2', R.j2_user(j1['text'], slots_json))
    if j2['fault']:
        raise InfraStop(f'shared-stage node fault at J2: {j2["fault"]}')
    shared_calls += [j1, j2]
    rows, rejected = R.evidence_rows(texts, docs_norm)
    base = BT.total(OLD.extract_json(texts['E_D2']), docs['D2'])
    bline = base_line(base, slots)
    states = slot_states(slots, j2['parsed'], rows)
    m2 = D5.detect_m2(slots, j2['parsed'], base)

    def sink_user(j2_text):
        return f'核验结果：\n{j2_text}\n\n{R.evidence_block(rows)}\n\n{bline}\n\n槽位：{slots_json}'

    explicit = {f for f, v in states.items() if v['state'] == 'EXPLICIT_SUPPRESSION'}
    unknown = {f for f, v in states.items() if v['state'] == 'UNKNOWN_LABEL'}
    omission = {f for f, v in states.items() if v['state'] == 'OMISSION_WITH_EVIDENCE'}
    targets = explicit | unknown | omission

    # A
    arm_a = Arm('A')
    a_res = arm_a.run(ctx, 'SINK', sink_user(j2['text']))
    a_out = a_res['parsed'] if a_res else None
    a_view = terminal_view(a_out, rows, base, slots) if a_out else None
    finals = {'A': (arm_a, a_out)}

    # B
    arm_b = Arm('B')
    b_out = a_out
    if targets:
        arm_b.trace.append(dict(action='fixed_recheck', targets=sorted(targets, key=lambda x: int(x[1:]))))
        jt = arm_b.run(ctx, 'J2_recheck', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets, states, rows, slots))
        if jt:
            sb = arm_b.run(ctx, 'SINK_after_recheck', sink_user(jt['text']))
            if sb:
                b_out = sb['parsed']
    else:
        arm_b.trace.append(dict(action='none'))
    finals['B'] = (arm_b, b_out)

    # C
    arm_c = Arm('C')
    c_out, c_j2_text = a_out, j2['text']
    if targets:
        if unknown:
            step = 'recheck'
        elif explicit:
            step = 'bypass'
        else:
            step = 'check'
        while True:
            if step == 'check':
                arm_c.trace.append(dict(action='check_pre_recovery_terminal', targets=sorted(omission, key=lambda x: int(x[1:]))))
                if a_view is not None and recovered(a_view, targets):
                    break
                step = 'recheck'
                continue
            if step == 'bypass':
                arm_c.trace.append(dict(action='sink_bypass', deleted=sorted(explicit, key=lambda x: int(x[1:]))))
                keep = [v for v in (j2['parsed'] or {}).get('verified') or [] if not (isinstance(v, dict) and str(v.get('fact_id')) in explicit)]
                bypass_text = json.dumps(dict(j2['parsed'], verified=keep), ensure_ascii=False)
                sc = arm_c.run(ctx, 'SINK_bypass', sink_user(bypass_text))
                if sc:
                    c_out, c_j2_text = sc['parsed'], bypass_text
                    view = terminal_view(c_out, rows, base, slots)
                    lost = degraded(a_view, view, targets)
                    arm_c.trace.append(dict(action='terminal_check', recovered=recovered(view, targets), degraded=lost))
                    if recovered(view, targets) and not lost:
                        break
                step = 'recheck'
                continue
            if step == 'recheck':
                arm_c.trace.append(dict(action='j2_recheck', targets=sorted(targets, key=lambda x: int(x[1:]))))
                jt = arm_c.run(ctx, 'J2_recheck', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets, states, rows, slots))
                if jt:
                    sc = arm_c.run(ctx, 'SINK_after_recheck', sink_user(jt['text']))
                    if sc:
                        c_out, c_j2_text = sc['parsed'], jt['text']
                        view = terminal_view(c_out, rows, base, slots)
                        arm_c.trace.append(dict(action='terminal_check', recovered=recovered(view, targets),
                                                degraded=degraded(a_view, view, targets), final_escalation=True))
                break
    else:
        arm_c.trace.append(dict(action='none'))
    if c_out is not None:
        m3 = D5.detect_m3(slots, c_out, rows, base)
        viol = sorted((f for f, v in m3.items() if v['state'] == 'SELF_EVIDENCE_INCONSISTENT'), key=lambda x: int(x[1:]))
        if viol:
            before = {a['fact_id']: a.get('value') for a in c_out.get('answers') or [] if isinstance(a, dict) and a.get('fact_id')}
            c_out = convert_to_unknown(c_out, viol)
            arm_c.trace.append(dict(action='m3_convert_to_unknown', slots=viol))
            if arm_c.calls < arm_c.cap:
                by_slot = {s['fact_id']: s for s in slots}
                items = [TXT.H_ITEM.format(fact_id=f, subject=by_slot[f]['subject'], predicate=by_slot[f]['predicate'],
                                           value=before.get(f), reason=m3[f]['reason']) for f in viol]
                h = arm_c.run(ctx, 'SINK_h', sink_user(c_j2_text) + '\n\n' + TXT.H_HEADER + '\n' + '\n'.join(items))
                if h:
                    m3b = D5.detect_m3(slots, h['parsed'], rows, base)
                    viol_b = sorted((f for f, v in m3b.items() if v['state'] == 'SELF_EVIDENCE_INCONSISTENT'), key=lambda x: int(x[1:]))
                    c_out = convert_to_unknown(h['parsed'], viol_b) if viol_b else h['parsed']
                    arm_c.trace.append(dict(action='h_rerun', remaining_violations_converted=viol_b))
    finals['C'] = (arm_c, c_out)

    shared_yuan = sum(c['yuan'] for c in shared_calls)
    shared_lat = sum(c['lat'] for c in shared_calls)
    shared_tok = sum(c['tokens'] for c in shared_calls)
    a_sink_cost = (arm_a.yuan, arm_a.lat, arm_a.calls, arm_a.tokens)
    record = dict(rep=ctx.rep, states={f: v['state'] for f, v in states.items()}, targets=sorted(targets, key=lambda x: int(x[1:])),
                  m2=m2, base_total=dict(value=base.get('value'), parties=base.get('parties'), merged=base.get('merged')),
                  evidence_rows=len(rows), evidence_rejected=rejected,
                  shared=dict(calls=len(shared_calls), yuan=round(shared_yuan, 6), lat=round(shared_lat, 2), tokens=shared_tok), arms={})
    for name, (arm, out) in finals.items():
        score = Q.score(out, ct)
        incomplete = out is None
        pre_yuan, pre_lat, pre_calls, pre_tok = (0, 0, 0, 0) if name == 'A' else a_sink_cost
        record['arms'][name] = dict(
            incomplete=incomplete, budget_exhausted=arm.budget_exhausted, failures=arm.failures, trace=arm.trace,
            output=out, metrics={k: v for k, v in score.items() if k != 'rows'}, rows={r['fact_id']: r['status'] for r in score['rows']},
            safety=SM.metrics(score),
            own=dict(calls=arm.calls, yuan=round(arm.yuan, 6), lat=round(arm.lat, 2), tokens=arm.tokens),
            deployment=dict(calls=len(shared_calls) + pre_calls + arm.calls, yuan=round(shared_yuan + pre_yuan + arm.yuan, 6),
                            tokens=shared_tok + pre_tok + arm.tokens),
            latency=dict(recovery_increment=round(arm.lat if name != 'A' else 0.0, 2),
                         end_to_end=round(shared_lat + pre_lat + arm.lat, 2)),
            target_recovered=sum(1 for f in targets if score_status(score, f) == 'TP'))
    return record


def score_status(score, fid):
    return next(r['status'] for r in score['rows'] if r['fact_id'] == fid)


def sign_test_one_sided(diffs):
    pos = sum(1 for d in diffs if d > 0)
    n = sum(1 for d in diffs if d != 0)
    if n == 0:
        return dict(n_eff=0, positive=0, p=None)
    p = sum(math.comb(n, j) for j in range(pos, n + 1)) / 2 ** n
    return dict(n_eff=n, positive=pos, p=round(p, 6))


def analyse(out_dir):
    reps = [json.loads(p.read_text('utf-8')) for p in sorted(Path(out_dir).glob('REP_*.json'), key=lambda p: int(p.stem.split('_')[1]))]
    rows = []
    for r in reps:
        a, b, c = (r['arms'][k] for k in ('A', 'B', 'C'))
        rows.append(dict(rep=r['rep'], flagged=bool(r['targets']), q=dict(A=a['metrics']['Q_all'], B=b['metrics']['Q_all'], C=c['metrics']['Q_all']),
                         calls=dict(A=a['deployment']['calls'], B=b['deployment']['calls'], C=c['deployment']['calls']),
                         yuan=dict(A=a['deployment']['yuan'], B=b['deployment']['yuan'], C=c['deployment']['yuan']),
                         lat=dict(B=b['latency']['recovery_increment'], C=c['latency']['recovery_increment']),
                         err=dict(A=a['safety']['error_rate'], B=b['safety']['error_rate'], C=c['safety']['error_rate']),
                         incomplete=dict(A=a['incomplete'], B=b['incomplete'], C=c['incomplete'])))
    if not rows:
        return {}
    mean = lambda xs: round(sum(xs) / len(xs), 6) if xs else None
    d_ca = [x['q']['C'] - x['q']['A'] for x in rows]
    d_cb = [x['q']['C'] - x['q']['B'] for x in rows]
    gates = [SM.safety_gate(dict(error_rate=x['err']['C']), dict(error_rate=x['err'][k])) for x in rows for k in ('A', 'B') if x['flagged']]
    out = dict(reps=len(rows), flagged_reps=sum(x['flagged'] for x in rows), per_rep=rows,
               H1=dict(test=sign_test_one_sided(d_ca), mean_delta=mean(d_ca)),
               H2a=dict(min_delta_C_minus_B=min(d_cb), all_noninferior=all(d >= -0.05 for d in d_cb)),
               H2b=dict(calls=dict(B=mean([x['calls']['B'] for x in rows]), C=mean([x['calls']['C'] for x in rows])),
                        yuan=dict(B=mean([x['yuan']['B'] for x in rows]), C=mean([x['yuan']['C'] for x in rows]))),
               H2c=dict(recovery_latency=dict(B=mean([x['lat']['B'] for x in rows]), C=mean([x['lat']['C'] for x in rows]))),
               H3=dict(gates=gates, all_pass=bool(gates) and all(g == 'PASS' for g in gates)),
               note='Descriptive until both blocks are complete; the preregistered decision uses all eight replicates.')
    Path(out_dir, 'ANALYSIS.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), 'utf-8')
    return out


def used_from_ledger(path, block=None):
    """Spend of one block only: the block caps never charge another block's replicates."""
    used = dict(calls=0, tokens=0, yuan_accounting=0.0, yuan_marginal=0.0)
    reps = BLOCKS.get(block, ()) if block else None
    for r in R.read_ledger(path):
        if r['phase'] != 'done' or (reps and r.get('rep') not in reps):
            continue
        used['calls'] += 1
        used['tokens'] += (r.get('in') or 0) + (r.get('out') or 0)
        used['yuan_accounting'] += r.get('yuan_accounting') or 0.0
        used['yuan_marginal'] += r.get('yuan_marginal') or 0.0
    return used


def run_block(block, transport, out_dir=OUT, resume=False):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    task = load_task()
    ledger = R.Ledger(out_dir / 'LEDGER.jsonl')
    reps = BLOCKS[block]
    if resume:
        # Minimal resumption (operator 2026-11-07): keep finished scenes, run only the replicates that have
        # none. The budget continues from the ledger, so the block caps still bound the whole block.
        reps = [r for r in reps if not (out_dir / f'REP_{r}.json').exists()]
        if not reps:
            raise SystemExit('REFUSED: nothing to resume; every replicate in this block already has a scene')
        prior = used_from_ledger(ledger.path, block)
        budget = BlockBudget(**BLOCK_CAPS)
        budget.calls, budget.tokens = prior['calls'], prior['tokens']
        budget.yuan, budget.yuan_marginal = prior['yuan_accounting'], prior['yuan_marginal']
    else:
        budget = BlockBudget(**BLOCK_CAPS)
        for rep in reps:
            if (out_dir / f'REP_{rep}.json').exists():
                raise SystemExit(f'REFUSED: replicate {rep} already ran; its scene is never rerun')
    stopped, done = None, []
    for rep in reps:
        try:
            rec = run_rep(Ctx(transport, ledger, budget, rep), task)
        except InfraStop as stop:
            stopped = f'rep {rep}: {stop}'
            break
        (out_dir / f'REP_{rep}.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), 'utf-8')
        done.append(rep)
    ledger_ok = R.ledger_integrity(ledger.path) if ledger.path.exists() else False
    planned = reps if resume else BLOCKS[block]
    summary = dict(block=block, resumed=resume, reps_done=done, stopped=stopped, ledger_ok=ledger_ok,
                   verdict='PASS' if stopped is None and ledger_ok and len(done) == len(planned) else 'FAIL',
                   used=dict(calls=budget.calls, tokens=budget.tokens, yuan_accounting=round(budget.yuan, 6),
                             yuan_marginal=round(budget.yuan_marginal, 6)), caps=BLOCK_CAPS, analysis=analyse(out_dir))
    name = f'BLOCK_{block}.json' if not (out_dir / f'BLOCK_{block}.json').exists() else f'BLOCK_{block}_RESUME.json'
    (out_dir / name).write_text(json.dumps(summary, ensure_ascii=False, indent=1), 'utf-8')
    return summary


def freeze_inputs():
    files = [Path(__file__).resolve(), HERE / 'PREREG_QS_CONFIRM_V2_1.md', HERE / 'qs_scorer.py', HERE / 'dag_qs.json', Q.CONTRACT_PATH,
             HERE / 'run/REP_6.json', HERE / 'RESUME_AMENDMENT.md',
             SD / 'sc_e1_1/detectors_v5.py', SD / 'sc_e1_1/detectors_v4.py', SD / 'sc_e1_1/detectors_v3.py', SD / 'sc_e1_1/detectors_v2.py',
             SD / 'sc_e1_1/base_total_v2.py', SD / 'sc_e1_1/safety_metrics.py', SD / 'sc_e1_1/sc_e1_1_runner.py', SD / 'sc_e1_runner.py',
             SD / 'sc_e1_1/fork_t1/render_fork_t1.py', Path(R.DS_TRANSPORT.__file__).resolve(), SD / 'j2_probe/PROBE_RESULTS.json']
    return dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                route={k: [v[0], R._sha(v[1]), v[2]] for k, v in ROUTE.items()}, block_caps=BLOCK_CAPS, arm_caps=ARM_CAPS,
                blocks={str(k): list(v) for k, v in BLOCKS.items()}, models=dict(ds=R.DS_MODEL, glm=R.GLM_MODEL),
                templates={k: R._sha(getattr(TXT, k)) for k in ('A2_HEADER', 'A2_ITEM', 'A2_ROW', 'BASE_LINE', 'H_HEADER', 'H_ITEM')})


def check_real_gate(block, freeze_sha, after_sha, resume=False):
    if os.environ.get('QS_BLOCK_GO') != str(block):
        raise SystemExit(f'REFUSED: requires QS_BLOCK_GO={block}')
    prev = OUT / ('BLOCK_2.json' if (resume and block == 2) else 'BLOCK_1.json')
    if block == 2 and not prev.exists():
        raise SystemExit('REFUSED: BLOCK_2.json (the stop record) is missing')
    if block == 2 and hashlib.sha256(prev.read_bytes()).hexdigest() != after_sha:
        raise SystemExit(f'REFUSED: --after does not match {prev.name}')
    if block == 2 and not resume and json.loads(prev.read_text('utf-8'))['verdict'] != 'PASS':
        raise SystemExit('REFUSED: block 1 did not pass')
    if block == 2 and resume:
        rec = json.loads(prev.read_text('utf-8'))
        if rec.get('verdict') != 'FAIL' or 'rep 6' not in str(rec.get('stopped', '')):
            raise SystemExit('REFUSED: resume is only for the block-2 stop at rep 6')
    p = HERE / 'FREEZE_QS_EXEC.json'
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != freeze_sha:
        raise SystemExit('REFUSED: --freeze does not match FREEZE_QS_EXEC.json')
    if json.loads(p.read_text('utf-8')) != json.loads(json.dumps(freeze_inputs())):
        raise SystemExit('REFUSED: frozen inputs changed since FREEZE_QS_EXEC.json was written')
    for key in (R.DS_KEY_ENV, 'STAGE_D_GLM_KEY'):
        if not os.environ.get(key, '').strip():
            raise SystemExit(f'REFUSED: {key} not set')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--block', type=int, choices=(1, 2))
    ap.add_argument('--freeze', default='')
    ap.add_argument('--after', default='')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--write-freeze', action='store_true')
    a = ap.parse_args()
    if a.write_freeze:
        p = HERE / 'FREEZE_QS_EXEC.json'
        p.write_text(json.dumps(freeze_inputs(), ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_QS_EXEC sha256:', hashlib.sha256(p.read_bytes()).hexdigest())
        return
    if not a.block:
        raise SystemExit('REFUSED: --block is required')
    check_real_gate(a.block, a.freeze, a.after, a.resume)
    s = run_block(a.block, R.RealTransport(), resume=a.resume)
    print(json.dumps({k: v for k, v in s.items() if k != 'analysis'}, ensure_ascii=False))
    print('BLOCK file sha256:', hashlib.sha256((OUT / f'BLOCK_{a.block}.json').read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
