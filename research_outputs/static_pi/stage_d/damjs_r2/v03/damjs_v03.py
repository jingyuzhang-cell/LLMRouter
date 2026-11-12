"""DAMJS V0.3: non-destructive result commit (H-ND) + failure-probability EV gate (H-EV).

Implements DAMJS_V0_3.md (frozen before this file) as subclasses of the R2 bridge; the R2 files,
the A‴ executor and the engine are imported read-only and left unchanged. Both mechanisms have
independent switches (nd=, ev=) so R2 / ND-only / EV-only / V0.3 can be compared.
"""
import json

import d2_executor as D2
import damjs_bridge as BR

GLM = ("glm53flash", "glm53")
VERSION = "V0.3.1"
# Model-failure rate per call; censored calls (cut by a timeout before the model finished) are
# excluded from numerator and denominator in both the priors and the online counts.
#   normal: Jeffreys + baseline J1-GLM caps 14 / 241 outcome calls (23 censored 120-s cuts removed)
#   slow:   Jeffreys + power prior a0=0.5 on the 2026-11-06 smoke, 3 failures / 8 outcome calls
PRIOR_NORMAL = (14.5, 227.5)
PRIOR_SLOW = (0.5 + 0.5 * 3, 0.5 + 0.5 * 5)
SLOW_WALL_S = {"glm53flash": 154.0, "glm53": 154.0, "deepseek": 10.5}
# EV gain/loss on one caliber (lenient TP; equal to DOCMAP-normalized strict within 0.2 TP):
#   mu = success-conditional mean gain of a J1 structure repair (baseline S3, n=7)
#   L  = largest observed loss of a failed repair (baseline 4.25; smoke 6 and 10)
# V0.3.2 candidate (off by default; needs a prereg amendment before any real use): under a
# latched-slow GLM service the repaired node's latency uses the repair-attempt quantile observed
# under slow service (2026-11-06/07 capped repair walls 119.8-151.4 s; baseline repeat p95 is
# only 100.2 s), so the remaining critical path must actually fit the deadline.
CP_GATE = False
P95_REPAIR_SLOW = 151.4

MU_EV = {"Z_structure": 1.89, "R": 1.89}
L_EV = {"Z_structure": 10.0, "R": 10.0}
L_STRICT = L_EV
TRUNCATION_SLACK_S = 1.0


def _valid(text):
    return isinstance(D2.extract_json(text or ""), dict)


class FailureEstimator:
    """Execution-local Beta-Binomial failure rate per model with a slow-service latch."""

    def __init__(self):
        self.calls, self.fails, self.slow, self.truncated, self.injected = {}, {}, {}, {}, {}

    def observe(self, model, outcome, wall_s):
        """outcome: "ok" | "fail" | "truncated" (bool accepted: True="fail", False="ok").
        A truncated call is censored: it is not counted, but its wall time still feeds the latch."""
        outcome = {True: "fail", False: "ok"}.get(outcome, outcome)
        if outcome == "injected":            # controlled experiment: never a service observation
            self.injected[model] = self.injected.get(model, 0) + 1
            return
        if outcome == "truncated":
            self.truncated[model] = self.truncated.get(model, 0) + 1
        else:
            self.calls[model] = self.calls.get(model, 0) + 1
            self.fails[model] = self.fails.get(model, 0) + int(outcome == "fail")
        if outcome == "fail" or wall_s > SLOW_WALL_S.get(model, float("inf")):
            self.slow[model] = True

    def post(self, model):
        a, b = PRIOR_SLOW if self.slow.get(model) else PRIOR_NORMAL
        k, n = self.fails.get(model, 0), self.calls.get(model, 0)
        alpha, beta = a + k, b + (n - k)
        p = alpha / (alpha + beta)
        ci = 1.96 * (p * (1 - p) / (alpha + beta)) ** 0.5
        return dict(p=p, n_eff=round(alpha + beta, 1), observed=dict(calls=n, fails=k),
                    truncated=self.truncated.get(model, 0), injected=self.injected.get(model, 0),
                    ci95=[round(max(0.0, p - ci), 4), round(min(1.0, p + ci), 4)], slow=bool(self.slow.get(model)))

    def p(self, model):
        return self.post(model)["p"]

    def state(self):
        return {m: self.post(m) for m in sorted(set(self.calls) | set(self.slow) | set(self.truncated))}


class CommitDict(dict):
    """ex.outputs replacement: the H-ND commit rule runs at the write itself, so the restored v1
    is in place before exec_llm marks the node Completed and the DAG loop can dispatch children."""

    def __init__(self, data, harness):
        super().__init__(data)
        self._h = harness

    def __setitem__(self, node, value):
        snap = self._h.armed.get(node)
        if snap is not None and _valid(snap) and not _valid(value):
            rec = dict(ev="node_rollback", node=node, reason="v2_unparseable", v1_len=len(snap),
                       v2_len=len(value or ""), t=round(self._h.now(), 2))
            self._h.rollbacks.append(rec)
            self._h.progress.write(rec)
            value = snap
        super().__setitem__(node, value)


class HarnessV03(BR.Harness):
    def __init__(self, ex, deadline_s, progress, cancel_path, routing, nd=True):
        super().__init__(ex, deadline_s, progress, cancel_path, routing)
        self.nd = nd
        self.routing = dict(routing)
        self.estimator = FailureEstimator()
        self.rollbacks = []
        self.armed = {}
        self.recovered = set()      # nodes targeted by a recovery action (node-level protection scope)

    def wrap_transport(self, node, fn):
        """R2 wrapper plus per-call failure classification feeding the estimator."""
        outer = self

        def observed(alias, system, user, max_tokens, timeout_s, temperature):
            t0 = outer.now()
            try:
                r = fn(alias, system, user, max_tokens, timeout_s, temperature)
            except Exception as e:
                wall = outer.now() - t0
                timed_out = isinstance(e, TimeoutError) or "timed out" in str(e).lower()
                cut = timed_out and timeout_s is not None and wall >= float(timeout_s) - TRUNCATION_SLACK_S
                outcome = "truncated" if cut else "fail"
                outer.estimator.observe(alias, outcome, wall)
                outer.progress.write(dict(ev="call_outcome", node=node, alias=alias, failed=outcome == "fail",
                                          outcome=outcome, reason=type(e).__name__, wall=round(wall, 2),
                                          timeout_s=timeout_s, estimator=outer.estimator.state()))
                raise
            capped = r.get("stop") in ("max_tokens", "length") or int(r.get("out", 0)) >= int(max_tokens)
            valid = _valid(r.get("text"))
            wall = outer.now() - t0
            outcome = "injected" if r.get("_injected") else ("fail" if (capped or not valid) else "ok")
            outer.estimator.observe(alias, outcome, wall)
            outer.progress.write(dict(ev="call_outcome", node=node, alias=alias, failed=outcome == "fail",
                                      outcome=outcome, capped=capped, valid=valid, wall=round(wall, 2),
                                      estimator=outer.estimator.state()))
            return r
        return super().wrap_transport(node, observed)

    def install_progress(self):
        """R2 progress events plus H-ND. Node-level protection (operator ruling 2026-11-07): only a
        node directly targeted by a recovery action is armed; downstream nodes invalidated by the
        repair are re-executed unconditionally (existing A‴ semantics) and are never rolled back."""
        super().install_progress()
        ex = self.ex
        if self.nd:
            ex.outputs = CommitDict(ex.outputs, self)
        r2_apply = ex.apply_action

        DIRECT = ("structure_repair", "format_repair", "rerun_asis", "retry", "swap")

        def apply_action(node, kind):
            if self.nd and kind in DIRECT:
                self.recovered.add(node)
            return r2_apply(node, kind)

        inner = ex.call

        def call(node):
            armed = self.nd and node in self.recovered
            if armed:
                self.recovered.discard(node)
                self.armed[node] = ex.outputs.get(node)
            try:
                return inner(node)
            finally:
                self.armed.pop(node, None)

        ex.apply_action = apply_action
        ex.call = call


class BridgeV03(BR.SchedulerBridge):
    def __init__(self, harness, repair_lib, ev=True):
        super().__init__(harness, repair_lib)
        self.ev = ev

    def _model_for(self, c):
        if c.kind == "Z_format":
            return None
        return self.h.routing.get(c.node, self.ex.spec[c.node]["model"])

    def _ev(self, c):
        model = self._model_for(c)
        if model is None or c.kind not in L_EV:
            return None
        post = self.h.estimator.post(model)
        p, mu, L = post["p"], MU_EV[c.kind], L_EV[c.kind]
        return dict(model=model, p=round(p, 4), n_eff=post["n_eff"], ci95=post["ci95"], observed=post["observed"],
                    truncated=post["truncated"], slow=post["slow"], mu=mu, L=L,
                    ev=round((1 - p) * mu - p * L, 4))

    def _calibrate(self, c):
        super()._calibrate(c)
        if CP_GATE and c.kind != "NONE" and any(self.h.estimator.slow.get(m) for m in GLM):
            affected = self._affected(c)
            adj = [P95_REPAIR_SLOW if (m in ("J1",) ) else BR.P95_WALL[m] for m in affected]
            c.lat = round(sum(adj), 2)

    def _describe(self, c, d_rem):
        d = super()._describe(c, d_rem)
        e = self._ev(c)
        if e:
            d.update(p_fail=e["p"], n_eff=e["n_eff"], ci95=e["ci95"], observed=e["observed"], slow=e["slow"],
                     mu=e["mu"], L=e["L"], ev=e["ev"])
        return d

    def policy(self, node, sig):
        # Copy of R2 SchedulerBridge.policy with one insertion (EV gate, marked below).
        with self.h.lock:
            t = self.h.now()
            fams = list(sig.values())
            self._observe(node, fams)
            if not sig:
                return []
            family = BR.FAMILY.get(fams[0], fams[0])
            d_rem = self.sched.deadline - t
            rec = dict(ev="damjs_decide", engine="damjs_engine.Scheduler", version=VERSION, node=node, sig=sig,
                       family=family, t=round(t, 2), d_rem=round(d_rem, 2), nd=self.h.nd, ev_gate=self.ev,
                       estimator=self.h.estimator.state())
            if not self.sched.can_dispatch():
                rec.update(chosen="NONE", reason="L3_no_dispatch", candidates=[], excluded=[])
                return self._emit(rec, [])
            cands = self.sched.build_candidates(node, family, current_q=0.0)
            self.counts["build_candidates"] += 1
            kept, excluded = [], []
            for c in cands:
                why = self._executable(c)
                if why:
                    excluded.append(dict(kind=c.kind, node=c.node, why=why))
                    continue
                self._calibrate(c)
                e = self._ev(c)                                         # V0.3 insertion: H-EV gate
                if self.ev and e is not None and e["ev"] <= 0:
                    excluded.append(dict(kind=c.kind, node=c.node, why=f"EV_gate:p={e['p']},EV={e['ev']}", ev_record=e))
                    continue
                kept.append(c)
            chosen = self.sched.select(kept, 0.0, BR.P95_WALL.get(node, 0.0))
            self.counts["select"] += 1
            rec.update(candidates=[self._describe(c, d_rem) for c in kept], excluded=excluded)
            if chosen is None or chosen.kind == "NONE":
                rec.update(chosen="NONE", reason="no_feasible_gain" if chosen is None else "argmax_NONE")
                return self._emit(rec, [])
            self.sched.apply(chosen)
            self.counts["apply"] += 1
            target = "FMT" if chosen.kind == "Z_format" else chosen.node
            self.pending[(target, chosen.kind)] = (family, round(t, 2))
            act = (BR.ACTION[chosen.kind], target)
            rec.update(chosen=chosen.kind, action=list(act))
            return self._emit(rec, [act])

    def summary(self):
        s = super().summary()
        s.update(version=VERSION, nd=self.h.nd, ev_gate=self.ev, rollbacks=list(self.h.rollbacks),
                 estimator=self.h.estimator.state())
        return s


def install(ex, deadline_s, progress, cancel_path, routing, repair_lib, nd=True, ev=True):
    """Wire V0.3 onto a FinalExec the same way the R2 child wires R2 (harness + DAMJS policy)."""
    h = HarnessV03(ex, deadline_s, progress, cancel_path, routing, nd=nd)
    h.install_progress()
    br = BridgeV03(h, repair_lib, ev=ev)
    ex.policy = br.policy
    return h, br
