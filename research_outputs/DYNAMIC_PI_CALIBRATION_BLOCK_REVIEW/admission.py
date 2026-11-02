"""Offline admission revision. No HTTP, credential loading, or model dispatch.
Partial coverage is evaluated per node, not by all-contract model completeness.
"""
import math

def assess(nodes,models,profiles,remaining_ids):
    candidates={};missing=[]
    for n in nodes:
        if n['output_contract']=='capital.retrieve.v1':continue
        options=[]
        for m in models:
            p=profiles.get(n['output_contract']+'|'+m)
            latency=p.get('latency') if isinstance(p,dict) else None
            if type(latency) in (int,float) and math.isfinite(latency) and latency>=0 and p.get('source') and isinstance(p.get('usage'),dict):
                options.append(m)
            else:missing.append({'node':n['node_id'],'model':m,'contract':n['output_contract'],'reason':'NO_MATCHED_MEASUREMENT'})
        candidates[n['node_id']]=options
    uncovered=[n for n,ms in candidates.items() if not ms]
    unresolved=[n for n in remaining_ids if n not in candidates]
    changing=[n for n in remaining_ids if len(candidates.get(n,[]))>1]
    choices=1
    for n in remaining_ids:choices*=len(candidates.get(n,[]))
    if uncovered or unresolved:decision='HOLD_UNMEASURED_REQUIRED_NODE'
    elif not changing:decision='STOP_BEFORE_EVALUATION_NO_REMAINING_PI_CHOICE'
    else:decision='CANDIDATE_SPACE_PRESENT_REQUIRE_SHARED_HARD_CONSTRAINT_CHECK'
    return dict(decision=decision,candidates=candidates,missing=missing,uncovered=uncovered,remaining_assignment_count=choices,changeable_remaining_nodes=changing,
                actual_feasible_assignment_count=None,quality_guarantee='UNKNOWN',notes=['observed failed output duration is an observation, not a guarantee of successful task latency','candidate availability does not establish independent benefit or require a switch','both arms use identical per-node candidates, dependencies, budgets and deadline feasibility','unknown cells are excluded individually, never filled from other contracts','only frozen choose() may determine hard-constraint feasibility; no result-dependent baseline selection'])
