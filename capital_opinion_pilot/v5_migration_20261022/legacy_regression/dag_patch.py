"""dag_patch.py — controlled, versioned DAG extension (conditional verification).

Adds ANNOTATION nodes (e.g. verify.v1) to a frozen base DAG. Annotation nodes:
  - consume a target node's OUTPUT (read-only) + the target's own input pack;
  - produce verdict annotations; they are NOT dataflow inputs to any node, so
    downstream caches stay valid when they are added (this is exactly what
    makes VERIFY a distinct action class from REEXEC);
  - cannot create cycles: annotation edges are excluded from the dataflow
    topology; we still run an explicit guard (base topo order unchanged).

Node spec registry (versioned):
  verify.v1: inputs {facts: list, pack: text}; outputs {fact_verdicts: list};
             termination: single model call + contract check; deps: [target].
"""
import copy

NODE_SPECS = {
    'verify.v1': {'kind': 'annotation',
                  'inputs': {'facts': 'list', 'pack': 'text'},
                  'outputs': {'fact_verdicts': 'list'},
                  'termination': 'single_call_plus_contract',
                  'cycle_safe': 'annotation edges excluded from dataflow topo'},
}


class PatchedDAG:
    def __init__(self, base_nodes, base_edges):
        """base_nodes: {id: {'kind': str}}; base_edges: {id: [deps]} (dataflow)."""
        self.version = 0
        self.base_nodes = copy.deepcopy(base_nodes)
        self.base_edges = copy.deepcopy(base_edges)
        self.annotations = {}          # node_id -> {'spec':..., 'target':...}
        self._base_order = self._topo(base_edges)

    @staticmethod
    def _topo(edges):
        order, seen = [], set()

        def visit(u):
            if u in seen:
                return
            seen.add(u)
            for d in edges.get(u, []):
                visit(d)
            order.append(u)
        for n in sorted(edges):
            visit(n)
        return order

    def add_annotation(self, node_id, spec, target):
        assert spec in NODE_SPECS, f'unregistered spec {spec}'
        assert target in self.base_nodes, 'target must be a base node'
        assert node_id not in self.base_nodes and node_id not in self.annotations
        self.version += 1
        self.annotations[node_id] = {'spec': spec, 'target': target, 'graph_version': self.version}
        # cycle guard: base dataflow order must be unchanged by the patch
        assert self._topo(self.base_edges) == self._base_order, 'patch altered topology'
        return self.version

    def dataflow_edges(self):
        """Annotations never enter the dataflow — downstream caches unaffected."""
        return self.base_edges

    def describe(self):
        return {'graph_version': self.version, 'base_nodes': sorted(self.base_nodes),
                'annotations': {k: dict(v) for k, v in self.annotations.items()}}
