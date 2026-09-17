"""E8 recovery matrix v2 spec — FROZEN with four design safeguards (2026-09-17).

Four pre-collection safeguards per advisor review:
1. Diagnosis BEFORE recovery: D(s_i) uses only execution-time visible info,
   never recovery outcome. No circular labeling.
2. Operationalized failure types (Structural ≠ 'decompose succeeded'):
   Evidence   = required operands absent from node input
   Reasoning  = operands present, expression/value wrong
   Structural = single node carries multiple separable dependent steps AND
                simple model switch already failed (NOT defined by decompose success)
   Parse      = output unconsumable by interface/executor
3. Same-starting-point actions: all five actions branch from the SAME failure
   state snapshot (same question, DAG, parent outputs, consumed budget, node input).
   switch_model changes ONLY the model; evidence_retrieval fixes downstream
   reasoning model; local_decompose gets NO gold facts.
4. Recovery-profit matrix, not just recovery rate: every (φ,a) cell records
   R= P(recover|φ,a), ΔC (extra tokens), ΔT (extra time), E = R/ΔC.
   Empirical basis for a* = argmax[R̂(φ,a) − λΔC − μΔT].
"""
SPEC = dict(
    min_n=150, target_n=200,
    actions=['no_recovery', 'retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose'],
    failure_types=dict(
        evidence='required operands absent from node input (operand recall fail)',
        reasoning='operands present, expression or computed value wrong',
        structural='node carries multiple separable steps AND model switch already failed '
                   '(NOT defined by decompose success — no circular labeling)',
        parse='output unconsumable by interface/executor/parser'),
    diagnosis_rule='D(s_i) uses only execution-time visible signals: operand coverage, '
                   'expression legality, node step complexity, parse status. '
                   'NEVER uses recovery outcome.',
    same_start='all actions branch from identical failure snapshot: same question, DAG, '
               'parent outputs, consumed budget, node input',
    action_purity=dict(
        retry_same='same model, same prompt, new sampling',
        switch_model='different model ONLY; same prompt and context',
        evidence_retrieval='relocate table region + keyword-directed row selection; '
                           'downstream reasoning model FIXED; NOT re-calling LLM extraction',
        local_decompose='D1(report alignment)+D2(expression)+tool; NO gold facts injected'),
    metrics_per_cell=['R = P(recover|φ,a)', 'ΔC (extra tokens)', 'ΔT (extra seconds)',
                      'E = R/ΔC (recovery per 1k extra tokens)', 'zero_harm_check'],
    min_per_core_type=dict(evidence=40, reasoning=40),
    statistical_reporting='each cell: n, R, exact binomial CI95; paired action diffs '
                          'with task-cluster bootstrap; E ranked for budget decision layer',
    circular_labeling_guard='if a node is labeled Structural, it must satisfy: multi-step '
                            'complexity AND switch_model failure, determined BEFORE any '
                            'decompose is attempted')
