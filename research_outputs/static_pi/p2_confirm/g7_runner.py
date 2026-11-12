#!/usr/bin/env python3
"""G7 confirmatory executor: 40 tasks x 2 reps, paired arms G6-M vs G7 (pre-registration P2C_G7_PREREG_FROZEN).
G6-M = P2-C G6 pipeline verbatim (frozen p2c_runner.py sha 7396f432) + stage metadata input, no enforcement.
G7   = G6-M + R1-R3 constraints + bounded re-anchoring (<=2/block) driven by deterministic span check +
       independent stage verifier (Plan A). Zero protocol drift; ledger kind=normal|verify|reanchor."""
import argparse, hashlib, json, os, re, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SD = HERE.parent / 'stage_d'
sys.path[:0] = [str(HERE), str(SD / 'sc_e1_1'), str(SD / 'sc_e1_1' / 'fork_t1'), str(SD), str(SD / 'qs_confirm')]
import sc_e1_1_runner as R
import detectors_v5 as D5
import base_total_v2 as BT
import render_fork_t1 as TXT

OUT = HERE / 'g7_runs'
TASKSET = HERE / 'g7_tasks' / 'G7_TASKSET_FREEZE.json'
RAND = HERE / 'g7_tasks' / 'G7_RANDOMIZATION_TABLE.json'
PROMPTS_F = HERE / 'G7_PROMPTS_FROZEN.json'
CAPS = dict(calls=1000, tokens=8_000_000, yuan=15.0)
ROUTE = {'E_D1': ('ds', 8000), 'E_D2': ('ds', 8000), 'J1': ('ds', 8000), 'J2': ('glm', 8000),
         'J2R': ('glm', 12000), 'SINK': ('ds', 4000), 'REANCHOR': ('ds', 4000), 'VERIFIER': ('glm', 8000)}
MAX_REANCHOR, MAX_VERIFY = 2, 3
ARMS = ('G6-M', 'G7')

class Stop(Exception): pass
class ModelFault(Stop): pass

def sha(t): return hashlib.sha256(t.encode('utf-8')).hexdigest()

def strip_pageno(t): return re.sub(r'\n\s*\d+\s*(?=\n|$)', '', t)

def resolve_docs(contract, batch_dir):
    """GO gate resolution priority: normalized -> embedded pages -> raw file (+text_corrections)."""
    docs, docs_norm = {}, {}
    for d, meta in contract['source_pages'].items():
        if 'normalized' in meta:
            txt = meta['normalized']
        elif 'pages' in meta:
            txt = ''.join(meta['pages'].values())
        else:
            fp = batch_dir / meta['file']
            if not fp.exists():
                fp = batch_dir / 'raw' / Path(meta['file']).name
            txt = strip_pageno(fp.read_text(errors='ignore'))
            for corr in contract.get('text_corrections', []):
                if corr.get('file') == Path(meta['file']).name or corr.get('doc') == d:
                    pos = txt.find(corr['text_layer'])
                    if pos >= 0:
                        txt = txt[:pos] + corr['printed'] + txt[pos + len(corr['text_layer']):]
        docs[d] = txt
        docs_norm[d] = R.SC.norm_text(txt)   # 冻结管线规范化（NFKC+去空白）——与evidence_rows引文检查同口径
    return docs, docs_norm

class Env:
    def __init__(self, transport, ledger, budget):
        self.t, self.l, self.b = transport, ledger, budget
        self.task, self.rep, self.arm, self.kind = '', 0, '', 'normal'
    def call(self, node, user, system=None):
        backend, mt = ROUTE[node]
        if system is None:
            system = {'E_D1': R.E_SYS, 'E_D2': R.E_SYS, 'J1': R.J1_SYS, 'J2': R.J2_SYS,
                      'J2R': R.J2_SYS, 'SINK': R.SINK_SYS}[node]
        rec = dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), task=self.task, rep=self.rep, arm=self.arm,
                   kind=self.kind, node=node, backend=backend, max_tokens=mt, system_sha256=sha(system),
                   user_sha256=sha(user), chars_in=len(system) + len(user))
        self.b.preflight(backend, system, user, mt)
        url, body = self.t.describe(backend, system, user, mt)
        self.l.write({**rec, 'phase': 'sent', 'url': url, 'request_body': body})
        try:
            res = self.t.call(backend, system, user, mt)
        except Exception as e:
            self.b.book(backend, 0, 0)
            self.l.write({**rec, 'phase': 'done', 'raw_response': None, 'text': '', 'stop': 'transport_error',
                          'error': f'{type(e).__name__}: {e}'[:200]})
            raise Stop(f'{node}/{backend} transport: {e}') from e
        cost = self.b.book(backend, res['in'], res['out'])
        if node == 'VERIFIER':
            text = res.get('text') or ''
            if res.get('stop') in ('length', 'max_tokens'):
                fault, parsed = 'truncated', None
            elif res.get('stop') not in ('stop', 'end_turn'):
                fault, parsed = 'abnormal_stop', None
            elif not text.strip():
                fault, parsed = 'empty_text', None
            else:
                parsed = R.OLD.extract_json(text)
                fault = None if (isinstance(parsed, dict) and 'stages' in parsed) else 'schema_invalid'
        else:
            fault, parsed = R.guard({'J2R': 'J2', 'REANCHOR': 'SINK'}.get(node, node), res)
        self.l.write({**rec, 'phase': 'done', 'raw_response': res.get('raw_response'),
                      'response_model': res.get('response_model'), 'text': res.get('text', ''),
                      'stop': res.get('stop'), 'in': res['in'], 'out': res['out'],
                      'yuan_accounting': cost, 'yuan_marginal': cost if backend == 'ds' else 0, 'fault': fault})
        if self.b.reached(): raise Stop(self.b.reached())
        if fault: raise ModelFault(f'{node} fault: {fault}')
        return dict(text=res['text'], parsed=parsed, fault=None)

def load_block_state():
    ts = json.loads(TASKSET.read_text('utf-8'))
    rt = json.loads(RAND.read_text('utf-8'))
    pr = json.loads(PROMPTS_F.read_text('utf-8'))
    contracts = {}
    for t in ts['tasks']:
        b = t['batch']
        cpath = HERE / 'g7_tasks' / f'batch{b}' / 'contracts' / f"TASK_CONTRACT_{t['task']}_v1.0.json"
        c = json.loads(cpath.read_text('utf-8'))
        docs, docs_norm = resolve_docs(c, HERE / 'g7_tasks' / f'batch{b}')
        slots = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                      fact_stage=f['fact_stage'],
                      **({'unit': f.get('unit') or f.get('value_kind')} if (f.get('unit') or f.get('value_kind')) else {}))
                 for f in c['required_facts']]
        contracts[t['task']] = dict(contract=c, docs=docs, docs_norm=docs_norm,
                                    slots=slots, slots_json=json.dumps(slots, ensure_ascii=False),
                                    stage_sensitive={f['fact_id']: (len(f.get('allowed_docs') or f.get('allowed_citation_docs') or []) == 1)
                                                     for f in c['required_facts']})
    return ts, rt, pr, contracts

def verify_g7_terminal(env, contract, terminal, prompts):
    """One verifier call covering all stage-sensitive answered facts; returns (fail_list, raw)."""
    ss = contract['stage_sensitive']
    records = []
    for a in terminal.get('answers', []):
        if isinstance(a, dict) and a.get('fact_id') in ss and a.get('quote'):
            records.append(f"{a['fact_id']} | {a.get('doc','')} | {a['quote']}")
    if not records:
        return [], None, 0
    user = prompts['verifier']['user_template'].format(records='\n'.join(records))
    env.arm, env.kind = 'G7', 'verify'
    out = env.call('VERIFIER', user, system=prompts['verifier']['system'])
    stages = {s.get('fact_id'): s.get('quote_stage') for s in (out['parsed'] or {}).get('stages', [])
              if isinstance(s, dict)}
    fails = []
    by_id = {a.get('fact_id'): a for a in terminal.get('answers', []) if isinstance(a, dict)}
    for rec_line in records:
        fid = rec_line.split(' | ')[0]
        a = by_id.get(fid)
        q = R.SC.norm_text(a.get('quote', ''))   # 冻结管线同口径规范化（NFKC+去空白）
        reasons = []
        # deterministic R2-precheck: quote must exist verbatim in cited doc
        if a.get('doc') not in contract['docs_norm'] or q not in contract['docs_norm'].get(a.get('doc'), ''):
            reasons.append('引文非被引文书逐字原文')
        vs = stages.get(fid)
        gold_stage = next(x['fact_stage'] for x in contract['contract']['required_facts'] if x['fact_id'] == fid)
        if vs is None:
            reasons.append('核验器未覆盖')
        elif vs == '不明确':
            reasons.append('核验器判阶不明确')
        elif vs != gold_stage:
            reasons.append(f'核验器判阶{vs}≠事实阶段{gold_stage}')
        if reasons:
            fails.append(dict(rec_line=rec_line, fid=fid, reasons=reasons, stage=gold_stage,
                              doc=a.get('doc',''), quote=a.get('quote','')))
    return fails, out['parsed'], len(records)

def build_reanchor_user(prev_terminal, fails, rows, slots_json, prompts):
    items = [prompts['failure_item_template'].format(
        fid=f['fid'], stage=f['stage'], doc=f['doc'], quote=f['quote'], reason='；'.join(f['reasons']))
             for f in fails]
    return prompts['reanchor']['user_template'].format(
        prev=json.dumps(prev_terminal, ensure_ascii=False), failures='\n'.join(items),
        evidence=R.evidence_block(rows), slots=slots_json)

def run_block(tag, rep, ct, env, prompts, arm_first):
    c = ct['contract']
    docs, docs_norm, slots_json = ct['docs'], ct['docs_norm'], ct['slots_json']
    env.task, env.rep = tag, rep
    env.arm, env.kind = 'shared', 'normal'
    try:
        e1 = env.call('E_D1', R.e_user(docs['D1']))
        e2 = env.call('E_D2', R.e_user(docs['D2']))
        j1 = env.call('J1', R.j1_user({'E_D1': e1['text'], 'E_D2': e2['text']}))
        j2 = env.call('J2', R.j2_user(j1['text'], slots_json))
    except ModelFault as mf:
        return dict(shared_fault=str(mf), arms={a: None for a in ARMS}, states={}, targets=[])
    e_texts = {'E_D1': e1['text'], 'E_D2': e2['text']}
    rows, _ = R.evidence_rows(e_texts, docs_norm)
    base = BT.total(R.OLD.extract_json(e_texts['E_D2']), docs['D2'])
    bline = '\n'.join(TXT.BASE_LINE.format(fact_id=f['fact_id'], subject=f['subject'],
                    predicate=f['predicate'], value=base['value'], parties=base['parties'])
                    for f in c['required_facts'] if D5.slot_type(dict(predicate=f['predicate'])) == 'derived') if base.get('value') else ''
    m1 = D5.detect_m1([dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                            **({'unit': f.get('unit') or f.get('value_kind')} if (f.get('unit') or f.get('value_kind')) else {}))
                       for f in c['required_facts']], j2['parsed'], rows)
    states = {}
    for f in c['required_facts']:
        s = m1[f['fact_id']]['state']
        states[f['fact_id']] = {'EXPLICIT_SUPPRESSION': 'S1', 'UNKNOWN_LABEL': 'S2', 'OMISSION': 'S3'}.get(s, 'OK')
    targets = {k for k, v in states.items() if v in ('S1', 'S2', 'S3')}
    def sink_user(j2t): return f'核验结果：\n{j2t}\n\n{R.evidence_block(rows)}\n\n{bline}\n\n槽位：{slots_json}'
    by_row = {r['row']: r for r in rows}
    def addendum(fids):
        items = []
        for f in c['required_facts']:
            if f['fact_id'] in fids and m1[f['fact_id']]['candidate_rows']:
                cands = '；'.join(TXT.A2_ROW.format(row=r, doc=by_row[r]['doc'], quote=by_row[r]['quote'])
                                 for r in m1[f['fact_id']]['candidate_rows'])
                items.append(TXT.A2_ITEM.format(fact_id=f['fact_id'], subject=f['subject'],
                                                predicate=f['predicate'], rows=cands))
        return TXT.A2_HEADER + '\n' + '\n'.join(items) if items else ''
    def g6_actions():   # G6-M: P2-C G6 logic verbatim
        g2 = env.call('SINK', sink_user(j2['text']))['parsed']
        if not targets: return g2
        s2_present = any(states[f] == 'S2' for f in targets)
        if not s2_present:
            edit = json.dumps(dict(j2['parsed'], verified=[v for v in j2['parsed'].get('verified', [])
                                if not (isinstance(v, dict) and str(v.get('fact_id')) in targets)]), ensure_ascii=False)
            return env.call('SINK', sink_user(edit))['parsed']
        jt = env.call('J2R', R.j2_user(j1['text'], slots_json) + '\n\n' + addendum(targets))
        return env.call('SINK', sink_user(jt['text']))['parsed']
    out = dict(shared_fault=None, states=states, targets=sorted(targets), arms={}, audit={})
    order = [arm_first, 'G7' if arm_first == 'G6-M' else 'G6-M']
    for arm in order:
        env.arm, env.kind = arm, 'normal'
        try:
            terminal = g6_actions()
            audit = dict(reanchor_calls=0, verify_calls=0, versions=[], final_failed=None)
            if arm == 'G7':
                n_verify = 0
                fails, vraw, nrec = verify_g7_terminal(env, ct, terminal, prompts)
                n_verify += 1
                audit['verify_calls'] = n_verify
                audit['versions'].append(dict(version=0, verifier=vraw, fails=[f['fid'] for f in fails]))
                n_reanchor = 0
                while fails and n_reanchor < MAX_REANCHOR and n_verify < MAX_VERIFY:
                    env.arm, env.kind = 'G7', 'reanchor'
                    term2 = env.call('REANCHOR', build_reanchor_user(terminal, fails, rows, slots_json, prompts),
                                     system=prompts['reanchor']['system'])['parsed']
                    n_reanchor += 1
                    terminal = term2
                    env.arm, env.kind = 'G7', 'normal'
                    fails, vraw, nrec = verify_g7_terminal(env, ct, terminal, prompts)
                    n_verify += 1
                    audit['versions'].append(dict(version=n_reanchor, verifier=vraw, fails=[f['fid'] for f in fails]))
                audit['reanchor_calls'] = n_reanchor
                audit['verify_calls'] = n_verify
                audit['final_failed'] = [f['fid'] for f in fails]
            # M3 zeroing verbatim (both arms)
            m3 = D5.detect_m3([dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'])
                              for f in c['required_facts']], terminal, rows, base)
            viol = sorted((f for f, v in m3.items() if v['state'] == 'SELF_EVIDENCE_INCONSISTENT'), key=lambda x: int(x[1:]))
            if viol:
                terminal = dict(terminal)
                terminal['answers'] = [a for a in terminal.get('answers', [])
                                       if not (isinstance(a, dict) and a.get('fact_id') in viol)]
                terminal['unknown_slots'] = sorted(set(map(str, terminal.get('unknown_slots', []))) | set(viol), key=lambda x: int(x[1:]))
                audit['m3_zeroed'] = viol
            out['arms'][arm] = terminal
            out['audit'][arm] = audit
        except ModelFault as mf:
            out['arms'][arm] = None
            out['audit'][arm] = dict(execution_failed=str(mf))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--real', action='store_true')
    args = ap.parse_args()
    if not args.real:
        raise SystemExit('offline mode removed; use --real with G7_GO=1')
    if os.environ.get('G7_GO') != '1': raise SystemExit('REFUSED: G7_GO=1 required')
    for k in ('DEEPSEEK_API_KEY', 'STAGE_D_GLM_KEY'):
        if not os.environ.get(k, '').strip(): raise SystemExit(f'REFUSED: {k} not set')
    ts, rt, prompts, contracts = load_block_state()
    gate = json.loads((HERE / 'g7_tasks' / 'G7_GO_GATE.json').read_text('utf-8'))
    assert prompts['sha256'] == hashlib.sha256(
        json.dumps({k: v for k, v in prompts.items() if k != 'sha256'}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    OUT.mkdir(exist_ok=True)
    ledger = R.Ledger(OUT / 'LEDGER.jsonl')
    ledger.write(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'), kind='manifest', phase='pre-registered',
                      prompts_sha256=prompts['sha256'], gate_status=gate['status'],
                      taskset_sha256=ts['manifest_sha256'], randomization_sha256=rt['seed'],
                      note='提示词实例化sha预登记（GO门规则）；此后方可发起模型调用'))
    budget = R.Budget(**CAPS)
    env = Env(R.RealTransport(), ledger, budget)
    results = {}
    if (OUT / 'G7_RESULTS.json').exists():
        results = json.loads((OUT / 'G7_RESULTS.json').read_text('utf-8'))
    for blk in rt['block_execution_order']:
        tag, rep = blk['task'], blk['rep']
        key = f'{tag}_r{rep}'
        if key in results:
            continue
        ct = contracts[tag]
        arm_first = rt['arm_order_within_block'][f'{tag}|{rep}']
        try:
            o = run_block(tag, rep, ct, env, prompts, arm_first)
            results[key] = dict(seq=blk['seq'], arm_first=arm_first, shared_fault=o['shared_fault'],
                                states=o.get('states') or {}, targets=o.get('targets') or [],
                                arms=o.get('arms') or {a: None for a in ARMS},
                                audit=o.get('audit') or {a: dict(shared_fault=o['shared_fault']) for a in ARMS})
        except Stop as s:
            results[key] = dict(seq=blk['seq'], arm_first=arm_first, stopped=str(s))
            (OUT / 'G7_RESULTS.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), 'utf-8')
            print(f'BATCH STOP at block {blk["seq"]} {key}: {s}', flush=True)
            return
        (OUT / 'G7_RESULTS.json').write_text(json.dumps(results, ensure_ascii=False, indent=1), 'utf-8')
        done = len([k for k, v in results.items() if 'stopped' not in v])
        print(f'  [{blk["seq"]:2}/80] {key} arm_first={arm_first} '
              f'G6M={"OK" if o["arms"]["G6-M"] else "FAIL"} G7={"OK" if o["arms"]["G7"] else "FAIL"} '
              f'({done} done, {budget.calls} calls, {budget.tokens/1e6:.2f}M)', flush=True)
    print('ALL BLOCKS COMPLETE', flush=True)

if __name__ == '__main__':
    main()
