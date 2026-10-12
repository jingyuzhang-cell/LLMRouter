"""Public planning capabilities derived from executable contracts; no task labels."""
from .protocol import CONTRACTS,digest
from .goal_ir import OPERATIONS

VERSION='planner-operations.v1'
GOAL_FIRST = ('Plan backwards from the required final output and its type: choose an operation '
 'that actually produces that type; enumerate its required input roles; trace every input '
 'to a unique producer or a declared task source; then check that all necessary branches '
 'contribute to the final goal. Emit only the selected planning representation. The program '
 'derives dependencies from explicit producers/symbols. Forward references, multiple roots '
 'and variable node counts are allowed. Never invent producers, facts, conversions or edges. '
 'Operation declarations, not descriptive step names, determine executable behavior. '
 'Static validity is not proof of task meaning; independent semantic review remains required.')

BINDINGS={'extract':'facts.v1','form_expression':'expression.v1',
 'calculate':'calculate.v1','verify_value':'verify_value.v1',
 'verify_expression':'verify_expression.v1'}

def catalogue(registry=None):
    registry=CONTRACTS if registry is None else registry
    rows=[]
    for op,(kind,roles,out) in OPERATIONS.items():
        cid=BINDINGS[op]
        if cid not in registry:continue
        contract=registry[cid]
        if contract!=CONTRACTS[cid] or contract[0]!=kind:raise ValueError('Unsupported executable contract')
        rows.append(dict(operation=op,contract_id=cid,node_type=kind,
          required_roles={role:dict(type=contract[1][role],minimum=1,
            maximum=None if role=='facts' else 1) for role in roles},
          task_inputs={k:v for k,v in contract[1].items() if k not in roles},
          output_role=out,output_ports=dict(contract[2]),
          allowed_task_sources=['ctx_table','ctx_text'] if op=='extract' else [],
          execution='deterministic_expression_evaluation' if op=='calculate' else 'llm',
          rule='calculate requires a separately produced expression; no intrinsic arithmetic rule' if op=='calculate' else 'registered contract only'))
    body=dict(version=VERSION,operations=rows,
      forbidden=['expression as number','derived value as source facts','implicit unit conversion',
        'duplicate symbol producers','unknown producers','unused required branches'],
      unit_policy='Explicit symbol units must match; catalogue does not establish semantic unit correctness',
      final_policy='Final output must have a unique producer and complete required source ancestry',
      semantic_guarantee=False)
    return dict(**body,sha256=digest(body))
