"""E8 recovery matrix v2 spec — FROZEN with five design safeguards (2026-09-17).

Five pre-collection safeguards per advisor review:
1. Diagnosis BEFORE recovery: D(s_i) uses only execution-time visible info,
   never recovery outcome. No circular labeling — INCLUDING Structural.
2. Structural defined by PRE-RECOVERY structural complexity only:
   multiple sub-goals / multi-step dependency / multiple intermediate
   variables / cross-evidence-block span / high input-source count.
   NOT 'switch_model already failed' (that is a recovery outcome → circular).
   If Structural nodes end up showing decompose > switch, that is a genuine
   experimental finding, not a definition.
3. Same-starting-point actions: all five actions branch from the SAME failure
   state snapshot (same question, DAG, parent outputs, consumed budget, node input).
   switch_model changes ONLY the model; evidence_retrieval fixes downstream
   reasoning model; local_decompose gets NO gold facts.
4. Recovery-profit matrix, not just recovery rate: every (φ,a) cell records
   R= P(recover|φ,a), ΔC (extra tokens), ΔT (extra SERVICE time, uniformly
   measured from action start to result, EXCLUDING model load), E = R/ΔC
   (defined only for ΔC>0 actions; no_recovery is baseline without E).
5. Uniform ΔT: one time metric = additional service latency from recovery
   action start to result obtained. No wall-clock, no startup, no sojourn.
"""
SPEC = dict(
    min_n=150, target_n=200,
    actions=['no_recovery', 'retry_same', 'switch_model', 'evidence_retrieval', 'local_decompose'],
    failure_types=dict(
        evidence='required operands absent from node input (operand recall fail)',
        reasoning='operands present, expression or computed value wrong',
        structural='node exhibits PRE-RECOVERY structural complexity: multiple sub-goals, '
                   'multi-step dependency, multiple intermediate variables, cross-evidence '
                   'span, or high input-source count. NOT defined by switch/decompose outcome.',
        parse='output unconsumable by interface/executor/parser'),
    diagnosis_rule='D(s_i) uses only execution-time visible signals: operand coverage, '
                   'expression legality, PRE-RECOVERY structural complexity metrics, parse '
                   'status. NEVER uses any recovery action outcome.',
    same_start='all actions branch from identical failure snapshot: same question, DAG, '
               'parent outputs, consumed budget, node input',
    action_purity=dict(
        retry_same='same model, same prompt, new sampling',
        switch_model='different model ONLY; same prompt and context',
        evidence_retrieval='relocate table region + keyword-directed row selection; '
                           'downstream reasoning model FIXED; NOT re-calling LLM extraction',
        local_decompose='D1(report alignment)+D2(expression)+tool; NO gold facts injected'),
    metrics_per_cell=['R = P(recover|φ,a)', 'ΔC (extra tokens)',
                      'ΔT (extra SERVICE seconds, action-start to result, no model load)',
                      'E = R/ΔC, only for ΔC>0; no_recovery is baseline without E',
                      'zero_harm_check'],
    min_per_core_type=dict(evidence=40, reasoning=40),
    statistical_reporting='each cell: n, R, exact binomial CI95; paired action diffs '
                          'with task-cluster bootstrap; E ranked for budget decision layer',
    circular_labeling_guard='Structural is labeled from PRE-RECOVERY structural signals '
                            'ONLY (sub-goal count, dependency depth, intermediate-variable '
                            'count, evidence span, input-source count). The finding '
                            '"Structural nodes: decompose > switch" is an EXPERIMENTAL '
                            'RESULT, not a definition.')
