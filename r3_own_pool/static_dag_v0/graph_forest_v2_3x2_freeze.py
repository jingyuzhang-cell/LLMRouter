"""Freeze the 3x2 paired experiment protocol BEFORE any generation call."""
import json
import time
from pathlib import Path

from . import core

GF2 = core.ROOT / 'static_dag_v0/graph_forest_v2'
GPU = GF2 / 'gpu_3x2'
FILES = [core.ROOT / 'static_dag_v0/graph_forest_v2_diagnostic.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_reuse_arm.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_write_validation.py',
         core.ROOT / 'static_dag_v0/graph_forest_v2_3x2.py',
         GF2 / 'DIAGNOSTIC.json', GF2 / 'REUSE_ARM.json', GF2 / 'WRITE_VALIDATION.json',
         core.ROOT / 'static_dag_v0/fresh_static_confirmation/NODES.json',
         core.ROOT / 'static_dag_v0/fresh_static_confirmation/TASKS.json',
         core.ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json']

protocol = dict(
    role='graph_forest_v2 paired 3x2: write-time validation x follow-up strategy',
    panel='identical 20 tasks as graph_forest_v1 (selection rule unchanged), '
          'follow-up modification fact[0] x1.10 unchanged',
    arms=dict(
        A='reuse stored expression on modified facts (0 calls at follow-up)',
        B='regenerate reasoning (v1 arm; FROZEN results reused, temperature 0)',
        C='full-chain rerun ignoring forest: extraction(follow_q)->reasoning; '
          'value-level correctness vs exact expected (DIAGNOSTIC.json)'),
    write_conditions=dict(
        V0='store round-1 expression as-is (frozen responses)',
        V1D='deployable write validation flags -> ONE feedback-targeted repair '
            'retry per flagged node (6 nodes); feedback lists only static-check '
            'findings, never gold information',
        V1O='oracle selection upper bound: retry exactly the 8 known-wrong '
            'nodes with generic deployable feedback; selection uses oracle '
            'knowledge, prompts do not'),
    validator_checks=['exec', 'ref_complete', 'percent', 'magnitude', 'rel_div'],
    hypotheses=['Q(V1O-A) > Q(V0-A) iff targeted repair breaks systematic errors',
                'C(V1-A) << C(B), C(C) (reuse stays near-zero cost)',
                'V1D repair may HARM correct flagged nodes (write-time '
                'intervention harm, mirroring task-level Always-Dynamic harm)'],
    evaluation='correctness vs exact expected follow-up values derived from gold '
               'programs (oracle used for EVALUATION only, never in prompts or '
               'algorithm inputs); accuracy vs discriminative-utility reported '
               'separately for all validators',
    generation='temperature 0, top_p 1, max_tokens 512; models = router-chosen '
               'per-task (same as v1); vLLM serve identical to prior experiments',
    budget=dict(repair_calls='<=14 (V1D 6 + V1O 8, disjoint keys)',
                arm_c_calls='<=60 (e1+r per task)', total_cap=80),
    resume='REQUESTS/RESPONSES jsonl append-only cache; keys repair:{arm}:{uid}, '
           'c_e:{uid}, c_r:{uid}',
    zero_call_inputs_frozen=True,
    bindings={str(p): core.sha(p) for p in FILES},
    created_unix=time.time())
GPU.mkdir(parents=True, exist_ok=True)
(GPU / 'PROTOCOL.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=1))
print(json.dumps(dict(frozen=True, bindings=len(protocol['bindings']),
                      out=str(GPU / 'PROTOCOL.json'))))
