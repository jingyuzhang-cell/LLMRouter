#!/usr/bin/env python3
"""
E2 Checkpoint Audit - Read-only analysis of current E2 Stage 1 status
"""

import json
from collections import defaultdict, Counter
from pathlib import Path
from datetime import datetime

# Configuration
E2_DIR = Path("/root/e2_targeted_decomposition")
EVENTS_FILE = E2_DIR / "E2_STAGE1_RESPONSE_EVENTS.jsonl"
PROTOCOL_FILE = E2_DIR / "E2_PROTOCOL.json"
TASKS_FILE = E2_DIR / "E2_STAGE1_30.jsonl"

def load_protocol():
    """Load the E2 protocol to understand expected structure"""
    with open(PROTOCOL_FILE) as f:
        return json.load(f)

def load_tasks():
    """Load the E2 tasks"""
    tasks = []
    with open(TASKS_FILE) as f:
        for line in f:
            tasks.append(json.loads(line))
    return tasks

def load_events():
    """Load all response events"""
    events = []
    with open(EVENTS_FILE) as f:
        for line in f:
            events.append(json.loads(line))
    return events

def analyze_events(events, protocol):
    """Comprehensive event analysis"""

    # Expected structure from protocol
    models = protocol.get("models", ["qwen-plus", "glm-5.2"])
    repeats = protocol.get("repeats", 2)  # Usually 2 for validation

    # Get task info
    tasks = load_tasks()
    num_tasks = len(tasks)
    nodes_per_task = 4  # Based on subtask decomposition
    expected_total = num_tasks * nodes_per_task * len(models) * repeats

    print("=" * 80)
    print("E2 STAGE 1 CHECKPOINT AUDIT")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    print("EXPECTED OUTCOMES:")
    print(f"  Tasks: {num_tasks}")
    print(f"  Nodes per task: {nodes_per_task}")
    print(f"  Models: {models}")
    print(f"  Repeats: {repeats}")
    print(f"  Expected total outcomes: {expected_total}")
    print()

    # Analyze events by model
    print("EVENTS BY MODEL:")
    model_stats = defaultdict(lambda: {
        "total_attempts": 0,
        "successful": 0,
        "failed": 0,
        "total_cost": 0.0,
        "total_tokens": 0,
        "errors": Counter(),
        "attempts_distribution": Counter()
    })

    for event in events:
        model = event["model"]
        stats = model_stats[model]
        stats["total_attempts"] += 1
        stats["total_cost"] += event["total_billed_cost_usd"]
        stats["total_tokens"] += event["usage"]["total_tokens"]
        stats["attempts_distribution"][event["attempt"]] += 1

        if event["success"]:
            stats["successful"] += 1
        else:
            stats["failed"] += 1
            if event["error"]:
                stats["errors"][event["error"]] += 1

    for model in models:
        stats = model_stats[model]
        success_rate = (stats["successful"] / stats["total_attempts"] * 100) if stats["total_attempts"] > 0 else 0
        print(f"\n{model}:")
        print(f"  Total attempts: {stats['total_attempts']}")
        print(f"  Successful: {stats['successful']}")
        print(f"  Failed: {stats['failed']}")
        print(f"  Success rate: {success_rate:.1f}%")
        print(f"  Total cost: ${stats['total_cost']:.4f}")
        print(f"  Total tokens: {stats['total_tokens']}")
        print(f"  Attempts distribution: {dict(stats['attempts_distribution'])}")
        if stats["errors"]:
            print(f"  Errors: {dict(stats['errors'])}")

    print()

    # Calculate current outcomes
    print("CURRENT OUTCOMES STATUS:")

    # Group by (task_id, model, repeat, node_id) to find final state
    outcomes = {}
    for event in events:
        key = (event["task_id"], event["model"], event["repeat"], event["node_id"])

        # If this is the first time we see this key, or if this attempt is higher
        if key not in outcomes or event["attempt"] > outcomes[key]["attempt"]:
            outcomes[key] = {
                "task_id": event["task_id"],
                "model": event["model"],
                "repeat": event["repeat"],
                "node_id": event["node_id"],
                "attempt": event["attempt"],
                "success": event["success"],
                "error": event["error"],
                "cost": event["total_billed_cost_usd"],
                "tokens": event["usage"]["total_tokens"]
            }

    successful_outcomes = sum(1 for o in outcomes.values() if o["success"])
    failed_outcomes = sum(1 for o in outcomes.values() if not o["success"])
    missing_outcomes = expected_total - len(outcomes)

    total_cost = sum(o["cost"] for o in outcomes.values())
    total_tokens = sum(o["tokens"] for o in outcomes.values())

    print(f"  Expected outcomes: {expected_total}")
    print(f"  Completed outcomes: {len(outcomes)}")
    print(f"  Successful outcomes: {successful_outcomes}")
    print(f"  Failed outcomes: {failed_outcomes}")
    print(f"  Missing outcomes: {missing_outcomes}")
    print(f"  Completion rate: {(len(outcomes) / expected_total * 100):.1f}%")
    print(f"  Total cost so far: ${total_cost:.4f}")
    print(f"  Total tokens used: {total_tokens}")
    print()

    # External calls tracking
    total_external_calls = len(events)
    print("EXTERNAL CALLS TRACKING:")
    print(f"  External calls used: {total_external_calls}")
    print(f"  Expected calls (520 limit): 520")
    print(f"  Calls remaining: {max(0, 520 - total_external_calls)}")
    print(f"  Cost per call average: ${total_cost/total_external_calls:.6f}" if total_external_calls > 0 else "  N/A")
    print()

    # Task completion analysis
    print("TASK COMPLETION ANALYSIS:")
    task_completion = defaultdict(lambda: {"completed": 0, "expected": nodes_per_task * len(models) * repeats})

    for (task_id, model, repeat, node_id), outcome in outcomes.items():
        task_completion[task_id]["completed"] += 1

    completed_tasks = sum(1 for t_id, stats in task_completion.items()
                         if stats["completed"] >= stats["expected"])

    print(f"  Fully completed tasks: {completed_tasks}/{num_tasks}")
    print(f"  Partially completed tasks: {num_tasks - completed_tasks}")

    # Show completion distribution
    completion_dist = Counter(stats["completed"] for stats in task_completion.values())
    print(f"  Completion distribution: {dict(sorted(completion_dist.items()))}")
    print()

    # Key findings
    print("KEY FINDINGS:")
    print(f"  1. Experiment is {((len(outcomes) / expected_total) * 100):.1f}% complete")
    print(f"  2. Success rate: Qwen-plus: {(model_stats['qwen-plus']['successful'] / model_stats['qwen-plus']['total_attempts'] * 100):.1f}%, GLM-5.2: {(model_stats['glm-5.2']['successful'] / model_stats['glm-5.2']['total_attempts'] * 100):.1f}%")
    print(f"  3. GLM-5.2 shows {'higher' if model_stats['glm-5.2']['total_cost'] > model_stats['qwen-plus']['total_cost'] else 'similar'} cost per call")
    print(f"  4. GLM-5.2 requires {model_stats['glm-5.2']['total_attempts'] / (model_stats['glm-5.2']['total_attempts'] + model_stats['glm-5.2']['failed']) * 100:.1f}% attempts per outcome (including retries)")
    print(f"  5. Budget status: ${total_cost:.4f} spent, ${5.0 - total_cost:.4f} remaining of $5.00 budget")
    print(f"  6. Call budget: {total_external_calls}/520 calls used")

    # Risk assessment
    print()
    print("RISK ASSESSMENT:")
    if missing_outcomes > 100:
        print(f"  ⚠️  HIGH: {missing_outcomes} outcomes still missing, significant work remaining")
    elif missing_outcomes > 50:
        print(f"  ⚠️  MEDIUM: {missing_outcomes} outcomes still missing")
    else:
        print(f"  ✅  LOW: {missing_outcomes} outcomes remaining")

    if total_cost > 4.5:
        print(f"  ⚠️  HIGH: Budget nearly exhausted (${total_cost:.4f}/${5.0})")
    elif total_cost > 3.0:
        print(f"  ⚠️  MEDIUM: Budget usage significant (${total_cost:.4f}/${5.0})")
    else:
        print(f"  ✅  LOW: Budget comfortable (${total_cost:.4f}/${5.0})")

    if total_external_calls > 450:
        print(f"  ⚠️  HIGH: Call budget nearly exhausted ({total_external_calls}/520)")
    elif total_external_calls > 300:
        print(f"  ⚠️  MEDIUM: Call budget usage significant ({total_external_calls}/520)")
    else:
        print(f"  ✅  LOW: Call budget comfortable ({total_external_calls}/520)")

    print()
    print("=" * 80)

    return {
        "expected_total": expected_total,
        "completed_outcomes": len(outcomes),
        "successful_outcomes": successful_outcomes,
        "failed_outcomes": failed_outcomes,
        "missing_outcomes": missing_outcomes,
        "total_external_calls": total_external_calls,
        "total_cost": total_cost,
        "total_tokens": total_tokens,
        "model_stats": dict(model_stats),
        "fully_completed_tasks": completed_tasks,
        "total_tasks": num_tasks
    }

def main():
    """Main audit function"""
    try:
        protocol = load_protocol()
        events = load_events()

        print(f"Loaded {len(events)} events from {EVENTS_FILE}")
        print()

        results = analyze_events(events, protocol)

        # Save audit results
        audit_file = E2_DIR / f"E2_CHECKPOINT_AUDIT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(audit_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)

        print(f"Audit results saved to: {audit_file}")

    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please ensure E2 experiment files exist in the expected location.")
    except Exception as e:
        print(f"Error during audit: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()