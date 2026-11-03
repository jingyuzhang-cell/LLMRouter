"""Phase V2.3-A / S2 analysis: per-task qualification verdict.

Rules (preregistered in S2_PROTOCOL.md):
  A_any = target slots correct in >=1 of the 2 full-material repetitions
  B_any = target slots correct in >=1 of the 2 ablated repetitions
  flips = |A_any - B_any|
  drop  = flips / |A_any|
  PASS  if A_any non-empty and (flips >= 2 or drop >= 0.5)
  FAIL  if A_any non-empty and not PASS
  INCONCLUSIVE if A_any empty (no baseline to lose)
  ERROR if any cell failed to produce a sink
"""
import json, sys

ROOT = '/root/research_outputs/static_pi/stage_d/v23a'


def main(path):
    d = json.load(open(path))
    cells = d['results']
    by_task = {}
    for c in cells:
        by_task.setdefault(c['task_id'], []).append(c)
    rows = []
    for tid, cs in by_task.items():
        err = [c for c in cs if c.get('error') or not c.get('parse_ok', True)]
        if err:
            rows.append(dict(task_id=tid, verdict='ERROR', n_cells=len(cs),
                             errors=[c.get('error') or 'no_sink' for c in err][:3]))
            continue
        slots = cs[0]['target_slots']
        def correct_set(cond):
            s = set()
            for c in cs:
                if c['condition'] != cond:
                    continue
                for fid in slots:
                    if (c['grades'].get(fid) or {}).get('correct'):
                        s.add(fid)
            return s
        A, B = correct_set('A'), correct_set('B')
        flips = sorted(A - B)
        drop = len(flips) / len(A) if A else None
        if not A:
            verdict = 'INCONCLUSIVE'
        elif len(flips) >= 2 or (drop is not None and drop >= 0.5):
            verdict = 'PASS'
        else:
            verdict = 'FAIL'
        per_rep = {}
        for c in cs:
            per_rep[f"{c['condition']}r{c['repeat']}"] = dict(
                correct=c['completed'], total=c['total'],
                slots={f: (c['grades'].get(f) or {}).get('status') for f in slots})
        rows.append(dict(task_id=tid, verdict=verdict,
                         A_correct=sorted(A), B_correct=sorted(B),
                         flips=flips, n_flips=len(flips), drop_rate=round(drop, 3) if drop is not None else None,
                         per_rep=per_rep))
    summary = {}
    for r in rows:
        summary[r['verdict']] = summary.get(r['verdict'], 0) + 1
    out = dict(batch='PHASE_V23A_S2_ANALYSIS', source=path,
               budget=d.get('used'), caps=d.get('caps'),
               verdict_counts=summary, tasks=rows)
    json.dump(out, open(f'{ROOT}/S2_ANALYSIS.json', 'w'), ensure_ascii=False, indent=1)
    print(f"{'task':34s} {'verdict':14s} {'A':>2s} {'B':>2s} {'flips':>5s} {'drop':>6s}")
    for r in rows:
        print(f"{r['task_id'][:34]:34s} {r['verdict']:14s} {len(r.get('A_correct', [])):2d} "
              f"{len(r.get('B_correct', [])):2d} {r.get('n_flips', 0):5d} "
              f"{r.get('drop_rate') if r.get('drop_rate') is not None else '-':>6}")
    print('counts:', summary)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else f'{ROOT}/S2_RESULTS.json')
