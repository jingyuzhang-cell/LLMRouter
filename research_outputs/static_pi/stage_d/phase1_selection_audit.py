#!/usr/bin/env python3
"""Phase-1 zero-call terminal fact-selection audit (operator directive 2026-11-07).

Per unit (4 tasks x base/Zx, from V3_STAGE_A_PRIME stored data):
  per-Gold-slot first-loss stage:
    EXTRACT   - slot not in code-carried store (upstream)
    SELECTION - in store, but neither cited (key_facts) nor expressed in narrative
    NARRATIVE - expressed in narrative (survives regardless of citation)
    CITED     - its gold-bearing fact's fid was cited into the delivered answer
  delivery variants (all zero-call, same stored narrative):
    V1 original key_facts      (measured delivery)
    V2 deterministic key facts (FROZEN gold-independent rules below)
    V3 full fact appendix      (two-layer delivery: body + complete appendix)
  body vs appendix quality reported SEPARATELY (appendix must not mask body).

Deterministic selection rules (frozen BEFORE looking at gold outcomes):
  force-keep: amounts (numbers with 元/万元/%), dates (19xx/20xx年 or ISO),
  entities (公司/证监会/交易所/局/协会 etc.), penalties (处罚/罚款/禁入/警告/
  责令/立案), core events (违法/违规/虚增/虚减/退市/虚假/欺诈/风险警示)
  dedup by norm(value) keeping sources; conflicts (same value, different doc) kept + flagged.
"""
import json, re
from pathlib import Path
from v3_experiment_runner import TASKS
import qcl_v3_runner as UB

HERE = Path(__file__).parent
AP = HERE / 'v3_aprime_runs'
NORM = lambda s: re.sub(r'[\s,，、；;：:]+', '', str(s))

RE_AMOUNT = re.compile(r'\d[\d,，.]*\s*(万元|亿元|元|%|％)')
RE_DATE = re.compile(r'(19|20)\d{2}\s*年|\d{4}-\d{2}-\d{2}|\d{4}\.\d{1,2}\.\d{1,2}')
RE_ENTITY = re.compile(r'公司|证监会|交易所|管理局|监管局|银行|协会|委员会|事务所')
RE_PENALTY = re.compile(r'处罚|罚款|禁入|警告|责令|立案|没收|市场禁入')
RE_CORE = re.compile(r'违法|违规|虚增|虚减|虚列|退市|虚假|欺诈|风险提示|信息披露违法违规|内幕')


def force_keep(f):
    v = str(f.get('value', '')) + str(f.get('quote', ''))
    return bool(RE_AMOUNT.search(v) or RE_DATE.search(v) or RE_ENTITY.search(v)
                or RE_PENALTY.search(v) or RE_CORE.search(v))


def deterministic_select(store):
    seen, out, dropped = {}, [], []
    for f in store:
        k = NORM(f.get('value', ''))
        if not force_keep(f):
            dropped.append(f['fid'])
            continue
        if k in seen:
            seen[k]['sources'].append(f['fid'])
            continue
        rec = {**f, 'sources': [f['fid']]}
        seen[k] = rec
        out.append(rec)
    return out, dropped


def slot_hits_in(text):
    def _hits(blob, gold):
        n = 0
        for c in gold:
            gs, gv = NORM(c['span']), NORM(c['value'])
            if (gs and gs in blob) or (len(gv) >= 6 and gv in blob):
                n += 1
        return n
    return _hits


def main():
    units = json.loads('{}')
    # load stage-A stores + A-PRIME narratives/key_facts/deliveries
    outs = [json.loads(l) for l in open(HERE / 'v3_exp_runs/outputs.jsonl')]
    aprime = [json.loads(l) for l in open(AP / 'outputs.jsonl')]
    results = {}
    for task in TASKS:
        for strat, tag, vstrat in (('Shared', 'base', 'Static'), ('DA-JS-v3.1', 'Zx', 'DA-JS-v3.1')):
            unit = f'{task}|A|r1'
            facts = []
            for o in outs:
                if o.get('unit') == unit and o.get('strat') == strat \
                        and o.get('node', '').startswith('ext_') and not o.get('injected'):
                    from rq2_p2r_runner import parse_facts
                    _, f2, _ = parse_facts(o['raw_output'])
                    if tag == 'base':
                        di = o['node'].replace('ext_', '')
                        pre = f"{di}::"
                    else:
                        di, seg = o['node'].replace('ext_', '').rsplit('_s', 1)
                        pre = f"{di}::s{seg}::"
                    facts += [{'fid': pre + str(x.get('fid', '')), 'value': x.get('value', ''),
                               'doc': x.get('doc', ''), 'quote': x.get('quote', '')}
                              for x in f2 if isinstance(x, dict)]
            store = UB.det_merge(facts)
            # A-PRIME narrative + key_facts (real outputs)
            rep = [o for o in aprime if o.get('unit') == f'{task}|{tag}'
                   and o.get('node') == 'report_narrative']
            if not rep:
                continue
            t = rep[-1]['raw_output']
            try:
                o = json.loads(t[t.find('{'):t.rfind('}') + 1])
                narrative, key_facts = str(o.get('narrative', '')), o.get('key_facts', [])
            except Exception:
                narrative, key_facts = t, []
            by_fid = {f['fid']: f for f in store}
            cited = [by_fid[str(k)] for k in key_facts if str(k) in by_fid]
            sel2, dropped = deterministic_select(store)
            gold = TASKS[task]['gold']
            H = slot_hits_in(None)

            def hits(text):
                blob = NORM(text)
                n = 0
                per = []
                for c in gold:
                    gs, gv = NORM(c['span']), NORM(c['value'])
                    hit = (gs and gs in blob) or (len(gv) >= 6 and gv in blob)
                    per.append(hit)
                    n += hit
                return n / len(gold), per

            store_blob = NORM(json.dumps(store, ensure_ascii=False))
            v1_text = narrative + json.dumps(cited, ensure_ascii=False)
            v2_text = narrative + json.dumps(sel2, ensure_ascii=False)
            v3_text = narrative + json.dumps(store, ensure_ascii=False)  # appendix = full store
            qt, per_t = hits(json.dumps(store, ensure_ascii=False))
            qv1, per_1 = hits(v1_text)
            qv2, per_2 = hits(v2_text)
            qv3, per_3 = hits(v3_text)
            qn, per_n = hits(narrative)

            # per-slot first-loss attribution (vs V1 measured delivery)
            cited_fids = {str(k) for k in key_facts}
            attribution = {}
            for i, c in enumerate(gold):
                if per_t[i]:
                    stage = ('NARRATIVE' if per_n[i] else
                             'CITED' if (per_1[i] and any(
                                 str(k) in cited_fids for k in
                                 [f['fid'] for f in store if NORM(c['span']) and NORM(c['span']) in
                                  NORM(str(f.get('value', '')) + str(f.get('quote', '')))]))
                             else 'SELECTION')
                else:
                    stage = 'EXTRACT'
                attribution[c['span'][:18]] = stage
            from collections import Counter
            cnt = Counter(attribution.values())
            results[f'{task}|{tag}'] = dict(
                store_n=len(store), cited_n=len(cited), det_sel_n=len(sel2), det_drop=len(dropped),
                Q_transport=round(qt, 3), Q_body_narrative=round(qn, 3),
                Q_V1_keyfacts=round(qv1, 3), Q_V2_deterministic=round(qv2, 3),
                Q_V3_appendix=round(qv3, 3),
                appendix_alone=round(hits(json.dumps(store, ensure_ascii=False))[0], 3),
                first_loss=dict(cnt), attribution=attribution)

    json.dump(results, open(HERE / 'PHASE1_SELECTION_AUDIT.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f"{'unit':10} {'store':>5} {'cited':>5} {'detsel':>6} | {'Qt':>5} {'Qn(body)':>8} "
          f"{'V1':>5} {'V2(det)':>7} {'V3(appx)':>8} | first-loss E/S/C/N")
    for k, r in sorted(results.items()):
        fl = r['first_loss']
        print(f"{k:10} {r['store_n']:>5} {r['cited_n']:>5} {r['det_sel_n']:>6} | "
              f"{r['Q_transport']:>5} {r['Q_body_narrative']:>8} {r['Q_V1_keyfacts']:>5} "
              f"{r['Q_V2_deterministic']:>7} {r['Q_V3_appendix']:>8} | "
              f"{fl.get('EXTRACT', 0)}/{fl.get('SELECTION', 0)}/"
              f"{fl.get('CITED', 0)}/{fl.get('NARRATIVE', 0)}")
    print('\npaired dQ (Zx - base) by delivery variant:')
    for task in TASKS:
        b, z = results.get(f'{task}|base'), results.get(f'{task}|Zx')
        if b and z:
            print(f"  {task}: V1={z['Q_V1_keyfacts'] - b['Q_V1_keyfits'] if False else z['Q_V1_keyfacts'] - b['Q_V1_keyfacts']:+.3f} "
                  f"V2={z['Q_V2_deterministic'] - b['Q_V2_deterministic']:+.3f} "
                  f"V3={z['Q_V3_appendix'] - b['Q_V3_appendix']:+.3f}")


if __name__ == '__main__':
    main()
