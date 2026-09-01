#!/usr/bin/env python3
"""
E2 Data Integrity Audit - Ensure unique final responses per key
"""

import json
from pathlib import Path
from collections import defaultdict

E2_DIR = Path("/root/e2_targeted_decomposition")
RESPONSES_FILE = E2_DIR / "E2_STAGE1_RESPONSES.jsonl"

def audit_response_uniqueness():
    """Audit that each (task_id, model, repeat, node_id) has exactly one final response"""

    print("Loading responses...")
    responses = []
    with open(RESPONSES_FILE) as f:
        for line in f:
            responses.append(json.loads(line))

    print(f"Total responses in file: {len(responses)}")

    # Group by unique key
    key_groups = defaultdict(list)
    for i, resp in enumerate(responses):
        key = (resp["task_id"], resp["model"], resp["repeat"], resp["node_id"])
        key_groups[key].append((i, resp))

    print(f"\nUnique (task, model, repeat, node) keys: {len(key_groups)}")
    print(f"Expected unique keys: 480 (30 tasks × 2 models × 2 repeats × 4 nodes)")

    # Find duplicates
    duplicates = {k: v for k, v in key_groups.items() if len(v) > 1}

    print(f"\nKeys with multiple responses: {len(duplicates)}")

    if duplicates:
        print("\nDuplicate details:")
        for key, items in duplicates.items():
            print(f"  {key}: {len(items)} responses")
            for idx, resp in items:
                print(f"    Line {idx}: success={resp.get('success')}, attempt={resp.get('attempt', 1)}, timestamp={resp.get('timestamp', 'N/A')}")

    # Check for missing keys
    expected_keys = set()
    # This would need task list to generate properly
    # For now, just report what we have

    print(f"\nData integrity summary:")
    print(f"  Total records: {len(responses)}")
    print(f"  Unique keys: {len(key_groups)}")
    print(f"  Duplicate keys: {len(duplicates)}")
    print(f"  Records affected by duplicates: {sum(len(v) for v in duplicates.values())}")

    if len(duplicates) == 0 and len(key_groups) == 480:
        print("✅ Data integrity: PASS")
        return True
    else:
        print("⚠️  Data integrity: NEEDS ATTENTION")
        return False

def get_final_responses_only():
    """Extract only the final (most recent) response for each key"""

    print("\nExtracting final responses only...")

    responses = []
    with open(RESPONSES_FILE) as f:
        for line in f:
            responses.append(json.loads(line))

    # Keep only the most recent response for each key
    final_responses = {}
    for resp in responses:
        key = (resp["task_id"], resp["model"], resp["repeat"], resp["node_id"])

        # Keep the one with highest attempt number, or most recent timestamp
        if key not in final_responses:
            final_responses[key] = resp
        else:
            existing = final_responses[key]
            # Prefer higher attempt number
            if resp.get("attempt", 1) > existing.get("attempt", 1):
                final_responses[key] = resp
            # If same attempt, prefer more recent timestamp
            elif resp.get("attempt", 1) == existing.get("attempt", 1):
                if resp.get("timestamp", "") > existing.get("timestamp", ""):
                    final_responses[key] = resp

    final_list = list(final_responses.values())
    print(f"Final unique responses: {len(final_list)}")

    return final_list

if __name__ == "__main__":
    audit_response_uniqueness()
    final_responses = get_final_responses_only()