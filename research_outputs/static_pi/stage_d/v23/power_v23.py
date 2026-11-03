"""Phase Pi V2.3 — power and budget calculator (offline; no calls).

Per operator ruling (2026-11-02):
  - the independent TASK is the statistical unit; repeats of one task are not
    independent samples;
  - V2's TP measurement is systematically defective, so its SD=0.75-1.27 must NOT
    be used as the variance basis for the new endpoint;
  - formal sample size must come from new-system pilot data.

This calculator therefore refuses any input whose source is not a V2.3 pilot.
"""
import json, math, sys

Z = 1.959964 + 0.841621  # alpha=.05 two-sided, power=.80
TEMPLATE = {
    'source': 'v23_pilot',
    'endpoint': 'Q_final or Q_partial_diagnostic (declare one)',
    'unit': 'independent_task',
    'paired_differences': [],
    'notes': 'Fill with per-task paired differences from a V2.3 pilot. Do not use V2 TP.',
}


def required_k(sd, delta):
    if delta <= 0:
        return None
    return math.ceil(Z * Z * sd * sd / (delta * delta))


def main(path):
    data = json.load(open(path, encoding='utf-8'))
    source = str(data.get('source', ''))
    endpoint = str(data.get('endpoint', ''))
    diffs = data.get('paired_differences') or []
    if source != 'v23_pilot':
        print(f'REFUSED: source={source!r}; only a V2.3 pilot may set the variance basis.')
        print('Reason: V2 terminal TP is dominated by exact-token formatting, so its SD is not a valid basis.')
        return 2
    if 'frozen_tp' in endpoint.lower() or 'v1.2.3' in endpoint.lower():
        print('REFUSED: the frozen-TP endpoint is not admissible for the new power calculation.')
        return 2
    if len(diffs) < 3:
        print(f'NOT READY: {len(diffs)} paired task differences; need at least 3 to estimate SD.')
        return 3
    mean = sum(diffs) / len(diffs)
    var = sum((x - mean) ** 2 for x in diffs) / (len(diffs) - 1)
    sd = math.sqrt(var)
    grid = {}
    for delta in (0.01, 0.02, 0.03, 0.05, 0.075, 0.10):
        grid[str(delta)] = required_k(sd, delta)
    out = dict(batch='PHASE_PI_V23_POWER', source=source, endpoint=endpoint,
               unit=data.get('unit'), pairs=len(diffs), mean_delta=round(mean, 6),
               sd_delta=round(sd, 6), required_tasks_by_mde=grid,
               note=('Tasks are the unit. Repeats within a task estimate within-task '
                     'noise and do not add independent samples. Analysis must be paired '
                     'by task with task clustering.'))
    json.dump(out, open('/root/research_outputs/static_pi/stage_d/v23/POWER_V23.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  '/root/research_outputs/static_pi/stage_d/v23/pilot_variance_template_v23.json'))
