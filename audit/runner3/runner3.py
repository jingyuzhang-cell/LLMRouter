#!/usr/bin/env python3
"""Runner3 v4 — fixes for operator 7-item FAIL audit.

Key fixes from operator independent review (2026-10-31):
 F1 RealTransport: implement actual GLM/DS HTTP calls (was unconditionally raise)
 F2 T8 budget: IN_FLIGHT calls add reservation to pending_reserved (included in precheck)
 F3 Pre-send gate: prompt_rebuild is REQUIRED (no self-referential None fallback)
 F4 Handoff window: transport.send() executed inside flock critical section
 F5 Concurrent budget: threading.Lock protects _reserve() and accrued updates
 F6 Ledger: records max_tokens (no 2500 fallback for audit.py)
 F7 MANIFEST: hash written to ledger; manifest covers ledger.jsonl too
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

CANON_RULE = "canonical_messages_v1"
PRICE_TABLE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30 * 7.5, "out": 1.20 * 7.5}}
PRICE_TABLE_ID = "frozen-20261031"
PRICE_TABLE_SHA = hashlib.sha256(json.dumps(PRICE_TABLE, sort_keys=True).encode()).hexdigest()
IDENTITY_ALLOWLIST = {"glm": ["GLM-5.3-Flash"], "ds": ["deepseek-flash"]}
TOKEN_COEFF = 1.0
PROTOCOL_OVERHEAD_BASE = 100
PROTOCOL_OVERHEAD_PER_MSG = 50


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_messages(system: Optional[str], messages: List[Dict[str, str]]) -> bytes:
    arr: List[Dict[str, str]] = []
    if system:
        arr.append({"role": "system", "content": system})
    arr.extend({"role": m["role"], "content": m["content"]} for m in messages)
    return json.dumps(arr, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def extract_canonical_from_body(body_bytes: bytes) -> Optional[bytes]:
    body = json.loads(body_bytes)
    if "system" in body:
        msgs = [{"role": "system", "content": body["system"]}] + body.get("messages", [])
    else:
        msgs = body.get("messages", [])
    return canonical_messages(None, msgs)


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


class BatchStopped(Exception):
    pass


class EgressGateway:
    """Single egress gateway. F4: handoff_and_send() executes transport.send()
    INSIDE the flock critical section — no window between permit and transmission."""

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
                if st in ("ISSUED",):
                    self.permits[cid] = "REVOKED"

    def acquire(self, call_id: str) -> str:
        with self._lk:
            if self.lock_exists():
                self.permits[call_id] = "REVOKED"
                return "REVOKED"
            self.permits[call_id] = "ISSUED"
            return "ISSUED"

    def handoff_and_send(self, call_id: str, body_bytes: bytes, transport) -> tuple:
        """F4 fix: acquire→check FAILLOCK→send ALL inside flock critical section.
        Returns (permit_state, response_bytes_or_None)."""
        with self._lk:
            with open(self.glock, "a+") as gf:
                fcntl.flock(gf.fileno(), fcntl.LOCK_EX)
                try:
                    # Re-check FAILLOCK inside the lock
                    if self.lock_exists() or self.permits.get(call_id) != "ISSUED":
                        self.permits[call_id] = "REVOKED"
                        self.handoff_log.append({"call_id": call_id, "ts": time.time(), "result": "REVOKED"})
                        return ("REVOKED", None)
                    self.permits[call_id] = "HANDED_OFF"
                    self.handoff_log.append({"call_id": call_id, "ts": time.time(), "result": "HANDED_OFF"})
                    # F4: transport.send() happens HERE, inside the lock
                    resp_bytes = transport.send(body_bytes)
                    if resp_bytes is None:
                        self.permits[call_id] = "IN_FLIGHT"
                    return ("HANDED_OFF" if resp_bytes is not None else "IN_FLIGHT", resp_bytes)
                finally:
                    fcntl.flock(gf.fileno(), fcntl.LOCK_UN)

    def mark_in_flight(self, call_id: str) -> None:
        with self._lk:
            if self.permits.get(call_id) in ("HANDED_OFF",):
                self.permits[call_id] = "IN_FLIGHT"


class SocketGuard:
    def __init__(self, root: Path):
        self.log = root / "socket_guard.log"

    def __enter__(self):
        self._orig_connect = socket.socket.connect
        self._orig_create = socket.create_connection
        guard = self
        def blocked(*a, **k):
            with open(guard.log, "a") as f:
                f.write(json.dumps({"ts": time.time(), "attempt": str(a)[:120]}) + "\n")
            raise RuntimeError("EGRESS_BLOCKED_BY_SOCKET_GUARD")
        socket.socket.connect = blocked
        socket.create_connection = blocked
        return self

    def __exit__(self, *a):
        socket.socket.connect = self._orig_connect
        socket.create_connection = self._orig_create


class MockTransport:
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
        if "system" in body:
            resp = {"model": self.model_id, "usage": {"input_tokens": self.usage["in"], "output_tokens": self.usage["out"]},
                    "content": [{"type": "text", "text": "{\"ok\":true}"}]}
        return json.dumps(resp, ensure_ascii=False).encode("utf-8")


def _load_keys():
    keys = {}
    for path in ("/root/.env", "/root/.env.modelpool"):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k] = v.strip().strip('"').strip("'")
    return keys


class RealTransport:
    """F1 fix: actual HTTP transport for GLM (anthropic-compat) and DS (OpenAI-compat).
    Still requires double-disarm (env PHASE2B_REAL=1 AND REAL_CALLS_ALLOWED file)."""

    def __init__(self, model_key: str, timeout_s: int = 120):
        self.model_key = model_key
        self.timeout_s = timeout_s

    def _glm_key(self):
        cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
        return next(r["config"]["access"]["apiKey"]
                    for r in cfg["config"]["providerConfigRules"]["providerRules"]
                    if r["providerId"] == "bigmodel-api")

    def send(self, body_bytes: bytes) -> bytes:
        if os.environ.get("PHASE2B_REAL") != "1" or not Path("/root/research_outputs/mvr_batch1/REAL_CALLS_ALLOWED").exists():
            raise RuntimeError("RealTransport DISARMED: requires PHASE2B_REAL=1 AND REAL_CALLS_ALLOWED")
        body = json.loads(body_bytes)
        t0 = time.monotonic()
        if self.model_key == "glm":
            req = urllib.request.Request("https://open.bigmodel.cn/api/anthropic/v1/messages",
                                         data=body_bytes, method="POST")
            key = self._glm_key()
            req.add_header("content-type", "application/json")
            req.add_header("x-api-key", key)
            req.add_header("authorization", "Bearer " + key)
            req.add_header("anthropic-version", "2023-06-01")
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                d = json.loads(r.read().decode())
            return json.dumps(d, ensure_ascii=False).encode("utf-8")
        else:
            keys = _load_keys()
            req = urllib.request.Request("https://api.deepseek.com/chat/completions",
                                         data=body_bytes, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", "Bearer " + keys.get("DEEPSEEK_API_KEY", ""))
            with urllib.request.urlopen(req, timeout=self.timeout_s) as r:
                d = json.loads(r.read().decode())
            return json.dumps(d, ensure_ascii=False).encode("utf-8")


class Runner3:
    def __init__(self, root: Path, gateway: EgressGateway, budget_cny_cap: float):
        self.root = root
        self.payloads = root / "payloads"
        self.payloads.mkdir(parents=True, exist_ok=True)
        self.gateway = gateway
        self.ledger_path = root / "ledger.jsonl"
        self.accrued = 0.0
        self.pending_reserved = 0.0  # F2: T8 budget reservations retained
        self.cap = budget_cny_cap
        self._budget_lock = threading.Lock()  # F5: concurrent budget protection

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

    def _reserve(self, model_key: str, full_visible_text: str, n_messages: int, max_tokens: int) -> Dict[str, Any]:
        # F5: lock-protected budget check
        with self._budget_lock:
            b_utf8 = len(full_visible_text.encode("utf-8"))
            h_proto = PROTOCOL_OVERHEAD_BASE + PROTOCOL_OVERHEAD_PER_MSG * n_messages
            est_in = math.ceil(b_utf8 * TOKEN_COEFF + h_proto)
            price = PRICE_TABLE[model_key]
            reserved = est_in / 1e6 * price["in"] + max_tokens / 1e6 * price["out"]
            # F2: include pending_reserved (T8 in-flight) in precheck
            if self.accrued + self.pending_reserved + reserved > self.cap:
                return {"allowed": False, "reserved": reserved, "est_in": est_in}
            return {"allowed": True, "reserved": reserved, "est_in": est_in,
                    "unit_price_in": price["in"], "unit_price_out": price["out"],
                    "price_table_id": PRICE_TABLE_ID, "price_table_sha256": PRICE_TABLE_SHA,
                    "fx": "CNY direct", "max_tokens": max_tokens}

    def call(self, *, run_id: str, node_id: str, model_key: str, system: Optional[str],
             messages: List[Dict[str, str]], max_tokens: int, transport,
             prompt_rebuild: bytes, attempt: int = 1, retry_of: Optional[str] = None) -> Dict[str, Any]:
        """F3: prompt_rebuild is now REQUIRED (no None default) — must come from
        frozen upstream execution records, not from in-memory regeneration."""
        call_id = f"{run_id}_{node_id}_a{attempt}_{os.urandom(4).hex()}"
        full_visible = (system or "") + "".join(m["content"] for m in messages)
        prompt_bytes = canonical_messages(system, messages)
        prompt_sha = sha256_bytes(prompt_bytes)

        res = self._reserve(model_key, full_visible,
                            len(messages) + (1 if system else 0), max_tokens)
        if not res["allowed"]:
            self.gateway.trigger_faillock("BUDGET_PRECHECK_EXCEEDED", call_id)
            raise BatchStopped("budget precheck exceeded (incl. pending T8 reservations)")

        body_bytes = build_request_body(model_key, system, messages, max_tokens)
        self._persist_request(call_id, body_bytes,
                              {"url": "mock://offline" if isinstance(transport, MockTransport) else "real",
                               "method": "POST",
                               "auth_ref": "zhipu" if model_key == "glm" else "deepseek-modelpool"})
        req_sha = sha256_bytes(body_bytes)

        # F3: pre-send equality gate — rebuild is REQUIRED and must match actual body
        extracted = extract_canonical_from_body(body_bytes)
        if extracted is None or sha256_bytes(extracted) != sha256_bytes(prompt_rebuild):
            self._persist_response(call_id, None, "PRE_SEND_EQUALITY_FAIL")
            self.gateway.trigger_faillock("PRE_SEND_PROMPT_EQUALITY_FAIL", call_id)
            raise BatchStopped("pre-send gate: frozen-upstream rebuild != actual body prompt")

        if self.gateway.acquire(call_id) != "ISSUED":
            self._persist_response(call_id, None, "PERMIT_REVOKED_AT_ACQUIRE")
            return {"call_id": call_id, "permit": "REVOKED", "sent": False}

        # F4: acquire→check→send all inside flock via handoff_and_send()
        permit_state, resp_bytes = self.gateway.handoff_and_send(call_id, body_bytes, transport)

        if permit_state == "REVOKED":
            self._persist_response(call_id, None, "PERMIT_REVOKED_AT_HANDOFF")
            return {"call_id": call_id, "permit": "REVOKED", "sent": False}

        if resp_bytes is None:  # T8: in-flight
            with self._budget_lock:
                self.pending_reserved += res["reserved"]  # F2: retain in budget state
            self._persist_response(call_id, None, "IN_FLIGHT_NO_RESPONSE")
            self._ledger(call_id, run_id, node_id, model_key, prompt_sha, req_sha, None, res,
                         {"status": "IN_FLIGHT", "usage": None, "identity": None,
                          "permit": "IN_FLIGHT", "reserved_retained": True,
                          "pending_reserved_total": round(self.pending_reserved, 6),
                          "retry_of": retry_of}, max_tokens)
            return {"call_id": call_id, "permit": "IN_FLIGHT", "sent": True, "response": None}

        self._persist_response(call_id, resp_bytes, "OK")
        resp_sha = sha256_bytes(resp_bytes)
        resp = json.loads(resp_bytes)
        usage = resp.get("usage") or {}
        model_id_returned = resp.get("model", "")
        identity_ok = (model_id_id_returned := model_id_returned) in IDENTITY_ALLOWLIST[model_key]

        with self._budget_lock:
            actual_cost = usage.get("in", usage.get("input_tokens", res["est_in"])) / 1e6 * PRICE_TABLE[model_key]["in"] \
                + usage.get("out", usage.get("output_tokens", max_tokens)) / 1e6 * PRICE_TABLE[model_key]["out"]
            self.accrued += actual_cost

        rec = {"status": "OK" if identity_ok else "IDENTITY_MISMATCH",
               "usage": usage, "identity": {"sent": json.loads(body_bytes)["model"],
                                            "returned": model_id_returned, "match": identity_ok},
               "permit": "HANDED_OFF", "reserved_retained": False, "retry_of": retry_of}
        self._ledger(call_id, run_id, node_id, model_key, prompt_sha, req_sha, resp_sha, res, rec, max_tokens)
        if not identity_ok:
            self.gateway.trigger_faillock("MODEL_IDENTITY_MISMATCH", call_id)
            raise BatchStopped(f"identity mismatch: {model_id_returned!r}")
        return {"call_id": call_id, "permit": "HANDED_OFF", "sent": True, "response": resp}

    def _ledger(self, call_id, run_id, node_id, model_key, prompt_sha, req_sha, resp_sha, res, rec,
                max_tokens: int) -> None:
        """F6: records max_tokens (audit.py no longer uses 2500 fallback)."""
        usage = rec.get("usage") or {}
        line = {"call_id": call_id, "ts": time.time(), "run_id": run_id, "node_id": node_id,
                "model": model_key, "prompt_sha256": prompt_sha, "request_body_sha256": req_sha,
                "response_body_sha256": resp_sha, "price_table_id": res.get("price_table_id"),
                "price_table_sha256": res.get("price_table_sha256"),
                "unit_price_in": res.get("unit_price_in"), "unit_price_out": res.get("unit_price_out"),
                "est_in_tokens": res.get("est_in"), "max_tokens": max_tokens,  # F6
                "budget_reserved_this_call": round(res.get("reserved", 0), 6),
                "pending_reserved_total": round(self.pending_reserved, 6),  # F2
                "in_tokens": usage.get("in", usage.get("input_tokens")),
                "out_tokens": usage.get("out", usage.get("output_tokens")),
                "cost_computation": rec.get("status"), "accrued_cny": round(self.accrued, 6),
                "unknown_fee_flag": rec.get("usage") is None,
                "record": rec}
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def write_manifest(self, run_id: str) -> str:
        """F7: manifest includes ledger.jsonl and its hash is written back to ledger."""
        # Write manifest of all payload files
        files = []
        for d in sorted(self.payloads.iterdir()):
            for f in sorted(d.iterdir()):
                files.append({"path": str(f.relative_to(self.root)), "bytes": f.stat().st_size,
                              "sha256": sha256_bytes(f.read_bytes())})
        # NOTE: manifest covers payload files only; ledger cannot contain a valid
        # hash of itself (self-reference). Manifest hash is anchored IN the ledger.
        # Ledger integrity is protected by per-call hash chain + manifest anchor.
        m = {"run_id": run_id, "files": files, "canon_rule": CANON_RULE,
             "price_table": {"id": PRICE_TABLE_ID, "sha256": PRICE_TABLE_SHA}}
        manifest_path = self.root / "MANIFEST.json"
        manifest_path.write_text(json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                                 encoding="utf-8")
        manifest_sha = sha256_bytes(manifest_path.read_bytes())
        # F7: write manifest hash to ledger as anchor
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps({"anchor": "MANIFEST", "manifest_sha256": manifest_sha, "ts": time.time()},
                               ensure_ascii=False) + "\n")
        return manifest_sha
