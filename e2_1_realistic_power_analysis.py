#!/usr/bin/env python3
"""
E2.1 Realistic Power Analysis - Based on E2 exploratory signal
More realistic parameters following +0.117 heuristic signal
"""

import numpy as np
from scipy import stats
import json
from pathlib import Path
from datetime import datetime

def realistic_power_analysis():
    """
    Power analysis with more realistic parameters based on E2 exploratory results
    """

    print("=" * 80)
    print("E2.1 REALISTIC POWER ANALYSIS")
    print("=" * 80)
    print("")
    print("CONTEXT FROM E2 EXPLORATORY RESULTS:")
    print("  - N1 Evidence Localization: Mean heuristic Δ = +0.117")
    print("  - This suggests actual effect size may be larger than 0.03 minimum")
    print("  - Objective Evidence F1 may show different magnitude but directional signal")
    print("")

    # More realistic scenarios
    scenarios = [
        {
            "name": "Conservative",
            "effect_size": 0.03,
            "sd_estimate": 0.18,  # More realistic than 0.20
            "target_power": 0.80
        },
        {
            "name": "Moderate",
            "effect_size": 0.04,
            "sd_estimate": 0.18,
            "target_power": 0.75
        },
        {
            "name": "Optimistic",
            "effect_size": 0.05,
            "sd_estimate": 0.15,  # If signal is strong
            "target_power": 0.70
        }
    ]

    print("REALISTIC SCENARIO ANALYSIS:")
    print("")

    for scenario in scenarios:
        print(f"Scenario: {scenario['name']}")
        print(f"  Effect size: {scenario['effect_size']}, SD: {scenario['sd_estimate']}, Target power: {scenario['target_power']}")

        # Find sample size for this scenario
        cohens_d = scenario['effect_size'] / scenario['sd_estimate']

        recommended_n = None
        for n in range(30, 151, 5):
            df = n - 1
            ncp = np.sqrt(n) * cohens_d
            t_critical = stats.t.ppf(1 - 0.025, df)
            power = 1 - stats.nct.cdf(t_critical, df, ncp) + stats.nct.cdf(-t_critical, df, ncp)

            # Also check precision
            se_mean = scenario['sd_estimate'] / np.sqrt(n)
            ci_lower = scenario['effect_size'] - 1.96 * se_mean
            precision_ok = ci_lower > 0

            if power >= scenario['target_power'] * 0.95 and precision_ok:  # 95% of target
                recommended_n = n
                actual_power = power
                ci_width = 1.96 * 2 * se_mean
                break

        if recommended_n:
            print(f"  ✅ Recommended N = {recommended_n}")
            print(f"     Actual power: {actual_power:.1%}, CI width: {ci_width:.4f}")
        else:
            print(f"  ❌ No suitable N found up to 150")
        print("")

    # Specific recommendation for E2.1
    print("E2.1 SPECIFIC RECOMMENDATION:")
    print("")

    # Given E2 exploratory signal, let's assume:
    # - Objective effect size might be 0.04-0.06 (smaller than +0.117 heuristic but still meaningful)
    # - SD around 0.15-0.18 (evidence F1 differences)
    # - Target power: 70-75% (reasonable for confirmatory follow-up)

    target_effect = 0.04
    target_sd = 0.16
    target_power = 0.70

    cohens_d = target_effect / target_sd

    print(f"Assumptions for E2.1:")
    print(f"  - Target effect size: {target_effect} (based on exploratory signal)")
    print(f"  - Estimated SD: {target_sd} (evidence F1 differences)")
    print(f"  - Target power: {target_power} (reasonable for confirmatory study)")
    print("")

    # Find optimal N
    best_n = None
    best_power = 0
    analysis_results = []

    for n in range(40, 121, 5):
        df = n - 1
        ncp = np.sqrt(n) * cohens_d
        t_critical = stats.t.ppf(1 - 0.025, df)
        power = 1 - stats.nct.cdf(t_critical, df, ncp) + stats.nct.cdf(-t_critical, df, ncp)

        se_mean = target_sd / np.sqrt(n)
        ci_lower = target_effect - 1.96 * se_mean
        ci_width = 1.96 * 2 * se_mean
        precision_ok = ci_lower > 0

        analysis_results.append({
            "n": n,
            "power": power,
            "ci_width": ci_width,
            "ci_lower": ci_lower,
            "precision_ok": precision_ok
        })

        if power >= target_power and precision_ok and best_n is None:
            best_n = n
            best_power = power

    print(f"Sample Size Analysis:")
    print(f"{'N':<6} {'Power':<10} {'CI Width':<12} {'CI Lower':<12} {'Status':<10}")
    print("-" * 60)

    for result in analysis_results[:10]:  # Show first 10
        status = "✅ GOOD" if (result['power'] >= target_power and result['precision_ok']) else "❌ LOW"
        print(f"{result['n']:<6} {result['power']:.3f}     {result['ci_width']:.4f}      {result['ci_lower']:.4f}      {status:<10}")

    print("")

    if best_n:
        final_result = next(r for r in analysis_results if r['n'] == best_n)
        print(f"🎯 FINAL RECOMMENDATION: N = {best_n} TASKS")
        print("")
        print("Justification:")
        print(f"  - Achieves {best_power:.1%} power (target: {target_power:.0%})")
        print(f"  - 95% CI width: {final_result['ci_width']:.4f}")
        print(f"  - CI lower bound for effect={target_effect}: {final_result['ci_lower']:.4f} (> 0)")
        print(f"  - Reasonable balance of statistical rigor and cost")
        print("")
        print("Cost Implications:")
        e2_1_a_calls = best_n * 3 * 3
        e2_1_a_cost = e2_1_a_calls * 0.005
        print(f"  - E2.1-A: {e2_1_a_calls} calls (~${e2_1_a_cost:.1f})")
        print(f"  - E2.1-B: 1350 calls (~$4-6)")
        print(f"  - Total estimated: ~${e2_1_a_cost + 5:.1f}")
        print("")

        # Updated protocol parameters
        print("UPDATED E2.1 PROTOCOL PARAMETERS:")
        print(f"  - E2.1-A Tasks: {best_n} (finalized)")
        print(f"  - Minimum effect size: {target_effect}")
        print(f"  - Target power: {target_power}")
        print(f"  - SD estimate: {target_sd}")
        print("")

        return {
            "recommended_n": best_n,
            "expected_power": best_power,
            "effect_size": target_effect,
            "sd_estimate": target_sd,
            "target_power": target_power,
            "cost_estimate": {
                "e2_1_a_calls": e2_1_a_calls,
                "e2_1_a_cost": e2_1_a_cost,
                "total_cost_low": e2_1_a_cost + 5,
                "total_cost_high": e2_1_a_cost + 7
            }
        }
    else:
        print("❌ RECONSIDER EXPERIMENTAL DESIGN")
        print("   Consider increasing minimum effect size or accepting lower power")
        return None

def main():
    """Run realistic power analysis and generate final protocol parameters"""

    print("Running E2.1 Realistic Power Analysis...")
    print("Based on E2 exploratory signal: N1 Mean heuristic Δ = +0.117")
    print()

    result = realistic_power_analysis()

    if result:
        # Save final protocol parameters
        output_dir = Path("/root/e2_1_protocol")
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        params_file = output_dir / f"E2_1_FINAL_PARAMETERS_{timestamp}.json"

        final_parameters = {
            "e2_1_a_tasks": result["recommended_n"],
            "minimum_effect_size": result["effect_size"],
            "target_power": result["target_power"],
            "sd_estimate": result["sd_estimate"],
            "expected_power": result["expected_power"],
            "cost_estimate": result["cost_estimate"],
            "analysis_basis": "E2 exploratory signal (N1 Mean heuristic Δ = +0.117)",
            "statistical_assumptions": "More realistic SD estimate based on evidence F1 scale"
        }

        with open(params_file, 'w') as f:
            json.dump(final_parameters, f, indent=2)

        print(f"✅ Final parameters saved to: {params_file}")
        print("")
        print("NEXT STEP: Update E2.1_PROTOCOL_FINAL.json with N = {} tasks".format(result["recommended_n"]))
        print("         Then calculate SHA256 and finalize protocol.")
    else:
        print("⚠️  Could not determine suitable parameters. Reconsider experimental design.")

if __name__ == "__main__":
    main()