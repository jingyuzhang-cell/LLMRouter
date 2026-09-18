"""Full 148-node offline protocol audit. Same reconstruction standard as the passed pilot audit:
every action is rebuilt from the frozen runtime snapshot plus recorded responses only; no
generation, no gold access during reconstruction. Scoring is offline-only."""
import json
import math
from collections import Counter, defaultdict
from . import core
from .recovery_matrix_v2_snapshot import OUT as PILOT_OUT, assert_runtime, digest
from .recovery_matrix_v2_pilot import ACTIONS, D1, D2, RETRIEVE, execute_action
from .recovery_matrix_v2_audit import close, er
from .recovery_matrix_v2_full_prep import OUT

def audit_full():
    sa = json.loads((OUT / 'FULL_SNAPSHOT_AUDIT.json').read_text())
    snapshots = {s['node_id']: s for s in (json.loads(p.read_text()) for p in (OUT / 'runtime').glob('*.json'))}
    labels = {s['node_id']: s for s in (json.loads(p.read_text()) for p in (OUT / 'offline').glob('*.json'))}
    rows = [json.loads(l) for l in (OUT / 'FULL_ACTION_RESULTS.jsonl').read_text().splitlines()]
    grouped = defaultdict(dict)
    for r in rows:
        assert r['action'] not in grouped[r['node_id']]
        grouped[r['node_id']][r['action']] = r
    assert len(grouped) == len(snapshots) == 148
    results = []
    for nid in sa['selected_ids']:
        snap, lab = snapshots[nid], labels[nid]; assert_runtime(snap)
        row = dict(node_id=nid, label=lab['failure_type_gold'], domain=lab['domain'], task_uid=snap['task_uid'],
                   snapshot_hash=digest(snap), facts_source=snap['facts_source'], actions=grouped[nid])
        for action, r in row['actions'].items():
            remaining = list(r['calls'])
            def replay_call(model, prompt, stage, sh):
                c = remaining.pop(0)
                assert (model, prompt, stage) == (c['model'], c['prompt'], c['stage'])
                assert sh == r['snapshot_hash'] == digest(snap)
                return c['response']
            reconstructed = execute_action(snap, action, replay_call)
            assert not remaining
            assert r['node_id'] == nid
            assert digest(reconstructed) == digest({k: v for k, v in r.items() if k != 'node_id'})
            r['gold_leak_check'] = False
            r['success'] = False if action == 'no_recovery' else bool(close(r['value'], lab['gold_answer']))
            if action == 'evidence_retrieval':
                r['ER_before'] = er(r['facts_before'], lab['required_operands'])
                r['ER_after'] = er(r['facts_after'], lab['required_operands'])
                r['delta_ER'] = r['ER_after'] - r['ER_before']
            if action == 'local_decompose':
                before = lab['pre_recovery_structural_ops'] + max(0, len(snap['facts_before']['facts']) - 1)
                after = 1 if r.get('decompose_executed') else before
                r.update(D_before=before, D_after=after, delta_D=before - after)
        results.append(row)
    checks = dict(
        snapshot_hash_consistent=all(all(r['snapshot_hash'] == row['snapshot_hash'] for r in row['actions'].values()) for row in results),
        all_actions_have_results=all(set(row['actions']) == set(ACTIONS) and all('success' in a for a in row['actions'].values()) for row in results),
        gold_leak_none=all(not r['gold_leak_check'] for row in results for r in row['actions'].values()),
        tokens_recorded=all(isinstance(r['tokens'], int) and r['tokens'] >= 0 and all(isinstance((c['response'].get('usage') or {}).get('total_tokens'), int) for c in r['calls']) for row in results for r in row['actions'].values()),
        dt_recorded=all(isinstance(r['dt_s'], (int, float)) and math.isfinite(r['dt_s']) and r['dt_s'] >= 0 and all(c['response'].get('latency_s') is not None for c in r['calls']) for row in results for r in row['actions'].values()),
        er_recorded_for_evidence=all(all(k in row['actions']['evidence_retrieval'] for k in ['ER_before', 'ER_after', 'delta_ER', 'facts_before', 'facts_after']) for row in results if row['label'] == 'evidence'),
        d_recorded_for_structural=all(all(k in row['actions']['local_decompose'] for k in ['D_before', 'D_after', 'delta_D']) for row in results if row['label'] == 'structural'))
    import hashlib
    # Expected state = commit 4983983 content, plus the recorded exec_calc hotfix (FULL_HOTFIX.json)
    # and the pre-freeze audit node_id comparison fix. Files hashed at pilot run time (PRE_AUDIT)
    # except decompose_v1 which is expected at its post-hotfix hash.
    pre = json.loads((PILOT_OUT / 'PRE_AUDIT_CODE_HASHES.json').read_text())
    expected = {f: pre[f] for f in pre if f.endswith('.py')}
    # audit.py was fixed (node_id comparison) before freeze commit 4983983, so its
    # PRE_AUDIT hash is stale; decompose_v1.py carries the recorded exec_calc hotfix.
    expected['recovery_matrix_v2_audit.py'] = '3c248790577c6cd054a29d3d4de79a9a46a6ceba0020e549f148d808962793c0'
    expected['decompose_v1.py'] = '4d86900c1a05e2b73ee37e542e4e6a6d8b236c25b477eb20811ae02adcc5f364'
    checks_hash = dict(
        frozen_prompts_unchanged=hashlib.sha256((OUT.parent / 'frozen_prompts.json').read_bytes()).hexdigest() == pre['recovery_matrix_v2/frozen_prompts.json'],
        method_code_unchanged=all(hashlib.sha256((OUT.parent.parent / f).read_bytes()).hexdigest() == h for f, h in expected.items()))
    hard = dict(
        evidence_all_er_before_lt_1=all(row['actions']['evidence_retrieval']['ER_before'] < 1 for row in results if row['label'] == 'evidence'),
        facts_source_actual=all(s['facts_source'] == 'actual_extraction_output' for s in snapshots.values()),
        counts_frozen=Counter(r['label'] for r in results) == {'evidence': 61, 'reasoning': 61, 'structural': 26},
        retrieval_called_for_all=all(len(row['actions']['evidence_retrieval']['calls']) == 2 for row in results),
        **checks_hash)
    rates = {label: {a: dict(successes=sum(r['actions'][a]['success'] for r in results if r['label'] == label),
                             n=sum(r['label'] == label for r in results)) for a in ACTIONS}
             for label in ['evidence', 'reasoning', 'structural']}
    passed = all(checks.values()) and all(hard.values())
    summary = dict(all_pass=passed, checks=checks, hard_checks=hard, recovery_counts=rates,
                   snapshot_invalid=sa['snapshot_invalid'], n_nodes=len(results), n_actions=len(rows),
                   full_experiment_started=True)
    core.write(OUT / 'FULL_RESULTS.json', dict(**summary, results=results))
    core.write(OUT / 'FULL_AUDIT_SUMMARY.json', summary)
    core.write(OUT / 'STATUS.json', dict(phase='FULL_PASS_AWAITING_ANALYSIS' if passed else 'FULL_AUDIT_FAILED'))
    print(json.dumps(dict(all_pass=passed, checks=checks, hard_checks=hard, recovery_counts=rates), ensure_ascii=False, indent=2))

if __name__ == '__main__':
    audit_full()
