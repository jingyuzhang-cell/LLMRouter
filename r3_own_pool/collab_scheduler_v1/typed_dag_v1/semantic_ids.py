"""Exact semantic handles -> program-owned IDs; uses the existing assembler/Graph.

A ref is an opaque, unique handle, not a fuzzy subtask description. Repeated
names or decorative LLM IDs are allowed only with distinct explicit refs.
Legacy id-only plans are accepted as handles for saved-candidate replay.
"""
import copy
from .assembly import ConstraintError, assemble, guard_repair
from .protocol import digest, Limits, CONTRACTS


def normalize_plan(plan, task_id, limits=Limits(), *, registry=None, _identity_only=False):
    if not _identity_only:
        from .semantic_validation import inspect_semantic_plan, SemanticErrors
        errors=[e for e in inspect_semantic_plan(plan,registry,limits) if e["error_code"]!="CONTRACT_UNBINDABLE"]
        if errors:raise SemanticErrors(errors)
    if not isinstance(plan, dict) or set(plan) != {'nodes', 'final_outputs'}:
        raise ConstraintError('PLAN_FORMAT', field='root')
    rows = plan['nodes']
    if not isinstance(rows, list) or not 1 <= len(rows) <= limits.max_nodes:
        raise ConstraintError('NODE_COUNT', field='nodes')
    handles = {}; mapping = {}; labels = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'ref', 'id', 'name', 'type', 'subtask', 'dependencies', 'context_field'}:
            raise ConstraintError('PLAN_NODE_FORMAT', actual=row)
        ref = row.get('ref', row.get('id'))
        if not isinstance(ref, str) or not ref or ref != ref.strip():
            raise ConstraintError('SEMANTIC_REFERENCE_FORMAT', field='ref', actual=ref)
        if ref in handles:
            raise ConstraintError('AMBIGUOUS_SEMANTIC_REFERENCE', field='ref', actual=ref)
        for label in ('id', 'name'):
            if label in row and not isinstance(row[label], str):
                raise ConstraintError('PLAN_NODE_FORMAT', field=label, actual=row[label])
        handles[ref] = row
        mapping[ref] = 'node_' + digest({'task_id': task_id, 'semantic_ref': ref})[:24]
        labels[ref] = {k: row[k] for k in ('id', 'name') if k in row}
    if len(set(mapping.values())) != len(mapping):
        raise ConstraintError('PROGRAM_ID_COLLISION', repairable=False)
    normalized = []
    for ref in sorted(handles):
        row = handles[ref]; deps = row.get('dependencies')
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ConstraintError('DEPENDENCY_FORMAT', ref, 'dependencies', actual=deps)
        missing = [d for d in deps if d not in mapping]
        if missing:
            raise ConstraintError('DEPENDENCY_REFERENCE', ref, 'dependencies', sorted(mapping), missing)
        n = {k: copy.deepcopy(row[k]) for k in ('type', 'subtask', 'context_field') if k in row}
        n.update(id=mapping[ref], dependencies=sorted(mapping[d] for d in deps))
        normalized.append(n)
    finals = plan['final_outputs']
    if not isinstance(finals, list):
        raise ConstraintError('FINAL_OUTPUT_FORMAT', field='final_outputs')
    outputs = []
    for item in finals:
        if not isinstance(item, dict) or set(item) not in ({'name', 'node_ref'}, {'name', 'node_id'}):
            raise ConstraintError('FINAL_OUTPUT_FORMAT', field='final_outputs', actual=item)
        ref = item.get('node_ref', item.get('node_id'))
        if not isinstance(ref, str) or ref not in mapping:
            raise ConstraintError('FINAL_OUTPUT_REFERENCE', field='final_outputs', expected=sorted(mapping), actual=ref)
        outputs.append(dict(name=item['name'], node_id=mapping[ref]))
    return dict(nodes=normalized, final_outputs=outputs), mapping, labels


def assemble_semantic(plan, task_id, context, required_outputs, registry=None, limits=Limits()):
    from .semantic_validation import validate_semantic_plan
    validate_semantic_plan(plan,registry,limits)
    normalized, mapping, labels = normalize_plan(plan, task_id, limits, registry=registry)
    graph = assemble(normalized, task_id, context, required_outputs, registry, limits)
    graph.provenance.update(semantic_plan=copy.deepcopy(plan), normalized_plan=normalized,
                            semantic_ref_map=mapping, semantic_labels=labels,
                            id_policy='program_owned_task_and_exact_ref_v1')
    return graph


def guard_semantic_repair(previous, repaired, task_id, limits=Limits()):
    # Validate handles independently of dangling edges, so repairing an unknown
    # reference is possible, but duplicate handles cannot be silently collapsed.
    def handles_only(p):
        q = copy.deepcopy(p)
        if not isinstance(q, dict) or not isinstance(q.get('nodes'), list):
            return None
        for n in q['nodes']:
            if not isinstance(n, dict): return None
            n['dependencies'] = []
        q['final_outputs'] = []
        normalized, mapping, _ = normalize_plan(q, task_id, limits, _identity_only=True)
        original = {n.get('ref', n.get('id')): n for n in p['nodes']}
        for n in normalized['nodes']:
            ref = next(r for r, u in mapping.items() if u == n['id'])
            deps = original[ref].get('dependencies', [])
            n['dependencies'] = [mapping.get(d, 'missing_' + digest(d)) for d in deps] if isinstance(deps, list) and all(isinstance(d, str) for d in deps) else []
        return normalized
    try:
        old = handles_only(previous)
    except ConstraintError as exc:
        if exc.feedback['error_code'] == 'AMBIGUOUS_SEMANTIC_REFERENCE':
            # No unique correspondence exists, so preservation cannot be
            # established. Fail closed rather than invent a node correspondence.
            raise ConstraintError('REPAIR_AMBIGUOUS_IDENTITY', field='ref',
                                  actual=exc.feedback, repairable=False) from exc
        raise
    new = handles_only(repaired)
    if old is not None and new is not None:
        guard_repair(old, new)
        old_rows={n.get("ref",n.get("id")):n for n in previous["nodes"]}
        new_rows={n.get("ref",n.get("id")):n for n in repaired["nodes"]}
        for ref,row in old_rows.items():
            original=row.get("subtask")
            if isinstance(original,str) and original.strip() and original not in (row.get("type"),*CONTRACTS):
                if original!=new_rows[ref].get("subtask"):
                    raise ConstraintError("REPAIR_CHANGED_SUBTASK",ref,"subtask",original,new_rows[ref].get("subtask"),repairable=False)


def semantic_schema(types, max_nodes):
    variants = []
    for typ in sorted(types):
        properties = dict(ref={'type': 'string', 'minLength': 1},
                          name={'type': 'string'}, type={'enum': [typ]},
                          subtask={'type': 'string', 'minLength': 1},
                          dependencies={'type': 'array', 'items': {'type': 'string', 'minLength': 1}})
        required = ['ref', 'name', 'type', 'subtask', 'dependencies']
        properties['dependencies']['maxItems']=max_nodes-1
        if typ=='extraction':
            properties['dependencies']['maxItems']=0
        else:
            minimum=2 if typ=='transformation' else 1
            if max_nodes<=minimum:continue
            properties['dependencies']['minItems']=minimum
        if typ == 'extraction':
            properties['context_field'] = {'enum': ['ctx_table', 'ctx_text']}
            required.append('context_field')
        variants.append(dict(type='object', required=required, additionalProperties=False, properties=properties))
    return dict(type='object', required=['nodes', 'final_outputs'], additionalProperties=False,
                properties=dict(nodes=dict(type='array', minItems=1, maxItems=max_nodes, items={'anyOf': variants}),
                    final_outputs=dict(type='array', minItems=1, items=dict(type='object', required=['name', 'node_ref'], additionalProperties=False,
                        properties=dict(name={'type': 'string'}, node_ref={'type': 'string', 'minLength': 1})))))


def resolve_review_references(review, graph):
    """Resolve only explicit known handles or actual IDs; reject collisions."""
    result = copy.deepcopy(review)
    mapping = graph.provenance.get('semantic_ref_map', {})
    ids = {n.node_id for n in graph.nodes}
    requirements = result.get('requirements')
    if not isinstance(requirements, dict): return result
    for key, refs in requirements.items():
        if not isinstance(refs, list): continue
        resolved = []
        for ref in refs:
            if not isinstance(ref, str): raise ConstraintError('COVERAGE_REFERENCE', actual=ref)
            possible = ({ref} if ref in ids else set()) | ({mapping[ref]} if ref in mapping else set())
            if len(possible) != 1:
                raise ConstraintError('COVERAGE_REFERENCE', field=key, actual=ref)
            resolved.append(possible.pop())
        requirements[key] = resolved
    return result
