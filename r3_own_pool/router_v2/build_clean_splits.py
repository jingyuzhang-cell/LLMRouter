"""Export all partitions with response-bound labels; test quality stays unreported.

Missing data remain explicit. Clean is not equivalent to complete or unexposed.
No generation, judge requests, or candidate-code execution happens here.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
from .assemble_clean_matrix import snapshot, label_key
from .data import load_cohort, sha
from .score_available import digest, score
from .core import SLOTS
from .integrity import known_exposure, normalize_prompt
from .assemble_clean_matrix import storage

ROOT = Path(__file__).resolve().parents[1]


def invalid_response(raw):
    if raw is None:
        return 'not_collected'
    if raw.get('error') or raw.get('status') == 'failed':
        return 'infrastructure_failure_missing'
    if raw.get('status') not in ('ok', 'truncated', 'parse_failed'):
        return 'unknown_generation_status'
    if not raw.get('answer') and raw.get('status') != 'truncated':
        return 'empty_response_missing'
    return None


def load_labels(root, partition):
    labels, evidence = {}, {}
    # The first valid label on the EXACT source+response is retained. Versions
    # are only recovery caches; old-response labels cannot bind to new outputs.
    patterns = [f'scored_code_{partition}_v*/SCORES.jsonl',
                f'scored_code_numpy_{partition}_v*/SCORES.jsonl',
                f'judged_{partition}_primary_v*/ATTEMPTS.jsonl']
    for pattern in patterns:
        for path in sorted((root / 'data').glob(pattern)):
            rows, info = snapshot(path)
            evidence[str(path)] = info
            for row in rows:
                if 'event' in row and row['event'] != 'grade':
                    continue
                q = row.get('quality')
                if q is None or row.get('evaluation_status') == 'generation_failure':
                    continue
                if isinstance(q, bool) or not math.isfinite(q) or not 0 <= q <= 1:
                    raise ValueError('Invalid label in ' + str(path))
                labels.setdefault(label_key(row), (str(path), row))
    return labels, evidence


def make_cell(source, slot, raw, labels):
    reason = invalid_response(raw)
    raw = raw or {}
    sh, rh = digest(source), digest(raw)
    cell = dict(slot=slot, model=raw.get('model'), status=raw.get('status', 'not_collected'),
                source_sha256=sh, response_sha256=rh,
                cost=raw.get('cost') or {}, latency=raw.get('latency') or {},
                provenance=raw.get('provenance') or {})
    result, origin = {}, None
    if reason is None:
        if source['dataset'] in ('gsm8k', 'mmlupro'):
            result = score(source, raw)
            origin = 'auto'
            if result.get('evaluation_status') == 'generation_failure':
                result['evaluation_status'] = 'no_final_answer'
        else:
            origin, result = labels.get((source['query_id'], slot, sh, rh), (None, {}))
    value = None if reason else result.get('quality')
    if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError('Invalid quality')
    cache_origin = origin
    if origin and '/scored_code_numpy_' in origin: origin = 'code_numpy'
    elif origin and '/scored_code_' in origin: origin = 'code_stdlib'
    elif origin and '/judged_' in origin: origin = 'judge_primary'
    cell['label_cache'] = cache_origin if cache_origin != 'auto' else None
    cell['quality'] = dict(final=value, quality_source=reason or origin or 'unscored',
                           flags=['judge_components_inconsistent'] if result.get('rubric', {}).get('components_consistent') is False else [])
    cell['evaluation_status'] = reason or result.get('evaluation_status', result.get('event', 'unscored'))
    return cell


def run(root, output):
    root, out = Path(root), Path(output)
    out.mkdir(parents=True, exist_ok=False)
    cohort, splits = load_cohort(root / 'data/cohort_full_v2')
    raw = {s: storage.canonical_rows(root / 'data/raw' / (s + '.jsonl')) for s in SLOTS}
    exposure = json.loads((root / 'router_v2/exposure_audit/AUDIT.json').read_text())
    manifest = dict(role='clean split matrix with explicit missingness; no test performance report',
                    source_query_sha256=sha(root / 'data/cohort_full_v2/queries.jsonl'),
                    source_split_sha256=sha(root / 'data/cohort_full_v2/split.json'),
                    builder_sha256=sha(__file__),
                    metrics_sha256=sha(root / 'collect/metrics.py'),
                    failure_policy='API and infrastructure errors map to null; valid incorrect answers remain zero; no correctness-based retries',
                    raw_selection='first successful response, otherwise latest terminal attempt; original history retained',
                    test_performance_reported=False, split_modified=False, partitions={})
    repair = []
    for partition, ids in splits.items():
        labels, evidence = load_labels(root, partition)
        counts, datasets, objective = Counter(), {}, Counter()
        all_path = out / (partition.upper() + '_MATRIX.jsonl')
        complete_path = out / (partition.upper() + '_COMPLETE.jsonl')
        objective_path = out / (partition.upper() + '_OBJECTIVE_COMPLETE.jsonl')
        with all_path.open('x') as full, complete_path.open('x') as clean, objective_path.open('x') as obj:
            for qid in ids:
                source = cohort[qid]
                row = {k: source[k] for k in ('query_id', 'query', 'dataset', 'task_type')}
                row['responses'] = [make_cell(source, s, raw[s].get(qid), labels) for s in SLOTS]
                per = datasets.setdefault(source['dataset'], Counter())
                good = all(c['quality']['final'] is not None for c in row['responses'])
                for c in row['responses']:
                    counts['expected_cells'] += 1
                    key = 'labeled_cells' if c['quality']['final'] is not None else c['evaluation_status']
                    counts[key] += 1; per[key] += 1
                    if c['quality']['final'] is None:
                        repair.append(dict(partition=partition, query_id=qid, dataset=source['dataset'], slot=c['slot'], reason=c['evaluation_status']))
                    if c['status'] == 'failed' and c['quality']['final'] is not None:
                        raise AssertionError('Failure leaked into labels')
                counts['queries'] += 1; counts['complete_queries'] += int(good)
                if source['dataset'] != 'arenahard':
                    objective['queries'] += 1; objective['complete_queries'] += int(good)
                text = json.dumps(row, ensure_ascii=False) + '\n'
                full.write(text)
                if good:
                    clean.write(text)
                    if source['dataset'] != 'arenahard': obj.write(text)
        manifest['partitions'][partition] = dict(counts=dict(counts), objective=dict(objective),
            by_dataset={k: dict(v) for k,v in datasets.items()}, cache_snapshots=evidence,
            files={p.name: sha(p) for p in (all_path, complete_path, objective_path)},
            complete_case_policy='Secondary diagnostic only; excluded IDs remain in full matrix and repair queue')
    with (out / 'REPAIR_QUEUE.jsonl').open('x') as f:
        for row in repair: f.write(json.dumps(row) + '\n')
    exposed_ids, exposed_texts, opened = known_exposure(root)
    quarantine = {p: sorted(q for q in ids if q in exposed_ids or normalize_prompt(cohort[q]['query']) in exposed_texts) for p, ids in splits.items()}
    manifest['prior_test_opening_evidence'] = opened
    manifest['pilot_only_exposure_counts'] = exposure['overlap_counts']
    (out / 'KNOWN_EXPOSURE_IDS.json').write_text(json.dumps(quarantine, indent=2) + '\n')
    manifest.update(clean_failure_policy_pass=True, all_cells_labeled=not repair,
        known_exposure_counts={p: len(v) for p,v in quarantine.items()},
        holdout_uncontaminated=False, formal_training_ready=False,
        cost_provenance_verified=False, comparable_latency_verified=False,
        limitations=['Historical test exposure is not undone by re-export or reshuffling.',
                     'Fresh independent holdout or a fully audited untouched subset is required.',
                     'Recorded USD costs are legacy proxies; mixed local/API latency is exploratory.',
                     'Stable-pair collection/training requires separate verified repeat labels.'])
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    lines = ['# Clean matrix audit', '', '| Partition | Queries | Complete | Missing cells | Objective complete |', '|---|---:|---:|---:|---:|']
    for p, v in manifest['partitions'].items():
        c, o = v['counts'], v['objective']
        lines.append(f"| {p} | {c['queries']} | {c['complete_queries']} | {c['expected_cells']-c.get('labeled_cells',0)} | {o.get('complete_queries',0)}/{o.get('queries',0)} |")
    lines += ['', 'Infrastructure failures are null, never zero. Full matrices retain every original query.',
              'COMPLETE files are explicitly conditional development subsets, not a silently reduced primary benchmark.',
              'No test quality aggregates were emitted. Original test has prior evaluation exposure; all 750 historical test IDs are retired from independent confirmation.',
              'See REPAIR_QUEUE.jsonl for exact missing cells and MANIFEST.json for provenance.']
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return manifest


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', default=str(ROOT)); ap.add_argument('--output', required=True)
    a = ap.parse_args(); run(a.root, a.output)
