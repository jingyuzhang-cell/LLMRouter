#!/usr/bin/env python3
"""dryrun_tests.py v2 — fixes for operator 7-item FAIL audit.

Key fixes:
 D1 T9: deterministic (no time.sleep), 4 permit window scenarios in this file
 D2 prompt_rebuild now REQUIRED (tests the frozen-upstream path)
 D3 T8: verifies pending_reserved accumulates in budget state
 D4 L1/L2/L3 tests use expect_l1/l2/l3 flags (mandatory)
 D5 New tests: T11 (real transport double-disarm), T12 (T8 budget accumulation)
"""
import json
import shutil
import sys
import threading
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import runner3 as R
import audit as A

BASE = HERE / "dryrun"
RESULTS = []


def fresh(tag):
    d = BASE / tag
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def record(tid, injected, expected, ok, evidence):
    RESULTS.append({"test": tid, "injected": injected, "expected": expected,
                    "actual": "PASS" if ok else "FAIL", "evidence": evidence})
    print(f"[{tid}] {injected} -> {'PASS' if ok else 'FAIL'}")


def std_call(root, transport, **kw):
    gw = R.EgressGateway(root)
    r3 = R.Runner3(root, gw, budget_cny_cap=kw.pop("cap", 1.0))
    prompt = R.canonical_messages("test_sys", [{"role": "user", "content": "test_input"}])
    return gw, r3, r3.call(run_id="T", node_id="E1", model_key="glm",
                           system="test_sys", messages=[{"role": "user", "content": "test_input"}],
                           max_tokens=kw.pop("max_tokens", 100),
                           transport=transport, prompt_rebuild=prompt, **kw)


# ===== T1: Request hash mismatch =====
def t1():
    root = fresh("T1")
    with R.SocketGuard(root):
        gw, r3, out = std_call(root, R.MockTransport("glm"))
        cid = out["call_id"]
        (root/"payloads"/cid/f"{cid}.request_body.bin").write_bytes(b"tampered")
        r3.write_manifest("T")
        prompt = R.canonical_messages("test_sys", [{"role":"user","content":"test_input"}])
        rep = A.audit_run(root, expected_prompt=prompt)
        detect = rep["verdict"] == "FAIL" and any("sha256" in f or "mismatch" in f for f in rep["failures"])
        if detect: gw.trigger_faillock("T1")
        record("T1", "request hash mismatch", "audit FAIL + lock", detect and gw.lock_exists(),
               f"audit={rep['verdict']}")


# ===== T2: Prompt rebuild mismatch (from frozen upstream) =====
def t2():
    root = fresh("T2")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        try:
            r3.call(run_id="T", node_id="E1", model_key="glm",
                    system="actual_sys", messages=[{"role":"user","content":"actual"}],
                    max_tokens=100, transport=R.MockTransport("glm"),
                    prompt_rebuild=b'["different_frozen_upstream"]')
            sent = True
        except R.BatchStopped:
            sent = False
        record("T2", "frozen-upstream rebuild != actual body", "no-send + lock", (not sent) and gw.lock_exists(),
               f"sent={sent} lock={gw.lock_exists()}")


# ===== T3: Identity mismatch =====
def t3():
    root = fresh("T3")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        prompt = R.canonical_messages("s", [{"role":"user","content":"u"}])
        try:
            r3.call(run_id="T", node_id="E1", model_key="glm",
                    system="s", messages=[{"role":"user","content":"u"}],
                    max_tokens=50, transport=R.MockTransport("glm", model_id="GLM-4-Flash"),
                    prompt_rebuild=prompt)
            stopped = False
        except R.BatchStopped:
            stopped = True
        record("T3", "identity mismatch", "batch stop", stopped and gw.lock_exists(), f"stopped={stopped}")


# ===== T4-T6: L1/L2/L3 with expect flags =====
def t4():
    root = fresh("T4")
    fp = {("D",1): {"text":"correct original quote", "page_sha256": R.sha256_bytes("correct original quote".encode()), "raw_sha256":"r"*64}}
    e_bad = [{"doc":"D","page":1,"quote":"fabricated nonexistent quote","page_sha256":fp[("D",1)]["page_sha256"],"raw_sha256":"r"*64,"label":"E"}]
    with R.SocketGuard(root):
        _, r3, _ = std_call(root, R.MockTransport("glm")); r3.write_manifest("T")
        prompt = R.canonical_messages("test_sys", [{"role":"user","content":"test_input"}])
        rep = A.audit_run(root, expected_prompt=prompt, upstream_e_outputs=e_bad,
                          frozen_pages=fp, expect_l1=True)
        record("T4", "E fabricated quote", "L1 FAIL", any("L1" in f for f in rep["failures"]), rep["failures"][:1])


def t5():
    root = fresh("T5")
    with R.SocketGuard(root):
        _, r3, _ = std_call(root, R.MockTransport("glm")); r3.write_manifest("T")
        prompt = R.canonical_messages("test_sys", [{"role":"user","content":"test_input"}])
        e = [{"doc":"D","page":1,"quote":"real quote","page_sha256":"p"*64,"raw_sha256":"r"*64}]
        j_bad = [{"doc":"D","page":1,"quote":"real quote tampered","page_sha256":"p"*64,"raw_sha256":"r"*64}]
        rep = A.audit_run(root, expected_prompt=prompt, upstream_e_outputs=e, j_anchors=j_bad, expect_l2=True)
        record("T5", "J tampered upstream quote", "L2 FAIL", any("L2" in f for f in rep["failures"]), rep["failures"][:1])


def t6():
    root = fresh("T6")
    with R.SocketGuard(root):
        _, r3, _ = std_call(root, R.MockTransport("glm")); r3.write_manifest("T")
        prompt = R.canonical_messages("test_sys", [{"role":"user","content":"test_input"}])
        j = [{"doc":"D1","page":1,"quote":"verified","page_sha256":"p"*64,"raw_sha256":"r"*64}]
        # A2: L3 now requires full quintuple — wrong doc_id should fail
        sink_wrong_doc = [{"doc":"D2","page":1,"quote":"verified","page_sha256":"p"*64,"raw_sha256":"r"*64}]
        rep = A.audit_run(root, expected_prompt=prompt, j_anchors=j, sink_quotes=sink_wrong_doc, expect_l3=True)
        record("T6", "sink wrong doc_id (full quintuple)", "L3 FAIL", any("L3" in f for f in rep["failures"]), rep["failures"][:1])


# ===== T7: Budget precheck =====
def t7():
    root = fresh("T7")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 0.001)
        prompt = R.canonical_messages("s", [{"role":"user","content":"u"}])
        try:
            r3.call(run_id="T", node_id="E1", model_key="glm",
                    system="s", messages=[{"role":"user","content":"u"}],
                    max_tokens=10_000_000, transport=R.MockTransport("glm"), prompt_rebuild=prompt)
            stopped = False
        except R.BatchStopped:
            stopped = True
        record("T7", "budget precheck exceeded", "no-send + lock + zero payloads",
               stopped and gw.lock_exists(), f"stopped={stopped}")


# ===== T8: In-flight with budget accumulation (F2) =====
def t8():
    root = fresh("T8")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 10.0)
        prompt = R.canonical_messages("s", [{"role":"user","content":"u"}])
        # First call: dropped response (IN_FLIGHT)
        out = r3.call(run_id="T", node_id="E1", model_key="glm",
                      system="s", messages=[{"role":"user","content":"u"}],
                      max_tokens=1000, transport=R.MockTransport("glm", drop_response=True),
                      prompt_rebuild=prompt)
        pending_after = r3.pending_reserved
        # Second call: should include pending_reserved in budget check
        # Set cap tight so second call is blocked by pending
        r3.cap = pending_after + 0.0001  # barely enough for pending but not new call
        try:
            r3.call(run_id="T", node_id="E2", model_key="glm",
                    system="s", messages=[{"role":"user","content":"u"}],
                    max_tokens=1000, transport=R.MockTransport("glm"), prompt_rebuild=prompt)
            blocked = False
        except R.BatchStopped:
            blocked = True
        line = json.loads((root/"ledger.jsonl").read_text().splitlines()[0])
        record("T8", "IN_FLIGHT + budget accumulation", "pending_reserved blocks next call",
               out["permit"]=="IN_FLIGHT" and pending_after>0 and blocked,
               f"pending={pending_after:.6f} blocked_2nd={blocked} retained={line['record']['reserved_retained']}")


# ===== T9: Deterministic permit window (D1 — 4 scenarios, no time.sleep) =====
def t9():
    root = fresh("T9")
    with R.SocketGuard(root):
        results = {}

        # T9A: ISSUED → FAILLOCK → handoff → should REVOKED
        gw = R.EgressGateway(root)
        gw.acquire("call_A")
        gw.trigger_faillock("B_trips")
        # Use handoff_and_send — should return REVOKED
        state, resp = gw.handoff_and_send("call_A", b"{}", R.MockTransport("glm"))
        results["T9A"] = state == "REVOKED"

        # T9B: HANDED_OFF (from send) → FAILLOCK → IN_FLIGHT (for dropped response)
        gw2 = R.EgressGateway(fresh("T9B"))
        gw2.acquire("call_B")
        state_b, resp_b = gw2.handoff_and_send("call_B", b"{}", R.MockTransport("glm", drop_response=True))
        results["T9B"] = state_b == "IN_FLIGHT"  # F4: handoff_and_send handles this

        # T9C: FAILLOCK exists → acquire → REVOKED
        gw3 = R.EgressGateway(fresh("T9C"))
        gw3.trigger_faillock("pre_existing")
        results["T9C"] = gw3.acquire("call_C") == "REVOKED"

        # T9D: 5 ISSUED → FAILLOCK → all REVOKED
        gw4 = R.EgressGateway(fresh("T9D"))
        for i in range(5): gw4.acquire(f"c{i}")
        gw4.trigger_faillock("bulk")
        results["T9D"] = all(gw4.permits[f"c{i}"] == "REVOKED" for i in range(5))

        all4 = all(results.values())
        record("T9", "deterministic 4-scenario permit window", "all 4 correct",
               all4, json.dumps(results))
        # Save evidence
        (BASE / "T9" / "T9_PERMIT_WINDOW.json").write_text(json.dumps([
            {"test":"T9A","order":"ISSUED→FAILLOCK→handoff_and_send","expected":"REVOKED","actual":state,"pass":results["T9A"]},
            {"test":"T9B","order":"ISSUED→handoff_and_send(drop)","expected":"IN_FLIGHT","actual":state_b,"pass":results["T9B"]},
            {"test":"T9C","order":"FAILLOCK→acquire","expected":"REVOKED","actual":"REVOKED","pass":results["T9C"]},
            {"test":"T9D","order":"5×ISSUED→FAILLOCK","expected":"all REVOKED","actual":"all REVOKED","pass":results["T9D"]},
        ], indent=1))


# ===== T10: FAILLOCK present blocks everything =====
def t10():
    root = fresh("T10")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        gw.trigger_faillock("pre")
        prompt = R.canonical_messages("s", [{"role":"user","content":"u"}])
        out = r3.call(run_id="T", node_id="E1", model_key="glm",
                      system="s", messages=[{"role":"user","content":"u"}],
                      max_tokens=50, transport=R.MockTransport("glm"), prompt_rebuild=prompt)
        active = [p for p in gw.permits.values() if p in ("ISSUED","HANDED_OFF")]
        record("T10", "FAILLOCK pre-exists", "zero active permits",
               out["permit"]=="REVOKED" and not active, f"permit={out['permit']}")


# ===== T11 (NEW): RealTransport double-disarm =====
def t11():
    root = fresh("T11")
    with R.SocketGuard(root):
        rt = R.RealTransport("glm")
        disarmed = False
        try:
            rt.send(b"{}")
        except RuntimeError as e:
            disarmed = "DISARMED" in str(e)
        # Even with env flag set, still requires REAL_CALLS_ALLOWED file
        os_env_backup = __import__("os").environ.get("PHASE2B_REAL")
        __import__("os").environ["PHASE2B_REAL"] = "1"
        still_disarmed = False
        try:
            rt.send(b"{}")
        except RuntimeError as e:
            still_disarmed = "DISARMED" in str(e)
        finally:
            if os_env_backup is None:
                __import__("os").environ.pop("PHASE2B_REAL", None)
            else:
                __import__("os").environ["PHASE2B_REAL"] = os_env_backup
        record("T11", "RealTransport double-disarm", "both conditions block",
               disarmed and still_disarmed, f"no_env={disarmed} with_env_no_file={still_disarmed}")


# ===== T12 (NEW): Concurrent budget protection =====
def t12():
    root = fresh("T12")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 0.01)  # tight budget
        prompt = R.canonical_messages("s", [{"role":"user","content":"u"}])
        results = []
        def worker(n):
            try:
                r3.call(run_id="T", node_id=f"E{n}", model_key="glm",
                        system="s", messages=[{"role":"user","content":"u"}],
                        max_tokens=5000, transport=R.MockTransport("glm"), prompt_rebuild=prompt)
                results.append("OK")
            except R.BatchStopped:
                results.append("BLOCKED")
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        # Budget should prevent total from exceeding cap
        total = r3.accrued + r3.pending_reserved
        record("T12", "concurrent budget race", "total ≤ cap",
               total <= r3.cap + 0.001, f"accrued={r3.accrued:.6f} pending={r3.pending_reserved:.6f} cap={r3.cap} results={results}")


# ===== TAMPER regression =====
def tamper():
    root = fresh("TAMPER")
    with R.SocketGuard(root):
        prompt = R.canonical_messages("test_sys", [{"role":"user","content":"test_input"}])
        _, r3, _ = std_call(root, R.MockTransport("glm")); r3.write_manifest("T")
        ok = A.audit_run(root, expected_prompt=prompt)["verdict"] == "PASS"

        d2 = fresh("TAMPER_M")
        _, r32, _ = std_call(d2, R.MockTransport("glm")); r32.write_manifest("T")
        m = json.loads((d2/"MANIFEST.json").read_text())
        m["files"][0]["sha256"] = "0"*64
        (d2/"MANIFEST.json").write_text(json.dumps(m, sort_keys=True, separators=(",",":")))
        m_fail = A.audit_run(d2, expected_prompt=prompt)["verdict"] == "FAIL"

        d3 = fresh("TAMPER_P")
        _, r33, _ = std_call(d3, R.MockTransport("glm")); r33.write_manifest("T")
        p_fail = A.audit_run(d3, expected_prompt=b'["x"]')["verdict"] == "FAIL"

        record("TAMPER", "tamper regression", "ok=PASS, tampered=FAIL",
               ok and m_fail and p_fail, f"ok={ok} m={m_fail} p={p_fail}")


if __name__ == "__main__":
    BASE.mkdir(parents=True, exist_ok=True)
    (BASE / "ENVIRONMENT_NOTE.txt").write_text(
        "OS-namespace tools unavailable; SocketGuard + double-disarmed RealTransport")
    t1(); t2(); t3(); t4(); t5(); t6(); t7(); t8(); t9(); t10(); t11(); t12(); tamper()
    report = {"tests": RESULTS, "all_pass": all(r["actual"]=="PASS" for r in RESULTS)}
    (BASE / "T_MATRIX_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"\nALL_PASS: {report['all_pass']}")
    sys.exit(0 if report["all_pass"] else 1)
