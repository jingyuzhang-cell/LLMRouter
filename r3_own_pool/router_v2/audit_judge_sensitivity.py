"""Train-only descriptive sensitivity audit; never changes labels or certifies a judge."""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
import json
import math
from pathlib import Path
from .assemble_development import snapshot, label_key
from .data import load_cohort, sha
from .score_available import digest
from .core import SLOTS
from . import assemble_development as matrix

ROOT = Path(__file__).resolve().parents[1]


def component_quality(row):
    rubric = row.get('rubric', {})
    values = [rubric.get(k) for k in ('correctness', 'completeness', 'clarity')]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           not math.isfinite(v) or not 0 <= v <= limit
           for v, limit in zip(values, (6, 2, 2))):
        return None
    return sum(values) / 10


def summarize(rows):
    counts = Counter(); by_slot = defaultdict(Counter); groups = defaultdict(list)
    for row in rows:
        counts['primary_labels'] += 1
        slot = by_slot[row['slot']]; slot['primary_labels'] += 1
        alt = component_quality(row)
        if alt is None:
            counts['unusable_components'] += 1
            slot['unusable_components'] += 1
            continue
        changed = abs(row['quality'] - alt) > 1e-8
        counts['comparable_labels'] += 1
        counts['changed_labels'] += int(changed)
        counts['absolute_difference_sum'] += abs(row['quality'] - alt)
        slot['comparable_labels'] += 1; slot['changed_labels'] += int(changed)
        groups[row['query_id']].append((row['slot'], row['quality'], alt))
    sign = lambda x: 0 if abs(x) < 1e-8 else (1 if x > 0 else -1)
    for values in groups.values():
        for a, b in combinations(values, 2):
            primary, alternate = sign(a[1]-b[1]), sign(a[2]-b[2])
            counts['comparable_same_query_pairs'] += 1
            counts['strict_order_reversals'] += int(primary * alternate == -1)
            counts['tie_status_changes'] += int((primary == 0) != (alternate == 0))
        if {v[0] for v in values} == set(SLOTS) and len(values) == len(SLOTS):
            counts['complete_four_slot_queries'] += 1
            best = lambda col: {v[0] for v in values if abs(v[col]-max(x[col] for x in values)) < 1e-8}
            counts['best_slot_set_changes'] += int(best(1) != best(2))
    n = counts.get('comparable_labels', 0)
    return dict(counts=dict(counts), by_slot={k: dict(v) for k,v in by_slot.items()},
                mean_absolute_label_difference=counts.get('absolute_difference_sum', 0)/n if n else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    cohort, split = load_cohort(ROOT/'data/cohort_full_v2')
    train = set(split['train'])
    journal = ROOT/'data/judged_train_primary_v2/ATTEMPTS.jsonl'
    events, provenance = snapshot(journal)
    raw = {s: matrix.storage.canonical_rows(ROOT/'data/raw'/f'{s}.jsonl') for s in SLOTS}
    first = {}; exclusions = Counter()
    for event in events:
        if event.get('event') != 'grade': continue
        qid, slot = event['query_id'], event['slot']
        if qid not in train or cohort[qid]['dataset'] != 'arenahard':
            raise ValueError('Journal contains a grade outside train arenahard')
        response = raw.get(slot, {}).get(qid)
        if response is None or event['source_sha256'] != digest(cohort[qid]) or event['response_sha256'] != digest(response):
            exclusions['stale_or_unmatched_grade_events'] += 1
            continue
        quality = event.get('quality')
        if isinstance(quality, bool) or not isinstance(quality, (int,float)) or not math.isfinite(quality) or not 0 <= quality <= 1:
            raise ValueError('Invalid primary quality')
        first.setdefault(label_key(event), event)
    report = dict(partition='train', journal_snapshot=provenance,
                  query_sha256=sha(ROOT/'data/cohort_full_v2/queries.jsonl'),
                  split_sha256=sha(ROOT/'data/cohort_full_v2/split.json'),
                  implementation_sha256=sha(Path(__file__)), exclusions=dict(exclusions),
                  **summarize(list(first.values())),
                  interpretation='Component-sum is a sensitivity alternative, not ground truth. Available train labels are a nonrandom incomplete snapshot. No reliability certification, no router evaluation, no label changes.',
                  formal_training_ready=False, test_labels_loaded=False)
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    (out/'AUDIT.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
