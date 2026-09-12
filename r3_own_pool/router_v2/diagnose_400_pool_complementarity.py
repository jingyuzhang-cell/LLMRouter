"""Pool-complementarity diagnostic on the frozen 400-query repeat labels.

Read-only: counts oracle winners, winner entropy, per-model beats-R1 lists with
repeat-level consistency, subject breakdown, and the R1-centric gap decomposition.
Definitions match train_repeat_compatibility_400_fold_local (y = mean of 5 repeats).
"""
import json, math
from collections import Counter
from pathlib import Path

from .data import sha
from .mmlu_learnability import subject_from_query

ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / 'router_v2/mmlu_utility_panel_400'
DATA = ROOT / 'data/repeat_compatibility_400_rescore_v1'
OUT = ROOT / 'router_v2/pool_complementarity_400'
SLOTS = ['medium', 'large', 'coder', 'reasoning']  # R1 = reasoning


def main():
    manifest = json.loads((PANEL_DIR / 'MANIFEST.json').read_text())
    status = json.loads((DATA / 'STATUS.json').read_text())
    labels_path = DATA / 'EXPECTED_UTILITY_LABELS.jsonl'
    if sha(labels_path) != status['labels_sha256']:
        raise ValueError('Labels changed')
    panel = {r['query_id']: r for r in map(json.loads, (PANEL_DIR / 'PANEL.jsonl').read_text().splitlines())}
    labels = {r['query_id']: r for r in map(json.loads, labels_path.read_text().splitlines())}
    ids = sorted(labels)
    if set(panel) != set(labels) or len(ids) != 400:
        raise ValueError('Panel/label mismatch')

    y = {q: {m: labels[q]['models'][m]['mean'] for m in SLOTS} for q in ids}
    vals = {q: {m: labels[q]['models'][m]['values'] for m in SLOTS} for q in ids}
    subject = {q: subject_from_query(panel[q]['query']) for q in ids}

    # 1) oracle winners (unique argmax only; ties reported separately)
    winner = {}
    ties = {}
    for q in ids:
        best = max(y[q].values())
        top = [m for m in SLOTS if y[q][m] == best]
        winner[q] = top[0] if len(top) == 1 else 'tie'
        ties[q] = top
    counts = Counter(winner.values())
    unique_n = sum(c for k, c in counts.items() if k != 'tie')
    p = [c / unique_n for k, c in counts.items() if k != 'tie' and c > 0]
    entropy_norm = float(sum(-pi * math.log2(pi) for pi in p) / math.log2(len(SLOTS)))

    # 2) per-model beats-R1 lists + repeat-level consistency + margins
    beats = {}
    for m in SLOTS[:-1]:
        rows = []
        for q in ids:
            diff = y[q][m] - y[q]['reasoning']
            if diff > 0:
                pairs = [a - b for a, b in zip(vals[q][m], vals[q]['reasoning'])]
                rows.append({'query_id': q, 'subject': subject[q], 'margin': round(diff, 3),
                             'repeat_wins': int(sum(v > 0 for v in pairs)), 'repeat_ties': int(sum(v == 0 for v in pairs))})
        rows.sort(key=lambda r: (-r['margin'], r['query_id']))
        beats[m] = rows

    # 3) R1-centric gap decomposition on the full 400
    decomp = {q: round(max(max(y[q][m] for m in SLOTS[:-1]) - y[q]['reasoning'], 0.0), 3) for q in ids}
    gap_from_alt_wins = sum(decomp.values()) / len(ids)
    oracle_gap = sum(max(y[q].values()) - y[q]['reasoning'] for q in ids) / len(ids)

    # tie composition: all-correct / all-wrong / genuine mixed ties
    tie_comp = Counter()
    for q in ids:
        if winner[q] == 'tie':
            v = [y[q][m] for m in SLOTS]
            if all(x == 1.0 for x in v):
                tie_comp['all_correct'] += 1
            elif all(x == 0.0 for x in v):
                tie_comp['all_wrong'] += 1
            else:
                tie_comp['mixed'] += 1

    # 4) subject breakdown of alt>R1 queries (union over the three models)
    union_q = sorted({r['query_id'] for rows in beats.values() for r in rows})
    subj_total = Counter(subject.values())
    subj_union = Counter(subject[q] for q in union_q)

    result = {
        'labels_sha256': status['labels_sha256'],
        'n': len(ids),
        'winner_counts': {m: int(counts.get(m, 0)) for m in SLOTS} | {'tie': int(counts.get('tie', 0))},
        'winner_entropy_normalized': entropy_norm,
        'tie_composition': dict(tie_comp),
        'tie_detail': {q: ties[q] for q in ids if winner[q] == 'tie'},
        'beats_r1': {m: {'count': len(rows), 'queries': rows} for m, rows in beats.items()},
        'beats_r1_union_count': len(union_q),
        'oracle_gap_mean': round(oracle_gap, 4),
        'gap_share_from_alt_beats_r1': round(gap_from_alt_wins, 4),
        'subject_breakdown': {s: {'union_beats_r1': subj_union[s], 'panel_total': subj_total[s]}
                              for s in sorted(subj_union, key=lambda s: -subj_union[s])},
    }
    OUT.mkdir(exist_ok=True)
    (OUT / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')

    print(json.dumps({k: v for k, v in result.items() if k not in ('tie_detail', 'beats_r1')}, indent=2))
    for m, rows in beats.items():
        strong = [r for r in rows if r['repeat_wins'] >= 3]
        print(f"\n{m}: beats R1 on {len(rows)}/400 (>=3/5 repeat wins: {len(strong)})")
        for r in rows[:12]:
            print(f"  {r['query_id']} {r['subject']:<28} margin={r['margin']:+.2f} repeats {r['repeat_wins']}/5")


if __name__ == '__main__':
    main()
