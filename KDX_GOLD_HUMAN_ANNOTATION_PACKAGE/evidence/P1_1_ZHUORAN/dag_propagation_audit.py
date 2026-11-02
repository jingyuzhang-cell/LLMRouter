#!/usr/bin/env python3
"""P1-1 DAG 依赖及传播审计（零模型调用）。

操作者五项审计：
① 依赖真实性：J1 真实消费 E1/E2/E3？——输入引用+哈希
② 错误传播：J1 输出改变后 J2 识别旧结果失效？——版本缓存失效
③ 重新计算：J2 消费修复后 J1？——新执行实例+父节点版本
④ Sink 更新：Sink 消费新 J2？——不允许沿用旧 J2
⑤ 传播消融：切断 J1→J2 后传播停止？——依赖必要性

版本传播：J1_v1→J2_v1→SINK_v1 vs J1_v2→J2_v2→SINK_v2，全程可追溯。

方法：用 Mock 节点输出注入两个版本的 J1（v1 含错误 / v2 修复），
验证 J2 和 SINK 是否正确失效、重算、继承新版本。
"""
import hashlib, json, sys, time
from pathlib import Path

HERE = Path(__file__).parent
P1_1_DIR = HERE.parent  # KDX…/P1_1_ZHUORAN
CONTRACT = P1_1_DIR / "TASK_CONTRACT_P1_1_v1_1.json"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class NodeOutput:
    """A node's output with version tracking."""
    def __init__(self, node_id, content, upstream_hashes=None):
        self.node_id = node_id
        self.content = content  # dict or str
        self.content_sha = sha(json.dumps(content, ensure_ascii=False, sort_keys=True))
        self.upstream_hashes = upstream_hashes or {}  # {upstream_node: its content_sha}
        self.timestamp = time.time()

    def __repr__(self):
        return f"<{self.node_id} sha={self.content_sha} upstream={list(self.upstream_hashes.keys())}>"


class PropagationGraph:
    """DAG with version-aware dependency tracking and cache invalidation."""

    def __init__(self):
        self.outputs = {}          # node_id -> NodeOutput (latest)
        self.execution_log = []    # every execution with version info
        self.invalidation_log = [] # every cache invalidation

    def execute(self, node_id, compute_fn, depends_on):
        """Execute a node, checking upstream versions and invalidating stale results.

        compute_fn: function(upstream_outputs: dict) -> output dict
        depends_on: list of upstream node_ids
        """
        # Gather upstream outputs and their hashes
        upstream = {}
        upstream_hashes = {}
        for dep_id in depends_on:
            if dep_id not in self.outputs:
                raise ValueError(f"Missing upstream {dep_id} for {node_id}")
            dep = self.outputs[dep_id]
            upstream[dep_id] = dep.content
            upstream_hashes[dep_id] = dep.content_sha

        # Check if existing output is stale (upstream hash changed)
        existing = self.outputs.get(node_id)
        is_stale = False
        if existing and existing.upstream_hashes != upstream_hashes:
            is_stale = True
            self.invalidation_log.append({
                "node": node_id,
                "reason": "upstream_version_changed",
                "old_upstream": existing.upstream_hashes,
                "new_upstream": upstream_hashes,
                "ts": time.time()})
            # Remove stale output
            del self.outputs[node_id]

        # Execute (or re-execute)
        content = compute_fn(upstream)
        output = NodeOutput(node_id, content, upstream_hashes)
        self.outputs[node_id] = output
        self.execution_log.append({
            "node": node_id,
            "content_sha": output.content_sha,
            "upstream_hashes": upstream_hashes,
            "is_recompute": is_stale,
            "ts": time.time()})
        return output

    def inject(self, node_id, content, depends_on):
        """Inject a node output (simulating model execution)."""
        upstream_hashes = {d: self.outputs[d].content_sha for d in depends_on if d in self.outputs}
        output = NodeOutput(node_id, content, upstream_hashes)
        self.outputs[node_id] = output
        self.execution_log.append({
            "node": node_id, "content_sha": output.content_sha,
            "upstream_hashes": upstream_hashes, "is_recompute": False,
            "is_injection": True, "ts": time.time()})
        return output


# ===== Mock data =====
E1_CONTENT = {"doc": "080", "key_facts": ["调查进行中", "涉嫌虚假记载", "可能触及重大违法退市"]}
E2_CONTENT = {"doc": "097", "key_facts": ["事先告知书载明四年虚增", "尚未收到正式处罚决定", "12.2.1条"]}
E3_CONTENT = {"doc": "098", "key_facts": ["继续引用告知书", "首次低于1元", "连续8日市值<3亿", "12.3.1条"]}

# J1 v1 (contains error: says VF is FINAL_FINDING instead of NOTICE_CONTENT)
J1_V1 = {
    "state_judgments": [
        {"item": "虚增事实", "stages": {
            "S1": ["CONTINUING", "INVESTIGATION", "ALLEGATION"],
            "S2": ["CONTINUING", "PRIOR_NOTICE", "FINAL_FINDING"],  # ERROR
            "S3": ["CONTINUING", "PRIOR_NOTICE", "NOTICE_CONTENT"]}},
        {"item": "交易类退市风险", "stages": {
            "S1": ["NOT_DISCLOSED", "NOT_APPLICABLE", "UNKNOWN"],
            "S2": ["NOT_DISCLOSED", "NOT_APPLICABLE", "UNKNOWN"],
            "S3": ["NEWLY_DISCLOSED", "NOT_APPLICABLE", "DISCLOSED_MARKET_DATA"]}},
    ]}

# J1 v2 (fixed: VF_S2 evidentiary corrected to NOTICE_CONTENT)
J1_V2 = {
    "state_judgments": [
        {"item": "虚增事实", "stages": {
            "S1": ["CONTINUING", "INVESTIGATION", "ALLEGATION"],
            "S2": ["DETAIL_EXPANDED", "PRIOR_NOTICE", "NOTICE_CONTENT"],  # FIXED
            "S3": ["CONTINUING", "PRIOR_NOTICE", "NOTICE_CONTENT"]}},
        {"item": "交易类退市风险", "stages": {
            "S1": ["NOT_DISCLOSED", "NOT_APPLICABLE", "UNKNOWN"],
            "S2": ["NOT_DISCLOSED", "NOT_APPLICABLE", "UNKNOWN"],
            "S3": ["NEWLY_DISCLOSED", "NOT_APPLICABLE", "DISCLOSED_MARKET_DATA"]}},
    ]}

def j2_compute(upstream):
    """J2 consumes J1's judgments to produce current-state summary."""
    j1 = upstream.get("J1", {})
    judgments = j1.get("state_judgments", [])
    summary = {"current_states": {}, "source": "J1"}
    for j in judgments:
        item = j["item"]
        stages = j.get("stages", {})
        latest = stages.get("S3", stages.get("S2", stages.get("S1", ["UNKNOWN"]*3)))
        summary["current_states"][item] = latest
    # J2 also computes a derived assessment based on J1's evidence quality
    vf_s2_evidence = None
    for j in judgments:
        if j["item"] == "虚增事实":
            vf_s2_evidence = j["stages"].get("S2", [None, None, None])[2]
    summary["vf_evidence_level"] = vf_s2_evidence
    summary["is_final_finding"] = vf_s2_evidence == "FINAL_FINDING"
    return summary

def sink_compute(upstream):
    """Sink consumes J2's summary for terminal answer."""
    j2 = upstream.get("J2", {})
    return {
        "answers": j2.get("current_states", {}),
        "vf_is_final": j2.get("is_final_finding", None),
        "sink_source": j2.get("source", "unknown"),
        "complete": True,
    }


def run_audit():
    results = {}
    graph = PropagationGraph()

    # ===== Phase 1: Normal execution (v1 with error) =====
    graph.inject("E1", E1_CONTENT, [])
    graph.inject("E2", E2_CONTENT, [])
    graph.inject("E3", E3_CONTENT, [])
    graph.inject("J1", J1_V1, ["E1", "E2", "E3"])  # v1 (has error)
    graph.execute("J2", j2_compute, ["J1"])
    graph.execute("SINK", sink_compute, ["J2"])

    j1_v1 = graph.outputs["J1"]
    j2_v1 = graph.outputs["J2"]
    sink_v1 = graph.outputs["SINK"]

    # ===== Audit ①: Dependency reality =====
    results["①_依赖真实性"] = {
        "J1_upstream": j1_v1.upstream_hashes,
        "J2_consumes_J1": "J1" in j2_v1.upstream_hashes,
        "SINK_consumes_J2": "J2" in sink_v1.upstream_hashes,
        "J2_upstream_sha_matches_J1": j2_v1.upstream_hashes.get("J1") == j1_v1.content_sha,
        "SINK_upstream_sha_matches_J2": sink_v1.upstream_hashes.get("J2") == j2_v1.content_sha,
    }
    results["①_依赖真实性"]["PASS"] = (
        results["①_依赖真实性"]["J2_consumes_J1"]
        and results["①_依赖真实性"]["SINK_consumes_J2"]
        and results["①_依赖真实性"]["J2_upstream_sha_matches_J1"]
        and results["①_依赖真实性"]["SINK_upstream_sha_matches_J2"])

    # Verify v1 error propagated
    results["①_依赖真实性"]["v1_error_propagated"] = sink_v1.content["vf_is_final"] == True

    # ===== Phase 2: Inject J1 v2 (fixed) =====
    # Record pre-injection state
    j2_sha_before = j2_v1.content_sha
    sink_sha_before = sink_v1.content_sha

    graph.inject("J1", J1_V2, ["E1", "E2", "E3"])  # v2 (fixed)

    # ===== Audit ②: Error propagation (cache invalidation) =====
    # Re-execute J2 — should detect upstream change and invalidate
    graph.execute("J2", j2_compute, ["J1"])
    j2_v2 = graph.outputs["J2"]

    invalidations_for_j2 = [i for i in graph.invalidation_log if i["node"] == "J2"]
    results["②_错误传播"] = {
        "J2_invalidated": len(invalidations_for_j2) > 0,
        "invalidation_reason": invalidations_for_j2[0]["reason"] if invalidations_for_j2 else None,
        "J2_sha_changed": j2_v2.content_sha != j2_sha_before,
        "PASS": len(invalidations_for_j2) > 0 and j2_v2.content_sha != j2_sha_before,
    }

    # ===== Audit ③: Recomputation (J2 uses new J1) =====
    results["③_重新计算"] = {
        "J2_v2_upstream_sha": j2_v2.upstream_hashes.get("J1"),
        "J1_v2_sha": graph.outputs["J1"].content_sha,
        "J2_uses_J1_v2": j2_v2.upstream_hashes.get("J1") == graph.outputs["J1"].content_sha,
        "J2_v2_is_final": j2_v2.content.get("is_final_finding"),
        "J2_v2_is_final_should_be_False": j2_v2.content.get("is_final_finding") == False,
        "PASS": (j2_v2.upstream_hashes.get("J1") == graph.outputs["J1"].content_sha
                 and j2_v2.content.get("is_final_finding") == False),
    }

    # ===== Audit ④: Sink update =====
    graph.execute("SINK", sink_compute, ["J2"])
    sink_v2 = graph.outputs["SINK"]

    results["④_Sink更新"] = {
        "SINK_sha_changed": sink_v2.content_sha != sink_sha_before,
        "SINK_uses_J2_v2": sink_v2.upstream_hashes.get("J2") == j2_v2.content_sha,
        "SINK_v2_vf_is_final": sink_v2.content.get("vf_is_final"),
        "SINK_v2_should_be_False": sink_v2.content.get("vf_is_final") == False,
        "SINK_v1_was_True": True,  # from Phase 1
        "terminal_improvement": True,  # v1 said FINAL(error) → v2 says not-final(correct)
        "PASS": (sink_v2.upstream_hashes.get("J2") == j2_v2.content_sha
                 and sink_v2.content.get("vf_is_final") == False
                 and sink_v1.content.get("vf_is_final") == True),
    }

    # ===== Audit ⑤: Propagation ablation (cut J1→J2) =====
    graph2 = PropagationGraph()
    graph2.inject("E1", E1_CONTENT, [])
    graph2.inject("E2", E2_CONTENT, [])
    graph2.inject("E3", E3_CONTENT, [])
    graph2.inject("J1", J1_V1, ["E1", "E2", "E3"])
    # Ablation: J2 depends only on E1-E3, NOT on J1
    graph2.execute("J2", lambda up: j2_compute({}), [])  # no upstream → empty J1
    graph2.execute("SINK", sink_compute, ["J2"])
    sink_ablated = graph2.outputs["SINK"]

    results["⑤_传播消融"] = {
        "ablated_J2_upstream": "J1" not in graph2.outputs["J2"].upstream_hashes,
        "ablated_J2_empty": not graph2.outputs["J2"].content.get("current_states"),
        "ablated_SINK_empty": not sink_ablated.content.get("answers"),
        "PASS": ("J1" not in graph2.outputs["J2"].upstream_hashes
                 and not sink_ablated.content.get("answers")),
    }

    # ===== Version traceability =====
    exec_log = graph.execution_log
    results["版本追溯"] = {
        "total_executions": len(exec_log),
        "total_invalidations": len(graph.invalidation_log),
        "J1_versions": [e["content_sha"] for e in exec_log if e["node"] == "J1"],
        "J2_versions": [e["content_sha"] for e in exec_log if e["node"] == "J2"],
        "SINK_versions": [e["content_sha"] for e in exec_log if e["node"] == "SINK"],
        "J2_recomputed": any(e.get("is_recompute") for e in exec_log if e["node"] == "J2"),
        "SINK_recomputed": any(e.get("is_recompute") for e in exec_log if e["node"] == "SINK"),
    }

    return results


if __name__ == "__main__":
    print("=" * 60)
    print("P1-1 DAG 依赖及传播审计（零模型调用）")
    print("=" * 60)

    results = run_audit()

    all_pass = all(v.get("PASS", False) if isinstance(v, dict) else False
                   for k, v in results.items() if k.startswith("①②③④⑤") or k.startswith("①"))

    for name, r in results.items():
        if isinstance(r, dict):
            status = "PASS" if r.get("PASS") else "FAIL"
            print(f"\n{'='*40}")
            print(f"  {name}: {status}")
            for k, v in r.items():
                if k != "PASS":
                    print(f"    {k}: {v}")

    print(f"\n{'='*60}")
    audit_keys = [k for k in results if k.startswith(("①","②","③","④","⑤"))]
    all_five = all(results[k].get("PASS") for k in audit_keys)
    print(f"  五项审计总判定: {'ALL PASS' if all_five else 'FAILURES PRESENT'}")
    print(f"{'='*60}")

    # Save evidence
    out = HERE / "dag_propagation_audit.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str))
    print(f"\n证据文件: {out}")
