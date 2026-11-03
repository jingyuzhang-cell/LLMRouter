"""task_quality.py — task-level quality estimator with identifiability tracking.

Q_task(action | state) = expected number of evidence-chained facts surviving to
the deliverable, estimated as:

  sum over extraction nodes v:
      [cached & kept]  observed_grounded(v) * surv(ev, model_of_cache)
      [re-executed]    g(ev, v, pi(v)) * facts(ev, v, pi(v)) * surv(ev, pi(v))

Provenance rules (strict):
  - every input rate carries (value, n, source);
  - a missing cell (UNIDENTIFIED) propagates: the estimate returns None and the
    caller must record 'quality_unidentified' — NEVER a guessed number, and
    NEVER an artificial bonus for a larger action;
  - surv: only KDX extraction->deliverable survival is measured (DS .70 n=10,
    GLM .29 n=7); ST is measured at 1.0 (24/24, n=12 chains); other events
    unidentified.
"""
from dataclasses import dataclass


@dataclass
class Cell:
    value: float
    n: int
    source: str


class TaskQuality:
    def __init__(self, grounding_cells, survival_cells, observed_facts=None):
        """grounding_cells: {(ev,node,model): Cell}; survival_cells: {(ev,model): Cell};
        observed_facts: {(ev,node): (grounded,total)} for cached outputs."""
        self.g = grounding_cells
        self.s = survival_cells
        self.obs = observed_facts or {}

    def estimate(self, ev, plan):
        """plan: {'keep': {node: model}, 'reexec': {node: model}, 'facts_per_call': {(node,model):int}}
        Returns (expected_chained_facts, identified: bool, provenance: dict)."""
        total, identified, prov = 0.0, True, {}
        for node in ('t1', 't2'):
            if node in plan.get('keep', {}):
                obs = self.obs.get((ev, node))
                surv = self.s.get((ev, plan['keep'][node]))
                if obs is None or surv is None:
                    identified = False
                    prov[node] = 'UNIDENTIFIED (cache obs or survival missing)'
                    continue
                total += obs[0] * surv.value
                prov[node] = f'cache {obs[0]}/{obs[1]} x surv {surv.value} (n={surv.n})'
            elif node in plan.get('reexec', {}):
                m = plan['reexec'][node]
                g = self.g.get((ev, node, m))
                surv = self.s.get((ev, m))
                facts = plan.get('facts_per_call', {}).get((node, m))
                if g is None or surv is None or facts is None:
                    identified = False
                    prov[node] = f'UNIDENTIFIED (grounding/survival/facts cell missing for {m})'
                    continue
                total += g.value * facts * surv.value
                prov[node] = f'reexec g={g.value}(n={g.n}) x {facts} facts x surv={surv.value}'
        return (total if identified else None), identified, prov


# Measured cells (zero-pay, from frozen responses; n = facts or chains)
def measured_cells():
    g = {('kdx', 't1', 'deepseek'): Cell(1.000, 14, 'f7v2 saved'),
         ('kdx', 't1', 'glm53'): Cell(0.714, 35, 'f7v2 saved'),
         ('kdx', 't2', 'deepseek'): Cell(0.964, 28, 'f7v2 saved'),
         ('kdx', 't2', 'glm53'): Cell(0.667, 15, 'f7v2 saved'),
         ('st', 't1', 'glm53'): Cell(0.924, 185, 'stv2/stv4 saved'),
         ('st', 't1', 'glm53flash'): Cell(0.951, 41, 'stv4 saved'),
         ('st', 't2', 'deepseek'): Cell(0.980, 300, 'stv2/stv4 saved')}
    s = {('kdx', 'deepseek'): Cell(0.70, 10, 'RF2-signal trace'),
         ('kdx', 'glm53'): Cell(0.29, 7, 'RF2-signal trace'),
         ('st', 'deepseek'): Cell(1.00, 2, '12 chains pooled: 24/24 (all models)'),
         ('st', 'glm53'): Cell(1.00, 18, '12 chains pooled'),
         ('st', 'glm53flash'): Cell(1.00, 4, '12 chains pooled')}
    obs = {('kdx', 't1'): (15, 22), ('kdx', 't2'): (10, 15)}
    return g, s, obs
