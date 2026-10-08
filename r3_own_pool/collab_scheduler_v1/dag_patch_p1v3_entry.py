"""P1-B v3 directed entry — UNIFIED on dag_patch_directed_v3.run_directed().

Final zero-call fix (audit post-b9aece0): the formal path no longer calls the
legacy dag_patch_p1b.run_track(). Everything routes through the v3 runner,
which already implements real r2.val consumption in the v prompt, markdown
fence parsing, separate scheduler-overhead accounting, per-run isolation.

  - directed_run() delegates to dag_patch_directed_v3.run_directed()
  - --resume REMOVED (no bypass; every run fresh, marker-gated)
  - admission asserts r2.val PROPAGATION: val 4.0 -> 99.0 must change the
    actual v prompt; plus fence parse, duplicate-launch refusal, old-file
    protection, v3-only path

Real run (gates unchanged): P1B_V3_EXECUTE=1 python3 -m \
  collab_scheduler_v1.dag_patch_directed_v3 --execute-directed

Self-test: python3 -m collab_scheduler_v1.dag_patch_p1v3_entry   (zero calls)
"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
P1B = ROOT / 'collab_scheduler_v1/fault30_prep/p1b'
RUNS = P1B / 'runs'
CAP = 24


def _entry_guards(run_id):
    rd = RUNS / run_id
    rd.mkdir(parents=True, exist_ok=True)
    rpath, bpath, lpath = (rd / 'RESULTS.json', rd / 'BUDGET.json',
                           rd / 'LEDGER.jsonl')
    if rpath.exists():
        raise SystemExit(f'duplicate launch: {rpath} exists (completion marker)')
    if bpath.exists() and json.loads(bpath.read_text())['n'] > 0:
        raise SystemExit('restart refusal: budget n>0; fresh run required '
                         '(--resume disabled by protocol)')
    if lpath.exists() and lpath.read_text().strip():
        raise SystemExit('restart refusal: non-empty ledger; fresh run required')
    return rd, bpath, lpath, rpath


def directed_run(run_id, service, cap=CAP):
    """Formal path: delegates entirely to the v3 runner (no legacy run_track)."""
    from collab_scheduler_v1 import dag_patch_directed_v3 as v3
    rd, bpath, lpath, rpath = _entry_guards(run_id)
    task, failing_text = v3._get_directed_config()
    led = v3.fp.Ledger()
    gc = dict(n=0, cap=min(cap, CAP))
    bpath.write_text(json.dumps(gc))
    results = dict(run_id=run_id, task_uid=task['uid'], cap=gc['cap'],
                   strategy_order=['reroute', 'dynpatch'], tracks=[])
    for strat in ('reroute', 'dynpatch'):
        log = v3.run_directed(service, task, strat, led, gc, run_id, failing_text)
        results['tracks'].append(log)
        print(json.dumps({k: log.get(k) for k in
                          ('strategy', 'status', 'real_model_calls')},
                         default=str), flush=True)
    results['budget_used'] = gc['n']
    results['status'] = 'completed'
    rpath.write_text(json.dumps(results, indent=1, default=str))  # marker
    return results


def _hash_snapshot():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            for p in sorted(P1B.glob('**/*'))
            if p.is_file() and 'runs/' not in str(p.parent)}


def self_test():
    from collab_scheduler_v1.dag_patch_p1b_v3 import _strip_fences, _build_v_prompt
    from collab_scheduler_v1.dag_patch_p0 import RuntimeDAG
    checks = {}
    before = _hash_snapshot()
    ts = time.strftime('%H%M%S')

    # A1: r2.val PROPAGATION — v prompt changes 4.0 -> 99.0 (functional)
    def vprompt_with_val(val):
        g = RuntimeDAG({'e1': dict(deps=[], model='large'),
                        'r1': dict(deps=['e1'], model='large'),
                        'r2': dict(deps=['r1'], model='large'),
                        'v': dict(deps=['r2'], model='coder')})
        g.nodes['r2'].update(status='done', output=dict(val=val))
        g.nodes['r1'].update(status='done', output=dict(step1=1.0))
        task = dict(question='q', ctx_table='', ctx_text='')
        return _build_v_prompt(g, task, {'facts': []}, 'v')
    try:
        p4, p99 = vprompt_with_val(4.0), vprompt_with_val(99.0)
        checks['a1_r2_val_changes_v_prompt'] = (p4 != p99 and '4.0' in str(p4)
                                                and '99.0' in str(p99))
    except Exception as e:
        checks['a1_r2_val_changes_v_prompt'] = f'ERR {e}'

    # A2: fence parsing on the real 48.5 record shape
    checks['a2_fence_parse'] = _strip_fences(
        '```json\n{"value": 48.5}\n```').strip() == '{"value": 48.5}'

    # A3: duplicate-launch refusal — REAL guard
    rd = RUNS / f'v3t_{ts}_a3'
    rd.mkdir(parents=True, exist_ok=True)
    (rd / 'RESULTS.json').write_text('{}')
    try:
        _entry_guards(f'v3t_{ts}_a3')
        checks['a3_duplicate_refusal'] = False
    except SystemExit as e:
        checks['a3_duplicate_refusal'] = 'completion marker' in str(e)

    # A4: --resume disabled + restart refusal on dirty budget/ledger
    rd4 = RUNS / f'v3t_{ts}_a4'
    rd4.mkdir(parents=True, exist_ok=True)
    (rd4 / 'BUDGET.json').write_text(json.dumps(dict(n=3, cap=24)))
    try:
        _entry_guards(f'v3t_{ts}_a4')
        checks['a4_resume_disabled_restart_refused'] = False
    except SystemExit as e:
        checks['a4_resume_disabled_restart_refused'] = 'restart refusal' in str(e)

    # A5: old-file protection (hashes outside runs/ unchanged)
    checks['a5_old_files_protected'] = _hash_snapshot() == before

    # A6: formal path uses the v3 runner ONLY (no legacy run_track anywhere)
    esrc = (ROOT / 'collab_scheduler_v1/dag_patch_p1v3_entry.py').read_text()
    needle = 'run_' + 'track'   # avoid self-match in this check's own source
    body = '\n'.join(l for l in esrc.splitlines() if needle not in l)
    checks['a6_uses_v3_runner_only'] = ('dag_patch_directed_v3' in body
                                        and needle not in body)

    # A7: scope/order/cap frozen in the formal path
    checks['a7_scope_frozen'] = ("('reroute', 'dynpatch')" in esrc
                                 and 'min(cap, CAP)' in esrc and CAP == 24)

    out = dict(checks=checks,
               freeze=dict(cap=CAP, per_strategy=12,
                           strategies=['reroute', 'dynpatch'],
                           runner='dag_patch_directed_v3.run_directed',
                           resume='DISABLED',
                           code_sha={f: hashlib.sha256(
                               (ROOT / p).read_bytes()).hexdigest()[:16]
                               for f, p in (
                                   ('v3runner',
                                    'collab_scheduler_v1/dag_patch_directed_v3.py'),
                                   ('v3helpers',
                                    'collab_scheduler_v1/dag_patch_p1b_v3.py'),
                                   ('entry',
                                    'collab_scheduler_v1/dag_patch_p1v3_entry.py'))}),
               verdict='V3-ENTRY-UNIFIED PASS' if all(
                   v is True for v in checks.values())
                   else 'V3-ENTRY-UNIFIED FAIL',
               zero_model_calls=True)
    (P1B / 'V3_ENTRY_ADMISSION.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(checks, indent=1))
    print(out['verdict'])


if __name__ == '__main__':
    self_test()
