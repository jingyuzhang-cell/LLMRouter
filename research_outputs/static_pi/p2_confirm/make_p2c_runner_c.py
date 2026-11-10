#!/usr/bin/env python3
"""Derive p2c_runner.py from the frozen P2-B runner (p2_runner.py, sha256 ef2f3089...) by audited text
replacements only. Arm logic is not touched. Each replacement must match exactly once.
Changes: (1) task list from final manifest v3 with full-sha check; (2) scorer -> p2c_scorer; (3) arm execution
order from the frozen randomization table (checked against its preregistration); (4) P2-C budget caps;
(5) G-9 option C (operator ruling 2026-11-08): model-output faults (truncated / abnormal stop / empty / invalid JSON
or schema) raise ModelFault and are handled -- recovery node fault -> RECOVERY_FAILED + G2 fallback (scored, not a
success); shared-upstream fault -> G2-G6 EXECUTION_FAILED (Q=0), G1 still runs, next block continues; G1/G2 own
fault -> that arm EXECUTION_FAILED. Transport errors, budget caps and any other exception halt the batch;
(6) P2C_GO gate + FREEZE_P2C.json. No retries anywhere.
"""
import hashlib, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / 'p2_runner.py'
OUT = HERE / 'p2c_runner.py'
OUT.chmod(0o644) if OUT.exists() else None
assert hashlib.sha256(SRC.read_bytes()).hexdigest() == 'ef2f3089d1600cfe46cdaadd96a1d706bcc179b4bf4536cab652e4b9ce512965'
s = SRC.read_text('utf-8')
R = []

def rep(a, b, tag):
    global s
    assert s.count(a) == 1, (tag, s.count(a))
    s = s.replace(a, b); R.append(tag)

rep('"""P2-B pilot executor: 3 tasks × 2 replicates × 6 arms (G1-G6).',
    '"""P2-C confirmatory executor: 26 tasks × 2 replicates × 6 arms (G1-G6); derived from p2_runner.py by make_p2c_runner.py.', 'docstring')
rep("OUT = HERE / 'p2_runs'", "OUT = HERE / 'p2c_runs'", 'out_dir')
i, j = s.index('TASKS = ['), s.index(']\nREPS = 2')
s = s[:i] + '''MANIFEST = HERE / 'P2C_FINAL_GOLD_MANIFEST_V3.json'
RANDOMIZATION = HERE / 'P2C_RANDOMIZATION_TABLE.json'
TASKS = [(r['task'], Path(r['file']), r['sha256']) for r in json.loads(MANIFEST.read_text('utf-8'))['contracts']''' + s[j:]
R.append('tasks_from_manifest')
rep("CAPS = dict(calls=180, tokens=1_400_000, yuan=2.20)", "CAPS = dict(calls=1300, tokens=TOKEN_CAP, yuan=YUAN_CAP)", 'caps')
rep("ARM_CAPS = {'G1': 2, 'G2': 2, 'G3': 4, 'G4': 4, 'G5': 4, 'G6': 5}",
    "ARM_CAPS = {'G1': 2, 'G2': 2, 'G3': 4, 'G4': 4, 'G5': 4, 'G6': 5}\nTOKEN_CAP, YUAN_CAP = __TOKEN_CAP__, __YUAN_CAP__", 'cap_consts')
i, j = s.index('class TaskScorer:'), s.index('class Env:')
s = s[:i] + '''class TaskScorer:
    """P2-C: frozen per-slot g11 specs in the v1.1 contract, scored by p2c_scorer (N excludes UNKNOWN)."""
    def __init__(self, contract):
        import p2c_scorer as P2C
        self.ct, self._score = contract, P2C.score
    def score(self, sink):
        return self._score(sink, self.ct)

''' + s[j:]
R.append('scorer')
rep("    assert hashlib.sha256(path.read_bytes()).hexdigest().startswith(sha_prefix), f'{tag} contract mismatch'",
    "    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha_prefix, f'{tag} contract mismatch (full sha256)'", 'full_sha')
rep("def run_task_rep(tag, ct, env, scorer, docs_norm, slots_json):",
    "def run_task_rep(tag, ct, env, scorer, docs_norm, slots_json, arm_order):", 'sig')
rep("""    results = {}
    # G1 Single
    env.arm = 'G1'
    g1 = env.call('G1', build_g1_user(ct))
    results['G1'] = g1['parsed']
""", """    results = {}
    assert sorted(arm_order) == sorted(ARMS) and arm_order.index('G2') < min(arm_order.index(a) for a in ('G3', 'G4', 'G5', 'G6'))
    def run_g1():
        env.arm = 'G1'
        results['G1'] = env.call('G1', build_g1_user(ct))['parsed']
    if arm_order.index('G1') < arm_order.index('G2'):
        run_g1()
""", 'g1_slot')
for a in ('G3', 'G4', 'G5', 'G6'):
    rep(f"    results['{a}'] = try_recover('{a}', {a.lower()}_actions)\n", f"    ARM_FNS['{a}'] = {a.lower()}_actions\n", f'thunk_{a}')
rep("""    # Helper for recovery arms
""", """    ARM_FNS = {}
    # Helper for recovery arms
""", 'arm_fns')
rep("""    # M3 post-processing for ALL arms
""", """    for arm in arm_order[arm_order.index('G2') + 1:]:
        if arm == 'G1':
            run_g1()
        else:
            results[arm] = try_recover(arm, ARM_FNS[arm])
    # M3 post-processing for ALL arms
""", 'ordered_exec')
i, j = s.index('def run_pilot(transport, out_dir=OUT):'), s.index('def main():')
s = s[:i] + '''def run_pilot(transport, out_dir=OUT):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    ledger = R.Ledger(out_dir / 'LEDGER.jsonl')
    budget = R.Budget(**CAPS)
    env = Env(transport, ledger, budget)
    table = json.loads(RANDOMIZATION.read_text('utf-8'))
    assert table['manifest_sha256'] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    paths = {t: (p, sh) for t, p, sh in TASKS}
    cache, all_records = {}, {}
    for blk in table['table']:
        tag, rep_i, order = blk['task'], blk['rep'], blk['arm_order']
        if tag not in cache:
            ct = load_task(tag, *paths[tag])
            slots = [dict(fact_id=f['fact_id'], subject=f['subject'], predicate=f['predicate'],
                          **({'unit': f['unit']} if f.get('unit') else {})) for f in ct['required_facts']]
            cache[tag] = (ct, TaskScorer(ct), R.SC.doc_index(ct), json.dumps(slots, ensure_ascii=False))
        ct, scorer, docs_norm, slots_json = cache[tag]
        env.task, env.rep = tag, rep_i
        key = f'{tag}_r{rep_i}'
        try:
            results, states, targets = run_task_rep(tag, ct, env, scorer, docs_norm, slots_json, order)
        except Stop as s:
            all_records[key] = dict(block=blk['block'], stopped=str(s))
            (out_dir / 'P2C_RESULTS.json').write_text(json.dumps(all_records, ensure_ascii=False, indent=1), 'utf-8')
            print(f'BATCH STOP at block {blk["block"]} {key}: {s}', flush=True)
            return all_records
        rec = {}
        for arm in ARMS:
            sc = scorer.score(results.get(arm))
            sm = SM.metrics(dict(total=sc['N'], rows=[r for r in sc['rows'] if r['scored']], asserted=sc['asserted'],
                                 wrong=sc['wrong'], tp=sc['TP'], Q_all=sc['Q_all']))
            rec[arm] = dict(Q=sc['Q_all'], tp=sc['TP'], N=sc['N'], wrong=sc['wrong'], asserted=sc['asserted'],
                            critical_TP=sc['critical_TP'], critical_N=sc['critical_N'],
                            unknown_asserted=sc['unknown_asserted'], safety=sm)
        all_records[key] = dict(block=blk['block'], arm_order=order, states=states, targets=sorted(targets), arms=rec)
        (out_dir / 'P2C_RESULTS.json').write_text(json.dumps(all_records, ensure_ascii=False, indent=1), 'utf-8')
        print(f'  [{blk["block"]:2}/52] {key}: ' + ' '.join(f'{a}={rec[a]["Q"]:.2f}' for a in ARMS), flush=True)
    return all_records

''' + s[j:]
R.append('run_loop')
rep("""        files = [Path(__file__).resolve()] + [p for _, p, _ in TASKS]
        fz = dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  caps=CAPS, arm_caps=ARM_CAPS, tasks=[t[0] for t in TASKS], reps=REPS)
        (HERE / 'FREEZE_P2B.json').write_text(json.dumps(fz, ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_P2B:', hashlib.sha256((HERE / 'FREEZE_P2B.json').read_bytes()).hexdigest()); return""",
"""        files = [Path(__file__).resolve(), MANIFEST, RANDOMIZATION, HERE / 'p2c_scorer.py'] + [p for _, p, _ in TASKS]
        fz = dict(files={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  caps=CAPS, arm_caps=ARM_CAPS, tasks=[t[0] for t in TASKS], reps=REPS, route=ROUTE)
        (HERE / 'FREEZE_P2C.json').write_text(json.dumps(fz, ensure_ascii=False, indent=1), 'utf-8')
        print('FREEZE_P2C:', hashlib.sha256((HERE / 'FREEZE_P2C.json').read_bytes()).hexdigest()); return""", 'freeze')
rep("        if os.environ.get('P2B_GO') != '1': raise SystemExit('REFUSED: P2B_GO=1 required')",
    "        if os.environ.get('P2C_GO') != '1': raise SystemExit('REFUSED: P2C_GO=1 required')", 'go_gate')
rep("        p = HERE / 'FREEZE_P2B.json'", "        p = HERE / 'FREEZE_P2C.json'", 'freeze_path')
rep("class Stop(Exception): pass", """class Stop(Exception): pass
class ModelFault(Stop):
    \"\"\"Model-output fault (G-9 option C): handled per arm; never an infrastructure stop.\"\"\"
    pass""", 'modelfault_cls')
rep("""        if fault: raise Stop(f'{node} fault: {fault}')
        if self.b.reached(): raise Stop(self.b.reached())""", """        if self.b.reached(): raise Stop(self.b.reached())
        if fault: raise ModelFault(f'{node} fault: {fault}')""", 'fault_to_modelfault')
rep("""    e1 = env.call('E_D1', R.e_user(docs['D1']))
    e2 = env.call('E_D2', R.e_user(docs['D2']))
    j1 = env.call('J1', R.j1_user({'E_D1': e1['text'], 'E_D2': e2['text']}))
    j2 = env.call('J2', R.j2_user(j1['text'], slots_json))
""", """    shared_fault = None
    try:
        e1 = env.call('E_D1', R.e_user(docs['D1']))
        e2 = env.call('E_D2', R.e_user(docs['D2']))
        j1 = env.call('J1', R.j1_user({'E_D1': e1['text'], 'E_D2': e2['text']}))
        j2 = env.call('J2', R.j2_user(j1['text'], slots_json))
    except ModelFault as mf:
        shared_fault = str(mf)
    if shared_fault:   # G2-G6 cannot obtain a terminal answer; G1 is independent and still runs
        env.arm = 'G1'
        try:
            g1o, g1s = env.call('G1', build_g1_user(ct))['parsed'], 'OK'
        except ModelFault as mf:
            g1o, g1s = None, f'EXECUTION_FAILED::{mf}'
        return dict(results={'G1': g1o}, states={}, targets=set(), shared_fault=shared_fault,
                    recovery={'G1': g1s, **{a: 'EXECUTION_FAILED::shared_upstream' for a in ('G2', 'G3', 'G4', 'G5', 'G6')}})
""", 'shared_fault')
rep("""    def run_g1():
        env.arm = 'G1'
        results['G1'] = env.call('G1', build_g1_user(ct))['parsed']
""", """    recov = {}
    def run_g1():
        env.arm = 'G1'
        try:
            results['G1'] = env.call('G1', build_g1_user(ct))['parsed']; recov['G1'] = 'OK'
        except ModelFault as mf:
            results['G1'] = None; recov['G1'] = f'EXECUTION_FAILED::{mf}'
""", 'g1_fault')
rep("""    env.arm = 'G2'
    g2 = env.call('SINK', sink_user(j2['text']))
    results['G2'] = g2['parsed']
    pre_terminal = g2['parsed']
""", """    env.arm = 'G2'
    try:
        g2 = env.call('SINK', sink_user(j2['text']))
        results['G2'] = g2['parsed']; pre_terminal = g2['parsed']; recov['G2'] = 'OK'
    except ModelFault as mf:
        results['G2'] = None; pre_terminal = None; recov['G2'] = f'EXECUTION_FAILED::{mf}'
""", 'g2_fault')
rep("""        try:
            return actions()
        except Stop as s:
            if 'fault' in str(s) or 'budget' in str(s).lower():
                return pre_terminal  # fallback to pre-recovery terminal
            raise
""", """        try:
            out = actions()
            recov[arm] = 'OK' if targets else 'OK_NO_TARGET'
            return out
        except ModelFault as mf:   # e.g. J2R truncated: recovery failed; G2 terminal used as safe fallback
            recov[arm] = ('RECOVERY_FAILED_TRUNCATED::' if 'truncated' in str(mf) else 'RECOVERY_FAILED::') + str(mf)
            return pre_terminal
""", 'try_recover_c')
rep("""    return results, states, targets
""", """    return dict(results=results, states=states, targets=targets, shared_fault=None, recovery=recov)
""", 'return_dict')
rep("""    assert table['manifest_sha256'] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()""",
    """    prereg = json.loads((HERE / 'P2C_RANDOMIZATION_PREREG.json').read_text('utf-8'))
    assert table['manifest_sha256'] == prereg['manifest_sha256'] and table['algorithm_sha256'] == prereg['algorithm_sha256']
    assert sorted({b['task'] for b in table['table']}) == sorted(t for t, _, _ in TASKS)""", 'rand_prereg')
rep("""        try:
            results, states, targets = run_task_rep(tag, ct, env, scorer, docs_norm, slots_json, order)
        except Stop as s:""", """        try:
            o = run_task_rep(tag, ct, env, scorer, docs_norm, slots_json, order)
            results, states, targets = o['results'], o['states'], o['targets']
        except Stop as s:   # transport / budget / leaked fault -> infrastructure halt""", 'unpack')
rep("""            rec[arm] = dict(Q=sc['Q_all'], tp=sc['TP'], N=sc['N'], wrong=sc['wrong'], asserted=sc['asserted'],""",
    """            rec[arm] = dict(Q=sc['Q_all'], tp=sc['TP'], N=sc['N'], wrong=sc['wrong'], asserted=sc['asserted'],
                            execution_failed=results.get(arm) is None, status=o['recovery'].get(arm, 'OK'),""", 'rec_status')
rep("""        all_records[key] = dict(block=blk['block'], arm_order=order, states=states, targets=sorted(targets), arms=rec)""",
    """        all_records[key] = dict(block=blk['block'], arm_order=order, shared_fault=o['shared_fault'], states=states,
                                targets=sorted(targets), arms=rec)""", 'rec_block')
caps = Path(sys.argv[1]).read_text().split()
s = s.replace('__TOKEN_CAP__', caps[0]).replace('__YUAN_CAP__', caps[1])
OUT.write_text(s, 'utf-8')
print('replacements:', R)
OUT.chmod(0o444)
print('p2c_runner.py sha256', hashlib.sha256(OUT.read_bytes()).hexdigest())
