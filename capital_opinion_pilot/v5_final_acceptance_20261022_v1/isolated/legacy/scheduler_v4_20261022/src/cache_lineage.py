"""cache_lineage.py — output registry with dependency-invalidation semantics.

Every completed node call registers: input fingerprint (hash of its actual
inputs), contract layer (strict/compat), deterministic grounding health
(extraction nodes), timestamp/model. A cache is VALID iff its input
fingerprint matches the current upstream state (dependency inputs unchanged)
AND its contract layer is compat-ok. Health (grounding rate) does NOT affect
validity — it feeds the SEMANTIC-SUSPICIOUS channel and REEXEC_EXPAND legality.
"""
import hashlib
import json


def fingerprint(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()[:16]


class Lineage:
    def __init__(self):
        self.entries = {}   # node -> list of versions (last = current)

    def register(self, node, model, output_value, inputs_fingerprint,
                 contract_layer, grounding=None):
        rec = {'node': node, 'model': model, 'inputs_fp': inputs_fingerprint,
               'layer': contract_layer, 'grounding': grounding,
               'version': len(self.entries.get(node, []))}
        self.entries.setdefault(node, []).append(rec)
        return rec['version']

    def current(self, node):
        e = self.entries.get(node)
        return e[-1] if e else None

    def valid(self, node, current_inputs_fp):
        """Valid iff input fingerprint unchanged AND contract (compat) held."""
        rec = self.current(node)
        if rec is None:
            return False
        return rec['inputs_fp'] == current_inputs_fp and rec['layer'] is not None

    def health(self, node):
        rec = self.current(node)
        return rec['grounding'] if rec else None

    def snapshot(self):
        return {n: e[-1] for n, e in self.entries.items()}
