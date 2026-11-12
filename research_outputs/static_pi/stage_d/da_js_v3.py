#!/usr/bin/env python3
"""DA-JS v3: auditable feedback-driven joint scheduling controller (zero-call).

Modules:
  V3QCL      experience-based terminal benefit predictor (from QCL_TABLE_V3;
             refuses to extrapolate unmeasured cells; conservative latencies)
  Policy      candidate generation -> budget/deadline/legality filter ->
             quality-first Pareto selection with tolerances; full audit trail
  Feedback    Beta posterior on fault persistence (R-probe outcomes only),
             E dual-gate (trigger + adoption), state/M updates

Discipline (operator 2026-11-07): small-sample means are NOT universal laws;
unverified joint gains get NO deterministic expectation; correct action choice
is not itself a positive-result claim. Every decision must be explainable.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent

# ---------------- V3-QCL: measured terminal-benefit table ----------------
# Sources: QCL_TABLE_V3_FREEZE.json + qcl_v3_runs ledger (latencies).
# Conservative latency = max observed x MARGIN (tiny n; no reliable quantiles).
MARGIN = 1.2
QCL = {
    'NONE':      dict(Q_d=0.0, calls=0, tok=0, lat=0,
                      basis='baseline; healthy continuation'),
    'R':         dict(Q_d=None, calls=1, tok=5700, lat=70 * MARGIN,
                      basis='transient fault 2/2 full terminal restoration; '
                            'persistent 2/2 fail (wasted call) -> value depends on '
                            'p_transient posterior'),
    'pi':        dict(Q_d=0.0, calls=1, tok=6000, lat=70 * MARGIN,
                      basis='persistent fault: sole recovery, 4/4 restore-to-baseline'),
    'Zx':        dict(Q_d=0.152, calls=8, tok=27500, lat=272 * MARGIN,
                      q_range=(0.091, 0.273), n=3,
                      basis='PROACTIVE upgrade above healthy baseline, 3/3 same '
                            'direction, E04 only; NOT a universal constant'),
    'E':         dict(Q_d=None, calls=3, tok=12000, lat=31 * MARGIN + 137 * MARGIN + 70 * MARGIN,
                      basis='NO verified positive value yet (in-batch cell was an '
                            'artifact-triggered negative control, -50pp); gated'),
    'E_Zx':      dict(Q_d=None, calls=4, tok=14000, lat=326 * MARGIN,
                      basis='UNMEASURED (no genuine trigger occurred); no expectation'),
}
BASE_PROFILE = dict(calls=5, tok=16700, lat=218 * MARGIN,  # max observed base span
                    Q_E04=(0.364, 0.636), Q_E03=(0.389, 1.0),
                    basis='10 measured UB-1 base units')
DELTA_Q_TOL = 0.05   # quality ties within this -> cheaper wins
DELTA_C_TOL = 1.0    # cost ties within this -> faster wins


# ---- v3.2: two-layer delivery value model (operator formula) ----
# dQ_terminal = dQ_transport * P_select - L_selection; exploratory anchors from
# PHASE1 audit (n=1/task; ranges, NOT universal constants). Zx costs scale with
# doc count (measured: 3-doc 8c/27.5K/235s; 5-doc 12c/82K/345s).
P_SELECT = {'V3_two_layer': (1.00, 1.00), 'V2_priority': (0.94, 1.00),
            'V1_model_keyfacts': (0.33, 0.70)}
L_SELECT = {'V3_two_layer': 0.0, 'V2_priority': 0.02, 'V1_model_keyfacts': 0.32}


def zx_hat(s):
    """v3.2 Zx valuation: returns (dQ_terminal_hat, calls, tokens, latency_cons, basis).
    Ceiling gate: if transport-saturation proxy says no headroom (task at ceiling),
    dQ_hat = 0 (no proactive Zx for quality). dQt prior from 4-task anchors:
    [0.0 (ceiling), 0.091, 0.143, 0.100] -> conservative default 0.09 unless
    saturation signaled."""
    docs_n = (s.task_profile or {}).get('docs_n', 3)
    saturated = (s.task_profile or {}).get('transport_saturated', False)
    dQt = 0.0 if saturated else 0.091   # conservative end of measured range
    p_lo, _ = P_SELECT['V3_two_layer']
    dq = round(dQt * p_lo - L_SELECT['V3_two_layer'], 4)
    scale = docs_n / 3.0
    calls = int(round(8 * scale))
    tok = int(27500 * scale)
    lat = int(272 * scale)
    basis = (f'v3.2 formula dQt={dQt}*P_sel={p_lo}-L_sel=0; cost scaled x{scale:.2f} '
             f'({docs_n} docs, 5-doc measured 12c/82K/345s)')
    return dq, calls, tok, lat, basis


def zx_lat():
    return QCL['Zx']['lat']


def q_hat_none(task):
    lo, hi = BASE_PROFILE['Q_E03'] if task.startswith('E03') else BASE_PROFILE['Q_E04']
    return (lo + hi) / 2


# ---------------- state ----------------
@dataclass
class Node:
    nid: str
    kind: str            # extract | verify | report | store
    agent: str
    status: str = 'ok'   # ok | faulted | done
    agents: tuple = ('deepseek', 'qwen')   # pool available for this node (G_t)
    branches: dict = field(default_factory=dict)  # branch -> {n, prov, deficient}


@dataclass
class State:
    task: str
    G: dict              # nid -> Node
    H: dict              # (nid, agent) -> BetaPosterior-like (alpha, beta)
    faulted: tuple = None        # (nid, kind_hint) kind_hint: transient|persistent|unknown
    B: dict = field(default_factory=dict)   # {'calls','tokens','yuan'}
    D: float = 2400.0            # seconds remaining
    M: dict = None               # global quality metrics summary
    task_profile: dict = field(default_factory=dict)  # {'zx_comparable': bool, ...}


class BetaPosterior:
    def __init__(self, alpha=1.0, beta=1.0):
        self.alpha, self.beta = alpha, beta

    def p_transient(self):
        return self.alpha / (self.alpha + self.beta)

    def update(self, r_success):
        if r_success:
            self.alpha += 1
        else:
            self.beta += 1


# ---------------- candidate + policy ----------------
@dataclass
class Candidate:
    action: str          # NONE | R | pi | Zx | E | E_Zx
    exec_plan: dict
    Q_hat: float
    C_hat: dict
    L_hat: float
    basis: str
    legal: bool = True
    veto: str = ''


class Policy:
    def __init__(self, qcl=QCL):
        self.qcl = qcl

    def generate(self, s: State, task_baseline_q):
        none_q = task_baseline_q if not s.faulted else 0.0
        none_basis = self.qcl['NONE']['basis'] if not s.faulted else \
            'NONE under fault = accept degraded terminal (Q=0)'
        cands = [Candidate('NONE', {}, round(none_q, 3),
                           dict(calls=0, tokens=0, yuan=0.0), 0.0, none_basis)]
        faulted = s.faulted
        if faulted:
            nid, hint = faulted
            node = s.G[nid]
            post = s.H.get((nid, node.agent), BetaPosterior())
            p_t = post.p_transient()
            # v3.1 conditional boundary (operator ruling): NOT a universal domination.
            #  - persistent evidence -> pi FIRST (4/4 measured)
            #  - transient/unknown   -> R probe FIRST (12/12+2/2 across batches; pi's
            #    transient replicate count is smaller), escalate to pi on R failure
            #  - pool-restricted     -> R is the legal recovery path
            persistent_like = (hint == 'persistent') or p_t < 1 / 3
            alt = next((a for a in node.agents if a != node.agent), None)
            q_r = task_baseline_q * p_t
            if persistent_like:
                cands.append(Candidate('R', dict(node=nid), round(q_r, 3),
                                       self._c('R'), self.qcl['R']['lat'],
                                       self.qcl['R']['basis'] + '; persistent-likely -> deprioritized',
                                       legal=False, veto='persistent-likely: R deprioritized (2/2 fail measured)'))
            else:
                cands.append(Candidate('R', dict(node=nid), round(q_r, 3),
                                       self._c('R'), self.qcl['R']['lat'],
                                       self.qcl['R']['basis'] + f'; transient/unknown p_t={p_t:.2f} -> probe first'))
            if alt:
                cands.append(Candidate('pi', dict(node=nid, to=alt),
                                       round(task_baseline_q, 3), self._c('pi'),
                                       self.qcl['pi']['lat'],
                                       self.qcl['pi']['basis'] +
                                       ('; persistent-evidence -> FIRST' if persistent_like
                                        else '; post-R fallback')))
            else:
                cands.append(Candidate('pi', dict(node=nid, to=None),
                                       round(task_baseline_q, 3), self._c('pi'),
                                       self.qcl['pi']['lat'], self.qcl['pi']['basis'],
                                       legal=False, veto='agent pool: no alternative executor'))
        else:
            # proactive axis, v3.1 applicability gates:
            #  gate-1 task comparability: only multi-doc extract-branch tasks flagged
            #        zx_comparable (measured on E04-like structure ONLY, n=3)
            #  gate-2 feasibility filter already enforces conservative latency
            #        (max observed x 1.2) <= D_rem with no slack assumed
            if s.task_profile.get('zx_comparable', False):
                dq, calls, tok, lat, basis = zx_hat(s)
                if (s.task_profile.get('transport_saturated', False)):
                    cands.append(Candidate('Zx', dict(docs='all'), round(task_baseline_q, 3),
                                           self._c('Zx'), lat,
                                           basis + '; CEILING: transport saturated, no headroom',
                                           legal=False, veto='zx ceiling: task at transport saturation'))
                else:
                    zx = self.qcl['Zx']
                    cands.append(Candidate('Zx', dict(docs='all', effect='segment-split extract + downstream'),
                                           round(task_baseline_q + dq, 3),
                                           dict(calls=calls, tokens=tok,
                                                yuan=round(calls * 0.0165, 4)), lat, basis))
            else:
                cands.append(Candidate('Zx', dict(docs='all'), 0.0,
                                       self._c('Zx'), zx_lat(),
                                       'v3.1 gate-1: task structure not comparable to measured '
                                       'Zx scenario (E04-like multi-doc); upgrade withheld',
                                       legal=False, veto='zx gate-1: task not comparable'))
        # E only via explicit trigger gate (caller passes M with deficient branches)
        if s.M and s.M.get('genuinely_deficient_branches'):
            cands.append(Candidate('E', dict(branches=s.M['genuinely_deficient_branches']),
                                   round(task_baseline_q, 3),  # NO positive expectation (unverified)
                                   self._c('E'), self.qcl['E']['lat'],
                                   self.qcl['E']['basis'] + '; trigger gate PASSED, Q expectation withheld'))
        return cands

    def _c(self, a):
        e = self.qcl[a]
        return dict(calls=e['calls'], tokens=e['tok'],
                    yuan=round(e['calls'] * 0.0165, 4))

    def filter_feasible(self, cands, s: State):
        out = []
        for c in cands:
            if not c.legal:
                continue
            if c.C_hat['calls'] > s.B['calls']:
                c.veto = f"budget: needs {c.C_hat['calls']}c, have {s.B['calls']}c"
                continue
            if c.C_hat['tokens'] > s.B['tokens']:
                c.veto = f"budget: needs {c.C_hat['tokens']}tok"
                continue
            if c.L_hat > s.D:
                c.veto = f"deadline: conservative L={c.L_hat:.0f}s > D_rem={s.D:.0f}s"
                continue
            out.append(c)
        return out

    def select(self, cands, all_cands=None):
        """Quality-first Pareto with tolerances. Returns Decision with audit."""
        order = sorted(cands, key=lambda c: (-c.Q_hat, c.C_hat['calls'], c.L_hat))
        best = order[0]
        for c in order[1:]:
            if best.Q_hat - c.Q_hat <= DELTA_Q_TOL and c.C_hat['calls'] < best.C_hat['calls'] - DELTA_C_TOL:
                best = c  # cheaper within quality tolerance
                break
        audit = [dict(action=c.action, Q=c.Q_hat, C=c.C_hat, L=c.L_hat,
                      plan=c.exec_plan, basis=c.basis, veto=c.veto)
                 for c in (all_cands or cands)]
        return dict(selected=best.action, exec_plan=best.exec_plan,
                    reason=f"quality-first (tol Q<={DELTA_Q_TOL}); "
                           f"Q_hat={best.Q_hat}, C={best.C_hat['calls']}c, L={best.L_hat:.0f}s",
                    candidates=audit)


def decide(s: State):
    """One decide() call = full auditable decision. task baseline from QCL."""
    base_q = q_hat_none(s.task)
    pol = Policy()
    cands = pol.generate(s, base_q)
    feas = pol.filter_feasible(cands, s)
    # v3.1 fault-axis ladder (operator ruling): transient/unknown -> R probe FIRST,
    # pi is the post-R escalation (same cost, posterior-learning + thin transient-pi
    # replicates); persistent-likely -> pi FIRST (R already vetoed in generate()).
    rec = [c for c in feas if c.action in ('R', 'pi')]
    if len(rec) == 2:
        r_c = next(c for c in rec if c.action == 'R')
        pi_c = next(c for c in rec if c.action == 'pi')
        if not r_c.veto:  # transient/unknown: R is the probe of record
            pi_c.veto = 'v3.1 ladder: R probe first; pi reserved as post-R escalation'
            feas.remove(pi_c)
    if not feas:
        return dict(selected='HALT', reason='no feasible candidate (budget/deadline)',
                    candidates=[dict(action=c.action, veto=c.veto) for c in cands])
    return pol.select(feas, all_cands=cands)


# ---------------- feedback ----------------
def e_trigger_gate(branch_metrics):
    """Trigger gate: CORRECTED signals only (quote-resolved provenance);
    doc-id anomalies alone are NOT evidence (E03 incident)."""
    out = []
    for b, m in branch_metrics.items():
        if m['n'] < 10 or m.get('corrected_prov', 1.0) < 0.8:
            out.append(b)
    return out


def e_adoption_gate(old_branch_facts, new_branch_facts):
    """Adoption gate: never replace with empty or strictly-worse reroll."""
    if not new_branch_facts:
        return False, 'reroll empty'
    def score(fs):
        return len(fs)
    if score(new_branch_facts) < 0.5 * max(score(old_branch_facts), 1):
        return False, 'reroll much thinner than original'
    return True, 'adopted'


def update_after_action(s: State, action, outcome):
    """Feedback update: posterior on R outcomes; state refresh after execution."""
    if action == 'R':
        nid = s.faulted[0] if s.faulted else None
        if nid:
            node = s.G[nid]
            post = s.H.setdefault((nid, node.agent), BetaPosterior())
            post.update(bool(outcome.get('restored')))
            if outcome.get('restored'):
                s.G[nid].status = 'ok'
                s.faulted = None
            else:
                s.faulted = (nid, 'persistent')  # posterior-driven rehint
    elif action == 'pi':
        if s.faulted and outcome.get('restored'):
            s.G[s.faulted[0]].status = 'ok'
            s.faulted = None
    elif action in ('Zx', 'E', 'E_Zx'):
        s.M = outcome.get('M_new', s.M)
    return s
