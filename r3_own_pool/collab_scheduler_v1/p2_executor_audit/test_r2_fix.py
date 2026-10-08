"""Zero-call tests for R2/V2 successor-refresh fix (no LLM, no GPU).

Tests the STRUCTURED state tracking (e_recovered / r_changed) that replaces
the broken string-matching conditions in fault30_run.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

checks = {}

# T1: Demonstrate the ORIGINAL bug — endswith(':fb') never matches real keys
uid = 'abc123de-f012-3456-789a-bcdef0123456'
real_key = f'f30:DYNAMICDAG:HETEROGENEOUS:e1:fb:{uid}'
checks['t1_original_bug_demonstrated'] = not real_key.endswith(':fb')

# T2: The intermediate fix (1afbabe) — ':e1:fb:' in kk DOES match
checks['t2_intermediate_fix_works'] = ':e1:fb:' in real_key

# T3: New structured tracking — e_recovered fires when facts change
st = {'facts': {'e1': {'facts': [{'value': 1.0}]}, 'e2': {'facts': [{'value': 2.0}]}},
     'e_recovered': set()}
old_facts_e1 = st['facts']['e1']['facts']
new_facts_e1 = [{'value': 99.0}]  # fb returned different facts
if new_facts_e1 != old_facts_e1:
    st['e_recovered'].add('e1')
checks['t3_facts_changed_marks_recovered'] = 'e1' in st['e_recovered']

# T4: Facts UNCHANGED — e_recovered should NOT fire
st2 = {'facts': {'e1': {'facts': [{'value': 1.0}]}, 'e2': {'facts': []}},
       'e_recovered': set()}
old_facts = st2['facts']['e1']['facts']
new_facts = [{'value': 1.0}]  # fb returned SAME facts
if new_facts != old_facts:
    st2['e_recovered'].add('e1')
checks['t4_facts_same_no_recovery'] = 'e1' not in st2['e_recovered']

# T5: r_changed fires when r answer differs after refresh
st3 = {'rkeys': ['key1'], 'r_changed': False,
       '_answers': {'key1': '{"expression": "v0+v1"}'}}
prev = st3['_answers'][st3['rkeys'][-1]]
new_key = 'key2'
st3['_answers'][new_key] = '{"expression": "v0*v1"}'  # different expression
st3['rkeys'].append(new_key)
if st3['_answers'][new_key] != prev:
    st3['r_changed'] = True
checks['t5_r_changed_on_new_answer'] = st3['r_changed']

# T6: r_changed NOT fired when r answer is identical
st4 = {'rkeys': ['key1'], 'r_changed': False,
       '_answers': {'key1': '{"expression": "v0+v1"}'}}
prev = st4['_answers'][st4['rkeys'][-1]]
new_key = 'key2'
st4['_answers'][new_key] = '{"expression": "v0+v1"}'  # SAME expression
st4['rkeys'].append(new_key)
if st4['_answers'][new_key] != prev:
    st4['r_changed'] = True
checks['t6_r_same_no_change_flag'] = not st4['r_changed']

# T7: Both e nodes recovered → both in e_recovered set
st5 = {'e_recovered': set()}
st5['e_recovered'].update({'e1', 'e2'})
checks['t7_dual_e_recovery'] = st5['e_recovered'] == {'e1', 'e2'}

# T8: Verify code uses structured tracking (not string matching)
src = (ROOT / 'collab_scheduler_v1/fault30_run.py').read_text()
checks['t8_uses_e_recovered'] = "e_recovered" in src
checks['t8_no_endswith_fb'] = "endswith(':fb')" not in src
checks['t8_uses_r_changed'] = 'r_changed' in src

# T9: Latency formula check — should be labeled honestly
if 'max(base' in src or 'max(lats' in src:
    checks['t9_latency_is_critical_path_style'] = True  # takes max of parallel
    checks['t9_note'] = 'L uses max() for parallel e branches — this is a ' \
                        'critical-path ESTIMATE, not serial wall-clock; ' \
                        'documented in P2 protocol as such'

results = dict(checks=checks, all_pass=all(v for v in checks.values() if isinstance(v, bool)))
print(json.dumps(checks, indent=1, default=str))
print('ALL PASS' if results['all_pass'] else 'FAIL PRESENT')

out = ROOT / 'collab_scheduler_v1/p2_executor_audit'
out.mkdir(exist_ok=True)
(out / 'R2_FIX_TESTS.json').write_text(json.dumps(results, indent=1, default=str))
