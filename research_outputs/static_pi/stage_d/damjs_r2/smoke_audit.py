#!/usr/bin/env python3
"""Read-only audit of DAMJS_EXP_36 smoke executions (operator GO 2026-11-06, section 5).

Run after every execution (--limit 1 cadence) and at the end (--expect-all). Exit code 0 only when
every check passes and no stop condition fired. Never prints credentials: the leak scan reports
file names and match counts only.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGE_D = HERE.parent
sys.path.insert(0, str(STAGE_D))
sys.path.insert(0, str(HERE))
import damjs_bridge as BR
import damjs_r2_runner as R
import d2_executor as D2

ROUTE = {"E1": "deepseek", "E2": "deepseek", "E3": "deepseek", "E4": "deepseek",
         "J1": "glm53flash", "J2": "deepseek", "SINK": "deepseek"}
UPS = {n: list(v["ups"]) for n, v in D2.base_spec().items()}
P_IN, P_OUT = 0.8e-6, 2.8e-6
KEY_PATTERNS = [r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{16,}", r"(?<![0-9a-f])[0-9a-f]{32}\.[A-Za-z0-9]{8,}",
                r"(?i)bearer\s+[A-Za-z0-9._-]{16,}", r"(?i)(api[_-]?key|x-api-key)\W{0,4}[A-Za-z0-9._-]{12,}"]


def load_jsonl(p):
    out = []
    if Path(p).exists():
        for line in Path(p).read_text("utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({"ev": "UNPARSEABLE"})
    return out


def audit_execution(runs, p, manifest_sha):
    tag = p["tag"]
    res_p = runs / "results" / f"{tag}.json"
    if not res_p.exists():
        return None
    res = json.loads(res_p.read_text("utf-8"))
    prog = load_jsonl(runs / "progress" / f"{tag}.jsonl")
    out_log = runs / "progress" / f"{tag}.jsonl.out"
    child_out = out_log.read_text("utf-8", errors="replace") if out_log.exists() else ""
    checks, anomalies, outcome_notes = {}, [], []
    completed = "exec_record" in res
    starts = [x for x in prog if x.get("ev") == "call_start"]
    ends = {x["id"]: x for x in prog if x.get("ev") == "call_end"}
    refused = [x for x in prog if x.get("ev") == "call_refused"]
    ok_ends = [e for e in ends.values() if e.get("ok")]
    exec_start = next((x for x in prog if x.get("ev") == "exec_start"), {})

    exp_id = f"{p['arm']}|{p['scenario']}|r{p['rep']}|D{int(p['deadline'])}"
    checks["id_and_coordinates"] = (res.get("arm") == p["arm"] and res.get("scenario") == p["scenario"]
                                    and int(res.get("rep")) == p["rep"] and float(res.get("deadline_s")) == p["deadline"]
                                    and (not completed or res.get("exec_id") == exp_id))
    exec_arm, policy = BR.ARM_MAP[p["arm"]]
    checks["arm_mapping"] = (exec_start.get("executor_arm") == exec_arm and exec_start.get("policy") == policy
                             and (not completed or (res.get("executor_arm") == exec_arm and res.get("policy_source") == policy)))
    bad_route = [(x["node"], x.get("alias")) for x in starts if ROUTE.get(x["node"]) != x.get("alias")]
    rec = json.loads(Path(res["exec_record"]).read_text("utf-8")) if completed else None
    if rec:
        bad_route += [(c["node"], c["alias"], c["model"]) for c in rec["raw"]["calls"]
                      if ROUTE.get(c["node"]) not in (c["alias"],) or c["model"] != c["alias"]]
    checks["model_routing"] = not bad_route and bool(starts)

    node_ok_t = {}
    order_violations = []
    for x in prog:
        if x.get("ev") == "node_end" and x.get("ok"):
            node_ok_t.setdefault(x["node"], x["t"])
    for x in starts:
        for u in UPS.get(x["node"], []):
            if u not in node_ok_t or node_ok_t[u] > x["t"] + 1e-6:
                order_violations.append((x["node"], u))
    acts = [(a["kind"], a["node"]) for a in res.get("actions") or []]
    if p["arm"] == "Static":
        actions_ok = not acts
    elif p["arm"] == "DAMJS":
        chosen = [tuple(d["action"]) for d in prog if d.get("ev") == "damjs_decide" and d.get("chosen") not in (None, "NONE")]
        actions_ok = (acts == chosen) if completed else True
    else:
        decided = [tuple(a) for d in res.get("decisions") or [] for a in d.get("acts", [])]
        actions_ok = all(a in decided for a in acts) and len(acts) == len(decided)
    inval_ok = all(any(e.get("ev") == "node_invalidate" and e.get("by") == k and e.get("target") == n for e in prog)
                   for k, n in set(acts) if k in ("structure_repair", "rerun_asis", "format_repair"))
    checks["dag_order_and_actions"] = not order_violations and actions_ok and inval_ok

    fmt_out = None
    for x in prog:
        if x.get("ev") == "node_end" and x["node"] == "FMT" and x.get("ok"):
            fmt_out = x.get("output")
    rescored = R.score_text(fmt_out) if fmt_out else 0
    real_calls = all((e.get("tokens_in") or 0) > 0 and (e.get("tokens_out") or 0) > 0 for e in ok_ends)
    checks["terminal_quality_real"] = (res.get("mode") == "real" and real_calls and bool(ok_ends)
                                       and (rec is None or (rec.get("dry_run") is False and rec.get("mock") is False))
                                       and rescored == res.get("tp"))

    tok = sum((e.get("tokens_in") or 0) + (e.get("tokens_out") or 0) for e in ok_ends)
    acct = sum((e.get("tokens_in") or 0) * P_IN + (e.get("tokens_out") or 0) * P_OUT for e in ok_ends)
    start_alias = {x["id"]: x.get("alias") for x in starts}
    cash = sum((e.get("tokens_in") or 0) * P_IN + (e.get("tokens_out") or 0) * P_OUT
               for cid, e in ends.items() if e.get("ok") and start_alias.get(cid) == "deepseek")
    n_calls = len(starts) + len(refused)
    cost_ok = True
    if completed:
        cost_ok = (res.get("calls") == n_calls and (res.get("tokens_in") or 0) + (res.get("tokens_out") or 0) == tok
                   and abs((res.get("accounting_yuan") or 0) - acct) < 1e-6
                   and abs((res.get("actual_cash_yuan") or 0) - cash) < 1e-6)
    checks["cost_consistency"] = cost_ok

    ident = res.get("identity") or {}
    comps = (ident.get("pre") or {}).get("components") or {}
    checks["identity"] = (exec_start.get("identity_pre_ok") is True and
                          (not completed or (ident.get("ok") is True and len(comps) == 12
                                             and (ident.get("pre") or {}).get("manifest_sha256") == manifest_sha
                                             and (ident.get("post") or {}).get("manifest_sha256") == manifest_sha)))

    for cid, e in ends.items():
        if not e.get("ok"):
            anomalies.append(f"call_failed:{e['node']}:{e.get('err', '')[:60]}")
    for cid in set(start_alias) - set(ends):
        outcome_notes.append(f"call_unsettled_at_abort:{cid.split('@')[0]}")
    if refused:
        outcome_notes.append(f"calls_refused:{[(x['node'], x['reason']) for x in refused]}")
    for n, s in (res.get("final_states") or {}).items():
        if s != "Completed":
            outcome_notes.append(f"node_not_completed:{n}={s}")
    if res.get("status") not in ("COMPLETE", "INCOMPLETE_DEADLINE_DEGRADED", "INCOMPLETE_DEADLINE"):
        anomalies.append(f"status:{res.get('status')}")
    elif res.get("status") != "COMPLETE":
        outcome_notes.append(f"status:{res.get('status')}")
    if "AttributeError" in child_out or "Traceback" in child_out:
        anomalies.append("child_traceback_or_AttributeError")
    if any(x.get("ev") == "UNPARSEABLE" for x in prog):
        anomalies.append("unparseable_progress_line")

    by_node = {}
    for x in starts:
        e = ends.get(x["id"], {})
        by_node.setdefault(x["node"], []).append(dict(alias=x.get("alias"), t=x["t"], timeout_s=x.get("timeout_s"),
                                                     wall=round(e["t"] - x["t"], 2) if "t" in e else None,
                                                     ok=e.get("ok"), tokens_in=e.get("tokens_in"),
                                                     tokens_out=e.get("tokens_out"), err=e.get("err")))
    return dict(
        tag=tag, phase=p["phase"], arm=p["arm"], scenario=p["scenario"], status=res.get("status"), tp=res.get("tp"),
        rescored_tp=rescored, joint_success=res.get("runner", {}).get("joint_success"),
        exec_id=res.get("exec_id"), executor_arm=exec_start.get("executor_arm"), policy=exec_start.get("policy"),
        actions=acts, decisions=[(d.get("node"), d.get("chosen"), d.get("d_rem")) for d in prog if d.get("ev") == "damjs_decide"]
        or [(d["node"], d["acts"], d.get("t_rem")) for d in res.get("decisions") or []],
        makespan_s=res.get("makespan_s"), elapsed_since_launch_s=res.get("elapsed_since_launch_s"),
        watchdog_elapsed_s=res.get("runner", {}).get("elapsed_s"), deadline_s=res.get("deadline_s"),
        startup_offset_s=res.get("startup_offset_s"),
        calls=n_calls, calls_refused=len(refused), tokens=tok, accounting_yuan=round(acct, 6), cash_yuan=round(cash, 6),
        reconcile=res.get("runner", {}).get("reconcile"), per_node_calls=by_node,
        identity_components=len(comps), checks=checks, anomalies=anomalies, outcome_notes=outcome_notes,
        ok=all(checks.values()) and not anomalies)


def scan_secrets(paths):
    hits = {}
    for p in paths:
        try:
            text = Path(p).read_text("utf-8", errors="replace")
        except (IsADirectoryError, FileNotFoundError):
            continue
        n = sum(len(re.findall(pat, text)) for pat in KEY_PATTERNS)
        if n:
            hits[str(p)] = n
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=str(HERE / "runs_real"))
    ap.add_argument("--expect-all", action="store_true")
    a = ap.parse_args()
    runs = Path(a.runs_dir)
    manifest_sha = hashlib.sha256(R.MANIFEST.read_bytes()).hexdigest()
    smoke = [p for p in R.build_order() if p["phase"] == "smoke"]
    rows = [r for r in (audit_execution(runs, p, manifest_sha) for p in smoke) if r]
    led_lines = load_jsonl(runs / "LEDGER.jsonl")
    ledger = R.read_ledger(runs)
    exp_calls = sum(r["calls"] for r in rows)
    exp_tokens = sum(r["tokens"] + ((r["reconcile"] or {}).get("topup_tokens") or 0) for r in rows)
    exp_yuan = sum(r["accounting_yuan"] + ((r["reconcile"] or {}).get("topup_yuan") or 0) for r in rows)
    caps = R.caps_for("smoke")
    files = [f for f in runs.rglob("*") if f.is_file()] + [R.MANIFEST]
    leaks = scan_secrets(files)
    tags = [l.get("tag") for l in led_lines]
    agg = dict(
        executed=len(rows), expected=len(smoke),
        unique_exec_ids=len({r["exec_id"] for r in rows if r["exec_id"]}) == len([r for r in rows if r["exec_id"]]),
        ledger_lines_one_per_execution=sorted(tags) == sorted(r["tag"] for r in rows) and len(tags) == len(set(tags)),
        ledger=ledger, expected_from_events=dict(calls=exp_calls, tokens=exp_tokens, yuan=round(exp_yuan, 6)),
        ledger_consistent=(ledger["calls"] == exp_calls and ledger["tokens"] == exp_tokens
                           and abs(ledger["yuan"] - exp_yuan) < 1e-5),
        ledger_last_line_matches=bool(led_lines) and led_lines[-1].get("ledger_after") == ledger,
        within_smoke_caps=all(ledger[k] <= caps[k] + (1e-9 if k == "yuan" else 0) for k in caps),
        within_batch_caps=all(ledger[k] <= R.CAPS[k] + (1e-9 if k == "yuan" else 0) for k in R.CAPS),
        cash_yuan=round(sum(r["cash_yuan"] for r in rows), 6),
        files_scanned=len(files), secret_pattern_hits=leaks, manifest_sha256=manifest_sha,
        manifest_verified=R.verify_manifest()["ok"])
    agg_ok = (agg["unique_exec_ids"] and agg["ledger_lines_one_per_execution"] and agg["ledger_consistent"]
              and agg["ledger_last_line_matches"] and agg["within_smoke_caps"] and agg["within_batch_caps"]
              and not leaks and agg["manifest_verified"] and (not a.expect_all or len(rows) == len(smoke)))
    out = dict(aggregate=agg, aggregate_ok=agg_ok, executions=rows,
               all_ok=agg_ok and all(r["ok"] for r in rows))
    (runs / "SMOKE_AUDIT.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    for r in rows:
        fails = [k for k, v in r["checks"].items() if not v]
        print(f"{r['tag']:<30} {r['status']:<12} tp={r['tp']} (rescored {r['rescored_tp']}) calls={r['calls']} "
              f"tok={r['tokens']} Y{r['accounting_yuan']:.4f} ms={r['makespan_s']} "
              f"{'OK' if r['ok'] else 'STOP'} failed_checks={fails} stop_anomalies={r['anomalies']} notes={r['outcome_notes']}")
    print(f"ledger={ledger} expected={agg['expected_from_events']} consistent={agg['ledger_consistent']} "
          f"smoke_caps_ok={agg['within_smoke_caps']} leaks={len(leaks)} manifest_ok={agg['manifest_verified']} "
          f"-> {'ALL_OK' if out['all_ok'] else 'STOP'}")
    return 0 if out["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
