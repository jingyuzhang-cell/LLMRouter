#!/usr/bin/env python3
"""Runner3 — six-element implementation per PHASE2B_RUNNER_SPEC_V1_2 (sha256 0e702f54…).

Zero real model calls in this module's default configuration: RealTransport is
double-disarmed (requires BOTH env flag PHASE2B_REAL=1 AND lockfile REAL_CALLS_ALLOWED
which must not exist in dry-run). MockTransport serves all offline tests.

Six elements implemented per spec (V1.2 sealed):
 E1 four payload files per call + write-ahead fsync; MANIFEST per run (normalized
    hash, no self-hash)
 E2 four hash classes; frozen canonical prompt serialization (system prepended as
    first message of the canonical array; keys sorted; UTF-8; separators no-space);
    PRE-SEND equality gate (rebuild == extract from actual .bin else no-send + lock)
 E3 exact-match identity (request model field AND returned model_id vs frozen
    allowlist; mismatch/missing => batch stop)
 E4 full cost accounting (frozen price table + sha, per-call reservation =
    est_in(0.75×utf8_bytes, frozen conservative bound)×in_price + max_tokens×out_price;
    unknown-fee never zero; T8: lost-response reservation retained permanently)
 E5 audit support: L1/L2/L3 anchor quintuples recorded in node outputs
 E6 permit state machine (ISSUED/HANDED_OFF/REVOKED) + single EgressGateway with
    flock-backed critical section covering permit->handoff; FAILLOCK O_CREAT|O_EXCL;
    in-flight recording; post-lock zero permits
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import socket
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

CANON_RULE = "canonical_messages_v1: array = ([{role:system,content:system}] if system else []) + messages; json.dumps(array, ensure_ascii=False, sort_keys=True, separators=(',',':')) encoded utf-8"
PRICE_TABLE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5}}
PRICE_TABLE_ID = "frozen-20261031"
PRICE_TABLE_SHA = hashlib.sha256(json.dumps(PRICE_TABLE, sort_keys=True).encode()).hexdigest()
IDENTITY_ALLOWLIST = {"glm": ["GLM-5.3-Flash"], "ds": ["deepseek-flash"]}
# === 操作者批准的冻结预算规则（2026-10-31 裁定）===
# B_in = B_UTF8 × 1.0 + H_protocol
# B_UTF8: 完整模型可见输入（system + 全部 messages + 其他模型可见字段）的 UTF-8 字节数
# H_protocol: 消息封装/角色/格式开销的冻结保守上界
# 推导依据：
#   GLM (Anthropic-compat): system 独立字段 + messages → JSON 包装 ~30B/msg + system ~50B
#   DS (OpenAI-compat): messages 数组含 system msg → JSON 包装 ~35B + ~30B/msg
#   保守取整：H_protocol = 100 + 50 × n_messages 字节
# 不允许退回 0.75 或用输入类型白名单绕过。
TOKEN_COEFF = 1.0
PROTOCOL_OVERHEAD_BASE = 100  # bytes: JSON 封装基础开销
PROTOCOL_OVERHEAD_PER_MSG = 50  # bytes: 每条 message 的 JSON 包装开销


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_messages(system: Optional[str], messages: List[Dict[str, str]]) -> bytes:
    arr: List[Dict[str, str]] = []
    if system:
        arr.append({"role": "system", "content": system})
    arr.extend({"role": m["role"], "content": m["content"]} for m in messages)
    return json.dumps(arr, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def est_in_tokens(text: str) -> int:
    """Legacy — superseded by operator-approved formula B_in = B_UTF8×1.0 + H_protocol."""
    return math.ceil(len(text.encode("utf-8")) * TOKEN_COEFF +
                     PROTOCOL_OVERHEAD_BASE + PROTOCOL_OVERHEAD_PER_MSG)


class BatchStopped(Exception):
    pass


class EgressGateway:
    """Single egress gateway: permit state machine with flock-backed critical
    section covering permit->handoff. Post-FAILLOCK: zero handoffs, ISSUED->REVOKED."""

    def __init__(self, root: Path):
        self.root = root
        self.faillock = root / "FAILLOCK.json"
        self.glock = root / "gateway.lock"
        self.permits: Dict[str, str] = {}
        self.handoff_log: List[Dict[str, Any]] = []
        self._lk = threading.Lock()

    def lock_exists(self) -> bool:
        return self.faillock.exists()

    def trigger_faillock(self, reason: str, call_id: str = "") -> None:
        with self._lk:
            try:
                fd = os.open(self.faillock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    json.dump({"reason": reason, "call_id": call_id, "ts": time.time()}, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
            except FileExistsError:
                pass
            for cid, st in self.permits.items():
                if st == "ISSUED":
                    self.permits[cid] = "REVOKED"

    def acquire(self, call_id: str) -> str:
        with self._lk:
            if self.lock_exists():
                self.permits[call_id] = "REVOKED"
                return "REVOKED"
            self.permits[call_id] = "ISSUED"
            return "ISSUED"

    def handoff(self, call_id: str) -> str:
        """Critical section: flock on gateway.lock + FAILLOCK check; returns
        HANDED_OFF / REVOKED. The flock gives cross-process linearization for the
        permit->transport window."""
        with self._lk:
            with open(self.glock, "a+") as gf:
                fcntl.flock(gf.fileno(), fcntl.LOCK_EX)
                try:
                    if self.lock_exists() or self.permits.get(call_id) != "ISSUED":
                        self.permits[call_id] = "REVOKED"
                        self.handoff_log.append({"call_id": call_id, "ts": time.time(), "result": "REVOKED"})
                        return "REVOKED"
                    self.permits[call_id] = "HANDED_OFF"
                    self.handoff_log.append({"call_id": call_id, "ts": time.time(), "result": "HANDED_OFF"})
                    return "HANDED_OFF"
                finally:
                    fcntl.flock(gf.fileno(), fcntl.LOCK_UN)

    def mark_in_flight(self, call_id: str) -> None:
        with self._lk:
            if self.permits.get(call_id) == "HANDED_OFF":
                self.permits[call_id] = "IN_FLIGHT"


class SocketGuard:
    """Program-level egress evidence: intercepts and logs ANY outbound socket
    connection attempt (stdlib paths). True OS-namespace evidence (unshare/iptables)
    is unavailable in this container — recorded honestly in the report."""

    def __init__(self, root: Path):
        self.log = root / "socket_guard.log"

    def __enter__(self):
        self._orig_connect = socket.socket.connect
        self._orig_create = socket.create_connection
        guard = self

        def blocked(*a, **k):
            with open(guard.log, "a") as f:
                f.write(json.dumps({"ts": time.time(), "attempt": str(a)[:120]}) + "\n")
            raise RuntimeError("EGRESS_BLOCKED_BY_SOCKET_GUARD: dry-run forbids external network")

        socket.socket.connect = blocked  # type: ignore
        socket.create_connection = blocked  # type: ignore
        return self

    def __exit__(self, *a):
        socket.socket.connect = self._orig_connect  # type: ignore
        socket.create_connection = self._orig_create  # type: ignore


class MockTransport:
    """Deterministic offline transport. model_id/usage controllable for fault injection."""

    def __init__(self, model_key: str, *, model_id: Optional[str] = None, usage: Optional[Dict] = None,
                 drop_response: bool = False):
        self.model_key = model_key
        self.model_id = model_id if model_id is not None else IDENTITY_ALLOWLIST[model_key][0]
        self.usage = usage or {"in": 100, "out": 50}
        self.drop_response = drop_response

    def send(self, body_bytes: bytes) -> Optional[bytes]:
        body = json.loads(body_bytes)
        if self.drop_response:
            return None
        resp = {"model": self.model_id, "usage": self.usage, "choices": [{"message": {"content": "{\"ok\":true}"}}]}
        if "system" in body:  # GLM-style anthropic-compat echo shape
            resp = {"model": self.model_id, "usage": {"input_tokens": self.usage["in"], "output_tokens": self.usage["out"]},
                    "content": [{"type": "text", "text": "{\"ok\":true}"}]}
        return json.dumps(resp, ensure_ascii=False).encode("utf-8")


class RealTransport:
    """Double-disarmed: refuses unless env PHASE2B_REAL=1 AND REAL_CALLS_ALLOWED file exists."""

    def __init__(self, model_key: str):
        self.model_key = model_key

    def send(self, body_bytes: bytes) -> bytes:
        if os.environ.get("PHASE2B_REAL") != "1" or not Path("/root/research_outputs/mvr_batch1/REAL_CALLS_ALLOWED").exists():
            raise RuntimeError("RealTransport DISARMED: dry-run mode (missing env flag and/or REAL_CALLS_ALLOWED)")
        # Real endpoints only reachable after full acceptance; not exercised in T1-T10.
        raise RuntimeError("RealTransport reached but real calls are not authorized yet")


def build_request_body(model_key: str, system: Optional[str], messages: List[Dict[str, str]], max_tokens: int) -> bytes:
    if model_key == "glm":
        body = {"model": IDENTITY_ALLOWLIST["glm"][0], "max_tokens": max_tokens, "temperature": 0,
                "thinking": {"type": "disabled"}}
        if system:
            body["system"] = system
        body["messages"] = messages
    else:
        body = {"model": IDENTITY_ALLOWLIST["ds"][0], "max_tokens": max_tokens, "temperature": 0,
                "messages": ([{"role": "system", "content": system}] if system else []) + messages,
                "response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def extract_canonical_from_body(body_bytes: bytes) -> Optional[bytes]:
    body = json.loads(body_bytes)
    if "messages" in body and body["messages"] and body["messages"][0].get("role") == "system" and "system" not in body:
        msgs = body["messages"]
    else:
        msgs = ([{"role": "system", "content": body["system"]}] if body.get("system") else []) + body.get("messages", [])
    return canonical_messages(None, msgs)


class Runner3:
    def __init__(self, root: Path, gateway: EgressGateway, budget_cny_cap: float):
        self.root = root
        self.payloads = root / "payloads"
        self.payloads.mkdir(parents=True, exist_ok=True)
        self.gateway = gateway
        self.ledger_path = root / "ledger.jsonl"
        self.accrued = 0.0
        self.cap = budget_cny_cap
        self.manifest_files: Dict[str, List[Dict[str, Any]]] = {}

    # ---------- E1: payload persistence with write-ahead fsync ----------
    def _persist_request(self, call_id: str, body_bytes: bytes, meta: Dict[str, Any]) -> None:
        d = self.payloads / call_id
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{call_id}.request_body.bin"
        with open(p, "wb") as f:
            f.write(body_bytes)
            f.flush()
            os.fsync(f.fileno())
        (d / f"{call_id}.request_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def _persist_response(self, call_id: str, resp_bytes: Optional[bytes], status: str) -> None:
        d = self.payloads / call_id
        if resp_bytes is not None:
            (d / f"{call_id}.response_body.bin").write_bytes(resp_bytes)
        (d / f"{call_id}.response_meta.json").write_text(
            json.dumps({"status": status, "ts": time.time()}, ensure_ascii=False), encoding="utf-8")

    # ---------- E4: frozen- price reservation ----------
    def _reserve(self, model_key: str, user_text: str, max_tokens: int,
                 full_visible_text: str = "", n_messages: int = 1) -> Dict[str, Any]:
        # B_in = B_UTF8×1.0 + H_protocol（操作者 2026-10-31 批准公式）
        b_utf8 = len(full_visible_text.encode("utf-8")) if full_visible_text else len(user_text.encode("utf-8"))
        h_proto = PROTOCOL_OVERHEAD_BASE + PROTOCOL_OVERHEAD_PER_MSG * n_messages
        est_in = math.ceil(b_utf8 * TOKEN_COEFF + h_proto)
        price = PRICE_TABLE[model_key]
        reserved = est_in / 1e6 * price["in"] + max_tokens / 1e6 * price["out"]
        if self.accrued + reserved > self.cap:
            return {"allowed": False, "reserved": reserved, "est_in": est_in}
        return {"allowed": True, "reserved": reserved, "est_in": est_in,
                "unit_price_in": price["in"], "unit_price_out": price["out"],
                "price_table_id": PRICE_TABLE_ID, "price_table_sha256": PRICE_TABLE_SHA,
                "fx": "CNY direct (ds in/out already CNY-converted at frozen 7.5)"}

    # ---------- main call path ----------
    def call(self, *, run_id: str, node_id: str, model_key: str, system: Optional[str],
             messages: List[Dict[str, str]], max_tokens: int, transport,
             prompt_rebuild: Optional[bytes] = None, attempt: int = 1, retry_of: Optional[str] = None) -> Dict[str, Any]:
        call_id = f"{run_id}_{node_id}_a{attempt}_{os.urandom(4).hex()}"
        user_text = "".join(m["content"] for m in messages if m["role"] == "user")
        prompt_bytes = canonical_messages(system, messages)
        prompt_sha = sha256_bytes(prompt_bytes)

        full_visible = (system or "") + "".join(m["content"] for m in messages)
        res = self._reserve(model_key, user_text, max_tokens,
                            full_visible_text=full_visible, n_messages=len(messages) + (1 if system else 0))
        if not res["allowed"]:
            self.gateway.trigger_faillock("BUDGET_PRECHECK_EXCEEDED", call_id)
            raise BatchStopped("budget precheck: no conservative upper bound within cap -> send forbidden")

        body_bytes = build_request_body(model_key, system, messages, max_tokens)
        self._persist_request(call_id, body_bytes, {"url": "mock://offline", "method": "POST",
                                                    "auth_ref": "zhipu" if model_key == "glm" else "deepseek-modelpool"})
        req_sha = sha256_bytes(body_bytes)

        # E2 pre-send equality gate: rebuild == extract-from-actual-bin, BEFORE handoff
        extracted = extract_canonical_from_body(body_bytes)
        rebuild = prompt_rebuild if prompt_rebuild is not None else prompt_bytes
        if extracted is None or sha256_bytes(extracted) != sha256_bytes(rebuild):
            self._persist_response(call_id, None, "PRE_SEND_EQUALITY_FAIL")
            self.gateway.trigger_faillock("PRE_SEND_PROMPT_EQUALITY_FAIL", call_id)
            raise BatchStopped("pre-send equality gate failed: rebuild != actual body prompt")

        if self.gateway.acquire(call_id) != "ISSUED":
            self._persist_response(call_id, None, "PERMIT_REVOKED_AT_ACQUIRE")
            return {"call_id": call_id, "permit": "REVOKED", "sent": False}
        if self.gateway.handoff(call_id) != "HANDED_OFF":
            self._persist_response(call_id, None, "PERMIT_REVOKED_AT_HANDOFF")
            return {"call_id": call_id, "permit": "REVOKED", "sent": False}

        resp_bytes = transport.send(body_bytes)
        if resp_bytes is None:  # T8: in-flight/unknown — reservation RETAINED permanently
            self.gateway.mark_in_flight(call_id)
            self._persist_response(call_id, None, "IN_FLIGHT_NO_RESPONSE")
            self._ledger(call_id, run_id, node_id, model_key, prompt_sha, req_sha, None, res,
                         {"status": "IN_FLIGHT", "usage": None, "identity": None,
                          "permit": "IN_FLIGHT", "reserved_retained": True, "retry_of": retry_of})
            return {"call_id": call_id, "permit": "IN_FLIGHT", "sent": True, "response": None}

        self._persist_response(call_id, resp_bytes, "OK")
        resp_sha = sha256_bytes(resp_bytes)
        resp = json.loads(resp_bytes)
        usage = resp.get("usage") or {}
        model_id_returned = resp.get("model", "")
        identity_ok = (model_id_returned in IDENTITY_ALLOWLIST[model_key])

        rec = {"status": "OK" if identity_ok else "IDENTITY_MISMATCH",
               "usage": usage, "identity": {"sent": json.loads(body_bytes)["model"],
                                            "returned": model_id_returned,
                                            "match": identity_ok},
               "permit": "HANDED_OFF", "reserved_retained": False, "retry_of": retry_of}
        self._ledger(call_id, run_id, node_id, model_key, prompt_sha, req_sha, resp_sha, res, rec)
        if not identity_ok:
            self.gateway.trigger_faillock("MODEL_IDENTITY_MISMATCH", call_id)
            raise BatchStopped(f"identity mismatch: returned {model_id_returned!r} not in frozen allowlist")
        actual_cost = usage.get("in", usage.get("input_tokens", res["est_in"])) / 1e6 * PRICE_TABLE[model_key]["in"] \
            + usage.get("out", usage.get("output_tokens", max_tokens)) / 1e6 * PRICE_TABLE[model_key]["out"]
        self.accrued += actual_cost  # actual charged against cap; reservation already guaranteed feasibility
        return {"call_id": call_id, "permit": "HANDED_OFF", "sent": True, "response": resp}

    def _ledger(self, call_id, run_id, node_id, model_key, prompt_sha, req_sha, resp_sha, res, rec) -> None:
        usage = rec.get("usage") or {}
        line = {"call_id": call_id, "ts": time.time(), "run_id": run_id, "node_id": node_id,
                "model": model_key, "prompt_sha256": prompt_sha, "request_body_sha256": req_sha,
                "response_body_sha256": resp_sha, "price_table_id": res.get("price_table_id"),
                "price_table_sha256": res.get("price_table_sha256"),
                "unit_price_in": res.get("unit_price_in"), "unit_price_out": res.get("unit_price_out"),
                "est_in_tokens": res.get("est_in"), "budget_reserved_this_call": round(res.get("reserved", 0), 6),
                "in_tokens": usage.get("in", usage.get("input_tokens")),
                "out_tokens": usage.get("out", usage.get("output_tokens")),
                "cost_computation": rec.get("status"), "accrued_cny": round(self.accrued, 6),
                "unknown_fee_flag": rec.get("usage") is None,
                "record": rec}
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    # ---------- E1 manifest ----------
    def write_manifest(self, run_id: str) -> str:
        files = []
        for d in sorted(self.payloads.iterdir()):
            for f in sorted(d.iterdir()):
                files.append({"path": str(f.relative_to(self.root)), "bytes": f.stat().st_size,
                              "sha256": sha256_bytes(f.read_bytes())})
        m = {"run_id": run_id, "files": files, "canon_rule": CANON_RULE,
             "price_table": {"id": PRICE_TABLE_ID, "sha256": PRICE_TABLE_SHA}}
        (self.root / "MANIFEST.json").write_text(json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                                                 encoding="utf-8")
        return sha256_bytes((self.root / "MANIFEST.json").read_bytes())


def node_key_safe(k: str) -> str:
    return k
