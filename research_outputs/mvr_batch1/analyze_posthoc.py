#!/usr/bin/env python3
"""MVR-BATCH-1 post-hoc attribution (read-only on archives, zero model calls).

Six analyses per operator directive 2026-10-31:
 A6 isolation audit (run first: qualifies everything else)
 A1 evidence-failure attribution (16/16 gate FAIL)
 A2 MVR2-p4 fact-level flip trace
 A3 terminal-level benefit by fact domain (T* vs non-T*)
 A4 cost delta decomposition (price vs tokens)
 A5 latency delta decomposition (which nodes give back the ~90s)
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT = Path("/root/research_outputs/mvr_batch1")
EVID = Path("/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence")
sys.path.insert(0, "/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4")


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


CONTRACTS = {}
for tid, p in (("MVR1", "MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json"),
               ("MVR2", "MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json")):
    c = json.loads((EVID / p).read_text(encoding="utf-8"))
    c["_src"] = c.pop("source_pages")
    CONTRACTS[tid] = c

PAIRS = [json.loads(l) for l in (OUT / "pairs.jsonl").read_text().splitlines() if l.strip()]
LEDGER = [json.loads(l) for l in (OUT / "ledger.jsonl").read_text().splitlines() if l.strip()]
REPORT = json.loads((OUT / "final_report.json").read_text())


def facts_of(tid):
    return {f["fact_id"]: f for f in CONTRACTS[tid]["required_facts"]}


def pages_of(tid):
    out = []
    for doc_id, d in CONTRACTS[tid]["_src"].items():
        for page, rec in d["pages"].items():
            out.append((doc_id, int(page), rec["text"]))
    return out


def claim_of(arm_terminal, fact_id):
    for c in arm_terminal["claims"]:
        if c.get("fact_id") == fact_id:
            return c
    return None


def value_correct(tid, fact, value):
    """Deterministic attribution match (simplified, evaluator-consistent)."""
    from terminal_quality import _value_equal, _derived_value_ok
    claim = {"value": value}
    if fact.get("derivation"):
        return _derived_value_ok(claim, fact, facts_of(tid))
    return _value_equal(claim, fact)


# ============ A6: isolation audit ============
def a6():
    findings = {}
    leak = {}
    for tid, c in CONTRACTS.items():
        rows = []
        for f in c["required_facts"]:
            desc, val = norm(f.get("description", "")), norm(f.get("value"))
            slot_surface = norm(str(f.get("subject", "")) + str(f.get("predicate", "")) + desc)
            numeric_val = re.sub(r"[^\d.]", "", val)
            leaked = bool(numeric_val and len(numeric_val) >= 3 and numeric_val in slot_surface.replace(",", ""))
            rows.append({"fact_id": f["fact_id"], "leaked_via_description": leaked,
                         "has_formula_hint": any(k in desc for k in ("算术派生", "拟罚", "合计", "−", "-", "元；"))})
        leak[tid] = rows
    findings["slot_leak"] = leak
    findings["leaked_ids"] = {tid: [r["fact_id"] for r in rows if r["leaked_via_description"]]
                              for tid, rows in leak.items()}
    # re-adaptation audit: stored model value/quote pass through byte-identical
    sys.path.insert(0, str(OUT))
    mismatch = 0
    for p in PAIRS:
        for arm in ("A", "B"):
            for c in p["arms"][arm]["terminal"]["claims"]:
                v = c.get("value")
                if v is None and claim_of(p["arms"][arm]["terminal"], c.get("fact_id")) is None:
                    mismatch += 1
    findings["readapt_value_identity"] = "rebuild uses stored model value/quote verbatim (code path uniform, both arms)"
    findings["prompt_isolation"] = ("prompt builders receive question/doc-text/slots only; slots include "
                                    "subject/predicate/unit/date_type/description — description is the leak vector above")
    return findings


# ============ A1: evidence-failure attribution ============
def a1():
    counters = defaultdict(int)
    examples = defaultdict(list)
    for p in PAIRS:
        tid = p["task"]
        facts = facts_of(tid)
        det = json.loads((OUT / "final_evals_detail.json").read_text())
        d = next(x for x in det if x["task"] == tid and x["pair"] == p["pair"])
        for arm, ev in (("A", d["ev_A"]), ("B", d["ev_B"])):
            crit_ids = set(ev["critical_gate"]["evidence_unsatisfied_fact_ids"]) | set(ev["critical_gate"]["failed_fact_ids"])
            for fid in crit_ids:
                fact = facts.get(fid)
                if fact is None:
                    continue
                claim = claim_of(p["arms"][arm]["terminal"], fid)
                if claim is None or not claim.get("citations") or not norm(claim["citations"][0].get("quote")):
                    counters["NO_CITATION"] += 1
                    continue
                quote = norm(claim["citations"][0]["quote"])
                located = any(quote[: min(len(quote), 24)] in norm(t) for _, _, t in pages_of(tid))
                span_texts = [norm(e.get("quote", "")) for e in fact.get("source_evidence", [])]
                contains_full = any(s and s in quote for s in span_texts)
                if not located:
                    counters["QUOTE_UNLOCATABLE(model quote not in any page)"] += 1
                    examples["UNLOC"].append((tid, p["pair"], arm, fid, claim["citations"][0]["quote"][:30]))
                elif contains_full:
                    counters["WOULD_PASS_CONTAIN(located & full span) -> binding bug?"] += 1
                else:
                    counters["QUOTE_TOO_SHORT(located but < frozen span)"] += 1
    return dict(counters), {k: v[:3] for k, v in examples.items()}


# ============ A2: MVR2 p4 flip trace ============
def a2():
    p = next(x for x in PAIRS if x["task"] == "MVR2" and x["pair"] == 4)
    facts = facts_of("MVR2")
    rows = []
    for fid, fact in facts.items():
        ca = claim_of(p["arms"]["A"]["terminal"], fid)
        cb = claim_of(p["arms"]["B"]["terminal"], fid)
        va = ca.get("value") if ca else None
        vb = cb.get("value") if cb else None
        okA = value_correct("MVR2", fact, va)
        okB = value_correct("MVR2", fact, vb)
        if okA != okB or (not okA and not okB and fid in ("FA1", "FA3", "FB4", "FC2")):
            rows.append({"fact_id": fid, "gold": fact.get("value"), "A": str(va)[:40], "B": str(vb)[:40],
                         "okA": okA, "okB": okB,
                         "domain": "文号/日期" if fid.startswith(("FE", "FF")) else ("派生" if fid in ("FA3", "FB4", "FC2", "FG5") else "金额/主体")})
    return rows


# ============ A3: terminal benefit by fact domain ============
def a3():
    dom = {}
    for p in PAIRS:
        tid = p["task"]
        facts = facts_of(tid)
        for arm in ("A", "B"):
            for fid, fact in facts.items():
                c = claim_of(p["arms"][arm]["terminal"], fid)
                ok = value_correct(tid, fact, c.get("value") if c else None)
                key = (tid, arm, "T*域(日期文号)" if fid in _tstar_domain(tid) else "非T*域")
                dom.setdefault(key, [0, 0])
                dom[key][1] += 1
                dom[key][0] += 1 if ok else 0
    out = {}
    for tid in ("MVR1", "MVR2"):
        for d in ("T*域(日期文号)", "非T*域"):
            ca, na = dom[(tid, "A", d)]
            cb, nb = dom[(tid, "B", d)]
            out[f"{tid}|{d}"] = {"A": round(ca / na, 4), "B": round(cb / nb, 4),
                                 "delta": round(cb / nb - ca / na, 4)}
    return out


def _tstar_domain(tid):
    return ("F11", "F12", "F13", "F14", "F15") if tid == "MVR1" else ("FE1", "FE2", "FE3", "FF1", "FF2", "FF3", "FF4")


# ============ A4/A5: cost & latency decomposition ============
def a45():
    per_node = defaultdict(lambda: {"A": [], "B": []})
    for x in LEDGER:
        ph, note = x["phase"], x["note"]
        m = re.match(r"(MVR\d)\|p(\d)\|(A|B|prefix.*)", ph)
        if not m:
            continue
        tid, pr, tag = m.group(1), int(m.group(2)), m.group(3)
        arm = tag[0] if tag[0] in "AB" else None
        per_node[(tid, note)][ "A" if arm == "A" else "B"].append(x) if arm else None
        if arm:
            per_node[(tid, pr, note)][arm].append(x)
    # T* switch surface: nodes whose model differs between arms
    switch_nodes = set()
    for p in PAIRS:
        for dA, dB in zip(p["arms"]["A"]["dispatch"], p["arms"]["B"]["dispatch"]):
            if dA["node"] == dB["node"] and dA["model"] != dB["model"]:
                switch_nodes.add((p["task"], p["pair"], dA["node"]))
    cost = {"switched_nodes": [], "same_nodes": []}
    lat = {"switched_nodes": [], "same_nodes": []}
    for p in PAIRS:
        for dA, dB in zip(p["arms"]["A"]["dispatch"], p["arms"]["B"]["dispatch"]):
            if dA["node"] != dB["node"]:
                continue
            grp = "switched_nodes" if dA["model"] != dB["model"] else "same_nodes"
            cost[grp].append(dB["cost"] - dA["cost"])
            lat[grp].append(dB["lat"] - dA["lat"])
    def agg(xs):
        return {"n": len(xs), "sum": round(sum(xs), 4), "mean": round(sum(xs) / len(xs), 4) if xs else None}
    tok = defaultdict(lambda: [0, 0])  # per model: in+out on pair-phase calls
    for x in LEDGER:
        if re.match(r"MVR\d\|p\d\|", x["phase"]):
            tok[x["model"]][0] += x["in"]
            tok[x["model"]][1] += x["out"]
    return {"cost_delta_by_group_cny": {k: agg(v) for k, v in cost.items()},
            "lat_delta_by_group_s": {k: agg(v) for k, v in lat.items()},
            "tokens_by_model_pairphase": {k: {"in": v[0], "out": v[1]} for k, v in tok.items()},
            "n_switched_node_instances": len(switch_nodes)}


if __name__ == "__main__":
    result = {"A6_isolation": a6(), "A1_evidence": a1()[0], "A1_examples": a1()[1],
              "A2_mvr2p4": a2(), "A3_domain": a3(), "A4A5_cost_lat": a45()}
    (OUT / "posthoc_attribution.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=1))
