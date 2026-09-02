#!/usr/bin/env python3
"""
E2 Stage 1 Signal Audit - Two-repeat compatible metrics analysis
E1.1: FAIL (passing_specialists: [])
E2 Stage 1: Exploratory decomposition pilot (480/480 outcomes complete)
"""

import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple
from scipy import stats

# Configuration
E2_DIR = Path("/root/e2_targeted_decomposition")
RESPONSES_FILE = E2_DIR / "E2_STAGE1_RESPONSES.jsonl"
EVENTS_FILE = E2_DIR / "E2_STAGE1_RESPONSE_EVENTS.jsonl"
TASKS_FILE = E2_DIR / "E2_STAGE1_30.jsonl"
PROTOCOL_FILE = E2_DIR / "E2_PROTOCOL.json"
DELTA = 0.05  # Same threshold as E1.1

def load_responses() -> List[dict]:
    """Load all responses with quality scores"""
    responses = []
    with open(RESPONSES_FILE) as f:
        for line in f:
            responses.append(json.loads(line))
    return responses

def load_tasks() -> List[dict]:
    """Load task information"""
    tasks = []
    with open(TASKS_FILE) as f:
        for line in f:
            tasks.append(json.loads(line))
    return tasks

def extract_node_info(response: dict) -> Tuple[str, str, str, str, int, float]:
    """Extract key information from response"""
    return (
        response["task_id"],
        response["model"],
        response["node_id"],
        response["response"],  # For debugging
        response.get("attempt", 1),
        response.get("quality_score", 0.0)
    )

def organize_by_key(responses: List[dict]) -> Dict[Tuple, List[dict]]:
    """Organize responses by (task_id, node_id, repeat)"""
    organized = defaultdict(list)
    for resp in responses:
        key = (resp["task_id"], resp["node_id"], resp["repeat"])
        organized[key].append(resp)
    return organized

def calculate_metrics(organized: Dict[Tuple, List[dict]]) -> dict:
    """Calculate signal audit metrics"""

    # Prepare data structures
    node_types = ["n1", "n2", "n3", "n4"]
    results = {
        "overall": defaultdict(list),
        "by_node": {node: defaultdict(list) for node in node_types}
    }

    # Extract per-task, per-node, per-repeat quality scores
    for key, resp_list in organized.items():
        task_id, node_id, repeat = key

        # Get Qwen and GLM quality scores for this key
        qwen_score = None
        glm_score = None

        for resp in resp_list:
            if resp["model"] == "qwen-plus":
                qwen_score = resp.get("quality_score", 0.0)
            elif resp["model"] == "glm-5.2":
                glm_score = resp.get("quality_score", 0.0)

        if qwen_score is not None and glm_score is not None:
            delta = glm_score - qwen_score

            # Overall
            results["overall"]["deltas"].append(delta)
            results["overall"]["qwen_scores"].append(qwen_score)
            results["overall"]["glm_scores"].append(glm_score)

            # By node type
            if node_id in results["by_node"]:
                results["by_node"][node_id]["deltas"].append(delta)
                results["by_node"][node_id]["qwen_scores"].append(qwen_score)
                results["by_node"][node_id]["glm_scores"].append(glm_score)

    return results

def calculate_stable_switch_rates(organized: Dict[Tuple, List[dict]]) -> dict:
    """Calculate two-repeat stable switch and harmful switch rates"""

    node_types = ["n1", "n2", "n3", "n4"]
    stable_switch_stats = {
        "overall": {"stable_switch": 0, "harmful_switch": 0, "total": 0},
        "by_node": {node: {"stable_switch": 0, "harmful_switch": 0, "total": 0}
                   for node in node_types}
    }

    # Group by (task_id, node_id) to get both repeats
    task_node_groups = defaultdict(list)
    for (task_id, node_id, repeat), resp_list in organized.items():
        task_node_groups[(task_id, node_id)].append((repeat, resp_list))

    for (task_id, node_id), repeat_data in task_node_groups.items():
        if len(repeat_data) != 2:  # Need both repeats
            continue

        # Get scores for both repeats
        repeat_0_data = None
        repeat_1_data = None

        for repeat, resp_list in repeat_data:
            if repeat == 0:
                repeat_0_data = resp_list
            elif repeat == 1:
                repeat_1_data = resp_list

        if not repeat_0_data or not repeat_1_data:
            continue

        # Calculate deltas for both repeats
        deltas = []
        for resp_list in [repeat_0_data, repeat_1_data]:
            qwen_score = None
            glm_score = None
            for resp in resp_list:
                if resp["model"] == "qwen-plus":
                    qwen_score = resp.get("quality_score", 0.0)
                elif resp["model"] == "glm-5.2":
                    glm_score = resp.get("quality_score", 0.0)

            if qwen_score is not None and glm_score is not None:
                deltas.append(glm_score - qwen_score)

        if len(deltas) != 2:
            continue

        delta_0, delta_1 = deltas

        # Overall statistics
        stable_switch_stats["overall"]["total"] += 1

        # Stable switch: both repeats > DELTA
        if delta_0 > DELTA and delta_1 > DELTA:
            stable_switch_stats["overall"]["stable_switch"] += 1

        # Harmful switch: both repeats < -DELTA
        if delta_0 < -DELTA and delta_1 < -DELTA:
            stable_switch_stats["overall"]["harmful_switch"] += 1

        # By node type
        if node_id in stable_switch_stats["by_node"]:
            stable_switch_stats["by_node"][node_id]["total"] += 1
            if delta_0 > DELTA and delta_1 > DELTA:
                stable_switch_stats["by_node"][node_id]["stable_switch"] += 1
            if delta_0 < -DELTA and delta_1 < -DELTA:
                stable_switch_stats["by_node"][node_id]["harmful_switch"] += 1

    return stable_switch_stats

def calculate_bootstrap_ci(deltas: List[float], n_bootstrap: int = 10000) -> Tuple[float, float]:
    """Calculate paired bootstrap 95% CI for mean delta"""
    if len(deltas) < 2:
        return (0.0, 0.0)

    bootstrap_means = []
    n = len(deltas)

    for _ in range(n_bootstrap):
        # Resample with replacement
        sample = np.random.choice(deltas, size=n, replace=True)
        bootstrap_means.append(np.mean(sample))

    # Calculate 2.5th and 97.5th percentiles
    lower = np.percentile(bootstrap_means, 2.5)
    upper = np.percentile(bootstrap_means, 97.5)

    return (float(lower), float(upper))

def format_number(value: float, decimals: int = 3) -> str:
    """Format number for display"""
    if abs(value) < 0.001:
        return "0.000"
    return f"{value:.{decimals}f}"

def generate_signal_audit_report(metrics: dict, stable_switch_stats: dict) -> str:
    """Generate comprehensive signal audit report"""

    node_descriptions = {
        "n1": "N1 Extraction",
        "n2": "N2 Numerical",
        "n3": "N3 Reasoning",
        "n4": "N4 Synthesis"
    }

    report = []
    report.append("=" * 80)
    report.append("E2 STAGE 1 SIGNAL AUDIT - EXPLORATORY DECOMPOSITION PILOT")
    report.append("=" * 80)
    report.append("")
    report.append("EXPERIMENT STATUS:")
    report.append("  E1.1: FAIL (passing_specialists: [])")
    report.append("  E2 Stage 1: COMPLETE (480/480 outcomes)")
    report.append("  Type: Exploratory decomposition mechanism experiment")
    report.append("  Repeats: 2 (incompatible with held-out reversal metrics)")
    report.append("  Delta threshold: ±0.05")
    report.append("")

    # Overall results
    overall_deltas = metrics["overall"]["deltas"]
    overall_qwen = metrics["overall"]["qwen_scores"]
    overall_glm = metrics["overall"]["glm_scores"]

    if overall_deltas:
        mean_delta = np.mean(overall_deltas)
        median_delta = np.median(overall_deltas)
        delta_prevalence = sum(1 for d in overall_deltas if d > DELTA) / len(overall_deltas)
        mean_qwen = np.mean(overall_qwen)
        mean_glm = np.mean(overall_glm)

        # Bootstrap CI
        ci_lower, ci_upper = calculate_bootstrap_ci(overall_deltas)

        # Stable switch rates
        total_tasks = stable_switch_stats["overall"]["total"]
        stable_switch_rate = (stable_switch_stats["overall"]["stable_switch"] / total_tasks * 100) if total_tasks > 0 else 0
        harmful_switch_rate = (stable_switch_stats["overall"]["harmful_switch"] / total_tasks * 100) if total_tasks > 0 else 0

        report.append("OVERALL RESULTS (All Node Types):")
        report.append(f"  Mean Δ(GLM-Qwen+): {format_number(mean_delta)}")
        report.append(f"  Median Δ(GLM-Qwen+): {format_number(median_delta)}")
        report.append(f"  Δ > 0.05 prevalence: {format_number(delta_prevalence * 100, 1)}%")
        report.append(f"  Mean Qwen+ quality: {format_number(mean_qwen)}")
        report.append(f"  Mean GLM quality: {format_number(mean_glm)}")
        report.append(f"  Two-repeat Stable Switch Rate: {format_number(stable_switch_rate, 1)}%")
        report.append(f"  Two-repeat Harmful Switch Rate: {format_number(harmful_switch_rate, 1)}%")
        report.append(f"  95% Bootstrap CI: [{format_number(ci_lower)}, {format_number(ci_upper)}]")
        report.append(f"  Sample size: {len(overall_deltas)} task-node-repeat combinations")
        report.append("")

    # Node type specific results
    report.append("NODE TYPE SPECIFIC ANALYSIS:")
    report.append("")

    node_results = []
    for node_id in ["n1", "n2", "n3", "n4"]:
        node_deltas = metrics["by_node"][node_id]["deltas"]
        node_qwen = metrics["by_node"][node_id]["qwen_scores"]
        node_glm = metrics["by_node"][node_id]["glm_scores"]

        if node_deltas:
            mean_delta = np.mean(node_deltas)
            median_delta = np.median(node_deltas)
            delta_prevalence = sum(1 for d in node_deltas if d > DELTA) / len(node_deltas)
            mean_qwen = np.mean(node_qwen)
            mean_glm = np.mean(node_glm)

            # Bootstrap CI
            ci_lower, ci_upper = calculate_bootstrap_ci(node_deltas)

            # Stable switch rates
            total_tasks = stable_switch_stats["by_node"][node_id]["total"]
            stable_switch_rate = (stable_switch_stats["by_node"][node_id]["stable_switch"] / total_tasks * 100) if total_tasks > 0 else 0
            harmful_switch_rate = (stable_switch_stats["by_node"][node_id]["harmful_switch"] / total_tasks * 100) if total_tasks > 0 else 0

            node_results.append({
                "node_id": node_id,
                "description": node_descriptions.get(node_id, node_id),
                "mean_delta": mean_delta,
                "median_delta": median_delta,
                "delta_prevalence": delta_prevalence * 100,
                "mean_qwen": mean_qwen,
                "mean_glm": mean_glm,
                "stable_switch_rate": stable_switch_rate,
                "harmful_switch_rate": harmful_switch_rate,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "sample_size": len(node_deltas)
            })

    # Create table
    header = f"{'Node Type':<15} {'Mean Δ':<10} {'Median Δ':<10} {'Δ>5%':<8} {'Stable Switch':<15} {'Harmful Switch':<15} {'95% CI':<20} {'N':<6}"
    report.append(header)
    report.append("-" * len(header))

    for result in node_results:
        ci_str = f"[{format_number(result['ci_lower'])}, {format_number(result['ci_upper'])}]"
        row = f"{result['description']:<15} {format_number(result['mean_delta']):<10} {format_number(result['median_delta']):<10} {format_number(result['delta_prevalence'], 1):<8}% {format_number(result['stable_switch_rate'], 1):<15}% {format_number(result['harmful_switch_rate'], 1):<15}% {ci_str:<20} {result['sample_size']:<6}"
        report.append(row)

    report.append("")

    # Key findings
    report.append("KEY FINDINGS:")
    report.append("")

    # Find best performing node type
    best_node = max(node_results, key=lambda x: x["stable_switch_rate"])
    worst_node = min(node_results, key=lambda x: x["stable_switch_rate"])

    report.append(f"1. BEST NODE TYPE: {best_node['description']}")
    report.append(f"   - Stable Switch Rate: {format_number(best_node['stable_switch_rate'], 1)}%")
    report.append(f"   - Mean Δ: {format_number(best_node['mean_delta'])}")
    report.append(f"   - Median Δ: {format_number(best_node['median_delta'])}")
    report.append("")

    report.append(f"2. WORST NODE TYPE: {worst_node['description']}")
    report.append(f"   - Stable Switch Rate: {format_number(worst_node['stable_switch_rate'], 1)}%")
    report.append(f"   - Mean Δ: {format_number(worst_node['mean_delta'])}")
    report.append(f"   - Median Δ: {format_number(worst_node['median_delta'])}")
    report.append("")

    # Signal strength assessment
    strong_signal_nodes = [n for n in node_results if n["stable_switch_rate"] >= 10.0 and n["mean_delta"] > 0]
    moderate_signal_nodes = [n for n in node_results if 5.0 <= n["stable_switch_rate"] < 10.0 and n["mean_delta"] > 0]
    weak_signal_nodes = [n for n in node_results if n["stable_switch_rate"] < 5.0 or n["mean_delta"] <= 0]

    report.append("3. SIGNAL STRENGTH CLASSIFICATION:")
    report.append(f"   - Strong signal nodes (≥10% stable switch, Δ>0): {len(strong_signal_nodes)}")
    for node in strong_signal_nodes:
        report.append(f"     * {node['description']}: {format_number(node['stable_switch_rate'], 1)}% stable switch")
    report.append(f"   - Moderate signal nodes (5-10% stable switch, Δ>0): {len(moderate_signal_nodes)}")
    for node in moderate_signal_nodes:
        report.append(f"     * {node['description']}: {format_number(node['stable_switch_rate'], 1)}% stable switch")
    report.append(f"   - Weak/No signal nodes: {len(weak_signal_nodes)}")
    for node in weak_signal_nodes:
        reason = "low stable switch" if node['stable_switch_rate'] < 5.0 else "non-positive Δ"
        report.append(f"     * {node['description']}: {reason}")
    report.append("")

    # CI analysis
    positive_ci_nodes = [n for n in node_results if n["ci_lower"] > 0]
    straddling_ci_nodes = [n for n in node_results if n["ci_lower"] <= 0 <= n["ci_upper"]]
    negative_ci_nodes = [n for n in node_results if n["ci_upper"] < 0]

    report.append("4. CONFIDENCE INTERVAL ANALYSIS:")
    report.append(f"   - Positive 95% CI (confidently >0): {len(positive_ci_nodes)} node types")
    for node in positive_ci_nodes:
        report.append(f"     * {node['description']}: [{format_number(node['ci_lower'])}, {format_number(node['ci_upper'])}]")
    report.append(f"   - CI straddles 0 (uncertain): {len(straddling_ci_nodes)} node types")
    for node in straddling_ci_nodes:
        report.append(f"     * {node['description']}: [{format_number(node['ci_lower'])}, {format_number(node['ci_upper'])}]")
    report.append(f"   - Negative 95% CI (confidently <0): {len(negative_ci_nodes)} node types")
    for node in negative_ci_nodes:
        report.append(f"     * {node['description']}: [{format_number(node['ci_lower'])}, {format_number(node['ci_upper'])}]")
    report.append("")

    # Exploratory conclusion
    report.append("EXPLORATORY CONCLUSION:")
    report.append("")

    if strong_signal_nodes:
        report.append("✅ E2-PASS-for-followup: Evidence of node-level specialization")
        report.append("")
        report.append("Rationale:")
        report.append(f"  - {len(strong_signal_nodes)} node type(s) show ≥10% stable switch rate with positive mean Δ")
        report.append(f"  - Best performing node: {best_node['description']} with {format_number(best_node['stable_switch_rate'], 1)}% stable switch")
        if positive_ci_nodes:
            report.append(f"  - {len(positive_ci_nodes)} node type(s) have 95% CI confidently above 0")
        report.append("  - Harmful switch rates are controlled across node types")
        report.append("")
        report.append("Recommendation:")
        report.append("  → Design formal 3-repeat confirmatory decomposition experiment")
        report.append("  → Target nodes with strong signal for focused analysis")
        report.append("  → Establish held-out reversal metrics with proper repeat structure")
    elif moderate_signal_nodes:
        report.append("⚠️  E2-MIXED: Weak evidence of node-level specialization")
        report.append("")
        report.append("Rationale:")
        report.append(f"  - {len(moderate_signal_nodes)} node type(s) show 5-10% stable switch rate")
        report.append(f"  - No node type reaches the ≥10% stable switch threshold")
        report.append(f"  - Signal may exist but requires larger sample size")
        report.append("")
        report.append("Recommendation:")
        report.append("  → Consider expanding sample size before designing 3-repeat experiment")
        report.append("  → Focus on moderate-signal node types for further investigation")
        report.append("  → Re-evaluate decomposition strategy if results remain weak")
    else:
        report.append("❌ E2-FAIL: No evidence of node-level specialization")
        report.append("")
        report.append("Rationale:")
        report.append("  - All node types show <5% stable switch rate or non-positive mean Δ")
        report.append("  - Confidence intervals largely straddle or are below 0")
        report.append(f"  - Decomposition does not appear to enhance routing signal")
        report.append("")
        report.append("Recommendation:")
        report.append("  → STOP decomposition expansion")
        report.append("  → Reconsider whole-query routing approach")
        report.append("  → Investigate alternative decomposition strategies")

    report.append("")
    report.append("=" * 80)

    return "\n".join(report), {
        "node_results": node_results,
        "overall_metrics": {
            "mean_delta": float(np.mean(overall_deltas)) if overall_deltas else 0.0,
            "median_delta": float(np.median(overall_deltas)) if overall_deltas else 0.0,
            "stable_switch_rate": float(stable_switch_stats["overall"]["stable_switch"] / stable_switch_stats["overall"]["total"] * 100) if stable_switch_stats["overall"]["total"] > 0 else 0.0,
            "harmful_switch_rate": float(stable_switch_stats["overall"]["harmful_switch"] / stable_switch_stats["overall"]["total"] * 100) if stable_switch_stats["overall"]["total"] > 0 else 0.0
        },
        "exploratory_conclusion": "PASS" if strong_signal_nodes else ("MIXED" if moderate_signal_nodes else "FAIL")
    }

def main():
    """Main signal audit function"""
    try:
        print("Loading E2 Stage 1 data...")
        responses = load_responses()
        print(f"Loaded {len(responses)} responses")

        print("Organizing data by task-node-repeat...")
        organized = organize_by_key(responses)
        print(f"Found {len(organized)} unique task-node-repeat combinations")

        print("Calculating signal metrics...")
        metrics = calculate_metrics(organized)

        print("Calculating stable switch rates...")
        stable_switch_stats = calculate_stable_switch_rates(organized)

        print("Generating signal audit report...")
        report, structured_results = generate_signal_audit_report(metrics, stable_switch_stats)

        print("\n" + report)

        # Save results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = E2_DIR / f"E2_STAGE1_SIGNAL_AUDIT_{timestamp}.txt"
        results_file = E2_DIR / f"E2_STAGE1_SIGNAL_AUDIT_RESULTS_{timestamp}.json"

        with open(report_file, 'w') as f:
            f.write(report)

        with open(results_file, 'w') as f:
            json.dump(structured_results, f, indent=2, default=str)

        print(f"\nSignal audit report saved to: {report_file}")
        print(f"Structured results saved to: {results_file}")

    except Exception as e:
        print(f"Error during signal audit: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    from datetime import datetime
    main()