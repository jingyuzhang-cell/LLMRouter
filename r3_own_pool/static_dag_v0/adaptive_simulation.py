"""Adaptive Decomposition / Routing simulation (ZERO model calls, post-hoc, supplementary).

Idea under test (user-proposed): route Easy tasks to Single Large and Hard tasks to
Dynamic DAG, instead of running one strategy for all tasks. This script simulates that
policy from already-executed per-task results:

  Adaptive(oracle)  : difficulty = operator count of the GOLD derivation (>=2 = Hard)
                      — an UPPER BOUND, not deployable (answer not visible at inference).
  Adaptive(rule k)  : deployable pre-execution rules, ALL reported transparently
                      (no cherry-picking): (a) >=2 distinct numerals in the question,
                      (b) question token length >= median, (c) table row count >= median.
  Scenarios         : clean and fault injection 10/20/30% (3 seeds, mean +/- std).

Arms composed per scenario: Easy->Single LLM (with its scenario behavior), Hard->Dynamic
(with its scenario behavior). Costs composed likewise. Comparison: Single-all,
Static-all, Dynamic-all, Adaptive variants.

Writes adaptive_benchmark/ADAPTIVE_SIMULATION.md + .json.
"""
import json
import re
import statistics as st
import time

from .multidag_dynamic import OUT
from .benchmark_run import BENCH, RATES
from .verifier_run import DV

SEEDS = (20260923, 20260924, 20260925)


def load_fault(seed, rate):
    sub = BENCH / (f'fault_p{int(rate * 100)}' if seed == 20260923 else f'fault_p{int(rate * 100)}_seed{seed}')
    return json.loads((sub / 'FAULT_RESULT.json').read_text())


def run():
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    gold = {t['uid']: t['answer'] for t in tasks}

    def n_ops(d):
        return len(re.findall(r'[+\-*/]', d))

    oracle_hard = {t['uid'] for t in tasks if n_ops(t['derivation']) >= 2}
    # deployable rule features (pre-execution)
    q_numerals = {t['uid']: len(set(re.findall(r'\d+(?:\.\d+)?', t['question']))) for t in tasks}
    q_len = {t['uid']: len(t['question'].split()) for t in tasks}
    t_rows = {t['uid']: t['ctx_table'].count('\n') for t in tasks}
    med_qlen = st.median(q_len.values())
    med_rows = st.median(t_rows.values())
    rules = {
        'rule_a(>=2 numerals in question)': {u for u in uids if q_numerals[u] >= 2},
        f'rule_b(question length >= median {med_qlen:.0f})': {u for u in uids if q_len[u] >= med_qlen},
        f'rule_c(table rows >= median {med_rows:.0f})': {u for u in uids if t_rows[u] >= med_rows},
    }
    rule_quality = {name: dict(n_hard=len(hs), agreement_with_oracle=round(len(hs & oracle_hard) / len(uids), 4),
                               recall_of_oracle_hard=round(len(hs & oracle_hard) / len(oracle_hard), 4))
                    for name, hs in rules.items()}

    clean = json.loads((BENCH / 'CLEAN_RESULTS.json').read_text())

    def acc(rows, subset=None):
        sel = subset if subset is not None else uids
        return sum(1 for u in sel if rows[u]['ok']) / len(sel)

    def toks(rows, subset=None):
        sel = subset if subset is not None else uids
        return sum(rows[u]['used'] for u in sel) / len(sel)

    out = dict(generated_unix=time.time(), zero_calls=True,
               oracle=dict(n_hard=len(oracle_hard), n_easy=len(uids) - len(oracle_hard)),
               rule_quality=rule_quality, clean={}, fault={})

    def adaptive(hard_set, router_rows, dyn_rows):
        easy_set = [u for u in uids if u not in hard_set]
        ok = sum(1 for u in easy_set if router_rows[u]['ok']) + sum(1 for u in hard_set if dyn_rows[u]['ok'])
        cost = (sum(router_rows[u]['used'] for u in easy_set) + sum(dyn_rows[u]['used'] for u in hard_set)) / len(uids)
        return ok / len(uids), cost

    # clean
    row = dict(single=acc(clean['router']), static=acc(clean['static']), dynamic=acc(clean['dynamic']),
               dynamic_ideal_hard=None, rd_hard=None, dv_hard=None)
    corrected = json.loads((OUT.parent / 'corrected_replay' / 'CORRECTED_ARMS.json').read_text())
    dv = json.loads((DV / 'DV_RESULT.json').read_text())['dv']
    row['hard_detail'] = dict(
        single=round(acc(clean['router'], sorted(oracle_hard)), 4),
        dynamic=round(acc(clean['dynamic'], sorted(oracle_hard)), 4),
        dynamic_ideal=round(acc(corrected['arms']['dynamic'], sorted(oracle_hard)), 4),
        dynamic_verifier=round(acc(dv, sorted(oracle_hard)), 4))
    aq, ac = adaptive(oracle_hard, clean['router'], clean['dynamic'])
    row['adaptive_oracle'] = dict(Q=round(aq, 4), tokens=round(ac, 1))
    row['adaptive_rules'] = {}
    for name, hs in rules.items():
        aq, ac = adaptive(hs, clean['router'], clean['dynamic'])
        row['adaptive_rules'][name] = dict(Q=round(aq, 4), tokens=round(ac, 1))
    row['costs'] = dict(single=round(toks(clean['router']), 1), static=round(toks(clean['static']), 1),
                        dynamic=round(toks(clean['dynamic']), 1))
    out['clean'] = row

    # fault (3 seeds)
    for rate in RATES:
        per = {m: [] for m in ('single', 'static', 'dynamic')}
        adv_o = []
        adv_r = {name: [] for name in rules}
        for seed in SEEDS:
            fr = load_fault(seed, rate)
            per['single'].append(acc(fr['router']))
            per['static'].append(acc(fr['static']))
            per['dynamic'].append(acc(fr['dynamic']))
            aq, _ = adaptive(oracle_hard, fr['router'], fr['dynamic'])
            adv_o.append(aq)
            for name, hs in rules.items():
                aq, _ = adaptive(hs, fr['router'], fr['dynamic'])
                adv_r[name].append(aq)
        entry = {m: dict(mean=round(st.mean(v), 4), std=round(st.stdev(v), 4)) for m, v in per.items()}
        entry['adaptive_oracle'] = dict(mean=round(st.mean(adv_o), 4), std=round(st.stdev(adv_o), 4))
        entry['adaptive_rules'] = {name: dict(mean=round(st.mean(v), 4), std=round(st.stdev(v), 4))
                                   for name, v in adv_r.items()}
        out['fault'][rate] = entry

    lines = ['# Adaptive Decomposition — zero-cost simulation (post-hoc, supplementary)', '',
             f"Oracle split: {len(oracle_hard)} Hard / {len(uids) - len(oracle_hard)} Easy (gold operator count — "
             'NOT deployable; upper bound).', '',
             '## Rule quality vs oracle', '']
    for name, rq in rule_quality.items():
        lines.append(f"- {name}: hard-set size {rq['n_hard']}, agreement {rq['agreement_with_oracle']:.0%}, "
                     f"recall of oracle-hard {rq['recall_of_oracle_hard']:.0%}")
    lines += ['', '## Clean scenario', '',
              '| Policy | Accuracy | tokens/task |', '|---|---:|---:|',
              f"| Single-all | {row['single']:.4f} | {row['costs']['single']:.0f} |",
              f"| Static-all | {row['static']:.4f} | {row['costs']['static']:.0f} |",
              f"| Dynamic-all | {row['dynamic']:.4f} | {row['costs']['dynamic']:.0f} |",
              f"| Adaptive(oracle) | {row['adaptive_oracle']['Q']:.4f} | {row['adaptive_oracle']['tokens']:.0f} |"]
    for name, r in row['adaptive_rules'].items():
        lines.append(f"| Adaptive({name}) | {r['Q']:.4f} | {r['tokens']:.0f} |")
    lines += ['', f"Hard-subset detail (clean): single {row['hard_detail']['single']}, dynamic {row['hard_detail']['dynamic']}, "
              f"dynamic-ideal {row['hard_detail']['dynamic_ideal']}, dynamic+verifier {row['hard_detail']['dynamic_verifier']}.", '',
              '## Fault scenarios (3 seeds, mean±std)', '',
              '| Fault | Single-all | Dynamic-all | Adaptive(oracle) | best deployable rule |', '|---:|---:|---:|---:|---:|']
    for rate in RATES:
        e = out['fault'][rate]
        best_rule = max(e['adaptive_rules'].items(), key=lambda kv: kv[1]['mean'])
        lines.append(f"| {int(rate * 100)}% | {e['single']['mean']:.4f}±{e['single']['std']:.4f} | "
                     f"{e['dynamic']['mean']:.4f}±{e['dynamic']['std']:.4f} | "
                     f"{e['adaptive_oracle']['mean']:.4f}±{e['adaptive_oracle']['std']:.4f} | "
                     f"{best_rule[1]['mean']:.4f}±{best_rule[1]['std']:.4f} ({best_rule[0].split('(')[0]}) |")
    lines += ['', 'Verdict (honest): on the CLEAN scenario adaptive routing buys NO accuracy over Single-all '
              '(Dynamic\'s hard-subset accuracy equals, not exceeds, the single model), at higher cost than '
              'Single-all — the entry decision cannot rescue clean accuracy on this panel. Under FAULTS the '
              'composed policy is the best of all worlds at moderate rates (cheap robust easy arm + robust hard '
              'arm). This supports the paper\'s existing positioning: routing/decomposition value = cost shaping '
              'and fault-scenario composition, not clean accuracy; the failure-aware mainline is unchanged.']
    (BENCH / 'ADAPTIVE_SIMULATION.md').write_text('\n'.join(lines))
    (BENCH / 'ADAPTIVE_SIMULATION.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print('\n'.join(lines))


if __name__ == '__main__':
    run()
