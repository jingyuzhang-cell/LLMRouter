# E2.1 Implementation Plan

## Current Status
- ✅ E2 Stage 1: SEALED as E2-EXPLORATORY-POSITIVE
- ✅ E2.1 Design: COMPLETE and approved
- 🔄 E2.1 Implementation: READY TO START

## Experimental Chain Summary

```
E1.1: FAIL (no passing specialists)
  ↓
E2 Stage 1: EXPLORATORY-POSITIVE
  - N1: Mean heuristic Δ = +0.117
  - N1: Two-repeat stable switch = 43.3%
  - N1: 95% CI = [0.063, 0.165]
  ↓
Hypothesis: Evidence Localization may expose stable model specialization
  ↓
E2.1-A: Objective N1 validation (THIS PHASE)
  - 60 fresh tasks × 3 models × 3 repeats
  - Evidence P/R/F1 scoring
  - C10-compliant metrics (G, S, R, Margin)
  ↓
E2.1-B: End-to-end causal validation (CONDITIONAL)
  - 30-task subset × 3 arms
  - Only change N1 model
  - Measure final quality impact
  ↓
E2.2: Router training (CONDITIONAL)
  - If both E2.1-A and E2.1-B PASS
```

---

## Phase 1: Data Preparation (Week 1)

### 1.1 Task Collection
**Goal**: Assemble 60 diverse financial tasks

**Sources & Targets**:
- FinLongDocQA: 15 tasks
- TAT-QA: 15 tasks
- FinanceBench: 15 tasks
- Long-context financial tasks: 15 tasks

**Selection Criteria** (outcome-blind):
```python
def task_complexity_score(task):
    """
    Calculate complexity based on observable features
    Used for balanced sampling, NOT selection
    """
    return {
        "context_length": len(task["context"]),
        "evidence_span": estimate_evidence_span(task),
        "table_complexity": count_tables(task),
        "cross_page_requirements": check_cross_page(task),
        "cross_section_requirements": check_cross_section(task),
        "numerical_density": count_numerical_entities(task),
        "regulatory_complexity": assess_regulatory_complexity(task)
    }
```

**Deliverable**: `E2_1_TASKS_60.jsonl`
- 60 unique tasks with metadata
- Complexity scores for balance verification
- No model results or annotations

### 1.2 Evidence Annotation Protocol
**Goal**: Create gold N1 evidence for all 60 tasks

**Annotation Schema**:
```json
{
  "task_id": "e2_1_task_001",
  "gold_evidence": {
    "primary_evidence": {
      "document_id": "doc_123",
      "page_id": "p12",
      "paragraph_id": "p12_s3",
      "sentence_ids": ["s12_3_1", "s12_3_2"],
      "table_id": "table4",
      "row_ids": ["r4_7"],
      "column_ids": ["c4_2", "c4_3"]
    },
    "acceptable_evidence_sets": [
      {
        "evidence_items": ["p12_s3", "table4_row7"],
        "explanation": "Equivalent evidence from adjacent paragraph"
      }
    ],
    "evidence_type": "numerical_regulatory",
    "evidence_complexity": "multi_source_cross_reference",
    "annotation_notes": "Primary evidence in table, supplementary in paragraph"
  }
}
```

**Quality Control**:
- Dual-annotation for 10 tasks (16.7% sample)
- Measure Inter-Annotator Agreement (IAA)
- Target: F1 IAA ≥ 0.85
- Disagreement resolution: Third senior annotator

**Deliverable**: `E2_1_N1_GOLD_EVIDENCE.json`
- 60 tasks with complete gold evidence
- IAA metrics for quality-controlled subset
- Annotation guidelines document

### 1.3 Task Partition for E2.1-B
**Goal**: Deterministically select 30 tasks for causal validation

**Selection Method**:
```python
import hashlib

def select_e2_1_b_tasks(task_ids, seed=20260901):
    """
    Deterministic hash-based selection
    Fixed before seeing any model results
    """
    selected = []
    for task_id in sorted(task_ids):
        hash_value = int(hashlib.md5(f"{task_id}_{seed}".encode()).hexdigest(), 16)
        if hash_value % 2 == 0:  # 50% selection probability
            selected.append(task_id)
    return selected[:30]  # Ensure exactly 30 tasks
```

**Deliverable**: `E2_1_TASK_PARTITION.json`
- 30 tasks for E2.1-B (frozen)
- 30 tasks for E2.1-A only
- Selection seed and method documented

---

## Phase 2: E2.1-A Execution (Week 2)

### 2.1 N1 Data Collection
**Goal**: Collect 540 N1 responses (60 tasks × 3 models × 3 repeats)

**Execution Matrix**:
```
Tasks: 60
Models: qwen-plus, glm-5.2, deepseek
Repeats: 3
Total: 540 N1 calls
Estimated Cost: ~$2-3
```

**N1 Prompt Template**:
```python
N1_PROMPT_TEMPLATE = """
You are an evidence localization specialist for financial document analysis.

TASK: {task_question}

CONTEXT: {document_context}

INSTRUCTIONS:
1. Identify the specific evidence needed to answer this question
2. Provide precise locations: page numbers, paragraph IDs, table references
3. Include both text and tabular evidence when relevant
4. Be as specific as possible with evidence coordinates

OUTPUT FORMAT:
evidence_locations: [
  {{
    "type": "paragraph|table|sentence",
    "document_id": "doc_id",
    "page_id": "page_number",
    "paragraph_id": "pX_sY",
    "sentence_ids": ["sX_Y_Z"],
    "table_id": "tableN",
    "row_ids": ["rN_M"],
    "column_ids": ["cN_K"],
    "evidence_text": "relevant excerpt",
    "relevance_score": 0.95
  }}
]
"""
```

**Quality Controls**:
- Retry logic for failed calls (max 3 attempts)
- Timeout handling (30s per call)
- Response validation (check for evidence_locations structure)
- Cost monitoring (stop if > $3.50)

**Deliverable**: `E2_1_A_N1_RESPONSES.jsonl`
- 540 successful N1 responses
- Complete metadata (timestamps, costs, latencies)
- SHA256 checksum for integrity

### 2.2 Evidence Parsing & Quality Scoring
**Goal**: Calculate evidence P/R/F1 for all 540 responses

**Parsing Logic**:
```python
def parse_evidence_locations(model_response):
    """
    Extract structured evidence from model output
    Handle various response formats
    """
    try:
        # Try JSON parsing first
        if "evidence_locations:" in model_response:
            json_part = model_response.split("evidence_locations:")[1].strip()
            evidence = json.loads(json_part)
            return normalize_evidence(evidence)
        else:
            # Fallback to regex extraction
            return extract_evidence_heuristic(model_response)
    except Exception as e:
        return {"error": str(e), "raw_response": model_response}
```

**Quality Scoring**:
```python
def calculate_evidence_quality(predicted_evidence, gold_evidence):
    """
    Calculate precision, recall, F1 against gold annotation
    Support multiple acceptable evidence sets
    """
    if not predicted_evidence or "error" in predicted_evidence:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    # Calculate for each acceptable set, take best
    best_scores = {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    acceptable_sets = gold_evidence.get("acceptable_evidence_sets",
                                      [{"evidence_items": [gold_evidence["primary_evidence"]]}])

    for acceptable_set in acceptable_sets:
        gold_items = normalize_evidence_items(acceptable_set["evidence_items"])
        predicted_items = normalize_evidence_items(predicted_evidence)

        precision = calculate_precision(predicted_items, gold_items)
        recall = calculate_recall(predicted_items, gold_items)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        if f1 > best_scores["f1"]:
            best_scores = {"precision": precision, "recall": recall, "f1": f1}

    return best_scores
```

**Deliverable**: `E2_1_A_EVIDENCE_QUALITY.jsonl`
- 540 evidence quality scores
- Per-response precision, recall, F1
- Parsing success/failure statistics

### 2.3 C10-Compliant Metrics Calculation
**Goal**: Calculate G, S, R, Margin following frozen protocol

**Metrics Implementation**:
```python
def calculate_c10_metrics(evidence_quality_data):
    """
    Calculate C10-compliant metrics for N1 evidence localization
    """
    # Organize data: tasks × models × repeats
    quality_matrix = organize_quality_matrix(evidence_quality_data)

    # Stable Semantic Oracle Gap (G)
    G = calculate_stable_semantic_oracle_gap(quality_matrix)

    # Stable Specialist Opportunity Rate (S)
    S = calculate_stable_specialist_opportunity_rate(quality_matrix)

    # Held-out Top1–Top2 Reversal Rate (R)
    R = calculate_held_out_reversal_rate(quality_matrix)

    # Margin Analysis
    margin_stats = calculate_margin_statistics(quality_matrix)

    return {
        "stable_semantic_oracle_gap": G,
        "stable_specialist_opportunity_rate": S,
        "held_out_reversal_rate": R,
        "margin_statistics": margin_stats
    }
```

**Statistical Validation**:
- Bootstrap CI for all metrics (10,000 samples)
- Per-model performance analysis
- Cross-repeat consistency checks

**Deliverable**: `E2_1_A_METRICS.json`
- Complete C10-compliant metrics
- Statistical confidence intervals
- Per-model breakdown
- Success/failure determination

### 2.4 E2.1-A Gate Decision
**Success Criteria**:
- G_{N1} ≥ 0.03
- S_{N1} ≥ 10%
- MedianMargin_{N1} > 0
- At least one specialist: 95% CI(ΔQ) > 0

**Decision Logic**:
```python
def make_e2_1_a_decision(metrics):
    """
    Make go/no-go decision for E2.1-B
    """
    success = all([
        metrics["stable_semantic_oracle_gap"] >= 0.03,
        metrics["stable_specialist_opportunity_rate"] >= 0.10,
        metrics["margin_statistics"]["median_margin"] > 0,
        any(ci["lower"] > 0 for ci in metrics["model_delta_cis"].values())
    ])

    return {
        "decision": "PROCEED_TO_E2_1_B" if success else "STOP_N1_HYPOTHESIS",
        "metrics": metrics,
        "rationale": generate_decision_rationale(metrics, success)
    }
```

**Deliverable**: `E2_1_A_GATE_DECISION.json`
- Clear PASS/FAIL determination
- Complete metrics supporting decision
- Rationale for decision

---

## Phase 3: E2.1-B Execution (Week 3) - CONDITIONAL

### 3.1 Controlled Decomposition Execution
**Goal**: Execute 3-arm comparison on 30 tasks

**Experimental Arms**:
```python
ARMS = {
    "A": {
        "name": "Qwen+ Baseline",
        "n1_model": "qwen-plus",
        "n2_model": "qwen-plus",
        "n3_model": "qwen-plus",
        "n4_model": "qwen-plus"
    },
    "B": {
        "name": "GLM@N1",
        "n1_model": "glm-5.2",
        "n2_model": "qwen-plus",
        "n3_model": "qwen-plus",
        "n4_model": "qwen-plus"
    },
    "C": {
        "name": "DeepSeek@N1",
        "n1_model": "deepseek",
        "n2_model": "qwen-plus",
        "n3_model": "qwen-plus",
        "n4_model": "qwen-plus"
    }
}
```

**Execution Protocol**:
- 30 tasks × 3 arms = 90 decompositions
- Fixed N2-N4: qwen-plus (established baseline)
- Only N1 varies: tests causal impact
- Estimated cost: ~$1-2

**Deliverable**: `E2_1_B_DECOMPOSITION_RESULTS.jsonl`
- 90 complete decomposition executions
- Per-node responses for all arms
- End-to-end timing and cost data

### 3.2 Final Quality Scoring
**Goal**: Measure impact of N1 specialist selection on final answers

**Scoring Method**:
```python
def score_final_quality(task, final_answer):
    """
    Use existing objective_score for N4 final answers
    """
    return objective_score(task, final_answer)
```

**Causal Analysis**:
```python
def analyze_causal_impact(arm_results):
    """
    Measure if N1 specialist advantage propagates to final quality
    """
    # Calculate ΔQ_final for each comparison
    glm_vs_qwen = []
    deepseek_vs_qwen = []

    for task in tasks:
        qwen_quality = arm_results["A"][task]["final_quality"]
        glm_quality = arm_results["B"][task]["final_quality"]
        deepseek_quality = arm_results["C"][task]["final_quality"]

        glm_vs_qwen.append(glm_quality - qwen_quality)
        deepseek_vs_qwen.append(deepseek_quality - qwen_quality)

    return {
        "glm_vs_qwen": {
            "mean_delta": np.mean(glm_vs_qwen),
            "median_delta": np.median(glm_vs_qwen),
            "ci_95": bootstrap_ci(glm_vs_qwen),
            "positive_rate": sum(d > 0 for d in glm_vs_qwen) / len(glm_vs_qwen)
        },
        "deepseek_vs_qwen": {
            "mean_delta": np.mean(deepseek_vs_qwen),
            "median_delta": np.median(deepseek_vs_qwen),
            "ci_95": bootstrap_ci(deepseek_vs_qwen),
            "positive_rate": sum(d > 0 for d in deepseek_vs_qwen) / len(deepseek_vs_qwen)
        }
    }
```

**Cost-Benefit Analysis**:
```python
def analyze_cost_benefit(arm_results):
    """
    Measure if quality gain justifies additional cost
    """
    return {
        "quality_improvement": calculate_quality_improvement(arm_results),
        "cost_increase": calculate_cost_increase(arm_results),
        "latency_increase": calculate_latency_increase(arm_results),
        "roi_score": calculate_roi(arm_results)
    }
```

**Deliverable**: `E2_1_B_CAUSAL_ANALYSIS.json`
- ΔQ_final statistics for all comparisons
- Cost-benefit analysis
- End-to-end impact assessment

### 3.3 E2.1-B Success Determination
**Success Criteria**:
- Mean ΔQ_final > 0 (statistically significant)
- 95% CI of ΔQ_final does not include 0
- Positive delta rate ≥ 60%
- Cost increase justified by quality gain

**Deliverable**: `E2_1_B_FINAL_DECISION.json`
- Clear causal validation PASS/FAIL
- Complete statistical analysis
- Recommendations for next steps

---

## Phase 4: Integration & Reporting (Week 4)

### 4.1 Mechanism Chain Validation
**Goal**: Validate complete causal chain

**Analysis**:
```python
def validate_mechanism_chain(e2_1_a_results, e2_1_b_results):
    """
    Validate: Evidence F1 → Final Quality
    """
    return {
        "evidence_to_final_correlation": calculate_correlation(
            e2_1_a_results["evidence_f1"],
            e2_1_b_results["final_quality"]
        ),
        "mechanism_strength": assess_mechanism_strength(
            e2_1_a_results, e2_1_b_results
        ),
        "causal_chain_valid": determine_causal_validity(
            e2_1_a_results, e2_1_b_results
        )
    }
```

### 4.2 Final Report Generation
**Comprehensive Report Sections**:
1. Executive Summary
2. Experimental Design
3. E2.1-A Results (Node-level validation)
4. E2.1-B Results (End-to-end validation)
5. Mechanism Chain Analysis
6. Statistical Robustness Checks
7. Cost-Benefit Analysis
8. Limitations & Future Work
9. Conclusions & Recommendations

**Deliverable**: `E2_1_FINAL_REPORT.pdf`
- Publication-ready analysis
- Complete statistical appendix
- Reproducibility package

---

## Risk Management & Contingency Plans

### Risk 1: E2.1-A FAIL
**Probability**: ~30-40%
**Impact**: High - N1 hypothesis rejected
**Mitigation**: Pre-planned alternative decomposition strategies

### Risk 2: E2.1-A PASS, E2.1-B FAIL
**Probability**: ~20-30%
**Impact**: Medium - Specialization exists but lacks system value
**Mitigation**: Investigate other node types or decomposition strategies

### Risk 3: Annotation Quality Issues
**Probability**: ~10-20%
**Impact**: High - Compromises validity
**Mitigation**: Dual-annotation, senior review, iterative refinement

### Risk 4: Cost Overrun
**Probability**: ~5-10%
**Impact**: Low-Medium - Budget constraints
**Mitigation**: Strict cost monitoring, early stopping criteria

---

## Success Metrics & Decision Points

### Primary Success Criteria
**Full Causal Chain Validation**:
- ✅ E2.1-A PASS (objective N1 specialization)
- ✅ E2.1-B PASS (end-to-end value)
- ✅ Mechanism chain validated
- ✅ Cost-benefit justified

### Secondary Success Criteria
**Partial Validation**:
- ⚠️ E2.1-A PASS, E2.1-B MIXED
- ⚠️ Strong signal but limited generalizability
- ⚠️ High cost but significant quality gain

### Failure Criteria
**Clear Negative Results**:
- ❌ E2.1-A FAIL (no objective specialization)
- ❌ E2.1-A PASS, E2.1-B FAIL (no system value)
- ❌ Insurmountable methodological issues

---

## Next Immediate Actions

1. **Freeze E2.1 Protocol**: Get final approval on experimental design
2. **Begin Task Collection**: Start assembling 60 diverse financial tasks
3. **Develop Annotation Tools**: Create evidence annotation interface
4. **Setup Infrastructure**: Prepare execution environment and monitoring
5. **Establish Quality Control**: Define annotation QA procedures

**The 43.3% exploratory signal gave us a promising clue. E2.1 will determine if it's a real scientific discovery.**