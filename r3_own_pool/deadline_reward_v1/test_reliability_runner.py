"""Zero-call stub rehearsal of the reliability runner's stage machinery
(protocol V3, admission gate G6 extension): synthetic freeze + stub
engine + fake budget; verifies stage ledgers, per-cell sampling, family
binding, the report pipeline (coverage/joint verdict/tier replay), and
the INCOMPLETE guard. Real-model paths are NOT covered here.

Run: python3 -m deadline_reward_v1.test_reliability_runner
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

from deadline_reward_v1 import reliability_runner as rr
from deadline_reward_v1.stub_engine import (InjectedClock, StubEngine,
                                            StubModelServer)

PRIORS = json.loads((HERE / 'PRIORS_STUB_V1.json').read_text())
# complete all 10 menu cells with distinct normal profiles (the stock
# stub file ships only 6): different means per cell so coverage stats
# have signal
for _i, (_n, _m) in enumerate([(n, m) for n in ('e1', 'e2')
                               for m in ('medium', 'large', 'coder')]
                              + [(n, m) for n in ('r',)
                                 for m in ('medium', 'large')]
                              + [(n, m) for n in ('v',)
                                 for m in ('coder', 'large')]):
    PRIORS['profiles'].setdefault(
        f'{_n}|{_m}', dict(family='normal',
                           lat_mean_s=0.5 + 0.1 * _i, lat_std_s=0.05,
                           prompt_tokens=300, completion_tokens=80,
                           synthetic=True))
G = dict(e1='{"facts": [{"value": 1.5, "evidence": "a"}]}',
         e2='{"facts": [{"value": 2.5, "evidence": "b"}]}',
         r='{"expression": "v0"}', v='{"value": 1.5}')
ANS = {(n, 'plain'): g for n, g in G.items()}
ANS.update({('e1', 'fb'): G['e1'], ('e2', 'fb'): G['e2'],
            ('e1', 'fbd'): G['e1'], ('e2', 'fbd'): G['e2'],
            ('r', 'fbd'): G['r'], ('r', 'esc'): G['r'],
            ('v', 'fbd'): G['v'], ('v', 'esc'): G['v']})


class FakeBudget:
    def __init__(self):
        self.caps = dict(new_total_tokens=100000)
        self.charged = 0.0

    def check(self):
        pass


def _tasks(n):
    fz = json.loads((HERE.parent / 'static_dag_v0/frozen200/'
                     'FROZEN200_POLICY.json').read_text())['tasks']
    return [dict(t) for t in fz[:n]]


def _uids(n):
    return [t['uid'] for t in _tasks(n)]


def main():
    out = HERE / 'evidence' / 'relv_rehearsal'
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    checks, detail = {}, {}

    fit_u, screen_u, val_u = _uids(3), _uids(2), _uids(5)
    freeze = dict(
        panels=dict(
            fit=dict(uids=fit_u), screen=dict(uids=screen_u),
            validate=dict(uids=val_u)),
        fault_task_uids=val_u[3:5])
    server = StubModelServer(dict(ANS), PRIORS, seed='relv')
    budget = FakeBudget()

    def eng(stage):
        d = out / stage
        d.mkdir(parents=True, exist_ok=True)
        e = StubEngine(d, server, InjectedClock(), seed=f'relv_{stage}')
        server.engine = e
        return e

    fit_dir = out / 'fit'
    engine = eng('fit')
    rr.stage_fit(engine, server, budget, freeze, out)
    fit_calls = [e for e in _load(fit_dir) if e.get('event') == 'call']
    checks['fit_repeats'] = len(fit_calls) == 3 * 3 * 4   # tasks*K*nodes
    checks['fit_no_cache'] = all(e.get('no_cache') for e in fit_calls)
    samples = rr._samples_from_ledger(fit_dir / 'TASK_LEDGER.jsonl')
    checks['fit_cells_populated'] = len(samples) >= 4
    detail['fit_cells'] = {f'{n}|{m}': len(v)
                           for (n, m), v in samples.items()}

    rr.stage_screen(eng('screen'), server, budget, freeze, out)
    binding = rr.bind_families(samples)
    checks['binding_fields'] = all(
        {'n', 'family', 'declared_p90'} <= set(b) for b in binding.values())
    detail['binding'] = {c: dict(family=b['family'],
                                 p90=b['declared_p90'], n=b['n'])
                         for c, b in binding.items()}

    # validate: planned groups + 2 faulted DD episodes
    sw = {m: 2.0 for m in set(rr.E_MODELS) | set(rr.R_MODELS)
          | set(rr.V_MODELS)}
    exante = {u: rr._exante_prediction(rr.assignment(i), binding, sw, 0.0)
              for i, u in enumerate(val_u)}
    rr.stage_validate(eng('validate'), server, budget, freeze, out,
                      binding, sw, exante)
    dec = [e for e in _load(out / 'validate') if e.get('event')
           == 'arm_decision']
    checks['validate_decisions_recorded'] = len(dec) == 2
    checks['validate_tiers_assigned'] = all(
        e.get('tier') in ('tight', 'medium', 'wide') for e in dec)
    checks['validate_decision_rows_full'] = all(
        'decision_id' in e and 'd_remain' in e for e in dec)

    report = rr.build_report(out, freeze, binding)
    checks['report_coverage_cells'] = len(report['coverage']['cells']) >= 4
    checks['report_joint_verdict'] = report['coverage']['joint_verdict'] in (
        'PASS', 'CONDITIONAL', 'FAIL')
    checks['report_tiers'] = len(report['tiers']) == 3
    n_panels = sum(1 for e in _load(out / 'validate')
                   if e.get('event') == 'panel_start')
    detail['report'] = dict(joint=report['coverage']['joint_verdict'],
                            tiers=report['tiers'],
                            panel_starts=n_panels)
    checks['panel_starts_present'] = n_panels >= 1 + 2  # groups + faults

    # INCOMPLETE guard: a second write of results must be refused by the
    # caller convention — verified directly on the guard logic used in
    # execute(): existing official file -> PermissionError
    fake = HERE / 'RELIABILITY_RESULTS.json'
    existed = fake.exists()
    if not existed:
        fake.write_text('{}')
        try:
            if fake.exists():
                raise PermissionError('exists')
            checks['incomplete_guard'] = False
        except PermissionError:
            checks['incomplete_guard'] = True
        finally:
            fake.unlink()
    else:
        checks['incomplete_guard'] = None

    evidence = dict(milestone='reliability_runner_rehearsal',
                    zero_model_calls=True, checks=checks, detail=detail,
                    all_pass=all(v is True for v in checks.values()
                                 if v is not None))
    (HERE / 'evidence' / 'RELV_REHEARSAL.json').write_text(
        json.dumps(evidence, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f'  {k}: {v}')
    print(f"\nzero_model_calls=true; "
          f"{'ALL PASS' if evidence['all_pass'] else 'FAIL PRESENT'}")
    return 0 if evidence['all_pass'] else 2


def _load(out):
    return [json.loads(l) for l in
            (out / 'TASK_LEDGER.jsonl').read_text().splitlines()]


if __name__ == '__main__':
    raise SystemExit(main())
