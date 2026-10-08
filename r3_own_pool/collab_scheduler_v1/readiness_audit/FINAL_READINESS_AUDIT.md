# Final Readiness Audit (zero LLM calls)

Date: 2026-10-08 11:29

## E3_p1b_direct
- ✅ e1_static_no_patches: True
- ✅ e1_static_no_extra_calls: True
- ✅ e1_reroute_no_patches: True
- ✅ e1_dynpatch_completes: True
- ✅ e2_static_no_patches: True
- ✅ e2_static_no_extra_calls: True
- ✅ e2_reroute_no_patches: True
- ✅ e2_dynpatch_completes: True
- ✅ r_static_no_patches: True
- ✅ r_static_no_extra_calls: True
- ✅ r_reroute_has_r_esc: True
- ✅ r_reroute_no_patches: True
- ✅ r_dynpatch_has_split: True
- ✅ r_dynpatch_executed_r1r2: True
- ✅ v_static_no_patches: True
- ✅ v_static_no_extra_calls: True
- ✅ v_reroute_no_patches: True
- ✅ v_dynpatch_completes: True
- ✅ nofault_static_no_patches: True
- ✅ nofault_static_completed: True
- ✅ nofault_reroute_no_patches: True
- ✅ nofault_reroute_completed: True
- ✅ nofault_dynpatch_no_patches: True
- ✅ nofault_dynpatch_completed: True
- **ALL PASS**

## E2_final
- e: P=0.3135 R=1.0 F1=0.4773 (tp=1500 fp=3285 fn=0 tn=6110)
- r: P=0.1381 R=0.6569 F1=0.2282 (tp=404 fp=2521 fn=211 tn=3710)
- v: P=0.1598 R=1.0 F1=0.2756 (tp=351 fp=1845 fn=0 tn=2398)

## E1_archive

## E4_fix

## P1B_admission
- ✅ f4_actual_fault_count: 1
- ❌ f4_docstring_says_2: False
- ✅ f4_count_correct: True
- ✅ detector_covers_r_only: True
- ✅ scheduler_overhead_includes_model_time: True
- ❌ smoke_runs_both_states: False
- ✅ model_lifecycle_wired: True
- ✅ global_counter_persists: True
- ✅ injected_fault_billed: True
- ⚠️ Detector only handles r-unparseable; e1/e2/v faults not detected
- ⚠️ scheduler_overhead_s includes model call time (double-counting)

## Summary
- E3 P1-B direct: PASS
- E1 archive: PASS
- P1-B smoke ready: NO — issues must be fixed first

**Verdict: P1-B real smoke is NOT YET AUTHORIZED**