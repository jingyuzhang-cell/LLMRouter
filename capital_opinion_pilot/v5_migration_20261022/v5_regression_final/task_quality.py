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

    def __post_init__(self):
        import math
        if not math.isfinite(self.value) or not 0 <= self.value <= 1 or self.n <= 0 or not self.source:
            raise ValueError('invalid calibrated rate cell')


class TaskQuality:
    quality_scope = "historical_chained_fact_proxy"
    required_nodes = ("t1", "t2")

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
        for node in self.required_nodes:
            if node in plan.get('keep', {}):
                obs = self.obs.get((ev, node))
                if node in plan.get('invalid_cache', ()):
                    identified = False
                    prov[node] = {'identified': False, 'reason': 'invalid_cache_not_reusable'}
                    continue
                surv = self.s.get((ev, plan['keep'][node]))
                if obs is None or surv is None:
                    identified = False
                    prov[node] = 'UNIDENTIFIED (cache obs or survival missing)'
                    continue
                total += obs[0] * surv.value
                prov[node] = {'formula': 'observed_grounded * survival', 'grounded': obs[0],
                              'total': obs[1], 'survival': vars(surv), 'contribution': obs[0] * surv.value}
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
                prov[node] = {'formula': 'grounding * facts * survival', 'grounding': vars(g),
                              'facts': facts, 'survival': vars(surv),
                              'contribution': g.value * facts * surv.value}
            else:
                identified = False
                prov[node] = {'identified': False, 'reason': 'required_node_absent_from_plan'}
        prov['_summary'] = {'metric': self.quality_scope, 'formula': 'sum(contributions)',
                            'identified_total': total if identified else None,
                            'partial_known_total': total, 'terminal_accuracy': None}
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
