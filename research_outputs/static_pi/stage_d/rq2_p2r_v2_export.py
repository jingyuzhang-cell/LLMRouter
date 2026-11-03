#!/usr/bin/env python3
"""Export V2 per-exec and per-slot CSVs (ZERO API calls)."""
import csv, json
from pathlib import Path
import rq2_p2r_v2_analyze as M

HERE = Path(__file__).parent
A = M.load_records(M.V1, ['A'])
BC = M.load_records(M.V2, ['B', 'C'])
ALL = dict(A); ALL.update(BC)
ex_a = M.exec_costs(M.load_ledger(M.V1))
ex_bc = M.exec_costs(M.load_ledger(M.V2))
EX = dict(ex_a); EX.update(ex_bc)


def chosen_stats(rec):
    base_fail = chosen_fail = adopted = 0
    for x in rec['nodes']:
        if 'chosen' not in x:
            continue
        base_fail += int(bool(x.get('signals', {}).get('exec')))
        chosen_fail += int(not M.chosen_ok(x))
        adopted += int(bool(x['chosen'].get('rerolled')))
    return base_fail, chosen_fail, adopted


with open(HERE / 'RQ2_P2R_V2_EXECS.csv', 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['arm', 'task', 'rep', 'report_gate', 'q_main', 'q_main_raw',
                'q_full', 'q_full_raw', 'tp', 'tp_raw', 'sup', 'sup_raw', 'n',
                'calls', 'tokens', 'yuan', 'span_s', 'verify_calls', 'verify_unique',
                'verify_reused', 'cap_hits', 'adopted', 'base_parse_fail',
                'chosen_parse_fail'])
    for (arm, task, rep), rec in sorted(ALL.items()):
        s = M.score(rec)
        c = EX.get((arm, task, rep), {})
        d = rec.get('dedup', {})
        bf, cf, ad = chosen_stats(rec)
        w.writerow([arm, task, rep, int(s['report_ok']),
                    round(s['q_main'], 4), round(s['q_main_raw'], 4),
                    '' if s['q_full'] is None else round(s['q_full'], 4),
                    '' if s['q_full_raw'] is None else round(s['q_full_raw'], 4),
                    s['tp'], s['tp_raw'],
                    '' if arm == 'A' else s['sup'],
                    '' if arm == 'A' else s['sup_raw'], s['n'],
                    c.get('calls', ''), c.get('tokens', ''), c.get('yuan', ''),
                    c.get('span_s', ''), d.get('verify_calls', ''),
                    d.get('unique', ''), d.get('reused', ''),
                    d.get('cap_hits', ''), ad, bf, cf])

# per-slot export
rows = []
for (arm, task, rep), rec in sorted(ALL.items()):
    facts = []
    first = {}
    for x in rec['nodes']:
        if 'chosen' not in x:
            continue
        for f in x['chosen'].get('facts', []):
            if isinstance(f, dict):
                facts.append(f)
        for v in x.get('verifies', []):
            first.setdefault(M.tup(v['fact']), bool(v['supported']))
    gate = any(x.get('kind') == 'report' and 'chosen' in x and M.chosen_ok(x)
               for x in rec['nodes'])
    for g in M.GOLD[task]:
        ms = [f for f in facts if M.match(g, f)]
        # value match ignoring doc (localization failure candidate)
        vm = []
        for f in facts:
            gg = dict(g); gg['evidence_doc'] = str(f.get('doc', ''))
            if M.match(gg, f):
                vm.append(f)
        loc_fail = bool(vm) and not bool(ms)
        sup = bool(ms) and any(first.get(M.tup(f), False) for f in ms)
        if arm == 'A':
            if g['value_match_rule'] == 'unknown':
                status = 'UNKNOWN_SLOT'
            elif ms:
                status = 'TP_MAIN'
            elif loc_fail:
                status = 'LOC_FAIL'
            else:
                status = 'FN'
            sup_col = ''
        else:
            if g['value_match_rule'] == 'unknown':
                status = 'UNKNOWN_SLOT'
            elif ms and gate and sup:
                status = 'TP_SUPPORTED'
            elif ms and gate and not sup:
                status = 'TP_UNSUPPORTED'
            elif ms and not gate:
                status = 'GATE_FAIL'
            elif loc_fail:
                status = 'LOC_FAIL'
            else:
                status = 'FN'
            sup_col = int(sup)
        rows.append([arm, task, rep, g['fact_id'], int(bool(g['critical'])),
                     g['value_match_rule'], g['expected_value'], g['evidence_doc'],
                     int(bool(ms)), sup_col, int(gate), int(loc_fail), status])

with open(HERE / 'RQ2_P2R_V2_SLOTS.csv', 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['arm', 'task', 'rep', 'fact_id', 'critical', 'value_rule',
                'gold_value', 'gold_doc', 'tp_loc', 'supported', 'report_gate',
                'loc_fail', 'status'])
    w.writerows(rows)
print('exec rows', len(ALL), 'slot rows', len(rows))
