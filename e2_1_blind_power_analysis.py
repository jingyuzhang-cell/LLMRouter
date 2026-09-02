#!/usr/bin/env python3
"""Outcome-blind sample-size calculation for E2.1-A.

Uses planning constants only; never opens E2/E2.1 task, response, score, or
outcome files.
"""

import json
from pathlib import Path
from scipy import stats

ALPHA = 0.05
TARGET_POWER = 0.80
MIN_RELEVANT_GAP = 0.03
PLANNING_SD = 0.20
SEARCH_MAX_N = 5000
ROUNDING_MULTIPLE = 10
OUTPUT_DIR = Path(__file__).resolve().parent / "e2_1_protocol"


def operating_characteristics(n: int, sd: float = PLANNING_SD) -> dict:
    """Two-sided paired-t planning approximation for a task-level gap."""
    df = n - 1
    standardized_effect = MIN_RELEVANT_GAP / sd
    critical_t = stats.t.ppf(1 - ALPHA / 2, df)
    noncentrality = n**0.5 * standardized_effect
    power = (1 - stats.nct.cdf(critical_t, df, noncentrality)
             + stats.nct.cdf(-critical_t, df, noncentrality))
    se = sd / n**0.5
    return {
        "n": n,
        "planning_sd": sd,
        "standardized_effect": float(standardized_effect),
        "power": float(power),
        "expected_ci_lower_at_gap_0_03": float(MIN_RELEVANT_GAP - critical_t * se),
        "expected_ci_width_95": float(2 * critical_t * se),
        "meets_power": bool(power >= TARGET_POWER),
        "expected_ci_lower_positive": bool(MIN_RELEVANT_GAP - critical_t * se > 0),
    }


def minimum_n(sd: float = PLANNING_SD) -> int:
    for n in range(2, SEARCH_MAX_N + 1):
        oc = operating_characteristics(n, sd)
        if oc["meets_power"] and oc["expected_ci_lower_positive"]:
            return n
    raise RuntimeError(f"No adequate N found through {SEARCH_MAX_N}")


def round_up(n: int, multiple: int) -> int:
    return ((n + multiple - 1) // multiple) * multiple


def build_result() -> dict:
    exact_n = minimum_n()
    final_n = round_up(exact_n, ROUNDING_MULTIPLE)
    sensitivity = {}
    for sd in (0.15, 0.16, 0.18, 0.20, 0.22, 0.25):
        n = minimum_n(sd)
        sensitivity[f"{sd:.2f}"] = {
            "minimum_n": n,
            "operating_characteristics": operating_characteristics(n, sd),
        }
    return {
        "analysis": "E2.1-A outcome-blind power/precision analysis",
        "status": "SAMPLE_SIZE_DETERMINED_PROTOCOL_NOT_YET_SHA256_FROZEN",
        "outcome_blindness": {
            "uses_e2_outcomes": False,
            "uses_e2_1_outcomes": False,
            "inputs": "Planning constants only; script performs no data-file reads.",
        },
        "estimand_planning_approximation": (
            "Task-level paired contribution to Stable Semantic Oracle Gap; "
            "two-sided noncentral-t approximation. Confirmatory CI remains the "
            "pre-specified task-level paired bootstrap."
        ),
        "fixed_inputs": {
            "minimum_relevant_gap": MIN_RELEVANT_GAP,
            "alpha_two_sided": ALPHA,
            "target_power": TARGET_POWER,
            "planning_sd_of_paired_task_differences": PLANNING_SD,
            "planning_sd_basis": (
                "Pre-outcome conservative design assumption for bounded Evidence-F1 "
                "paired task differences; not estimated from the sealed E2 30 tasks."
            ),
        },
        "decision": {
            "exact_minimum_n": exact_n,
            "rounding_rule": f"Round upward to the next multiple of {ROUNDING_MULTIPLE}",
            "final_e2_1_a_n": final_n,
            "operating_characteristics_at_final_n": operating_characteristics(final_n),
            "e2_1_a_planned_calls": final_n * 3 * 3,
        },
        "sensitivity_by_planning_sd": sensitivity,
        "important_interpretation": (
            "CI lower > 0 is an observed-data PASS condition, not guaranteed by sample "
            "size. The expected lower bound is evaluated at a true gap of 0.03."
        ),
        "next_step": (
            "Insert N=360 and all final A/B rules into the protocol, freeze it, then "
            "calculate a new SHA256 before annotation or model calls."
        ),
    }


def render_report(result: dict) -> str:
    d = result["decision"]
    oc = d["operating_characteristics_at_final_n"]
    lines = [
        "E2.1-A OUTCOME-BLIND POWER/PRECISION DECISION", "",
        "No E2 or E2.1 outcomes were used. The script reads no data files.", "",
        "Fixed planning inputs",
        f"- Minimum relevant gap: {MIN_RELEVANT_GAP:.3f}",
        f"- Two-sided alpha: {ALPHA:.2f}",
        f"- Target power: {TARGET_POWER:.0%}",
        f"- Planning SD of paired task differences: {PLANNING_SD:.2f}", "",
        "Decision",
        f"- Exact minimum N: {d['exact_minimum_n']}",
        f"- Rounding rule: {d['rounding_rule']}",
        f"- FINAL PLANNED E2.1-A N: {d['final_e2_1_a_n']}",
        f"- Power at N=360: {oc['power']:.6f}",
        f"- Expected 95% CI lower bound at true gap 0.03: {oc['expected_ci_lower_at_gap_0_03']:.6f}",
        f"- Expected 95% CI width: {oc['expected_ci_width_95']:.6f}",
        f"- E2.1-A planned calls: {d['e2_1_a_planned_calls']} (= 360 x 3 models x 3 repeats)", "",
        "Sensitivity: minimum N by assumed paired-difference SD",
    ]
    for sd, item in result["sensitivity_by_planning_sd"].items():
        lines.append(f"- SD={sd}: N={item['minimum_n']}")
    lines += ["", "The observed-data gate remains G_N1 >= 0.03 AND bootstrap 95% CI lower > 0.",
              "This artifact is a sample-size decision, not the final protocol SHA256."]
    return "\n".join(lines) + "\n"


def main() -> None:
    result = build_result()
    OUTPUT_DIR.mkdir(exist_ok=True)
    json_path = OUTPUT_DIR / "E2_1_BLIND_SAMPLE_SIZE_DECISION.json"
    text_path = OUTPUT_DIR / "E2_1_BLIND_SAMPLE_SIZE_DECISION.txt"
    json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    text_path.write_text(render_report(result), encoding="utf-8")
    print(render_report(result), end="")
    print(f"Wrote {json_path}")
    print(f"Wrote {text_path}")


if __name__ == "__main__":
    main()
