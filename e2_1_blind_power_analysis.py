#!/usr/bin/env python3
"""
E2.1 Blind Power/Precision Analysis
Outcome-blind sample size determination BEFORE protocol finalization
"""

import numpy as np
from scipy import stats
from typing import Tuple, Dict

def calculate_effect_size_power_analysis(
    n_tasks: int,
    min_effect_size: float = 0.03,
    alpha: float = 0.05,
    power_target: float = 0.80,
    n_models: int = 3,
    n_repeats: int = 3
) -> Dict:
    """
    Calculate statistical power for detecting minimum effect size

    Parameters:
    - n_tasks: Number of tasks (sample size)
    - min_effect_size: Minimum effect size we want to detect (G_N1 >= 0.03)
    - alpha: Type I error rate (0.05 for 95% CI)
    - power_target: Desired statistical power (0.80 for 80% power)
    - n_models: Number of models being compared (3)
    - n_repeats: Number of repeats per task-model combination (3)

    Returns: Power analysis results
    """

    # For paired comparison (specialist vs anchor), we use paired t-test power
    # Effect size (Cohen's d) for paired design
    # We need to estimate the standard deviation of the paired differences

    # Conservative estimate based on evidence F1 distribution:
    # - Evidence F1 typically ranges 0.0 to 1.0
    # - Reasonable SD of paired differences: ~0.15-0.25
    # - We use conservative SD = 0.20 for power calculation

    estimated_sd = 0.20  # Conservative estimate for evidence F1 differences
    cohens_d = min_effect_size / estimated_sd

    # Calculate power for paired t-test
    # Power analysis using non-central t-distribution
    df = n_tasks - 1  # degrees of freedom for paired test
    ncp = np.sqrt(n_tasks) * cohens_d  # non-centrality parameter

    # Critical t-value for two-tailed test
    t_critical = stats.t.ppf(1 - alpha/2, df)

    # Power calculation
    # Power = P(|T| > t_critical | H1)
    # Where T follows non-central t-distribution with ncp

    power = 1 - stats.nct.cdf(t_critical, df, ncp) + stats.nct.cdf(-t_critical, df, ncp)

    # Also calculate precision (width of 95% CI)
    # Standard error of mean difference
    se_mean = estimated_sd / np.sqrt(n_tasks)
    ci_width = 1.96 * 2 * se_mean  # 95% CI width

    # Precision check: Can we distinguish effect from zero?
    # If CI lower bound > 0, we have statistical significance
    precision_adequate = (min_effect_size - 1.96 * se_mean) > 0

    return {
        "n_tasks": n_tasks,
        "min_effect_size": min_effect_size,
        "cohens_d": cohens_d,
        "estimated_sd": estimated_sd,
        "power": power,
        "meets_power_target": power >= power_target,
        "ci_width_95": ci_width,
        "ci_lower_bound": min_effect_size - 1.96 * se_mean,
        "precision_adequate": precision_adequate,
        "se_mean": se_mean
    }

def find_minimum_sample_size(
    min_effect_size: float = 0.03,
    alpha: float = 0.05,
    power_target: float = 0.80,
    max_n: int = 200,
    step: int = 5
) -> Dict:
    """
    Find minimum sample size to achieve target power
    """

    results = []
    for n in range(20, max_n + 1, step):
        analysis = calculate_effect_size_power_analysis(n, min_effect_size, alpha, power_target)
        results.append(analysis)

        if analysis["meets_power_target"] and analysis["precision_adequate"]:
            return {
                "recommended_n": n,
                "power_at_n": analysis["power"],
                "ci_width_at_n": analysis["ci_width_95"],
                "ci_lower_bound": analysis["ci_lower_bound"],
                "all_analyses": results
            }

    # If we don't find adequate sample size within max_n
    best_result = max(results, key=lambda x: x["power"])
    return {
        "recommended_n": best_result["n_tasks"],
        "power_at_recommended": best_result["power"],
        "meets_power_target": False,
        "note": f"Could not achieve {power_target} power within {max_n} tasks. Recommended: {best_result['n_tasks']} tasks with {best_result['power']:.2f} power.",
        "all_analyses": results
    }

def analyze_candidate_sizes(
    candidate_sizes: list = [40, 50, 60, 70, 80, 90, 100],
    min_effect_size: float = 0.03
) -> Dict:
    """
    Analyze power and precision for multiple candidate sample sizes
    """

    results = {}
    for n in candidate_sizes:
        analysis = calculate_effect_size_power_analysis(n, min_effect_size)
        results[n] = analysis

    # Find recommended size
    recommended = None
    for n in sorted(results.keys()):
        if results[n]["meets_power_target"] and results[n]["precision_adequate"]:
            recommended = n
            break

    return {
        "candidate_analyses": results,
        "recommended_size": recommended,
        "min_effect_size": min_effect_size
    }

def sensitivity_analysis(
    base_n: int = 60,
    effect_sizes: list = [0.02, 0.025, 0.03, 0.035, 0.04],
    sd_estimates: list = [0.15, 0.18, 0.20, 0.22, 0.25]
) -> Dict:
    """
    Sensitivity analysis for different effect sizes and SD estimates
    """

    results = {"effect_size_sensitivity": {}, "sd_sensitivity": {}}

    # Effect size sensitivity
    for effect_size in effect_sizes:
        analysis = calculate_effect_size_power_analysis(base_n, effect_size)
        results["effect_size_sensitivity"][effect_size] = {
            "power": analysis["power"],
            "ci_width": analysis["ci_width_95"],
            "precision_adequate": analysis["precision_adequate"]
        }

    # SD sensitivity
    for sd in sd_estimates:
        analysis = calculate_effect_size_power_analysis(base_n, min_effect_size=0.03)
        # Manually adjust SD for this analysis
        cohens_d = 0.03 / sd
        df = base_n - 1
        ncp = np.sqrt(base_n) * cohens_d
        t_critical = stats.t.ppf(0.975, df)
        power = 1 - stats.nct.cdf(t_critical, df, ncp) + stats.nct.cdf(-t_critical, df, ncp)
        se_mean = sd / np.sqrt(base_n)
        ci_width = 1.96 * 2 * se_mean

        results["sd_sensitivity"][sd] = {
            "cohens_d": cohens_d,
            "power": power,
            "ci_width": ci_width,
            "precision_adequate": (0.03 - 1.96 * se_mean) > 0
        }

    return results

def generate_power_analysis_report() -> str:
    """Generate comprehensive power analysis report"""

    report = []
    report.append("=" * 80)
    report.append("E2.1 BLIND POWER/PRECISION ANALYSIS")
    report.append("=" * 80)
    report.append("")
    report.append("ANALYSIS PURPOSE:")
    report.append("  - Determine appropriate sample size for E2.1-A BEFORE protocol finalization")
    report.append("  - Outcome-blind: No E2.1 model results used in analysis")
    report.append("  - Based on minimum effect size: G_N1 >= 0.03")
    report.append("  - Target: 80% power with 95% confidence")
    report.append("")

    report.append("ANALYSIS PARAMETERS:")
    report.append("  - Minimum effect size: 0.03 (Stable Semantic Oracle Gap)")
    report.append("  - Alpha: 0.05 (95% confidence interval)")
    report.append("  - Target power: 0.80 (80% statistical power)")
    report.append("  - Models: 3 (qwen-plus, glm-5.2, deepseek)")
    report.append("  - Repeats: 3 (rotating held-out design)")
    report.append("  - Quality metric: Evidence F1 (0.0 to 1.0 scale)")
    report.append("  - Estimated SD of paired differences: 0.20 (conservative)")
    report.append("")

    # Analyze candidate sizes
    report.append("CANDIDATE SAMPLE SIZE ANALYSIS:")
    report.append("")

    candidate_analysis = analyze_candidate_sizes()

    header = f"{'N':<6} {'Power':<10} {'CI Width':<12} {'CI Lower':<12} {'Adequate':<10}"
    report.append(header)
    report.append("-" * len(header))

    for n in sorted(candidate_analysis["candidate_analyses"].keys()):
        analysis = candidate_analysis["candidate_analyses"][n]
        adequate = "✅ YES" if (analysis["meets_power_target"] and analysis["precision_adequate"]) else "❌ NO"
        ci_lower = f"{analysis['ci_lower_bound']:.4f}"

        row = f"{n:<6} {analysis['power']:.3f}     {analysis['ci_width_95']:.4f}      {ci_lower:<12} {adequate:<10}"
        report.append(row)

    report.append("")

    # Recommended size
    recommended = candidate_analysis["recommended_size"]
    if recommended:
        rec_analysis = candidate_analysis["candidate_analyses"][recommended]
        report.append(f"RECOMMENDED SAMPLE SIZE: {recommended} tasks")
        report.append("")
        report.append("Justification:")
        report.append(f"  - Achieves {rec_analysis['power']:.1%} power (target: 80%)")
        report.append(f"  - 95% CI width: {rec_analysis['ci_width_95']:.4f}")
        report.append(f"  - CI lower bound for effect=0.03: {rec_analysis['ci_lower_bound']:.4f} (> 0)")
        report.append(f"  - Meets both power and precision requirements")
    else:
        report.append("NO CANDIDATE SIZE MEETS REQUIREMENTS")
        report.append("  - Consider increasing minimum effect size or accepting lower power")
    report.append("")

    # Sensitivity analysis
    report.append("SENSITIVITY ANALYSIS:")
    report.append("")

    sensitivity = sensitivity_analysis()

    report.append("Effect Size Sensitivity (at N=60):")
    report.append(f"{'Effect Size':<15} {'Power':<10} {'CI Width':<12} {'Adequate':<10}")
    report.append("-" * 47)

    for effect_size, results in sensitivity["effect_size_sensitivity"].items():
        adequate = "✅" if results["precision_adequate"] else "❌"
        row = f"{effect_size:<15.3f} {results['power']:.3f}     {results['ci_width']:.4f}      {adequate:<10}"
        report.append(row)

    report.append("")

    report.append("SD Estimate Sensitivity (at N=60, effect=0.03):")
    report.append(f"{'SD Estimate':<15} {'Cohens d':<12} {'Power':<10} {'Adequate':<10}")
    report.append("-" * 47)

    for sd, results in sensitivity["sd_sensitivity"].items():
        adequate = "✅" if results["precision_adequate"] else "❌"
        row = f"{sd:<15.2f} {results['cohens_d']:<12.3f} {results['power']:.3f}     {adequate:<10}"
        report.append(row)

    report.append("")

    # Final recommendation
    report.append("FINAL RECOMMENDATION:")
    report.append("")

    if recommended and recommended <= 80:
        report.append(f"✅ ADOPT N = {recommended} TASKS")
        report.append("")
        report.append("Rationale:")
        report.append("  - Meets 80% power target for minimum effect size of 0.03")
        report.append("  - Provides adequate precision (CI lower bound > 0)")
        report.append("  - Reasonable cost for confirmatory experiment")
        report.append("  - Balances statistical rigor with practical feasibility")
    elif recommended:
        report.append(f"⚠️  CONSIDER N = {recommended} TASKS")
        report.append("")
        report.append("Rationale:")
        report.append(f"  - Required to achieve {candidate_analysis['candidate_analyses'][recommended]['power']:.1%} power")
        report.append("  - Higher cost but necessary for statistical validity")
        report.append("  - Consider if minimum effect size of 0.03 is realistic")
    else:
        report.append("❌ RECONSIDER EXPERIMENTAL DESIGN")
        report.append("")
        report.append("Rationale:")
        report.append("  - No sample size up to 100 tasks achieves desired power")
        report.append("  - Consider:")
        report.append("    * Increasing minimum effect size (e.g., 0.04)")
        report.append("    * Accepting lower power (e.g., 70%)")
        report.append("    * Using more sensitive statistical methods")
    report.append("")

    # Implementation guidance
    report.append("IMPLEMENTATION GUIDANCE:")
    report.append("")
    report.append("Next Steps:")
    report.append("  1. Update E2.1_PROTOCOL_FINAL.json with final N")
    report.append("  2. Calculate SHA256 of finalized protocol")
    report.append("  3. Begin gold evidence annotation for N tasks")
    report.append("  4. Execute E2.1-A with frozen parameters")
    report.append("")
    report.append("Cost Implications:")
    if recommended:
        e2_1_a_calls = recommended * 3 * 3  # N tasks × 3 models × 3 repeats
        e2_1_a_cost = e2_1_a_calls * 0.005  # ~$0.005 per evidence call
        report.append(f"  - E2.1-A: {e2_1_a_calls} calls (~${e2_1_a_cost:.1f})")
        report.append(f"  - E2.1-B: 1350 calls (~$4-6)")
        report.append(f"  - Total: ~${e2_1_a_cost + 5:.1f}-{e2_1_a_cost + 7:.1f}")
    report.append("")

    report.append("STATISTICAL ASSUMPTIONS:")
    report.append("  - Paired comparison design (specialist vs anchor)")
    report.append("  - Evidence F1 differences follow approximately normal distribution")
    report.append("  - Conservative SD estimate (0.20) accounts for task heterogeneity")
    report.append("  - Bootstrap CI will provide robustness to distribution assumptions")
    report.append("")

    report.append("LIMITATIONS:")
    report.append("  - Analysis based on estimated SD, not empirical data")
    report.append("  - Actual power may differ if true SD differs from estimate")
    report.append("  - Evidence F1 may have different distribution than assumed")
    report.append("  - Multiple comparisons across models not fully accounted for")
    report.append("")

    report.append("=" * 80)

    return "\n".join(report), {
        "recommended_n": recommended,
        "candidate_analysis": candidate_analysis,
        "sensitivity_analysis": sensitivity
    }

def main():
    """Run blind power analysis and generate final recommendation"""

    print("Running E2.1 Blind Power/Precision Analysis...")
    print("This analysis is outcome-blind - no E2.1 model results used.")
    print()

    report, results = generate_power_analysis_report()

    print(report)

    # Save results
    from pathlib import Path
    import json
    from datetime import datetime

    output_dir = Path("/root/e2_1_protocol")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = output_dir / f"E2_1_BLIND_POWER_ANALYSIS_{timestamp}.txt"
    results_file = output_dir / f"E2_1_BLIND_POWER_ANALYSIS_RESULTS_{timestamp}.json"

    with open(report_file, 'w') as f:
        f.write(report)

    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n✅ Power analysis report saved to: {report_file}")
    print(f"✅ Analysis results saved to: {results_file}")

    if results["recommended_n"]:
        print(f"\n🎯 RECOMMENDED SAMPLE SIZE: {results['recommended_n']} tasks")
        print("   Update E2.1_PROTOCOL_FINAL.json before SHA256 calculation.")
    else:
        print("\n⚠️  No suitable sample size found. Reconsider experimental design.")

if __name__ == "__main__":
    main()