"""Stage-C-R1: Behavioral differentiation test for six-arm scheduler.

Proves that different arms produce DIFFERENT scheduling decisions when given
the same DAG state, anomaly, and resource constraints.

Uses deterministic fake model calls (zero real API calls).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from six_arm_scheduler import (
    DAGState, NodeState, SchedulingDecision,
    ARM_DECIDERS, execute_decision,
)

PROFILES = {
    'index':     {'glm53': {'quality': 0.9, 'cost': 643},  'flash': {'quality': 0.8, 'cost': 1063}},
    'extracts':  {'glm53': {'quality': 0.9, 'cost': 2783}, 'flash': {'quality': 0.7, 'cost': 1063}},
    'timeline':  {'glm53': {'quality': 0.9, 'cost': 882},  'flash': {'quality': 0.8, 'cost': 1063}},
    'entity':    {'glm53': {'quality': 0.9, 'cost': 882},  'flash': {'quality': 0.7, 'cost': 1063}},
    'factcheck': {'glm53': {'quality': 0.9, 'cost': 1362}, 'flash': {'quality': 0.6, 'cost': 1063}},
    'report':    {'glm53': {'quality': 0.9, 'cost': 1051}, 'flash': {'quality': 0.7, 'cost': 1063}},
}


def make_test_state() -> DAGState:
    """Create a test DAG with n3 (timeline) failed, n4-n6 pending."""
    nodes = {}
    specs = [
        ('n1', 'index', 'done'),
        ('n2', 'extracts', 'done'),
        ('n3', 'timeline', 'failed'),
        ('n4', 'entity', 'pending'),
        ('n5', 'factcheck', 'pending'),
        ('n6', 'report', 'pending'),
    ]
    for nid, kind, status in specs:
        nodes[nid] = NodeState(nid, kind, model='glm53' if status == 'done' else '',
                               status=status)
    deps = {'n2': ['n1'], 'n3': ['n2'], 'n4': ['n2'], 'n5': ['n2', 'n3', 'n4'], 'n6': ['n5']}
    return DAGState(nodes=nodes, deps=deps, budget_remaining=2000,
                    deadline_remaining=120.0,
                    resource_slots={'glm53': 2, 'flash': 2},
                    anomaly_node='n3', anomaly_type='transport')


def decision_fingerprint(dec: SchedulingDecision) -> str:
    """Compact representation for comparing decisions."""
    nodes_sorted = sorted(dec.nodes_to_execute)
    recovery_sorted = sorted(dec.recovery_set) if dec.recovery_set else []
    return f"action={dec.action_type}|z={dec.z_op}|R={recovery_sorted}|π={nodes_sorted}"


def main():
    print("=== SIX-ARM BEHAVIORAL DIFFERENTIATION TEST ===\n")

    # Test 1: Different decisions on same failed state
    print("Test 1: All arms given the SAME failed DAG state (n3=failed, transport anomaly)")
    state_template = make_test_state()

    fingerprints = {}
    decisions = {}

    for arm_name, decider in ARM_DECIDERS.items():
        state = make_test_state()  # fresh state for each arm
        dec = decider(state, PROFILES)
        fp = decision_fingerprint(dec)
        fingerprints[arm_name] = fp
        decisions[arm_name] = dec
        print(f"  {arm_name:20s}: {fp}")
        print(f"    rationale: {dec.rationale}")

    # Check differentiation
    unique_fps = set(fingerprints.values())
    print(f"\n  Unique decision fingerprints: {len(unique_fps)}/{len(ARM_DECIDERS)}")

    if len(unique_fps) < 2:
        print("  ❌ FAIL: All arms produce identical decisions")
        return False

    # Show which arms are actually different
    from collections import defaultdict
    fp_groups = defaultdict(list)
    for arm, fp in fingerprints.items():
        fp_groups[fp].append(arm)

    print(f"\n  Decision groups:")
    for i, (fp, arms) in enumerate(fp_groups.items()):
        if len(arms) > 1:
            print(f"    Group {i+1} ({len(arms)} arms same): {arms}")
        else:
            print(f"    Group {i+1} (unique): {arms[0]}")

    # Test 2: Recovery behavior differences
    print("\n\nTest 2: Recovery set differences")
    for arm_name, dec in decisions.items():
        r_set = sorted(dec.recovery_set) if dec.recovery_set else []
        print(f"  {arm_name:20s}: R={r_set} | z={dec.z_op}")

    # Check if recovery sets differ
    recovery_sets = set()
    for dec in decisions.values():
        recovery_sets.add(frozenset(dec.recovery_set))
    print(f"\n  Unique recovery sets: {len(recovery_sets)}")

    # Test 3: Model assignment differences
    print("\n\nTest 3: Model assignment (π) differences")
    for arm_name, dec in decisions.items():
        models = {nid: model for nid, model in dec.nodes_to_execute}
        print(f"  {arm_name:20s}: π={models}")

    # Check if any arm uses Flash
    uses_flash = any('flash' in str(dec.nodes_to_execute) for dec in decisions.values())
    print(f"\n  Any arm uses Flash: {uses_flash}")

    # Test 4: No-failure normal execution (should be mostly same)
    print("\n\nTest 4: Normal execution (no failure) - expected similarity")
    for arm_name, decider in ARM_DECIDERS.items():
        state = make_test_state()
        # Fix n3 so it's not failed
        state.nodes['n3'].status = 'done'
        state.nodes['n3'].model = 'glm53'
        dec = decider(state, PROFILES)
        fp = decision_fingerprint(dec)
        print(f"  {arm_name:20s}: {fp[:60]}...")

    # Overall verdict
    min_different = 3  # at least 3 arms should behave differently on failure
    n_groups = len(fp_groups)
    print(f"\n{'='*60}")
    print(f"BEHAVIORAL DIFFERENTIATION: {'✓ PASS' if n_groups >= min_different else '✗ FAIL'}")
    print(f"  Decision groups: {n_groups} (minimum required: {min_different})")
    print(f"  At least some arms use different R: {'✓' if len(recovery_sets) > 1 else '✗'}")
    print(f"  At least some arms use different π: {any('flash' in str(d.nodes_to_execute) for d in decisions.values())}")

    return n_groups >= min_different


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
