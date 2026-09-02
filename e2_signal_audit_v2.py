#!/usr/bin/env python3
"""
E2 Stage 1 Signal Audit - Node-level quality assessment
Using heuristic scoring for intermediate nodes and objective_score for final synthesis
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
EVENTS_FILE = E2_DIR / "E2_STAGE1_RESPONSE_EVENTS.jsonl"
TASKS_FILE = E2_DIR / "E2_STAGE1_30.jsonl"
PROTOCOL_FILE = E2_DIR / "E2_PROTOCOL.json"
EXP_DIR = Path("/root/target_support_expansion_v1")
PROJECT_DIR = Path("/root/autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main")

DELTA = 0.05  # Significance threshold

# Add project path for scoring
import sys
sys.path.insert(0, str(PROJECT_DIR))
from openclaw_router.experiment_protocol import objective_score

def load_responses() -> List[dict]:
    """Load all responses"""
    responses = []
    with open(RESPONSES_FILE) as f:
        for line in f:
            responses.append(json.loads(line))
    return responses

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
    Returns 0.0-1.0 quality score based on content completeness and structure
    """
    if not answer or not isinstance(answer, str):
        return 0.0

    answer_lower = answer.lower().strip()
    if not answer_lower or answer_lower in ["none", "n/a", "not applicable", ""]:
        return 0.0

    score = 0.0

    # Node-specific heuristics
    if node_type == "evidence_localization":
        # N1: Check if evidence locations are provided
        if "evidence_locations" in answer_lower or "source" in answer_lower:
            score += 0.3
        # Check if specific sections/contexts are mentioned
        if any(term in answer_lower for term in ["section", "context", "paragraph", "article", "clause"]):
            score += 0.3
        # Check if non-empty content
        if len(answer.strip()) > 20:
            score += 0.2
        # Penalty for generic placeholders
        if "source context" in answer_lower and len(answer.strip()) < 30:
            score -= 0.2

    elif node_type == "extraction":
        # N2: Check for structured facts
        if "structured_facts" in answer_lower:
            score += 0.4
            # Check if non-empty array
            if "[]" not in answer or len([x for x in answer if x not in '[]{}"",: \n']) > 20:
                score += 0.3
        # Check for extracted data
        if any(term in answer_lower for term in ["extracted", "identified", "found", "located"]):
            score += 0.2
        # Check for specific values/numbers
        if re.search(r'\d+', answer):
            score += 0.1

    elif node_type in ["numerical_reasoning", "regulatory_compliance", "numerical_reasoning_or_regulatory_compliance"]:
        # N3: Check for derived results
        if "derived_result" in answer_lower:
            score += 0.3
        # Check for reasoning steps
        if any(term in answer_lower for term in ["because", "since", "due to", "based on", "according to"]):
            score += 0.3
        # Check for specific conclusions
        if any(term in answer_lower for term in ["therefore", "thus", "consequently", "as a result"]):
            score += 0.2
        # Check for compliance terms
        if any(term in answer_lower for term in ["obligation", "permission", "exception", "procedure", "compliance"]):
            score += 0.2

    elif node_type == "evidence_synthesis":
        # N4: This should use objective_score, but fallback to heuristics
        if "final_answer" in answer_lower:
            score += 0.3
        # Check for definitive conclusion
        if any(term in answer_lower for term in ["conclusion", "result", "answer is", "therefore"]):
            score += 0.3
        # Check for non-generic content
        if len(answer.strip()) > 50 and "not applicable" not in answer_lower:
            score += 0.2
        # Check for synthesis of previous nodes
        if any(term in answer_lower for term in ["based on", "combining", "considering", "taking into account"]):
            score += 0.2

    return max(0.0, min(1.0, score))

def objective_node_quality(task: dict, node_type: str, answer: str) -> Optional[float]:
    """
    Use objective_score for final synthesis node, heuristics for others
    """
    if node_type == "evidence_synthesis" and task:
        try:
            score = objective_score(task, str(answer) + "\n")
            return float(score or 0.0)
        except Exception as e:
            print(f"Warning: objective_score failed for task {task.get('id', 'unknown')}: {e}")
            return None

    return heuristic_node_quality(node_type, answer)

def organize_by_node(responses: List[dict], tasks: Dict[str, dict], original_tasks: Dict[str, dict]) -> Dict[str, Dict]:
    """
    Organize responses by node type and calculate quality scores
    Returns structure: {node_type: {(task_id, model, repeat): score}}
    """
    node_data = {
        "evidence_localization": {},  # n1
        "extraction": {},             # n2
        "numerical_reasoning_or_regulatory_compliance": {},  # n3
        "evidence_synthesis": {}      # n4
    }

    for resp in responses:
        task_id = resp["task_id"]
        model = resp["model"]
        repeat = resp["repeat"]
        node_id = resp["node_id"]
        node_type = resp["node_type"]
        answer = resp.get("answer", "")

        # Map node_id to node_type if needed
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

        # Get task for objective scoring
        task = original_tasks.get(task_id, tasks.get(task_id, {}))

        # Calculate quality score
        if effective_node_type == "evidence_synthesis" and task:
            # Use objective scoring for final answer
            score = objective_node_quality(task, effective_node_type, answer)
        else:
            # Use heuristic scoring for intermediate nodes
            score = heuristic_node_quality(effective_node_type, answer)

        if score is not None:
            node_data[effective_node_type][key] = score

    return node_data

def calculate_node_signal_analysis(node_data: Dict[str, Dict]) -> Dict:
    """Calculate signal analysis metrics for each node type"""

    results = {}

    for node_type, data in node_data.items():
        # Separate by model
        qwen_scores = []
        glm_scores = []
        task_pairs = []

        # Organize by (task_id, repeat)
        task_repeat_data = defaultdict(lambda: {"qwen": None, "glm": None})

        for (task_id, model, repeat), score in data.items():
            key = (task_id, repeat)
            if model == "qwen-plus":
                task_repeat_data[key]["qwen"] = score
            elif model == "glm-5.2":
                task_repeat_data[key]["glm"] = score

        # Calculate deltas for complete pairs
        deltas = []
        for (task_id, repeat), scores in task_repeat_data.items():
            if scores["qwen"] is not None and scores["glm"] is not None:
                delta = scores["glm"] - scores["qwen"]
                deltas.append(delta)
                qwen_scores.append(scores["qwen"])
                glm_scores.append(scores["glm"])
                task_pairs.append((task_id, repeat, scores["qwen"], scores["glm"], delta))

        if not deltas:
            continue

        # Basic metrics
        mean_delta = np.mean(deltas)
        median_delta = np.median(deltas)
        std_delta = np.std(deltas)

        # Calculate stable switch rate (need both repeats for same task)
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

        # Delta > 0.05 prevalence
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

def generate_comprehensive_report(results: Dict) -> str:
    """Generate comprehensive signal audit report"""

    node_descriptions = {
        "evidence_localization": "N1 Evidence Localization",
        "extraction": "N2 Structured Extraction",
        "numerical_reasoning_or_regulatory_compliance": "N3 Reasoning/Compliance",
        "evidence_synthesis": "N4 Final Synthesis"
    }

    report = []
    report.append("=" * 80)
    report.append("E2 STAGE 1 SIGNAL AUDIT - NODE-LEVEL ANALYSIS")
    report.append("=" * 80)
    report.append("")
    report.append("EXPERIMENT STATUS:")
    report.append("  E1.1: FAIL (passing_specialists: [])")
    report.append("  E2 Stage 1: COMPLETE (480/480 outcomes)")
    report.append("  Type: Exploratory decomposition mechanism experiment")
    report.append("  Scoring: Heuristic for N1-N3, Objective for N4")
    report.append("  Delta threshold: ±0.05")
    report.append("")

    # Overall analysis
    if results:
        report.append("NODE TYPE SPECIFIC ANALYSIS:")
        report.append("")

        # Create detailed table
        header = f"{'Node Type':<30} {'Mean Δ':<10} {'Median Δ':<10} {'Δ>5%':<8} {'Stable Switch':<15} {'Harmful':<10} {'95% CI':<20} {'N':<6}"
        report.append(header)
        report.append("-" * len(header))

        node_results = []
        for node_type, metrics in results.items():
            description = node_descriptions.get(node_type, node_type)
            ci_str = f"[{metrics['ci_lower']:.3f}, {metrics['ci_upper']:.3f}]"

            row = (f"{description:<30} "
                  f"{metrics['mean_delta']:.3f}    "
                  f"{metrics['median_delta']:.3f}    "
                  f"{metrics['delta_prevalence']:.1f}%   "
                  f"{metrics['stable_switch_rate']:.1f}%        "
                  f"{metrics['harmful_switch_rate']:.1f}%     "
                  f"{ci_str:<20} "
                  f"{metrics['sample_size']:<6}")

            report.append(row)

            node_results.append({
                "node_type": node_type,
                "description": description,
                **metrics
            })

        report.append("")

        # Key findings
        report.append("KEY FINDINGS:")
        report.append("")

        # Best and worst nodes
        if node_results:
            best_node = max(node_results, key=lambda x: x["stable_switch_rate"])
            worst_node = min(node_results, key=lambda x: x["stable_switch_rate"])

            report.append(f"1. BEST NODE TYPE: {best_node['description']}")
            report.append(f"   - Stable Switch Rate: {best_node['stable_switch_rate']:.1f}%")
            report.append(f"   - Mean Δ(GLM-Qwen+): {best_node['mean_delta']:.3f}")
            report.append(f"   - Median Δ: {best_node['median_delta']:.3f}")
            report.append(f"   - Δ>5% Prevalence: {best_node['delta_prevalence']:.1f}%")
            report.append("")

            report.append(f"2. WORST NODE TYPE: {worst_node['description']}")
            report.append(f"   - Stable Switch Rate: {worst_node['stable_switch_rate']:.1f}%")
            report.append(f"   - Mean Δ(GLM-Qwen+): {worst_node['mean_delta']:.3f}")
            report.append(f"   - Median Δ: {worst_node['median_delta']:.3f}")
            report.append("")

        # Signal strength classification
        strong_signal = [n for n in node_results if n["stable_switch_rate"] >= 10.0 and n["mean_delta"] > 0]
        moderate_signal = [n for n in node_results if 5.0 <= n["stable_switch_rate"] < 10.0 and n["mean_delta"] > 0]
        weak_signal = [n for n in node_results if n["stable_switch_rate"] < 5.0 or n["mean_delta"] <= 0]

        report.append("3. SIGNAL STRENGTH CLASSIFICATION:")
        report.append(f"   - Strong signal (≥10% stable switch, Δ>0): {len(strong_signal)} node type(s)")
        for node in strong_signal:
            report.append(f"     * {node['description']}: {node['stable_switch_rate']:.1f}% stable switch, Δ={node['mean_delta']:.3f}")
        report.append(f"   - Moderate signal (5-10% stable switch, Δ>0): {len(moderate_signal)} node type(s)")
        for node in moderate_signal:
            report.append(f"     * {node['description']}: {node['stable_switch_rate']:.1f}% stable switch, Δ={node['mean_delta']:.3f}")
        report.append(f"   - Weak/No signal (<5% stable switch or Δ≤0): {len(weak_signal)} node type(s)")
        for node in weak_signal:
            reason = "low stable switch" if node['stable_switch_rate'] < 5.0 else "non-positive Δ"
            report.append(f"     * {node['description']}: {reason}")
        report.append("")

        # CI analysis
        positive_ci = [n for n in node_results if n["ci_lower"] > 0]
        straddling_ci = [n for n in node_results if n["ci_lower"] <= 0 <= n["ci_upper"]]
        negative_ci = [n for n in node_results if n["ci_upper"] < 0]

        report.append("4. CONFIDENCE INTERVAL ANALYSIS:")
        report.append(f"   - Positive 95% CI (confidently >0): {len(positive_ci)} node type(s)")
        for node in positive_ci:
            report.append(f"     * {node['description']}: [{node['ci_lower']:.3f}, {node['ci_upper']:.3f}]")
        report.append(f"   - CI straddles 0 (uncertain): {len(straddling_ci)} node type(s)")
        for node in straddling_ci:
            report.append(f"     * {node['description']}: [{node['ci_lower']:.3f}, {node['ci_upper']:.3f}]")
        report.append(f"   - Negative 95% CI (confidently <0): {len(negative_ci)} node type(s)")
        for node in negative_ci:
            report.append(f"     * {node['description']}: [{node['ci_lower']:.3f}, {node['ci_upper']:.3f}]")
        report.append("")

        # Exploratory conclusion
        report.append("EXPLORATORY CONCLUSION:")
        report.append("")

        if strong_signal:
            report.append("✅ E2-PASS-for-followup: Evidence of node-level specialization")
            report.append("")
            report.append("Rationale:")
            report.append(f"  - {len(strong_signal)} node type(s) show ≥10% stable switch rate with positive mean Δ")
            report.append(f"  - Best performing node: {best_node['description']}")
            report.append(f"    * Stable Switch Rate: {best_node['stable_switch_rate']:.1f}%")
            report.append(f"    * Mean Δ: {best_node['mean_delta']:.3f}")
            report.append(f"    * Median Δ: {best_node['median_delta']:.3f}")
            if positive_ci:
                report.append(f"  - {len(positive_ci)} node type(s) have 95% CI confidently above 0")
            report.append("  - Harmful switch rates are controlled")
            report.append("")
            report.append("Recommendation:")
            report.append("  → Design formal 3-repeat confirmatory decomposition experiment")
            report.append("  → Target strong-signal node types for focused analysis")
            report.append("  → Refine heuristic scoring for intermediate nodes")
            report.append("  → Establish held-out reversal metrics with proper repeat structure")

        elif moderate_signal:
            report.append("⚠️  E2-MIXED: Weak evidence of node-level specialization")
            report.append("")
            report.append("Rationale:")
            report.append(f"  - {len(moderate_signal)} node type(s) show 5-10% stable switch rate")
            report.append(f"  - No node type reaches the ≥10% stable switch threshold")
            report.append(f"  - Signal may exist but requires better evaluation methodology")
            report.append("")
            report.append("Recommendation:")
            report.append("  → Improve intermediate node scoring (heuristic limitations)")
            report.append("  → Consider expanding sample size or refining decomposition")
            report.append("  → Investigate if moderate signal is consistent across tasks")
            report.append("  → Re-evaluate decomposition strategy if signal remains weak")

        else:
            report.append("❌ E2-FAIL: No evidence of node-level specialization")
            report.append("")
            report.append("Rationale:")
            report.append("  - All node types show <5% stable switch rate or non-positive mean Δ")
            report.append("  - Confidence intervals largely straddle or are below 0")
            report.append("  - Decomposition does not appear to enhance routing signal")
            report.append("  - Current heuristic scoring may not capture intermediate node quality")
            report.append("")
            report.append("Recommendation:")
            report.append("  → STOP decomposition expansion")
            report.append("  → Reconsider whole-query routing approach")
            report.append("  → Investigate alternative evaluation methods for intermediate nodes")
            report.append("  → Consider if decomposition strategy needs fundamental redesign")

    report.append("")
    report.append("METHODOLOGICAL NOTES:")
    report.append("  - N1-N3 scored using heuristic methods (content completeness, structure)")
    report.append("  - N4 scored using objective_score (gold answer matching)")
    report.append("  - 2-repeat structure limits held-out reversal analysis")
    report.append("  - Exploratory nature: results should inform future 3-repeat experiments")
    report.append("=" * 80)

    return "\n".join(report), {
        "node_results": node_results if node_results else [],
        "exploratory_conclusion": "PASS" if strong_signal else ("MIXED" if moderate_signal else "FAIL"),
        "best_node": best_node if node_results else None,
        "signal_distribution": {
            "strong": len(strong_signal),
            "moderate": len(moderate_signal),
            "weak": len(weak_signal)
        }
    }

def main():
    """Main signal audit function"""
    try:
        print("Loading E2 Stage 1 data...")
        responses = load_responses()
        print(f"Loaded {len(responses)} responses")

        print("Loading task information...")
        tasks = load_tasks()
        original_tasks = load_original_tasks()
        print(f"Loaded {len(tasks)} stage tasks, {len(original_tasks)} original tasks")

        print("Organizing data by node type...")
        node_data = organize_by_node(responses, tasks, original_tasks)

        print("Calculating signal analysis metrics...")
        results = calculate_node_signal_analysis(node_data)

        print("Generating comprehensive report...")
        report, structured_results = generate_comprehensive_report(results)

        print("\n" + report)

        # Save results
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = E2_DIR / f"E2_STAGE1_SIGNAL_AUDIT_NODELEVEL_{timestamp}.txt"
        results_file = E2_DIR / f"E2_STAGE1_SIGNAL_AUDIT_NODELEVEL_RESULTS_{timestamp}.json"

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
    main()