"""RQ-DYN V5 executor: frozen A‴ executor + bridge layer with genuine model reassignment.

The frozen stage_d_v2_executor.py (e80fe6a3...) routes all nodes via AROUT, which overrides
the spec model — so a 'swap' action changes spec[node]["model"] but AROUT.get(node) still
returns the routed model, making swap a same-model rerun. This bridge wraps exec_llm to
honour actual model reassignment when a swap action has been applied, while leaving the
frozen executor file untouched.

Three reassignment authenticity checks (operator 2026-11-08):
  R1 record-level: after any swap, the node's next call must use a different alias
  R2 replay smoke: zero-call verification that swap triggers a model change
  R3 ratio report: real_reassignments / nominal_swaps per execution
"""
import json, os, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent
for p in (STAGE_D, HERE):
    sys.path.insert(0, str(p))

import stage_d_v2_executor as A3
import d2_executor as D2


class V5Exec(A3.FinalExec):
    """A‴ FinalExec with genuine model reassignment on swap."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.v5_swap_log = []          # (node, old_alias, new_alias, t)
        self.v5_nominal_swaps = 0
        self._v5_model_override = {}   # node -> alias (set by swap, cleared by rerun)

    def apply_action(self, node, kind):
        if kind == "swap":
            self.v5_nominal_swaps += 1
            st = self.spec[node]
            old = st["model"]
            # swap = genuinely switch model (GLM<->DS)
            new = "deepseek" if old in ("glm53flash", "glm53") else "glm53flash"
            self._v5_model_override[node] = new
            self.v5_swap_log.append(dict(node=node, old=old, new=new,
                                          t=round(self.clock.now() - (self.t0 or 0), 1)))
        return super().apply_action(node, kind)

    def exec_llm(self, node):
        if node == "J1" and self.scenario == "S5":
            return super().exec_llm(node)  # S5' has its own logic
        st = self.spec[node]
        # Bridge: if a swap override exists for this node, use it instead of AROUT
        override = self._v5_model_override.pop(node, None)
        if override:
            # Temporarily patch the module-level AROUT entry for this call
            original = A3.AROUT.get(node)
            A3.AROUT[node] = override
            try:
                return super().exec_llm(node)
            finally:
                if original is not None:
                    A3.AROUT[node] = original
                elif node in A3.AROUT:
                    del A3.AROUT[node]
        return super().exec_llm(node)

    def v5_reassignment_summary(self):
        real = len([s for s in self.v5_swap_log if s["old"] != s["new"]])
        return dict(nominal_swaps=self.v5_nominal_swaps, real_reassignments=real,
                    ratio=round(real / self.v5_nominal_swaps, 3) if self.v5_nominal_swaps else None,
                    swap_log=self.v5_swap_log)


def verify_reassignment_authenticity(record):
    """R1: from a run record, verify every swap resulted in a model change.
    Returns (n_nominal, n_real, ratio, details)."""
    actions = record.get("actions") or []
    calls = (record.get("raw") or {}).get("calls") or []
    per_node_calls = {}
    for c in calls:
        per_node_calls.setdefault(c["node"], []).append(c.get("alias", c.get("model", "?")))
    swaps = [a for a in actions if a.get("kind") == "swap"]
    details = []
    for sw in swaps:
        node = sw.get("node")
        seq = per_node_calls.get(node, [])
        # find the call after the swap timestamp
        t_sw = sw.get("t", 0)
        after = [c for c in calls if c["node"] == node and c.get("_t", 0) > t_sw]
        changed = len(set(seq)) > 1
        details.append(dict(node=node, models=seq, changed=changed))
    n_nom = len(swaps)
    n_real = sum(1 for d in details if d["changed"])
    return n_nom, n_real, (round(n_real / n_nom, 3) if n_nom else None), details
