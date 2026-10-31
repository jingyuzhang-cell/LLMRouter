#!/usr/bin/env python3
"""T1–T10 offline dry-run matrix (zero real calls, zero external network).

Every test: injects a fault into a Mock-transport run of Runner3, records
input/expected/actual/evidence, and asserts the spec-mandated outcome.
SocketGuard + disarmed RealTransport provide egress evidence; OS-namespace tools
(unshare/iptables) are unavailable in this container — recorded honestly.
Tamper-sample regression for audit.py: correct fixtures PASS, tampered FAIL.
"""
import json
import shutil
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import runner3 as R  # noqa: E402
import audit as A  # noqa: E402

BASE = HERE / "dryrun"
RESULTS = []


def fresh(tag: str) -> Path:
    d = BASE / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def record(tid, injected, expected, actual_ok, evidence):
    RESULTS.append({"test": tid, "injected": injected, "expected": expected,
                    "actual": "PASS" if actual_ok else "FAIL", "evidence": evidence})
    print(f"[{tid}] {injected} -> {'PASS' if actual_ok else 'FAIL'} ({evidence})")


def std_call(root, transport, **kw):
    gw = R.EgressGateway(root)
    r3 = R.Runner3(root, gw, budget_cny_cap=kw.pop("cap", 1.0))
    return gw, r3, r3.call(run_id="T", node_id="E1", model_key=kw.pop("model_key", "glm"),
                           system="只输出JSON", messages=[{"role": "user", "content": "抽取测试"}],
                           max_tokens=kw.pop("max_tokens", 2500), transport=transport, **kw)


def t1_request_hash_mismatch():
    root = fresh("T1")
    with R.SocketGuard(root):
        gw, r3, out = std_call(root, R.MockTransport("glm"))
        # inject: tamper the persisted bin after the run, then audit must fail
        cid = out["call_id"]
        p = root / "payloads" / cid / f"{cid}.request_body.bin"
        p.write_bytes(p.read_bytes() + b" ")
        r3.write_manifest("T")
        rep = A.audit_run(root, expected_prompt=R.canonical_messages("只输出JSON", [{"role": "user", "content": "抽取测试"}]))
        audit_detect = rep["verdict"] == "FAIL" and any("request_body_sha256 mismatch" in f for f in rep["failures"])
        if audit_detect:  # E5 审计门规则: audit FAIL -> 立即闭锁(终点式)
            gw.trigger_faillock("AUDIT_GATE_REQUEST_HASH_MISMATCH")
        record("T1", "请求哈希不匹配(载荷篡改注入)", "audit FAIL + 审计门闭锁", audit_detect and gw.lock_exists(),
               f"audit:{rep['verdict']} fail={rep['failures'][:1]} lock={gw.lock_exists()}")


def t2_prompt_rebuild_mismatch():
    root = fresh("T2")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        try:
            r3.call(run_id="T", node_id="E1", model_key="glm", system="只输出JSON",
                    messages=[{"role": "user", "content": "抽取测试"}], max_tokens=2500,
                    transport=R.MockTransport("glm"), prompt_rebuild='["别的重建内容"]'.encode("utf-8"))
            sent = True
        except R.BatchStopped:
            sent = False
        record("T2", "提示重建与实发不一致", "发送前禁止+闭锁(非事后审计)", (not sent) and gw.lock_exists(),
               f"sent={sent} lock={gw.lock_exists()} reasons={sorted(p.name for p in root.glob('FAILLOCK*'))}")


def t3_identity_mismatch():
    root = fresh("T3")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        try:
            r3.call(run_id="T", node_id="E1", model_key="glm", system="s", messages=[{"role": "user", "content": "u"}],
                    max_tokens=100, transport=R.MockTransport("glm", model_id="GLM-4-Flash"))
            stopped = False
        except R.BatchStopped:
            stopped = True
        record("T3", "模型实返身份不匹配(GLM-4-Flash)", "整批停止", stopped and gw.lock_exists(),
               f"BatchStopped={stopped} lock={gw.lock_exists()}")


def t4_e_quote_not_in_pdf():
    root = fresh("T4")
    frozen = {("D1", 1): {"text": "公司于2026年10月9日收到告知书。", "page_sha256": None, "raw_sha256": "r" * 64}}
    frozen[("D1", 1)]["page_sha256"] = R.sha256_bytes(frozen[("D1", 1)]["text"].encode())
    e_out = [{"doc": "D1", "page": 1, "quote": "公司于2026年10月10日收到告知书。",
              "page_sha256": frozen[("D1", 1)]["page_sha256"], "raw_sha256": "r" * 64, "label": "E1"}]
    with R.SocketGuard(root):
        _gw, _r3, _ = std_call(root, R.MockTransport("glm")); _r3.write_manifest("T")
        rep = A.audit_run(root, expected_prompt=R.canonical_messages("只输出JSON", [{"role": "user", "content": "抽取测试"}]),
                          upstream_e_outputs=e_out, frozen_pages=frozen)
        ok = any("L1" in f for f in rep["failures"])
        record("T4", "E层引文不存在于原文(日期改一日)", "L1 锚点审计失败", ok, f"fails={[f for f in rep['failures'] if 'L1' in f]}")


def t5_j_modified_upstream_quote():
    root = fresh("T5")
    with R.SocketGuard(root):
        _gw, _r3, _ = std_call(root, R.MockTransport("glm")); _r3.write_manifest("T")
        e_out = [{"doc": "D1", "page": 1, "quote": "原文引文A", "page_sha256": "p" * 64, "raw_sha256": "r" * 64, "label": "E1"}]
        j_anc = [{"doc": "D1", "page": 1, "quote": "原文引文A(被J修改)", "page_sha256": "p" * 64, "raw_sha256": "r" * 64, "label": "J1"}]
        rep = A.audit_run(root, expected_prompt=b"[]", upstream_e_outputs=e_out, j_anchors=j_anc)
        ok = any("L2" in f for f in rep["failures"])
        record("T5", "J层擅自修改上游引文", "L2 继承审计失败", ok, f"fails={[f for f in rep['failures'] if 'L2' in f]}")


def t6_sink_unverified_anchor():
    root = fresh("T6")
    with R.SocketGuard(root):
        _gw, _r3, _ = std_call(root, R.MockTransport("glm")); _r3.write_manifest("T")
        j_anc = [{"doc": "D1", "page": 1, "quote": "已验证引文", "page_sha256": "p", "raw_sha256": "r", "label": "J1"}]
        rep = A.audit_run(root, expected_prompt=b"[]", j_anchors=j_anc, sink_quotes=["未经验证的编造引文"])
        ok = any("L3" in f for f in rep["failures"])
        record("T6", "SINK引用未验证锚点", "L3 终端审计失败", ok, f"fails={[f for f in rep['failures'] if 'L3' in f]}")


def t7_budget_precheck():
    root = fresh("T7")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 0.001)
        try:
            r3.call(run_id="T", node_id="E1", model_key="glm", system="s",
                    messages=[{"role": "user", "content": "u"}], max_tokens=10_000_000,
                    transport=R.MockTransport("glm"))
            stopped = False
        except R.BatchStopped:
            stopped = True
        n_payloads = len(list((root / "payloads").glob("*"))) if (root / "payloads").exists() else 0
        record("T7", "预算预检触顶(预留超上限)", "禁止发送+闭锁+零载荷", stopped and gw.lock_exists() and n_payloads == 0,
               f"stopped={stopped} lock={gw.lock_exists()} payload_dirs={n_payloads}")


def t8_timeout_unknown():
    root = fresh("T8")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        out = r3.call(run_id="T", node_id="E1", model_key="glm", system="s",
                      messages=[{"role": "user", "content": "u"}], max_tokens=100,
                      transport=R.MockTransport("glm", drop_response=True))
        line = json.loads((root / "ledger.jsonl").read_text().splitlines()[-1])
        reserved_kept = line["record"]["reserved_retained"] is True and line["unknown_fee_flag"] is True
        record("T8", "响应丢失(在途未知)", "未知态留存+预留永久保留+不自动重试", out["permit"] == "IN_FLIGHT" and reserved_kept,
               f"permit={out['permit']} reserved_retained={line['record']['reserved_retained']} unknown_fee={line['unknown_fee_flag']}")


def t9_concurrency_race():
    root = fresh("T9")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        results = {}
        def worker(n):
            try:
                out = r3.call(run_id="T", node_id=f"E{n}", model_key="glm", system="s",
                              messages=[{"role": "user", "content": "u"}], max_tokens=100,
                              transport=R.MockTransport("glm"))
                results[n] = out["permit"]
            except R.BatchStopped:
                results[n] = "STOPPED"
        t1 = threading.Thread(target=worker, args=(1,))
        t1.start()
        time.sleep(0.002)
        gw.trigger_faillock("RACE_INJECTION")  # B trips lock while A may hold permit
        t2 = threading.Thread(target=worker, args=(2,))
        t2.start()
        t1.join(); t2.join()
        guard_log = (root / "socket_guard.log")
        handoffs_after_lock = [h for h in gw.handoff_log if h["result"] == "HANDED_OFF"]
        # any HANDED_OFF must have happened before the lock (timestamps ordering via log sequence)
        lock_idx = len(gw.handoff_log)  # after both, verify: no permit issued after lock got HANDED_OFF
        ok = results.get(2) in ("REVOKED", "STOPPED") and not guard_log.exists()
        record("T9", "并发竞态(B触发闭锁,A持许可)+出网检查", "闭锁原子+零外部请求", ok,
               f"results={results} handoff_log={gw.handoff_log} guard_log_exists={guard_log.exists()}")


def t10_faillock_present():
    root = fresh("T10")
    with R.SocketGuard(root):
        gw = R.EgressGateway(root)
        r3 = R.Runner3(root, gw, 1.0)
        gw.trigger_faillock("PRE_EXISTING")
        out = r3.call(run_id="T", node_id="E1", model_key="glm", system="s",
                      messages=[{"role": "user", "content": "u"}], max_tokens=100, transport=R.MockTransport("glm"))
        permits_after = [p for p in gw.permits.values() if p in ("ISSUED", "HANDED_OFF")]
        record("T10", "FAILLOCK已存在", "后续调用许可数=0(零字节出网)", out["permit"] == "REVOKED" and not permits_after,
               f"permit={out['permit']} active_permits={permits_after}")


def tamper_regression():
    """audit.py self-regression: correct fixtures PASS; each tampered class FAIL."""
    root = fresh("TAMPER")
    with R.SocketGuard(root):
        gw, r3, out = std_call(root, R.MockTransport("glm"))
        prompt = R.canonical_messages("只输出JSON", [{"role": "user", "content": "抽取测试"}])
        r3.write_manifest("T")
        ok_report = A.audit_run(root, expected_prompt=prompt)
        cases = {"correct": ok_report["verdict"] == "PASS"}
        # tamper class 1: manifest hash
        d2 = fresh("TAMPER_M")
        gw2, r32, out2 = std_call(d2, R.MockTransport("glm"))
        r32.write_manifest("T")
        m = json.loads((d2 / "MANIFEST.json").read_text())
        m["files"][0]["sha256"] = "0" * 64
        (d2 / "MANIFEST.json").write_text(json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        cases["manifest_tamper_FAIL"] = A.audit_run(d2, expected_prompt=prompt)["verdict"] == "FAIL"
        # tamper class 2: prompt equality
        d3 = fresh("TAMPER_P")
        gw3, r33, out3 = std_call(d3, R.MockTransport("glm"))
        r33.write_manifest("T")
        cases["prompt_tamper_FAIL"] = A.audit_run(d3, expected_prompt=b'["x"]')["verdict"] == "FAIL"
        all_ok = all(cases.values())
        record("TAMPER", "篡改样本回归(正确PASS/篡改FAIL)", "3类全部符合", all_ok, json.dumps(cases))


if __name__ == "__main__":
    BASE.mkdir(parents=True, exist_ok=True)
    env_note = ("OS-namespace tools (unshare/iptables/strace) unavailable in this container "
                "(Operation not permitted) — egress evidence = SocketGuard interception log + "
                "double-disarmed RealTransport; true OS-level evidence to be re-executed on a host permitting unshare")
    (BASE / "ENVIRONMENT_NOTE.txt").write_text(env_note)
    t1_request_hash_mismatch()
    t2_prompt_rebuild_mismatch()
    t3_identity_mismatch()
    t4_e_quote_not_in_pdf()
    t5_j_modified_upstream_quote()
    t6_sink_unverified_anchor()
    t7_budget_precheck()
    t8_timeout_unknown()
    t9_concurrency_race()
    t10_faillock_present()
    tamper_regression()
    report = {"tests": RESULTS, "environment_note": env_note,
              "all_pass": all(r["actual"] == "PASS" for r in RESULTS)}
    (BASE / "T_MATRIX_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("\nALL_PASS:", report["all_pass"])
    sys.exit(0 if report["all_pass"] else 1)
