"""QP3 task 1: rebuild the real round-1 experiment matrix from primary records.

Sources (read-only): QP1_LEDGER.jsonl (all node texts), QP1_DEV_PROGRESS.json
(completion + old-scorer results), QP1_DEV_RESCORED.json (revised-scorer results).
Output: QP3_MATRIX.json — every planned cell with status and both scoring versions.
"""
import json, sys, collections
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
from real_provider_v22 import extract_any

QP = '/root/research_outputs/static_pi/stage_d/quality_phase_v1'
TASKS = ['E06', 'MVR1', 'KANGMEI', 'GUOEN']
ARMS = ['Baseline', 'E1', 'E2', 'E3']
REPS = (1, 2)


def main():
    ledger = {}
    for line in open(f'{QP}/QP1_LEDGER.jsonl'):
        r = json.loads(line)
        p = r['purpose'].split('|')
        if len(p) == 5:
            ledger[(p[1], p[2], p[3], p[4])] = r
    old = {(r['task'], r['arm'], f"r{r['rep']}"): r
           for r in json.load(open(f'{QP}/QP1_DEV_PROGRESS.json'))['results']}
    new = {(r['task'], r['arm'], r['rep']): r
           for r in json.load(open(f'{QP}/QP1_DEV_RESCORED.json'))['rows']}

    cells = []
    for t in TASKS:
        for rep in REPS:
            for arm in ARMS:
                nodes = {n: ledger.get((t, arm, f'r{rep}', n)) for n in
                         ('e0', 'e1', 't', 'm', 'r', 'v', 'p')}
                have = {k: bool(v) for k, v in nodes.items()}
                o = old.get((t, arm, f'r{rep}'))
                n_ = new.get((t, arm, f'r{rep}'))
                done = o is not None and 'error' not in o
                cells.append(dict(
                    task=t, rep=rep, arm=arm,
                    status='COMPLETED' if done else ('ERROR_COST_CAP' if o else 'NOT_RUN'),
                    calls_present=sum(have.values()),
                    nodes=have,
                    q_old=o.get('q') if o else None,
                    q_new=n_.get('q_new') if n_ else None,
                    source=dict(old='QP1_DEV_PROGRESS', new='QP1_DEV_RESCORED',
                                texts='QP1_LEDGER.jsonl')))
    json.dump(dict(batch='QP3_MATRIX', model_calls=0, cells=cells),
              open('/root/research_outputs/static_pi/stage_d/qp3/QP3_MATRIX.json', 'w'),
              ensure_ascii=False, indent=1)
    c = collections.Counter(x['status'] for x in cells)
    print('cell status:', dict(c), 'total', len(cells))
    for t in TASKS:
        row = [(x['arm'], x['rep'], x['status'][:4]) for x in cells if x['task'] == t]
        print(t, row)


if __name__ == '__main__':
    main()
