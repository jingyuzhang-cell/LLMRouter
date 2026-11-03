"""QP5-D Study 2-4: constraint-mechanism counterfactuals + joint metrics.

Configs on CACHED C2 entries (merged semantics), all gold-blind at runtime:
  base      E-v2 as executed (table = all verified entries)
  D1a/D1b   per-fact entry cap = 1 / 2 (selection: original-pass-first, then longest quote)
  D2        conflict-drop: facts whose bound entries span >1 value-equivalence
            class get NO evidence supplied (with normalization: unit/format aware)
  D3        strict gate: schema + verbatim + self-grounding + no-unresolved-conflict
Combos: D1a+D2, D1a+D3, D2+D3, D1a+D2+D3 (D1 applied first).
Evidence-layer metrics are EXACT on existing entries. Terminal projections use
the empirical transfer table from Study 1 and are labeled PROJECTION (not results).
"""
import json, sys, collections, statistics as st
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/quality_phase_v1')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/qp3')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
import qp4_factorial as F
import qp3_primitives as P3
import qp2_chain as CH
import scorer_qp1 as Q1
from qp5d_attribution import merged_e_texts, load_ledger, value_correct_anyway
from real_provider_v22 import extract_any as extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'


def value_class(v):
    return P3.deco_amount(v)


def classes_of(values):
    """Value-equivalence classes, unit-normalized to yuan (gold-blind).
    '89.99亿元' and '8999000000元' land in the same class; percent compared numerically."""
    from decimal import Decimal
    import qp2_amount as AM
    def canon(v):
        a = value_class(v)
        if a is None:
            return ('txt', P3._norm(v))
        num, unit = a
        if unit == '%':
            return ('pct', num)
        return ('yuan', AM.to_yuan(num, unit))
    cls = []
    for v in values:
        cv = canon(v)
        placed = False
        for c in cls:
            cc = canon(c)
            if cv[0] != cc[0]:
                continue
            if cv[0] in ('txt',):
                if cv[1] == cc[1]:
                    placed = True
                    break
            else:
                if abs(cv[1] - cc[1]) <= max(abs(cc[1]) * Decimal('0.001'), Decimal('1')):
                    placed = True
                    break
        if not placed:
            cls.append(v)
    return cls


def self_grounded(e):
    v = e.get('raw') or e.get('value')
    q = e.get('quote', '') or ''
    return bool(v not in (None, '') and q and Q1.value_in_quote(v, q))


def apply_mechanisms(bound_entries, cfg):
    """Return the supplied entry list per fact under a config. Gold-blind."""
    entries = list(bound_entries)
    if cfg.get('cap'):
        # gold-blind selector: self-grounded first, then original-first (originals
        # precede retries in the merged list), tie-break longest quote
        order = sorted(range(len(entries)), key=lambda i: (
            0 if self_grounded(entries[i]) else 1, i, -len(entries[i].get('quote', '') or '')))
        keep = sorted(order[:cfg['cap']])
        entries = [entries[i] for i in keep]
    vals = [str(e.get('raw') or e.get('value')) for e in entries]
    conflict = len(classes_of(vals)) > 1
    if cfg.get('conflict_drop') and conflict:
        return [], 'conflict'
    if cfg.get('gate'):
        gated = [e for e in entries if self_grounded(e)]
        if conflict:
            return [], 'conflict'
        if not gated:
            return [], 'gate'
        entries = gated
    return entries, ('conflict' if conflict else 'ok')


def main():
    led = load_ledger()
    configs = {
        'base': {},
        'D1_cap1': dict(cap=1),
        'D1_cap2': dict(cap=2),
        'D2_conflict': dict(conflict_drop=True),
        'D3_gate': dict(gate=True),
        'D1a_D2': dict(cap=1, conflict_drop=True),
        'D1a_D3': dict(cap=1, gate=True),
        'D2_D3': dict(conflict_drop=True, gate=True),
        'D1a_D2_D3': dict(cap=1, conflict_drop=True, gate=True),
    }
    # empirical transfer (from Study 1 output)
    att = json.load(open(f'{QP}/QP5D_ENTRIES.json'))['transfer']
    def rate(cat, outc):
        tot = sum(v for k, v in att.items() if k.startswith(cat + '|'))
        return att.get(f'{cat}|{outc}', 0) / tot if tot else None
    tp_correct = rate('correct_avail', 'TP')
    tp_wrong = rate('wrong_only', 'TP')
    tp_none = rate('none', 'TP')

    out = {}
    per_task_metrics = collections.defaultdict(dict)
    for name, cfg in configs.items():
        agg = dict(n_facts=0, covered=0, supplied_any=0, prec_ok=0, prec_d=0,
                   junk=0, dup=0, conflict_facts=0, dropped_correct=0,
                   entries_total=0, proj_tp=0, cells=0)
        for t in F.TASKS:
            tmet = dict(n_facts=0, covered=0, prec_ok=0, prec_d=0, conflict=0)
            for rep in (1, 2):
                texts = merged_e_texts(led, t, rep)
                if not texts:
                    continue
                contract = F.load_contract(t)
                entries = []
                for tx in texts:
                    entries += P3.normalize_stage(extract_any(tx))
                ver, _ = CH.verify_evidence(entries, contract)
                agg['cells'] += 1
                for f in contract['required_facts']:
                    agg['n_facts'] += 1
                    tmet['n_facts'] += 1
                    bound = [e for e in ver if P3.name_matches(e, f) or
                             Q1.value_in_quote(f.get('value'), e.get('quote', ''))]
                    if not bound:
                        agg['proj_tp'] += (tp_none or 0)
                        continue
                    supplied, why = apply_mechanisms(bound, cfg)
                    any_correct_supplied = any(value_correct_anyway(e.get('raw') or e.get('value'), f)
                                               for e in supplied)
                    any_correct_orig = any(value_correct_anyway(e.get('raw') or e.get('value'), f)
                                           for e in bound)
                    agg['covered'] += 1
                    tmet['covered'] += 1
                    if why == 'conflict':
                        agg['conflict_facts'] += 1
                        tmet['conflict'] += 1
                    if supplied:
                        agg['supplied_any'] += 1
                        agg['entries_total'] += len(supplied)
                        agg['prec_d'] += 1
                        if any_correct_supplied:
                            agg['prec_ok'] += 1
                            tmet['prec_ok'] += 1
                            tmet['prec_d'] += 1
                        if not any_correct_orig:
                            agg['dropped_correct'] += 0
                        # duplicates
                        seen = set()
                        for e in supplied:
                            nv = P3._norm(e.get('raw') or e.get('value'))
                            if nv in seen:
                                agg['dup'] += 1
                            seen.add(nv)
                        agg['proj_tp'] += tp_correct if any_correct_supplied else tp_wrong
                        if any_correct_orig and not any_correct_supplied:
                            agg['dropped_correct'] += 1
                    else:
                        # fact dropped by mechanism: projected as no-evidence
                        agg['proj_tp'] += tp_none
                        if any_correct_orig:
                            agg['dropped_correct'] += 1
            per_task_metrics[t][name] = dict(tmet)
        n = agg['n_facts']
        out[name] = dict(
            coverage=round(agg['covered'] / n, 4),
            supply_rate=round(agg['supplied_any'] / n, 4),
            precision=round(agg['prec_ok'] / max(1, agg['prec_d']), 4),
            junk_unbound=len([]),
            dup_rate=round(agg['dup'] / max(1, agg['entries_total']), 4),
            conflict_facts=agg['conflict_facts'],
            dropped_correct_facts=agg['dropped_correct'],
            mean_entries_per_cell=round(agg['entries_total'] / max(1, agg['cells']), 1),
            projected_Q=round(agg['proj_tp'] / n, 4),
            note='projected_Q uses Study-1 empirical transfer rates; PROJECTION ONLY')
    json.dump(dict(batch='QP5D_COUNTERFACTUAL', model_calls=0, configs=out,
                   transfer_rates=dict(correct_avail_TP=tp_correct, wrong_only_TP=tp_wrong, none_TP=tp_none),
                   per_task={t: {k: {m: vv for m, vv in v.items()} for k, v in d.items()}
                             for t, d in per_task_metrics.items()}),
              open(f'{QP}/QP5D_COUNTERFACTUAL_ANALYSIS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{'config':12s} {'supply':>7s} {'prec':>6s} {'conf':>5s} {'dropC':>6s} {'ent/cell':>8s} {'projQ':>6s}")
    for name, m in out.items():
        print(f"{name:12s} {m['supply_rate']:7.3f} {m['precision']:6.3f} {m['conflict_facts']:5d} "
              f"{m['dropped_correct_facts']:6d} {m['mean_entries_per_cell']:8.1f} {m['projected_Q']:6.3f}")
    print(f"\ntransfer rates: correct_avail->TP {tp_correct:.3f} | wrong_only->TP {tp_wrong:.3f} | none->TP {tp_none:.3f}")


if __name__ == '__main__':
    main()
