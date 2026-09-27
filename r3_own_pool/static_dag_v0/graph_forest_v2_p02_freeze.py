"""Freeze P0-2 protocol BEFORE any generation call: {A,B,C'} x {V0,V1}."""
import json
import time
from pathlib import Path

from . import core

GF2 = core.ROOT / 'static_dag_v0/graph_forest_v2'
OUT = core.ROOT / 'static_dag_v0/graph_forest_v2_p02'
FILES = [core.ROOT / 'static_dag_v0/graph_forest_v2_p02_dryrun.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_p02_freeze.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_p02_run.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_p02_analyze.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_write_validation.py',
         OUT / 'DRYRUN.json',
         core.ROOT / 'static_dag_v0/fresh_static_confirmation/NODES.json',
         core.ROOT / 'static_dag_v0/fresh_static_confirmation/TASKS.json',
         core.ROOT / 'static_dag_v0/fresh_static_confirmation/DEV_MODELS.npz']

protocol = dict(
    role='P0-2 normalized 3x2: reuse scope x write validation on follow-ups',
    panel=dict(
        source='fresh_static_confirmation (100 tasks)',
        eligible=96, excluded=4,
        exclusion='write-state unavailable (no response / expression not executable)',
        order='uid ascending, frozen',
        why_not_frozen200='frozen200 facts are model-extracted: only 134/200 tasks have '
                          'facts[0] aligned to a gold operand (exact target not derivable '
                          'elsewhere) and operand-usage unverified; fresh_static gives '
                          '96/96 exact targets and 96/96 source-locatable (DRYRUN.json)'),
    write_state=dict(
        model='router-top per task (frozen DEV_MODELS, same rule as graph_forest_v1/v2)',
        stored='round-1 reasoning expression (frozen {model}_RESPONSES.jsonl) + node '
               'gold_facts (the facts the model saw in round 1)',
        V0='raw stored expression',
        V1D='deployable write validation (5 frozen checks: exec/ref_complete/percent/'
            'magnitude/rel_div) + ONE repair retry with frozen GUIDE feedback for '
            'flagged nodes; rules fixed before run, never modified mid-run',
        V1O='oracle write validation kept OFFLINE upper bound only, not a main condition'),
    modification='structured facts[0] x 1.10 (same float op as GFv2); question text '
                 'UNCHANGED; the SAME modified facts object is input to A and B',
    arms=dict(
        A='re-execute stored (post-V1) expression on modified facts; 0 model calls; '
          'C counted as 0 model tokens',
        B='regenerate reasoning: sprompt(ORIGINAL question, modified stored facts) -> '
          'expression -> exec; 1 call; extraction NOT rerun',
        C_prime='normalized full rerun: replace FIRST occurrence of the facts[0] value '
                'string in the task context with its x1.10 rendering (format-matched '
                'variant from DRYRUN), then eprompt(ORIGINAL question, mutated context) '
                '-> parse_facts -> sprompt(ORIGINAL question, own extracted facts) -> '
                'exec; 2 calls; NO natural-language modification sentence anywhere',
        v_node='excluded from all arms (GFv2: verifier has zero discriminative utility); '
               'all arms end at the computed value'),
    metrics=dict(
        Q='exact correctness vs gold-program-derived follow-up target (facts[0]x1.10 '
          'substituted); oracle used for EVALUATION only',
        C='new model tokens in follow-up phase only; V1 additionally reports '
          'C_amortized = C_followup + C_write_validation / N with N=1 (conservative)',
        L='observed per-call latency (recorded latency_s); DAG critical-path reported '
          'where topology applies; no summing parallel branches',
        state_split='stored-correct (round-1 expression exactly correct on original '
                    'facts) vs stored-wrong; report Q(a|state), P(harm|stored correct,a), '
                    'P(recover|stored wrong,a), dC_a, dL_a',
        stats='paired: exact McNemar for Q (A-B, A-C\', B-C\'); paired bootstrap 10k for '
              'C/L (mean+median diff, 95% CI); dQ and dC reported directly'),
    safety_valves=dict(
        no_midrun_changes='prompts/validation rules/retry policy frozen; implementation '
                          'bugs stop the run, affected arm rerun from scratch with audit trail',
        pilot_gate='first 10 C-prime tasks must show source-mutation propagation '
                   '(extraction returns a value ~= facts[0]x1.10, rel tol 1e-3) in >=6/10, '
                   'else abort before burning the full budget',
        budget_cap=500),
    estimated_calls=dict(v1_repairs='<=38', B=96, C_prime=192, total='~330 <= 500'),
    generation='temperature 0, top_p 1, max_tokens 512; vLLM serve identical to prior '
               'experiments; REQUESTS/RESPONSES jsonl append-only cache, keys '
               'p02:repair:{uid}, p02:B:{uid}, p02:C_e:{uid}, p02:C_r:{uid}',
    bindings={str(p): core.sha(p) for p in FILES if p.exists()},
    created_unix=time.time())
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'PROTOCOL.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=1))
print(json.dumps(dict(frozen=True, bindings=len(protocol['bindings']))))
