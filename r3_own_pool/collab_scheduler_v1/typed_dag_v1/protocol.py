"""Registered contracts only; validation is structural, never semantic proof."""
from dataclasses import dataclass, field, asdict
import hashlib
import json
import re

class ValidationError(ValueError): pass

# id -> (node type, required input ports, output ports)
CONTRACTS = {
 'facts.v1': ('extraction', {'question':'text','context':'text'}, {'facts':'facts'}),
 'expression.v1': ('reasoning', {'question':'text','facts':'facts'}, {'expression':'expression'}),
 'calculate.v1': ('transformation', {'facts':'facts','expression':'expression'}, {'value':'number'}),
 'verify_expression.v1': ('verification', {'question':'text','facts':'facts','expression':'expression'}, {'value':'number'}),
 'verify_value.v1': ('verification', {'question':'text','value':'number'}, {'value':'number'}),
}
CONTEXT_PORTS = {'question':'text','ctx_table':'text','ctx_text':'text'}

def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x): return hashlib.sha256(canonical(x).encode()).hexdigest()

@dataclass
class Binding:
    port: str
    source: str # task or node
    field: str
    node_id: str | None = None

@dataclass
class Output:
    name: str
    node_id: str
    port: str

@dataclass
class Node:
    node_id: str
    node_type: str
    subtask: str
    inputs: list[Binding]
    output_contract: str
    dependencies: list[str]
    success_contract: str = 'schema.v1'

@dataclass
class Graph:
    graph_id: str
    schema_version: str
    graph_version: int
    task_id: str
    nodes: list[Node]
    final_outputs: list[Output]
    provenance: dict = field(default_factory=dict)

    def to_dict(self): return asdict(self)
    def to_json(self): return canonical(self.to_dict())
    @property
    def content_hash(self): return digest(self.to_dict())
    @classmethod
    def from_json(cls,text):
        try:
            d=json.loads(text)
            d['nodes']=[Node(**{**n,'inputs':[Binding(**b) for b in n['inputs']]}) for n in d['nodes']]
            d['final_outputs']=[Output(**o) for o in d['final_outputs']]
            return cls(**d)
        except (TypeError,KeyError,ValueError) as e: raise ValidationError('Malformed graph protocol') from e

@dataclass(frozen=True)
class Limits:
    max_nodes: int = 16
    max_depth: int = 8
    max_llm_calls: int = 16

@dataclass(frozen=True)
class Validated:
    graph_hash: str
    layers: tuple
    semantic_status: str = 'NOT_ASSESSED'

def _validate(graph,required_outputs=('answer',),limits=Limits()):
    if graph.schema_version!='typed-dag.v1': raise ValidationError('Unknown schema version')
    if type(graph.graph_version) is not int or graph.graph_version<1: raise ValidationError('Invalid graph version')
    for value in (graph.graph_id,graph.task_id):
        if not isinstance(value,str) or not value: raise ValidationError('Missing identity')
    if any(type(x) is not int or x<1 for x in (limits.max_nodes,limits.max_depth,limits.max_llm_calls)):
        raise ValidationError('Invalid limits')
    if not isinstance(graph.provenance,dict): raise ValidationError('Invalid provenance')
    if not graph.nodes or len(graph.nodes)>limits.max_nodes: raise ValidationError('Node count')
    ids=[n.node_id for n in graph.nodes]
    if any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*',x) for x in ids):
        raise ValidationError('Invalid node id')
    if len(set(ids))!=len(ids): raise ValidationError('Duplicate node')
    nodes={n.node_id:n for n in graph.nodes}
    llm=0
    for n in graph.nodes:
        if n.output_contract not in CONTRACTS: raise ValidationError('Unregistered contract/version')
        typ,ports,_=CONTRACTS[n.output_contract]
        if typ!=n.node_type: raise ValidationError('Contract/type mismatch')
        if n.success_contract!='schema.v1': raise ValidationError('Unregistered success contract')
        if not isinstance(n.subtask,str) or not n.subtask.strip(): raise ValidationError('Empty subtask')
        if len(set(n.dependencies))!=len(n.dependencies) or any(d not in nodes or d==n.node_id for d in n.dependencies):
            raise ValidationError('Invalid dependency')
        llm+=typ!='transformation'
        seen=set();referenced=set()
        for b in n.inputs:
            if b.port not in ports: raise ValidationError('Unknown input port')
            if b.port in seen and ports[b.port]!='facts': raise ValidationError('Duplicate scalar input')
            seen.add(b.port)
            if b.source=='task':
                if b.node_id is not None or b.field not in CONTEXT_PORTS: raise ValidationError('Forbidden task field')
                got=CONTEXT_PORTS[b.field]
            elif b.source=='node':
                if b.node_id not in n.dependencies: raise ValidationError('Binding lacks dependency')
                src=nodes[b.node_id]
                if src.output_contract not in CONTRACTS: raise ValidationError('Unknown source contract')
                got=CONTRACTS[src.output_contract][2].get(b.field)
                referenced.add(b.node_id)
            else: raise ValidationError('Unknown binding source')
            if got!=ports[b.port]: raise ValidationError('Incompatible interface')
        if seen!=set(ports): raise ValidationError('Missing input')
        if referenced!=set(n.dependencies): raise ValidationError('Dependency without explicit input')
    if llm>limits.max_llm_calls: raise ValidationError('LLM call bound')
    # Reuse the existing topology validator after checking all references.
    from static_dag_v0.core import topology
    try: layers=topology([{'id':n.node_id,'deps':n.dependencies} for n in graph.nodes])
    except ValueError as e: raise ValidationError(str(e)) from e
    if len(layers)>limits.max_depth: raise ValidationError('Depth bound')
    names=[o.name for o in graph.final_outputs]
    if any(not isinstance(x,str) or not x for x in names): raise ValidationError('Invalid output name')
    if len(set(names))!=len(names) or not set(required_outputs)<=set(names): raise ValidationError('Required output coverage')
    live=set()
    def ancestors(u):
        if u in live:return
        live.add(u)
        for p in nodes[u].dependencies:ancestors(p)
    for o in graph.final_outputs:
        if o.node_id not in nodes or o.port not in CONTRACTS[nodes[o.node_id].output_contract][2]:
            raise ValidationError('Invalid final output')
        if any(o.node_id in n.dependencies for n in graph.nodes): raise ValidationError('Final output must be terminal')
        ancestors(o.node_id)
    if live!=set(ids): raise ValidationError('Dead branch does not reach final output')
    return Validated(graph.content_hash,tuple(tuple(l) for l in layers))


def validate(graph,required_outputs=('answer',),limits=Limits()):
    try:
        return _validate(graph,required_outputs,limits)
    except ValidationError:
        raise
    except (TypeError,AttributeError,KeyError,ValueError,RecursionError) as exc:
        raise ValidationError('Malformed typed DAG: '+str(exc)) from exc
