"""DAMJS-R2 bridge: drives the tested damsj_engine.Scheduler from a live A‴ FinalExec.

Scope frozen for batch DAMJS_EXP_36 (operator ruling 2026-11-06):
  * DAMJS-arm decisions come from damsj_engine.Scheduler (build_candidates -> select -> apply);
  * action space = {NONE, Z_format, Z_structure, R}; PI and X' are disabled and agents are fixed;
  * History holds gold-blind observed outcomes of applied actions (C3-a / C3-b act on them);
  * L_hat(a) = sum of per-node p95 wall over the nodes the executor re-runs because of a
    (DAMJS_V0_2_1 correction 3; p95 table frozen in DAMJS_DESIGN.md section Q3).

The harness part (L2 call timeout, L3 no-dispatch, cancel token, call ledger events, node
progress for L4) is installed identically on every arm, so arms differ only in policy.
"""
import json
import os
import threading
import time

import damsj_engine as ENG

NODE_KIND = {"E1": "extracts", "E2": "extracts", "E3": "extracts", "E4": "extracts",
             "J1": "reasoning", "J2": "verification", "SINK": "report", "FMT": "FMT"}
NODE_AGENT = {"E1": "ext", "E2": "ext", "E3": "ext", "E4": "ext",
              "J1": "rsn", "J2": "ver", "SINK": "rep", "FMT": "fmt"}
AGENT_ROLE = {"ext": "extractor", "rsn": "reasoner", "ver": "verifier",
              "rep": "reporter", "fmt": "formatter"}
P95_WALL = {"E1": 3.6, "E2": 3.4, "E3": 4.4, "E4": 2.7, "J1": 102.6,
            "J2": 7.0, "SINK": 7.3, "FMT": 0.0}
ALLOWED_KINDS = ("NONE", "Z_format", "Z_structure", "R")
FAMILY = {"structure": "structure", "format": "format",
          "model_suspect": "model_suspect", "caliber_suspect": "caliber"}
ACTION = {"Z_format": "format_repair", "Z_structure": "structure_repair", "R": "rerun_asis"}
ARM_MAP = {"Static": ("Static", "native:Static"),
           "Current-Proposed": ("Proposed-Dynamic", "native:Proposed-Dynamic"),
           "DAMJS": ("Proposed-Dynamic", "damjs_engine.Scheduler")}
GAIN_CLEARED, GAIN_PERSISTED, GAIN_FAILED = 1.0, 0.0, -1.0


def resolve_arm(label):
    if label not in ARM_MAP:
        raise ValueError(f"UNKNOWN_ARM_LABEL:{label!r}")
    return ARM_MAP[label]


class Progress:
    """Append-only JSONL progress log read by the parent watchdog (L4) and the runner."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, rec):
        rec = dict(rec, schema=1, ts=time.time())
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def descendants(spec, node):
    out, stack = [], list(spec[node]["downs"])
    while stack:
        n = stack.pop(0)
        if n not in out:
            out.append(n)
            stack.extend(spec[n]["downs"])
    return out


class Harness:
    """Per-execution harness shared by all arms: engine clock/deadline, L2/L3, ledger events."""

    def __init__(self, ex, deadline_s, progress, cancel_path, routing):
        self.ex = ex
        self.progress = progress
        self.cancel_path = cancel_path
        self.clock = ENG.Clock(0.0)
        agents = {}
        for aid, role in AGENT_ROLE.items():
            node = next(n for n, a in NODE_AGENT.items() if a == aid)
            agents[aid] = ENG.Agent(aid, role, routing.get(node, ex.spec[node]["model"]),
                                    capacity=4 if aid == "ext" else 1)
        nodes = {n: ENG.NodeState(n, NODE_KIND[n], tuple(ex.spec[n]["ups"]), agent=NODE_AGENT[n])
                 for n in ex.spec}
        self.sched = ENG.Scheduler(self.clock, float(deadline_s), agents, nodes,
                                   budget_yuan=float(ex.cfg["per_exec"]["yuan"]))
        self.lock = threading.RLock()

    def now(self):
        with self.lock:
            self.clock.t = (self.ex.clock.now() - self.ex.t0) if self.ex.t0 is not None else 0.0
            self.sched.spent_yuan = float(self.ex.local_yuan)
            return self.clock.t

    def cancelled(self):
        return bool(self.cancel_path) and os.path.exists(self.cancel_path)

    def wrap_transport(self, node, fn):
        """L3 no-dispatch + cancel check, L2 W_eff socket timeout, call_start/call_end events."""
        def guarded(alias, system, user, max_tokens, timeout_s, temperature):
            t = self.now()
            est_in = len(system or "") + len(user or "") + 64
            est_yuan = (len(system or "") + len(user or "")) * 0.8e-6 + max_tokens * 2.8e-6
            if self.cancelled():
                self.progress.write(dict(ev="call_refused", node=node, reason="cancel_token", t=round(t, 2)))
                raise RuntimeError("CANCELLED")
            with self.lock:
                if not self.sched.can_dispatch():
                    self.progress.write(dict(ev="call_refused", node=node, reason="L3_no_dispatch",
                                             t=round(t, 2)))
                    raise RuntimeError("L3_NO_DISPATCH")
                w_eff = self.sched.effective_node_timeout(NODE_KIND[node], P95_WALL[node])
            cid = f"{node}@{t:.3f}"
            self.progress.write(dict(ev="call_start", id=cid, node=node, alias=alias, t=round(t, 2),
                                     timeout_s=round(w_eff, 2), est_tokens=est_in + int(max_tokens),
                                     est_yuan=round(est_yuan, 8)))
            try:
                r = fn(alias, system, user, max_tokens, w_eff, temperature)
            except Exception as e:
                self.progress.write(dict(ev="call_end", id=cid, node=node, ok=False,
                                         err=type(e).__name__ + ":" + str(e)[:80], t=round(self.now(), 2)))
                raise
            self.progress.write(dict(ev="call_end", id=cid, node=node, ok=True,
                                     tokens_in=int(r.get("in", 0)), tokens_out=int(r.get("out", 0)),
                                     t=round(self.now(), 2)))
            return r
        return guarded

    def install_progress(self):
        """M4: node_end with the real output text on completion; node_invalidate on resets."""
        ex, orig_call, orig_apply = self.ex, self.ex.call, self.ex.apply_action

        def call(node):
            if self.cancelled() and ex.state.get(node) != "Completed":
                self.progress.write(dict(ev="node_abort", node=node, reason="cancel_token"))
            self.progress.write(dict(ev="node_start", node=node, t=round(self.now(), 2)))
            try:
                return orig_call(node)
            finally:
                ok = ex.state.get(node) == "Completed"
                self.progress.write(dict(ev="node_end", node=node, ok=ok,
                                         output=ex.outputs.get(node) if ok else None,
                                         state=ex.state.get(node), t=round(self.now(), 2)))

        def apply_action(node, kind):
            before = dict(ex.state)
            out = orig_apply(node, kind)
            reset = [n for n, s in ex.state.items() if before.get(n) == "Completed" and s != "Completed"]
            if reset:
                self.progress.write(dict(ev="node_invalidate", nodes=reset, by=kind, target=node,
                                         t=round(self.now(), 2)))
            return out

        ex.call = call
        ex.apply_action = apply_action


class SchedulerBridge:
    """DAMJS-arm policy: every decision is made by the harness's damsj_engine.Scheduler."""

    def __init__(self, harness, repair_lib):
        self.h = harness
        self.ex = harness.ex
        self.sched = harness.sched
        self.repair_lib = repair_lib
        self.pending = {}
        self.trace = []
        self.counts = dict(build_candidates=0, select=0, apply=0, observe=0)

    def _executable(self, c):
        if c.kind not in ALLOWED_KINDS:
            return "F3_scope_excluded"
        if c.kind == "Z_structure" and c.node not in self.repair_lib:
            return "not_executable:no_repair_spec"
        if c.kind == "Z_format" and getattr(self.ex, "_fmtrep", 0) >= 1:
            return "not_executable:format_repair_already_applied"
        if c.kind in ("Z_structure", "R") and getattr(self.ex, "_reruncount", {}).get(c.node, 0) >= 2:
            return "not_executable:rerun_cap_reached"
        return None

    def _affected(self, c):
        if c.kind == "Z_format":
            return ["FMT"]
        return [c.node] + descendants(self.ex.spec, c.node)

    def _calibrate(self, c):
        if c.kind != "NONE":
            c.lat = round(sum(P95_WALL[m] for m in self._affected(c)), 2)

    def _describe(self, c, d_rem):
        feas = self.sched.feasible(c, 0.0, P95_WALL.get(c.node, 0.0))
        return dict(kind=c.kind, node=c.node, delta_q=c.delta_q, sigma_q=c.sigma_q, cost=c.cost,
                    sigma_c=c.sigma_c, lat=c.lat, sigma_l=c.sigma_l,
                    affected=self._affected(c) if c.kind != "NONE" else [], feasible=feas,
                    lat_gate=round(c.lat + c.sigma_l + self.sched.reserve, 2), d_rem=round(d_rem, 2))

    def _observe(self, node, fams):
        for (target, kind), (family, t_applied) in list(self.pending.items()):
            if target != node:
                continue
            fam_now = [FAMILY.get(f, f) for f in fams]
            gain = (GAIN_FAILED if "model_suspect" in fam_now
                    else GAIN_PERSISTED if family in fam_now else GAIN_CLEARED)
            entry = self.sched.hist.rec[(target, kind)]
            entry["gains"][-1] = gain
            del self.pending[(target, kind)]
            self.counts["observe"] += 1
            rec = dict(ev="damjs_observe", node=node, kind=kind, family=family, gain=gain,
                       hist=dict(count=entry["count"], gains=list(entry["gains"])),
                       forbidden_now=self.sched.hist.forbidden(target, kind), t=round(self.h.now(), 2))
            self.trace.append(rec)
            self.h.progress.write(rec)

    def policy(self, node, sig):
        with self.h.lock:
            t = self.h.now()
            fams = list(sig.values())
            self._observe(node, fams)
            if not sig:
                return []
            family = FAMILY.get(fams[0], fams[0])
            d_rem = self.sched.deadline - t
            rec = dict(ev="damjs_decide", engine="damjs_engine.Scheduler", node=node, sig=sig,
                       family=family, t=round(t, 2), d_rem=round(d_rem, 2))
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
                else:
                    self._calibrate(c)
                    kept.append(c)
            chosen = self.sched.select(kept, 0.0, P95_WALL.get(node, 0.0))
            self.counts["select"] += 1
            rec.update(candidates=[self._describe(c, d_rem) for c in kept], excluded=excluded)
            if chosen is None or chosen.kind == "NONE":
                rec.update(chosen="NONE", reason="no_feasible_gain" if chosen is None else "argmax_NONE")
                return self._emit(rec, [])
            self.sched.apply(chosen)
            self.counts["apply"] += 1
            target = "FMT" if chosen.kind == "Z_format" else chosen.node
            self.pending[(target, chosen.kind)] = (family, round(t, 2))
            act = (ACTION[chosen.kind], target)
            rec.update(chosen=chosen.kind, action=list(act))
            return self._emit(rec, [act])

    def _emit(self, rec, acts):
        self.trace.append(rec)
        self.h.progress.write(rec)
        self.ex.decisions.append({"node": rec["node"], "sig": rec["sig"],
                                  "acts": [list(a) for a in acts], "t_rem": round(rec["d_rem"]),
                                  "engine": rec["engine"], "chosen": rec["chosen"]})
        return acts

    def summary(self):
        return dict(engine_module=ENG.__file__, counts=dict(self.counts),
                    history={f"{k[0]}|{k[1]}": v for k, v in self.sched.hist.rec.items()},
                    engine_log=list(self.sched.log), unresolved=[f"{k[0]}|{k[1]}" for k in self.pending])
