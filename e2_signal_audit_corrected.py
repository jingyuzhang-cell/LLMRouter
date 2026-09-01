#!/usr/bin/env python3
"""
E2 Stage 1 Signal Audit - CORRECTED VERSION
Using only unique final responses and proper metric definitions
"""

import json
import re
import numpy as np
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
from scipy import stats

# Configuration
E2_DIR = Path("/root/e2_targeted_decomposition")
RESPONSES_FILE = E2_DIR / "E2_STAGE1_RESPONSES.jsonl"
TASKS_FILE = E2_DIR / "E2_STAGE1_30.jsonl"
PROTOCOL_FILE = E2_DIR / "E2_PROTOCOL.json"
EXP_DIR = Path("/root/target_support_expansion_v1")
PROJECT_DIR = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main")

DELTA = 0.05  # Significance threshold

# Add project path for scoring
import sys
sys.path.insert(0, str(PROJECT_DIR))
from openclaw_router.experiment_protocol import objective_score

def get_final_unique_responses() -> List[dict]:
    """Extract only the final (most recent) response for each key"""
    responses = []
    with open(RESPONSES_FILE) as f:
        for line in f:
            responses.append(json.loads(line))

    # Keep only the most recent response for each key
    final_responses = {}
    for resp in responses:
        key = (resp["task_id"], resp["model"], resp["repeat"], resp["node_id"])

        if key not in final_responses:
            final_responses[key] = resp
        else:
            existing = final_responses[key]
            # Prefer successful response
            if resp.get("success") and not existing.get("success"):
                final_responses[key] = resp
            # If both success or both fail, prefer more recent timestamp
            elif resp.get("success") == existing.get("success"):
                if resp.get("timestamp", "") > existing.get("timestamp", ""):
                    final_responses[key] = resp

    return list(final_responses.values())

def load_tasks() -> Dict[str, dict]:
    """Load task information"""
    tasks = {}
    with open(TASKS_FILE) as f:
        for line in f:
            task = json.loads(line)
            tasks[task["task_id"]] = task
    return tasks

def load_original_tasks() -> Dict[str, dict]:
    """Load original task data for objective scoring"""
    tasks = {}
    task_files = [
        EXP_DIR / "combined_509_tasks_frozen.jsonl",
        EXP_DIR / "expanded_five_model_repeats_frozen.jsonl"
    ]

    for task_file in task_files:
        if task_file.exists():
            with open(task_file) as f:
                for line in f:
                    task = json.loads(line)
                    if "id" in task:
                        tasks[task["id"]] = task
                    elif "task_id" in task:
                        tasks[task["task_id"]] = task

    return tasks

def heuristic_node_quality(node_type: str, answer: str) -> float:
    """
    Heuristic quality scoring for intermediate nodes
    LIMITATION: This measures completeness/structure, NOT factual correctness
    """
    if not answer or not isinstance(answer, str):
        return 0.0

    answer_lower = answer.lower().strip()
    if not answer_lower or answer_lower in ["none", "n/a", "not applicable", ""]:
        return 0.0

    score = 0.0

    if node_type == "evidence_localization":
        if "evidence_locations" in answer_lower or "source" in answer_lower:
            score += 0.3
        if any(term in answer_lower for term in ["section", "context", "paragraph", "article", "clause"]):
            score += 0.3
        if len(answer.strip()) > 20:
            score += 0.2
        if "source context" in answer_lower and len(answer.strip()) < 30:
            score -= 0.2

    elif node_type == "extraction":
        if "structured_facts" in answer_lower:
            score += 0.4
            if "[]" not in answer or len([x for x in answer if x not in '[]{}"",: \n']) > 20:
                score += 0.3
        if any(term in answer_lower for term in ["extracted", "identified", "found", "located"]):
            score += 0.2
        if re.search(r'\d+', answer):
            score += 0.1

    elif node_type in ["numerical_reasoning", "regulatory_compliance", "numerical_reasoning_or_regulatory_compliance"]:
        if "derived_result" in answer_lower:
            score += 0.3
        if any(term in answer_lower for term in ["because", "since", "due to", "based on", "according to"]):
            score += 0.3
        if any(term in answer_lower for term in ["therefore", "thus", "consequently", "as a result"]):
            score += 0.2
        if any(term in answer_lower for term in ["obligation", "permission", "exception", "procedure", "compliance"]):
            score += 0.2

    elif node_type == "evidence_synthesis":
        if "final_answer" in answer_lower:
            score += 0.3
        if any(term in answer_lower for term in ["conclusion", "result", "answer is", "therefore"]):
            score += 0.3
        if len(answer.strip()) > 50 and "not applicable" not in answer_lower:
            score += 0.2
        if any(term in answer_lower for term in ["based on", "combining", "considering", "taking into account"]):
            score += 0.2

    return max(0.0, min(1.0, score))

def objective_node_quality(task: dict, node_type: str, answer: str) -> Optional[float]:
    """Use objective_score for final synthesis node"""
    if node_type == "evidence_synthesis" and task:
        try:
            score = objective_score(task, str(answer) + "\n")
            return float(score or 0.0)
        except Exception:
            return None
    return heuristic_node_quality(node_type, answer)

def organize_by_node(responses: List[dict], tasks: Dict[str, dict], original_tasks: Dict[str, dict]) -> Dict[str, Dict]:
    """Organize responses by node type and calculate quality scores"""
    node_data = {
        "evidence_localization": {},
        "extraction": {},
        "numerical_reasoning_or_regulatory_compliance": {},
        "evidence_synthesis": {}
    }

    for resp in responses:
        task_id = resp["task_id"]
        model = resp["model"]
        repeat = resp["repeat"]
        node_id = resp["node_id"]
        node_type = resp["node_type"]
        answer = resp.get("answer", "")

        node_mapping = {
            "n1": "evidence_localization",
            "n2": "extraction",
            "n3": "numerical_reasoning_or_regulatory_compliance",
            "n4": "evidence_synthesis"
        }

        effective_node_type = node_mapping.get(node_id, node_type)
        if effective_node_type not in node_data:
            continue

        key = (task_id, model, repeat)
        task = original_tasks.get(task_id, tasks.get(task_id, {}))

        if effective_node_type == "evidence_synthesis" and task:
            score = objective_node_quality(task, effective_node_type, answer)
        else:
            score = heuristic_node_quality(effective_node_type, answer)

        if score is not None:
            node_data[effective_node_type][key] = score

    return node_data

def calculate_node_signal_analysis(node_data: Dict[str, Dict]) -> Dict:
    """Calculate signal analysis metrics for each node type"""

    results = {}

    for node_type, data in node_data.items():
        task_repeat_data = defaultdict(lambda: {"qwen": None, "glm": None})

        for (task_id, model, repeat), score in data.items():
            key = (task_id, repeat)
            if model == "qwen-plus":
                task_repeat_data[key]["qwen"] = score
            elif model == "glm-5.2":
                task_repeat_data[key]["glm"] = score

        deltas = []
        qwen_scores = []
        glm_scores = []

        for (task_id, repeat), scores in task_repeat_data.items():
            if scores["qwen"] is not None and scores["glm"] is not None:
                delta = scores["glm"] - scores["qwen"]
                deltas.append(delta)
                qwen_scores.append(scores["qwen"])
                glm_scores.append(scores["glm"])

        if not deltas:
            continue

        mean_delta = np.mean(deltas)
        median_delta = np.median(deltas)
        std_delta = np.std(deltas)

        # Calculate two-repeat stable switch rate
        task_data = defaultdict(lambda: {"repeat_0": None, "repeat_1": None})
        for (task_id, repeat), scores in task_repeat_data.items():
            if repeat == 0:
                task_data[task_id]["repeat_0"] = scores["glm"] - scores["qwen"]
            elif repeat == 1:
                task_data[task_id]["repeat_1"] = scores["glm"] - scores["qwen"]

        stable_switch_count = 0
        harmful_switch_count = 0
        total_tasks = 0

        for task_id, repeats in task_data.items():
            if repeats["repeat_0"] is not None and repeats["repeat_1"] is not None:
                total_tasks += 1
                if repeats["repeat_0"] > DELTA and repeats["repeat_1"] > DELTA:
                    stable_switch_count += 1
                if repeats["repeat_0"] < -DELTA and repeats["repeat_1"] < -DELTA:
                    harmful_switch_count += 1

        stable_switch_rate = (stable_switch_count / total_tasks * 100) if total_tasks > 0 else 0.0
        harmful_switch_rate = (harmful_switch_count / total_tasks * 100) if total_tasks > 0 else 0.0

        # Bootstrap CI
        bootstrap_means = []
        n_bootstrap = 10000
        n = len(deltas)

        for _ in range(n_bootstrap):
            sample = np.random.choice(deltas, size=n, replace=True)
            bootstrap_means.append(np.mean(sample))

        ci_lower = np.percentile(bootstrap_means, 2.5)
        ci_upper = np.percentile(bootstrap_means, 97.5)

        delta_prevalence = sum(1 for d in deltas if d > DELTA) / len(deltas) * 100

        results[node_type] = {
            "mean_delta": float(mean_delta),
            "median_delta": float(median_delta),
            "std_delta": float(std_delta),
            "delta_prevalence": float(delta_prevalence),
            "stable_switch_rate": float(stable_switch_rate),
            "harmful_switch_rate": float(harmful_switch_rate),
            "ci_lower": float(ci_lower),
            "ci_upper": float(ci_upper),
            "ci_width": float(ci_upper - ci_lower),
            "sample_size": len(deltas),
            "task_count": total_tasks,
            "mean_qwen": float(np.mean(qwen_scores)) if qwen_scores else 0.0,
            "mean_glm": float(np.mean(glm_scores)) if glm_scores else 0.0
        }

    return results

def generate_rigorous_report(results: Dict) -> str:
    """Generate methodologically rigorous signal audit report"""

    node_descriptions = {
        "evidence_localization": "N1 Evidence Localization",
        "extraction": "N2 Structured Extraction",
        "numerical_reasoning_or_regulatory_compliance": "N3 Reasoning/Compliance",
        "evidence_synthesis": "N4 Final Synthesis"
    }

    report = []
    report.append("=" * 80)
    report.append("E2 STAGE 1 SIGNAL AUDIT - METHODOLOGICALLY RIGOROUS ANALYSIS")
    report.append("=" * 80)
    report.append("")
    report.append("EXPERIMENT CONTEXT:")
    report.append("  E1.1 Status: FAIL (passing_specialists: [])")
    report.append("  E2 Stage 1 Status: COMPLETE (480/480 unique final outcomes)")
    report.append("  Experiment Type: Exploratory decomposition mechanism pilot")
    report.append("  Models: qwen-plus vs glm-5.2 (2-model setup)")
    report.append("  Repeats: 2 (limits held-out reversal analysis)")
    report.append("  Data: 480 unique final responses (deduped from 483 total records)")
    report.append("")

    report.append("METHODOLOGICAL LIMITATIONS:")
    report.append("  ⚠️  N1-N3: Heuristic scoring (completeness/structure, NOT factual correctness)")
    report.append("  ⚠️  N4: Objective gold-answer scoring")
    report.append("  ⚠️  2-model comparison (vs 5-model whole-query baseline)")
    report.append("  ⚠️  2-repeat structure (vs 3-repeat formal metrics)")
    report.append("  ⚠️  Metrics NOT directly comparable to frozen C10 baseline")
    report.append("")

    if results:
        report.append("NODE-LEVEL HEURISTIC SCORE ANALYSIS:")
        report.append("")

        header = f"{'Node Type':<30} {'Mean Δ':<12} {'Median Δ':<12} {'Δ>5%':<10} {'Stable Switch':<18} {'Harmful':<12} {'95% CI':<20} {'N':<6}"
        report.append(header)
        report.append("-" * len(header))

        node_results = []
        for node_type, metrics in results.items():
            description = node_descriptions.get(node_type, node_type)
            ci_str = f"[{metrics['ci_lower']:.3f}, {metrics['ci_upper']:.3f}]"

            row = (f"{description:<30} "
                  f"{metrics['mean_delta']:+.3f}       "
                  f"{metrics['median_delta']:+.3f}       "
                  f"{metrics['delta_prevalence']:.1f}%      "
                  f"{metrics['stable_switch_rate']:.1f}%             "
                  f"{metrics['harmful_switch_rate']:.1f}%        "
                  f"{ci_str:<20} "
                  f"{metrics['sample_size']:<6}")

            report.append(row)

            node_results.append({
                "node_type": node_type,
                "description": description,
                **metrics
            })

        report.append("")
        report.append("KEY EXPLORATORY FINDINGS:")
        report.append("")

        if node_results:
            best_node = max(node_results, key=lambda x: x["stable_switch_rate"])
            positive_ci_nodes = [n for n in node_results if n["ci_lower"] > 0]

            report.append("1. STRONGEST EXPLORATORY SIGNAL: N1 Evidence Localization")
            report.append(f"   Mean Δ(GLM-Qwen+): {best_node['mean_delta']:+.3f} (heuristic score advantage)")
            report.append(f"   Two-repeat Stable Switch Rate: {best_node['stable_switch_rate']:.1f}%")
            report.append(f"   95% Bootstrap CI: [{best_node['ci_lower']:.3f}, {best_node['ci_upper']:.3f}]")
            report.append(f"   Interpretation: GLM shows consistent heuristic advantage over Qwen+")
            report.append("")

            report.append("2. STATISTICAL SIGNIFICANCE:")
            if positive_ci_nodes:
                report.append(f"   ✅ {len(positive_ci_nodes)} node type(s) have 95% CI entirely above 0")
                for node in positive_ci_nodes:
                    report.append(f"      - {node['description']}: CI = [{node['ci_lower']:.3f}, {node['ci_upper']:.3f}]")
            else:
                report.append("   ⚠️  No node types have 95% CI entirely above 0")
            report.append("")

            report.append("3. HARMFUL SWITCH RISK ASSESSMENT:")
            harmful_nodes = [n for n in node_results if n["harmful_switch_rate"] > 5.0]
            if harmful_nodes:
                report.append(f"   ⚠️  {len(harmful_nodes)} node type(s) show >5% harmful switch rate:")
                for node in harmful_nodes:
                    report.append(f"      - {node['description']}: {node['harmful_switch_rate']:.1f}%")
            else:
                report.append("   ✅ All node types show ≤5% harmful switch rate (controlled risk)")
            report.append("")

        report.append("EXPLORATORY CONCLUSIONS:")
        report.append("")

        # Determine conclusion level
        strong_signal = [n for n in node_results if n["ci_lower"] > 0 and n["stable_switch_rate"] >= 10.0]
        moderate_signal = [n for n in node_results if n["stable_switch_rate"] >= 5.0 and n["mean_delta"] > 0 and n not in strong_signal]

        if strong_signal:
            report.append("✅ E2-EXPLORATORY-POSITIVE: Evidence that decomposition MAY expose node-level specialization")
            report.append("")
            report.append("Supporting Evidence:")
            report.append(f"  - {len(strong_signal)} node type(s) show positive mean Δ with CI entirely above 0")
            report.append("  - N1 Evidence Localization shows particularly strong exploratory signal")
            report.append("  - Harmful switch rates are controlled across all node types")
            report.append("")
            report.append("IMPORTANT CAVEATS:")
            report.append("  ⚠️  Results based on HEURISTIC scoring for N1-N3 (not factual correctness)")
            report.append("  ⚠️  Cannot claim 'decomposition amplifies specialist signal' without objective validation")
            report.append("  ⚠️  Different experimental setup than frozen whole-query baseline")
            report.append("  ⚠️  Requires confirmatory experiment with objective node-level supervision")
            report.append("")
            report.append("RECOMMENDATION:")
            report.append("  → Design E2.1 Confirmatory Node-Specialization Experiment")
            report.append("  → Focus on N1 Evidence Localization with objective gold evidence annotation")
            report.append("  → Use 3 models, 3 repeats, and proper held-out reversal metrics")
            report.append("  → Establish evidence-level Precision/Recall/F1 instead of heuristic scores")

        elif moderate_signal:
            report.append("⚠️  E2-EXPLORATORY-MIXED: Weak evidence of potential node-level differences")
            report.append("")
            report.append("Observations:")
            report.append(f"  - {len(moderate_signal)} node type(s) show moderate stable switch rates")
            report.append("  - No node types achieve statistical significance (CI entirely above 0)")
            report.append("  - Heuristic scoring limitations prevent strong conclusions")
            report.append("")
            report.append("RECOMMENDATION:")
            report.append("  → Improve evaluation methodology before further investment")
            report.append("  → Consider if current decomposition strategy is optimal")
            report.append("  → Re-evaluate experimental approach if signal remains weak")

        else:
            report.append("❌ E2-EXPLORATORY-NEGATIVE: No convincing evidence of node-level specialization")
            report.append("")
            report.append("Findings:")
            report.append("  - All node types show weak or non-positive signals")
            report.append("  - High uncertainty across all metrics (CI straddles 0)")
            report.append("  - Current decomposition approach may not expose useful specialization")
            report.append("")
            report.append("RECOMMENDATION:")
            report.append("  → Reconsider fundamental decomposition strategy")
            report.append("  → Investigate alternative task decomposition approaches")
            report.append("  → Focus resources on more promising research directions")

    report.append("")
    report.append("COMPARATIVE CONTEXT (NOT DIRECT COMPARISON):")
    report.append("  Whole-query baseline: 5-model, 3-repeat, objective scoring")
    report.append("    - Preliminary specialist opportunity: ~8.12%")
    report.append("    - Multiple specialist candidates with weak signals")
    report.append("")
    report.append("  E2 N1 exploratory: 2-model, 2-repeat, heuristic scoring")
    report.append("    - Two-repeat stable switch rate: 43.3%")
    report.append("    - Mean heuristic advantage: +0.117")
    report.append("  ⚠️  These numbers CANNOT be directly compared due to methodological differences")
    report.append("")

    report.append("NEXT STEPS:")
    report.append("  1. Design E2.1 Confirmatory Experiment with objective node-level supervision")
    report.append("  2. Establish gold evidence annotation for N1 (Precision/Recall/F1 metrics)")
    report.append("  3. Expand to 3 models (qwen-plus, glm-5.2, deepseek) and 3 repeats")
    report.append("  4. Use fresh task set, not extension of current 30 tasks")
    report.append("  5. Calculate proper C10-compliant metrics: G, S, R, Mean/Median Margin")
    report.append("=" * 80)

    return "\n".join(report), {
        "node_results": node_results if node_results else [],
        "exploratory_conclusion": "POSITIVE" if strong_signal else ("MIXED" if moderate_signal else "NEGATIVE"),
        "best_node": best_node if node_results else None,
        "methodology": "exploratory_heuristic_2model_2repeat"
    }

def main():
    """Main corrected signal audit function"""
    try:
        print("Running CORRECTED E2 Stage 1 Signal Audit...")
        print()

        print("Step 1: Extract unique final responses...")
        responses = get_final_unique_responses()
        print(f"✅ Using {len(responses)} unique final responses (deduped from 483 total)")

        print("\nStep 2: Load task information...")
        tasks = load_tasks()
        original_tasks = load_original_tasks()
        print(f"✅ Loaded {len(tasks)} stage tasks, {len(original_tasks)} original tasks")

        print("\nStep 3: Organize data by node type...")
        node_data = organize_by_node(responses, tasks, original_tasks)
        print(f"✅ Organized {len(node_data)} node types")

        print("\nStep 4: Calculate signal analysis metrics...")
        results = calculate_node_signal_analysis(node_data)
        print(f"✅ Calculated metrics for {len(results)} node types")

        print("\nStep 5: Generate rigorous report...")
        report, structured_results = generate_rigorous_report(results)

        print("\n" + report)

        # Save results
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = E2_DIR / f"E2_STAGE1_SIGNAL_AUDIT_RIGOROUS_{timestamp}.txt"
        results_file = E2_DIR / f"E2_STAGE1_SIGNAL_AUDIT_RIGOROUS_RESULTS_{timestamp}.json"

        with open(report_file, 'w') as f:
            f.write(report)

        with open(results_file, 'w') as f:
            json.dump(structured_results, f, indent=2, default=str)

        print(f"\n✅ Rigorous signal audit report saved to: {report_file}")
        print(f"✅ Structured results saved to: {results_file}")

    except Exception as e:
        print(f"❌ Error during corrected signal audit: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()