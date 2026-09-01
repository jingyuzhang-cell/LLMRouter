# E2 Experimental Status & Next Actions

## Current Experimental Status

### ✅ COMPLETED PHASES

**E1.1 Anchor-Specialist Audit**
- **Status**: FAIL
- **Finding**: No passing specialists (passing_specialists: [])
- **Note**: GLM and DeepSeek showed ~9.8% stable switch with ~3.5pp gain, but didn't pass enrichment gate

**E2 Stage 1 Exploratory Decomposition Pilot**
- **Status**: E2-EXPLORATORY-POSITIVE (SEALED)
- **Data**: 480/480 unique outcomes completed
- **Key Finding**: N1 Evidence Localization showed strong exploratory signal
  - Mean heuristic Δ(GLM-Qwen+): +0.117
  - Two-repeat stable switch rate: 43.3%
  - 95% Bootstrap CI: [0.063, 0.165]
- **Limitations**: Heuristic scoring, 2-model setup, 2-repeat structure
- **Conclusion**: Evidence that decomposition MAY expose node-level specialization

### 🔄 CURRENT PHASE

**E2.1 Confirmatory Node-Specialization Experiment**
- **Status**: READY TO START
- **Design**: COMPLETE and approved
- **Implementation Plan**: COMPLETE
- **Goal**: Transform heuristic exploratory evidence into objective confirmatory evidence

---

## Experimental Chain Visualization

```
┌─────────────────────────────────────────────────────────────┐
│                    EXPERIMENTAL CHAIN                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  E1.1: FAIL (no passing specialists)                        │
│    ↓                                                        │
│  E2 Stage 1: EXPLORATORY-POSITIVE ✅ SEALED                 │
│    • N1: Mean heuristic Δ = +0.117                          │
│    • N1: Two-repeat stable switch = 43.3%                   │
│    • N1: 95% CI = [0.063, 0.165]                           │
│    ↓                                                        │
│  Hypothesis: Evidence Localization exposes specialization   │
│    ↓                                                        │
│  E2.1-A: Objective N1 Validation 🔄 STARTING                │
│    • 60 fresh tasks × 3 models × 3 repeats                  │
│    • Evidence P/R/F1 scoring                                │
│    • C10-compliant metrics (G, S, R, Margin)                │
│    ↓                                                        │
│  [GATE] E2.1-A PASS? ──NO──→ STOP N1 hypothesis             │
│    ↓ YES                                                   │
│  E2.1-B: End-to-end Causal Validation                      │
│    • 30-task subset × 3 arms                                │
│    • Only change N1 model                                   │
│    • Measure final quality impact                           │
│    ↓                                                        │
│  [GATE] E2.1-B PASS? ──NO──→ Specialist exists, no value    │
│    ↓ YES                                                   │
│  E2.2: Router Training                                      │
│    • Learnable routing opportunity                          │
│    • Dynamic routing system                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Immediate Next Actions

### 🔥 PRIORITY 1: Freeze E2.1 Protocol (TODAY)
- [ ] Final review and approval of E2.1 design
- [ ] Confirm experimental parameters
- [ ] Lock down success criteria
- [ ] Archive E2.1 protocol with SHA256

### 🔥 PRIORITY 2: Begin Data Preparation (THIS WEEK)
- [ ] Start collecting 60 diverse financial tasks
- [ ] Develop evidence annotation interface
- [ ] Create annotation guidelines document
- [ ] Setup quality control procedures

### 🔥 PRIORITY 3: Infrastructure Setup (THIS WEEK)
- [ ] Prepare execution environment
- [ ] Setup cost monitoring and alerts
- [ ] Create data management pipeline
- [ ] Establish backup and version control

---

## Key Decisions Made

### 1. ✅ Current 30 Tasks: PERMANENTLY SEALED
- **Decision**: E2 Stage 1 tasks will NOT be used for E2.1
- **Reasoning**: Avoid outcome-selection bias
- **Status**: Archived as E2-EXPLORATORY-POSITIVE evidence

### 2. ✅ E2.1 Uses Fresh 60 Tasks
- **Decision**: New task set from diverse sources
- **Sources**: FinLongDocQA, TAT-QA, FinanceBench, long-context tasks
- **Selection**: Outcome-blind based on observable complexity

### 3. ✅ E2.1 Two-Layer Validation Framework
- **Layer 1 (E2.1-A)**: Node-level specialization validation
- **Layer 2 (E2.1-B)**: End-to-end causal validation
- **Rationale**: Prove both existence AND system value

### 4. ✅ Objective Evidence Scoring
- **Decision**: Replace heuristic scoring with evidence P/R/F1
- **Method**: Gold evidence annotation with acceptable alternatives
- **Quality**: Dual-annotation, IAA ≥ 0.85 target

### 5. ✅ Strict STOP Conditions
- **E2.1-A FAIL**: Stop N1 hypothesis, no post-hoc adjustments
- **E2.1-B FAIL**: Specialist exists but lacks system value
- **No threshold tuning**: Success criteria fixed before experiment

---

## Success Probabilities & Impact

### Best Case: Full Causal Chain Validation (40-50%)
- **Impact**: Establishes first complete decomposition → routing causal chain
- **Paper Value**: High - novel methodological + empirical contribution
- **Next Steps**: E2.2 router training, dynamic routing system

### Medium Case: Partial Validation (30-40%)
- **Impact**: Specialization exists but limited generalizability
- **Paper Value**: Medium - still valuable scientific contribution
- **Next Steps**: Investigate alternative decomposition strategies

### Worst Case: Complete Failure (10-20%)
- **Impact**: Exploratory signal was heuristic-driven
- **Paper Value**: Low - but negative result is scientifically valuable
- **Next Steps**: Reconsider fundamental approach, explore alternatives

---

## Timeline Summary

```
WEEK 1: Data Preparation
├─ Task collection (60 diverse financial tasks)
├─ Evidence annotation (gold N1 evidence)
├─ Quality control (dual-annotation, IAA)
└─ Task partition (30 for E2.1-B)

WEEK 2: E2.1-A Execution
├─ N1 data collection (540 responses)
├─ Evidence parsing & quality scoring
├─ C10 metrics calculation
└─ GO/NO-GO decision

WEEK 3: E2.1-B Execution (CONDITIONAL)
├─ Controlled decomposition (90 executions)
├─ Final quality scoring
├─ Causal impact analysis
└─ End-to-end validation

WEEK 4: Integration & Reporting
├─ Mechanism chain validation
├─ Cost-benefit analysis
├─ Final report generation
└─ Next steps planning
```

---

## Resource Requirements

### Financial
- **E2.1-A**: ~$2-3 (540 N1 calls)
- **E2.1-B**: ~$1-2 (90 decompositions)
- **Annotation**: 2-3 person-weeks
- **Total**: High value for confirmatory validation

### Technical
- **Compute**: Standard API access, no special hardware
- **Storage**: ~1-2GB for raw data + results
- **Tools**: Python, existing scoring infrastructure

### Human
- **Annotation**: 2-3 annotators for evidence labeling
- **Engineering**: 1 person for execution and analysis
- **Oversight**: 1 senior researcher for quality control

---

## Risk Management

### High Impact Risks
1. **E2.1-A FAIL** (30-40% probability)
   - **Mitigation**: Pre-planned alternative strategies

2. **Annotation Quality Issues** (10-20% probability)
   - **Mitigation**: Dual-annotation, senior review

### Medium Impact Risks
3. **E2.1-A PASS, E2.1-B FAIL** (20-30% probability)
   - **Mitigation**: Investigate other node types

4. **Cost Overrun** (5-10% probability)
   - **Mitigation**: Strict monitoring, early stopping

---

## Critical Success Factors

### Methodological Rigor
- ✅ Objective evidence scoring (not heuristic)
- ✅ Proper experimental controls (E2.1-B design)
- ✅ Statistical validation (bootstrap CI, repeat consistency)
- ✅ No post-hoc adjustments (frozen success criteria)

### Scientific Integrity
- ✅ Outcome-blind task selection
- ✅ Pre-registered analysis plan
- ✅ Clear STOP conditions
- ✅ Transparent reporting of limitations

### Practical Value
- ✅ End-to-end causal validation
- ✅ Cost-benefit analysis
- ✅ Router feasibility assessment
- ✅ Real-world applicability

---

## The Core Question

**After 4 weeks, we will answer:**

> Does decomposition expose stable and exploitable model specialization that provides end-to-end value?

**Current Evidence**: Strong exploratory signal (43.3% stable switch, +0.117 mean Δ)

**Next Validation**: Objective evidence F1 + end-to-end causal impact

**Final Answer**: Will determine if this is a real scientific discovery or an artifact of heuristic scoring.

---

## Conclusion

**The 43.3% exploratory signal was just the beginning. E2.1 will determine if we've discovered something fundamental about how decomposition exposes model specialization, or if we need to reconsider our approach entirely.**

**This is the most important experimental phase in the project so far. The results will determine the entire future direction.**

**Status: READY TO EXECUTE 🚀**