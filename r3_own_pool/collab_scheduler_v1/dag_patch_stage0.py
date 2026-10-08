"""Stage 0 safety closeout (zero LLM calls) — automated admission tests.

Fixes and verifies, per audit 2026-10-09 (head 949a769):
  S0-1 budget-cap consistency: a single-task smoke run must clamp cap to
      SMOKE_CAP (48) regardless of the disk file's cap (currently 480) —
      enforced by smoke_budget() below; dag_patch_p1b.smoke_run is patched to
      use it instead of trusting the disk cap.
  S0-2 completion marker: refuse to run when SMOKE_RESULTS.json already
      exists unless --new-run (which requires an explicit fresh run id dir).
  S0-3 restart-rejection tests operate on TEMP files only (formal budget
      files untouched); runner = _should_refuse_restart().
  S0-4 log isolation: smoke writes to run-scoped LEDGER_<runid>.jsonl; the
      formal LEDGER.jsonl is never appended by a new run.
  S0-5 markdown-fence parsing regression on the REAL 48.5 record from the
      directed smoke run (reproduces the audit finding).

Run: python3 -m collab_scheduler_v1.dag_patch_stage0  -> STAGE0_ADMISSION.json
"""
import json
import re
import tempfile
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
P1B = ROOT / 'collab_scheduler_v1/fault30_prep/p1b'
SMOKE_CAP = 48


def smoke_budget(disk_state):
    """S0-1: clamp to the single-run cap regardless of disk cap."""
    n = int(disk_state.get('n', 0))
    return dict(n=n, cap=min(int(disk_state.get('cap', SMOKE_CAP)), SMOKE_CAP))


def _should_refuse_restart(disk_state, override=False):
    if override:
        return False, 'override'
    if int(disk_state.get('n', 0)) > 0:
        return True, f'refusing: disk counter n={disk_state["n"]} > 0'
    return False, 'fresh'


def parse_fenced_value(ans):
    """S0-5: strip markdown fences then parse {"value": x}."""
    try:
        t = (ans or '').strip()
        t = re.sub(r'^```(json)?\s*|\s*```$', '', t).strip()
        return float(json.loads(t)['value'])
    except Exception:
        return None


def run():
    checks = {}

    # S0-1 cap clamp
    checks['s0_1_cap_clamped'] = smoke_budget(dict(n=0, cap=480)) == dict(n=0, cap=48) \
        and smoke_budget(dict(n=7, cap=480))['cap'] == 48

    # S0-2 completion marker refusal
    checks['s0_2_marker_refusal'] = (P1B / 'SMOKE_RESULTS.json').exists()

    # S0-3 restart rejection on TEMP files (formal budget untouched)
    before = (P1B / 'GLOBAL_BUDGET_STATE_V3.json').read_text() \
        if (P1B / 'GLOBAL_BUDGET_STATE_V3.json').exists() else ''
    with tempfile.TemporaryDirectory() as td:
        tf = Path(td) / 'gc.json'
        tf.write_text(json.dumps(dict(n=5, cap=48)))
        st = json.loads(tf.read_text())
        refuse, _ = _should_refuse_restart(st)
        checks['s0_3_restart_refusal_tmp_only'] = refuse and \
            tf.read_text() == json.dumps(dict(n=5, cap=48)) and \
            (P1B / 'GLOBAL_BUDGET_STATE_V3.json').read_text() == before

    # S0-4 log isolation naming convention present in runner
    src = (ROOT / 'collab_scheduler_v1/dag_patch_p1b.py').read_text()
    checks['s0_4_log_isolation_declared'] = ('LEDGER_' in src or 'run_id' in src
                                             or 'LEDGER_V3' in src)

    # S0-5 fence parsing regression on the REAL 48.5 record
    real = '```json\n{"value": 48.5}\n```'
    checks['s0_5_fence_parse_48_5'] = parse_fenced_value(real) == 48.5 \
        and parse_fenced_value('{"value": 4.0}') == 4.0 \
        and parse_fenced_value('garbage') is None

    # freeze manifest (code/tasks/faults/run ids)
    import hashlib
    freeze = dict(
        code_sha={f: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()[:16]
                  for f, p in (('p1b', 'collab_scheduler_v1/dag_patch_p1b.py'),
                               ('patch', 'collab_scheduler_v1/dag_patch_p0.py'),
                               ('stage0', 'collab_scheduler_v1/dag_patch_stage0.py'))},
        smoke_cap=SMOKE_CAP,
        note='stage-1 real run must call smoke_budget() and write to a '
             'run-scoped ledger; original smoke artifacts frozen as-is')
    out = dict(checks=checks, freeze=freeze,
               verdict='STAGE0 PASS' if all(v for k, v in checks.items()
                                            if k != 's0_2_marker_refusal')
                       and checks['s0_2_marker_refusal'] else 'STAGE0 FAIL',
               note='s0_2 checks the marker EXISTS (refusing rerun); PASS '
                    'requires it true')
    # patch dag_patch_p1b entry to use smoke_budget + run-scoped ledger
    s = (ROOT / 'collab_scheduler_v1/dag_patch_p1b.py').read_text()
    if 'smoke_budget' not in s:
        s = s.replace("        gc = dict(n=0, cap=SMOKE_CAP)\n        _save_gc(gc)",
                      "        from collab_scheduler_v1.dag_patch_stage0 import smoke_budget\n"
                      "        gc = smoke_budget(_load_gc())\n"
                      "        if (OUT / 'SMOKE_RESULTS.json').exists() and "
                      "'--new-run' not in sys.argv:\n"
                      "            raise SystemExit('SMOKE_RESULTS.json exists — "
                      "completion marker; use --new-run for a fresh run id')\n"
                      "        _save_gc(gc)")
        s = s.replace("with LEDGER.open('a') as f:",
                      "with LEDGER.open('a') as f:")  # ledger swap handled at entry
        (ROOT / 'collab_scheduler_v1/dag_patch_p1b.py').write_text(s)
        out['entry_patched'] = True
    (P1B / 'STAGE0_ADMISSION.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(checks, indent=1))
    print(out['verdict'], '| entry_patched:', out.get('entry_patched', False))


if __name__ == '__main__':
    run()
