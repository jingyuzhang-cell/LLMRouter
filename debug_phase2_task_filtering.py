#!/usr/bin/env python3
"""
Debug script to trace the 60→59 task filtering in Phase 2.2
"""

import json
import numpy as np
import torch
import sys
from collections import Counter

sys.path.append('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main')

from llmrouter.utils.finrome_metrics import (
    build_task_model_outcomes,
    MODELS
)

# Load data
manifest = json.load(open('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/finrome_v4_split_manifest.json'))
source_data = json.load(open('/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/run_logs/formal_context_v2_rescored_v22_result.json'))

train_ids = sorted(manifest['split_definition']['train'])
calibration_ids = sorted(manifest['split_definition']['validation'])

print(f"Initial state:")
print(f"  Train IDs: {len(train_ids)}")
print(f"  Calibration IDs: {len(calibration_ids)}")

# Build tasks
tasks = {x['id']: x for x in source_data['sampled_task_set']}
print(f"\nTasks from sampled_task_set: {len(tasks)}")

# Load embeddings
embeddings_path = '/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main/run_logs/offline_knn_baseline/longformer_embeddings.pt'
embedding_payload = torch.load(embeddings_path, map_location='cpu', weights_only=False)
embeddings_by_id = {
    tid: embedding_payload["embeddings"][i].numpy()
    for i, tid in enumerate(embedding_payload["task_ids"])
}
print(f"\nEmbeddings: {len(embeddings_by_id)}")

# Build features function
def task_features(task):
    return np.array([
        task.get('complexity', 0.5),
        task.get('risk', 0.5),
        float(task.get('requires_calculation', False)),
        float(task.get('requires_table_reasoning', False)),
        float(task.get('requires_kg_reasoning', False)),
        min(len(str(task.get('query', ''))), 5000) / 5000,
    ], dtype=np.float32)

# Build xmap and bmap
task_ids_list = list(tasks.keys())
xmap = {
    tid: np.r_[embeddings_by_id[tid], task_features(tasks[tid])]
    for tid in task_ids_list
}
bmap = {tid: task_features(tasks[tid]) for tid in task_ids_list}

print(f"\nXmap: {len(xmap)}")
print(f"Bmap: {len(bmap)}")

# Check for missing tasks in xmap
missing_from_xmap = [tid for tid in train_ids if tid not in xmap]
if missing_from_xmap:
    print(f"\n❌ Missing from xmap: {len(missing_from_xmap)} tasks")
    for tid in missing_from_xmap:
        print(f"  - {tid}")
else:
    print(f"\n✅ All train tasks in xmap")

# Build outcomes
outcomes = build_task_model_outcomes(list(tasks.values()), source_data["raw_model_runs"])
print(f"\nOutcomes: {len(outcomes)}")

# Check for missing tasks in outcomes
missing_from_outcomes = [tid for tid in train_ids if tid not in outcomes]
if missing_from_outcomes:
    print(f"❌ Missing from outcomes: {len(missing_from_outcomes)} tasks")
    for tid in missing_from_outcomes:
        print(f"  - {tid}")
else:
    print(f"✅ All train tasks in outcomes")

# Build utilities and labels
utilities = {}
labels = {}
for tid in train_ids:
    try:
        utilities[tid] = {model: outcomes[tid][model]["utility"] for model in MODELS}
        labels[tid] = int(np.argmax([utilities[tid][model] for model in MODELS]))
    except Exception as e:
        print(f"❌ Error processing task {tid}: {e}")
        continue

print(f"\nUtilities: {len(utilities)}")
print(f"Labels: {len(labels)}")

# Check for missing tasks
missing_from_utilities = [tid for tid in train_ids if tid not in utilities]
if missing_from_utilities:
    print(f"❌ Missing from utilities: {len(missing_from_utilities)} tasks")
    for tid in missing_from_utilities:
        print(f"  - {tid}")
else:
    print(f"✅ All train tasks in utilities")

# Prepare training data
try:
    x_train = np.stack([xmap[tid] for tid in train_ids])
    y_train = np.array([labels[tid] for tid in train_ids])
    u_train = np.array([[utilities[tid][model] for model in MODELS] for tid in train_ids])
    print(f"\nTraining data prepared:")
    print(f"  x_train shape: {x_train.shape}")
    print(f"  y_train shape: {y_train.shape}")
    print(f"  u_train shape: {u_train.shape}")
except Exception as e:
    print(f"\n❌ Error preparing training data: {e}")
    import sys
    sys.exit(1)

# Process rare labels
print(f"\n--- Rare Label Processing ---")
label_counts = Counter(y_train)
print(f"Label distribution: {dict(label_counts)}")

rare_labels = {k: v for k, v in label_counts.items() if v < 5}
print(f"Rare labels: {rare_labels}")

rare_tasks = [tid for tid in train_ids if labels[tid] in rare_labels]
common_tasks = [tid for tid in train_ids if tid not in rare_labels]

print(f"\nRare tasks: {len(rare_tasks)}")
if rare_tasks:
    for tid in rare_tasks:
        print(f"  - {tid} (label: {labels[tid]})")

print(f"Common tasks: {len(common_tasks)}")

# Final check
print(f"\n--- Final Check ---")
print(f"Train manifest: {len(train_ids)}")
print(f"Common tasks: {len(common_tasks)}")
print(f"Missing from common: {len(train_ids) - len(common_tasks)}")

missing_from_common = [tid for tid in train_ids if tid not in common_tasks]
if missing_from_common:
    print(f"Missing tasks: {missing_from_common}")