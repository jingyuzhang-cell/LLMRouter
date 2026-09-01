# E2.1 Confirmatory Node-Specialization Experiment Design

## Research Question
**Does decomposition expose stable and exploitable model specialization that provides end-to-end value?**

## Two-Layer Validation Framework

### Layer 1: E2.1-A - Node-level Specialization Validation
**Question**: Does stable model specialization truly exist in N1 Evidence Localization?

**Core Metrics**: Evidence P/R/F1, G, S, R, Margin (C10-compliant)

### Layer 2: E2.1-B - End-to-end Causal Validation
**Question**: Does N1 specialist selection actually improve final answers?

**Core Metrics**: Final semantic quality, ΔQ, CI, cost/latency

---

## E2.1-A: N1 Evidence Localization Validation

### Data Specification

#### 1. Fresh Task Set
- **Size**: 60 complex financial tasks
- **Sources**: Diverse financial QA datasets
  - FinLongDocQA
  - TAT-QA
  - FinanceBench / real financial report QA
  - Long-context financial tasks
- **Selection Criteria** (outcome-blind):
  - Context length distribution
  - Evidence span across documents
  - Table/text structure complexity
  - Cross-page evidence requirements
  - Cross-section evidence requirements

#### 2. N1 Gold Evidence Annotation
Each task requires comprehensive evidence annotation:

```json
{
  "task_id": "e2_1_task_001",
  "gold_document_id": "doc_123",
  "gold_evidence": {
    "primary_evidence": {
      "page_id": "p12",
      "paragraph_id": "p12_s3",
      "sentence_ids": ["s12_3_1", "s12_3_2"],
      "table_id": "table4",
      "row_ids": ["r4_7"],
      "column_ids": ["c4_2", "c4_3"]
    },
    "acceptable_evidence_sets": [
      ["p12_s3", "table4_row7"],
      ["p13_s1", "table4_row7"]
    ],
    "evidence_type": "numerical_regulatory",
    "evidence_complexity": "multi_source_cross_reference"
  }
}
```

### Model Setup
**Candidates**: qwen-plus + glm-5.2 + deepseek

**Repeats**: 3 (540 total N1 responses)

**Cost**: ~$2-3 (fully justified for confirmatory validation)

### Metrics Specification

#### 1. Evidence Quality Metrics
```python
def evidence_f1(predicted_evidence, gold_evidence):
    """
    Calculate evidence-level F1 using gold annotation
    Supports multiple acceptable evidence sets
    """
    precision = calculate_evidence_precision(predicted_evidence, gold_evidence)
    recall = calculate_evidence_recall(predicted_evidence, gold_evidence)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    return f1

def evidence_precision(predicted, gold):
    """How much of predicted evidence is actually correct"""
    correct_predictions = count_correct_evidence_items(predicted, gold)
    total_predictions = count_evidence_items(predicted)
    return correct_predictions / total_predictions if total_predictions > 0 else 0

def evidence_recall(predicted, gold):
    """How much of gold evidence was actually found"""
    correct_predictions = count_correct_evidence_items(predicted, gold)
    total_gold = count_gold_evidence_items(gold)
    return correct_predictions / total_gold if total_gold > 0 else 0
```

#### 2. C10-Compliant Metrics

**Stable Semantic Oracle Gap (G)**
```
Q_{i,m} = EvidenceF1(task_i, model_m)
G_{N1} = Q^{stable-oracle}_{N1} - Q^{best-single}_{N1}
```

**Stable Specialist Opportunity Rate (S)**
```
S_{N1} = P(non-global-best model stably wins across repeats)
```

**Held-out Top1–Top2 Reversal Rate (R)**
```
Use 2 repeats to determine Top1, Top2
Use 3rd held-out repeat to check reversal
R_{N1} = P(Top1 gets surpassed by Top2)
```

**Margin Analysis**
```
Margin_i = Q_{i,(1)} - Q_{i,(2)}
Report: Mean Margin, Median Margin, Tie Rate, Margin/Noise SNR
```

### E2.1-A Success Gate
To serve as formal specialization evidence:
- G_{N1} ≥ 0.03
- S_{N1} ≥ 10%
- MedianMargin_{N1} > 0
- At least one specialist: 95% CI(ΔQ) > 0

---

## E2.1-B: End-to-end Causal Validation

### Experimental Design
**Controlled Variable Experiment**: Only change N1 model, keep N2-N4 fixed

#### 3 Arms Comparison
**Arm A**: Qwen+ → N1, Qwen+ → N2, Qwen+ → N3, Qwen+ → N4
**Arm B**: GLM → N1, Qwen+ → N2, Qwen+ → N3, Qwen+ → N4
**Arm C**: DeepSeek → N1, Qwen+ → N2, Qwen+ → N3, Qwen+ → N4

### Task Selection
- **Size**: 30 tasks (pre-hash frozen from 60, not outcome-selected)
- **Selection**: Random but deterministic hash-based selection
- **No cherry-picking**: Selection done BEFORE seeing model results

### Causal Metrics
```python
def calculate_end_to_end_delta(arm_a_quality, arm_b_quality):
    """
    ΔQ_final = Q_final(GLM@N1) - Q_final(Qwen+@N1)
    Measures if N1 specialist advantage propagates to final answer
    """
    delta = arm_b_quality - arm_a_quality
    return delta

def causal_validation_statistics(arm_qualities):
    """
    Statistical analysis of causal effect
    """
    deltas = []
    for task in tasks:
        delta = calculate_end_to_end_delta(
            arm_qualities['A'][task],
            arm_qualities['B'][task]
        )
        deltas.append(delta)

    return {
        "mean_delta": np.mean(deltas),
        "median_delta": np.median(deltas),
        "delta_ci_95": bootstrap_ci(deltas),
        "positive_delta_rate": sum(d > 0 for d in deltas) / len(deltas)
    }
```

### E2.1-B Success Criteria
- Mean ΔQ_final > 0 (statistically significant)
- 95% CI of ΔQ_final does not include 0
- Positive delta rate ≥ 60%
- Cost increase justified by quality gain

---

## Implementation Protocol

### Phase 1: Data Preparation (Week 1)
1. **Task Collection**: Gather 60 diverse financial tasks
2. **Evidence Annotation**: Create comprehensive N1 gold evidence
3. **Quality Control**: Dual-annotation for subset, measure IAA
4. **Task Hash Partition**: Deterministically split 60 → 30 (E2.1-B)

### Phase 2: E2.1-A Execution (Week 2)
1. **N1 Data Collection**: 60 tasks × 3 models × 3 repeats = 540 responses
2. **Evidence Extraction**: Parse model outputs for evidence
3. **Quality Scoring**: Calculate evidence P/R/F1 for all responses
4. **Metrics Calculation**: Compute G, S, R, Margin following C10 protocol

### Phase 3: Gate Decision (End Week 2)
**IF E2.1-A PASS**:
- Proceed to E2.1-B
- Else: STOP N1 hypothesis, conclude exploratory signal was heuristic-driven

### Phase 4: E2.1-B Execution (Week 3)
1. **Decomposition Execution**: Run 3 arms on 30 tasks
2. **Final Quality Scoring**: Objective scoring of N4 outputs
3. **Causal Analysis**: Calculate ΔQ_final and statistics
4. **Cost Analysis**: Measure end-to-end cost/latency impact

### Phase 5: Integration Analysis (Week 4)
1. **Mechanism Chain Validation**: Evidence F1 → Final Quality
2. **Cost-Benefit Analysis**: Quality gain vs computational cost
3. **Router Feasibility**: Assess if signal is learnable

---

## Experimental Discipline

### STOP Conditions
1. **E2.1-A FAIL** (G < 0.02 OR S < 10% OR MedianMargin = 0):
   - Conclude: Exploratory signal was heuristic-scoring-driven
   - Action: STOP N1 hypothesis, do not tune scorer or threshold

2. **E2.1-B FAIL** (ΔQ_final ≤ 0 OR CI includes 0):
   - Conclude: Specialization exists but lacks system value
   - Action: Consider alternative decomposition strategies

### NO Post-Hoc Adjustments
- Do not change task selection based on results
- Do not adjust evidence annotation after seeing model outputs
- Do not modify success thresholds post-experiment
- Do not extend sample size to "fix" borderline results

### Data Management
- Current 30 tasks: PERMANENTLY SEALED as E2-EXPLORATORY-POSITIVE
- New 60 tasks: Fresh set, no contamination from exploratory results
- All raw data + intermediate results: Archived with SHA256 checksums

---

## Expected Outcomes & Impact

### Best Case: Full Causal Chain Validation
```
Whole-query signal weak (G_w = 0.00961, S_w = 8.12%)
    ↓
Decomposition exposes node-level specialization
    ↓
E2.1-A: Objective N1 evidence F1 shows stable specialization
    ↓
E2.1-B: N1 specialist selection improves final answers
    ↓
E2.2: Learnable routing opportunity confirmed
    ↓
Dynamic routing provides end-to-end Q/C/T/R gains
```

### Scientific Contribution
This would establish the first complete causal chain:
**Decomposition → Node Specialization → Learnable Routing → End-to-end Gain**

### Paper Value
- **Methodological**: Rigorous two-layer validation framework
- **Empirical**: First objective evidence of decomposition-exposed specialization
- **Practical**: Demonstrates system value of node-level routing
- **Theoretical**: Explains why whole-query routing fails

---

## Timeline & Resources

### Timeline: 4 Weeks
- Week 1: Data preparation & annotation
- Week 2: E2.1-A execution & analysis
- Week 3: E2.1-B execution (conditional on PASS)
- Week 4: Integration analysis & reporting

### Estimated Cost
- E2.1-A: ~$2-3 (540 N1 calls)
- E2.1-B: ~$1-2 (90 decompositions × 3 arms)
- Annotation: 2-3 person-weeks
- **Total**: High value for confirmatory validation

### Success Probability
- Based on E2 exploratory signal: ~60-70%
- Even if fails: Negative result is scientifically valuable

---

## Next Steps

1. **Immediate**: Begin E2.1 protocol freezing
2. **Week 1**: Start data collection & evidence annotation
3. **Week 2**: Execute E2.1-A, make go/no-go decision
4. **Conditional**: Execute E2.1-B based on E2.1-A results

**The 43.3% exploratory signal was just the clue. E2.1 will determine if it's a real discovery.**