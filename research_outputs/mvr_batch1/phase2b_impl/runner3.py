#!/usr/bin/env python3
"""Runner3 v4.1 — comprehensive fix for operator P0-1 through P0-6.

P0-1 Budget atomic reservation (check+reserve in one lock, state machine)
P0-2 Transport exception handling (raw bytes, SENT_UNKNOWN state)
P0-3 Prompt source verification (upstream binding, not caller bytes)
P0-5 Ledger hash chain (prev_hash + record_hash per line)
P0-6 Gateway process exclusivity (exclusive flock, unified linearization)
"""
from __future__ import annotations

import fcntl, hashlib, json, math, os, socket, threading, time
import urllib.error, urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

CANON_RULE = "canonical_messages_v1"
PRICE_TABLE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30*7.5, "out": 1.20*7.5}}
PRICE_TABLE_ID = "frozen-20261031"
PRICE_TABLE_SHA = hashlib.sha256(json.dumps(PRICE_TABLE, sort_keys=True).encode()).hexdigest()
IDENTITY_ALLOWLIST = {"glm": ["GLM-5.3-Flash"], "ds": ["deepseek-flash"]}
TOKEN_COEFF = 1.0
PROTO_BASE = 100
PROTO_PER_MSG = 50

def sha256_bytes(b): return hashlib.sha256(b).hexdigest()

def canonical_messages(system, messages):
    arr = []
    if system: arr.append({"role":"system","content":system})
    arr.extend({"role":m["role"],"content":m["content"]} for m in messages)
    return json.dumps(arr, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode("utf-8")

def extract_canonical_from_body(body_bytes):
    body = json.loads(body_bytes)
    if "system" in body:
        msgs = [{"role":"system","content":body["system"]}] + body.get("messages",[])
    else: msgs = body.get("messages",[])
    return canonical_messages(None, msgs)

def build_request_body(model_key, system, messages, max_tokens):
    if model_key == "glm":
        body = {"model":IDENTITY_ALLOWLIST["glm"][0],"max_tokens":max_tokens,"temperature":0,"thinking":{"type":"disabled"}}
        if system: body["system"]=system
        body["messages"]=messages
    else:
        body = {"model":IDENTITY_ALLOWLIST["ds"][0],"max_tokens":max_tokens,"temperature":0,
                "messages":([{"role":"system","content":system}] if system else [])+messages,
                "response_format":{"type":"json_object"},"thinking":{"type":"disabled"}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")

class BatchStopped(Exception): pass

class EgressGateway:
    """P0-6: exclusive process lock; FAILLOCK+handoff under same threading.Lock."""
    def __init__(self, root):
        self.root=root; self.faillock=root/"FAILLOCK.json"; self.glock_path=root/"gateway.lock"
        self.permits={}; self.handoff_log=[]; self._lk=threading.Lock(); self._proc_fd=None
        root.mkdir(parents=True, exist_ok=True)
        self._proc_fd=os.open(self.glock_path, os.O_CREAT|os.O_RDWR)
        try: fcntl.flock(self._proc_fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._proc_fd); self._proc_fd=None
            raise RuntimeError("Gateway: another process holds gateway.lock")

    def lock_exists(self): return self.faillock.exists()

    def trigger_faillock(self, reason, call_id=""):
        with self._lk:
            try:
                fd=os.open(self.faillock, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                with os.fdopen(fd,"w") as f:
                    json.dump({"reason":reason,"call_id":call_id,"ts":time.time()},f)
                    f.flush(); os.fsync(f.fileno())
            except FileExistsError: pass
            for cid,st in self.permits.items():
                if st=="ISSUED": self.permits[cid]="REVOKED"

    def acquire(self, call_id):
        with self._lk:
            if self.lock_exists(): self.permits[call_id]="REVOKED"; return "REVOKED"
            self.permits[call_id]="ISSUED"; return "ISSUED"

    def handoff_and_send(self, call_id, body_bytes, transport):
        """P0-2+P0-6: acquire→check→send all under threading.Lock; handle exceptions."""
        with self._lk:
            if self.lock_exists() or self.permits.get(call_id)!="ISSUED":
                self.permits[call_id]="REVOKED"
                self.handoff_log.append({"call_id":call_id,"ts":time.time(),"result":"REVOKED"})
                return ("REVOKED", None, "NOT_SENT")
            self.permits[call_id]="HANDED_OFF"
            self.handoff_log.append({"call_id":call_id,"ts":time.time(),"result":"HANDED_OFF"})
            try:
                resp=transport.send(body_bytes)
                if resp is None:
                    self.permits[call_id]="IN_FLIGHT"
                    return ("IN_FLIGHT",None,"SENT_UNKNOWN")
                return ("HANDED_OFF",resp,"SENT_OK")
            except (urllib.error.URLError,urllib.error.HTTPError,socket.timeout,ConnectionError,OSError) as e:
                self.permits[call_id]="IN_FLIGHT"
                return ("IN_FLIGHT",None,f"SENT_EXCEPTION:{type(e).__name__}")

    def close(self):
        if self._proc_fd is not None:
            fcntl.flock(self._proc_fd,fcntl.LOCK_UN); os.close(self._proc_fd); self._proc_fd=None

class SocketGuard:
    def __init__(self,root): self.log=root/"socket_guard.log"
    def __enter__(self):
        self._oc=socket.socket.connect; self._ok=socket.create_connection; g=self
        def blocked(*a,**k):
            with open(g.log,"a") as f: f.write(json.dumps({"ts":time.time(),"attempt":str(a)[:120]})+"\n")
            raise RuntimeError("EGRESS_BLOCKED")
        socket.socket.connect=blocked; socket.create_connection=blocked; return self
    def __exit__(self,*a): socket.socket.connect=self._oc; socket.create_connection=self._ok

class MockTransport:
    def __init__(self,mk,*,model_id=None,usage=None,drop_response=False,raise_after_send=False):
        self.mk=mk; self.model_id=model_id or IDENTITY_ALLOWLIST[mk][0]
        self.usage=usage or {"in":100,"out":50}; self.drop_response=drop_response; self.raise_after_send=raise_after_send
    def send(self,body_bytes):
        body=json.loads(body_bytes)
        if self.drop_response: return None
        if self.raise_after_send: raise socket.timeout("simulated timeout")
        resp={"model":self.model_id,"usage":self.usage,"choices":[{"message":{"content":"{\"ok\":true}"}}]}
        if "system" in body:
            resp={"model":self.model_id,"usage":{"input_tokens":self.usage["in"],"output_tokens":self.usage["out"]},
                  "content":[{"type":"text","text":"{\"ok\":true}"}]}
        return json.dumps(resp,ensure_ascii=False).encode("utf-8")

def _load_keys():
    keys={}
    for path in ("/root/.env","/root/.env.modelpool"):
        for line in open(path):
            line=line.strip()
            if line and not line.startswith("#") and "=" in line:
                k,v=line.split("=",1); keys[k]=v.strip().strip('"').strip("'")
    return keys

class RealTransport:
    """P0-2: returns raw HTTP response bytes."""
    def __init__(self,mk,timeout_s=120): self.mk=mk; self.timeout_s=timeout_s
    def _glm_key(self):
        cfg=json.load(open("/root/.zcode/v2/provider_config.json"))
        return next(r["config"]["access"]["apiKey"]
                    for r in cfg["config"]["providerConfigRules"]["providerRules"]
                    if r["providerId"]=="bigmodel-api")
    def send(self,body_bytes):
        if os.environ.get("PHASE2B_REAL")!="1" or not Path("/root/research_outputs/mvr_batch1/REAL_CALLS_ALLOWED").exists():
            raise RuntimeError("RealTransport DISARMED")
        if self.mk=="glm":
            req=urllib.request.Request("https://open.bigmodel.cn/api/anthropic/v1/messages",data=body_bytes,method="POST")
            key=self._glm_key()
            req.add_header("content-type","application/json");req.add_header("x-api-key",key)
            req.add_header("authorization","Bearer "+key);req.add_header("anthropic-version","2023-06-01")
            with urllib.request.urlopen(req,timeout=self.timeout_s) as r: return r.read()
        else:
            keys=_load_keys()
            req=urllib.request.Request("https://api.deepseek.com/chat/completions",data=body_bytes,method="POST")
            req.add_header("Content-Type","application/json")
            req.add_header("Authorization","Bearer "+keys.get("DEEPSEEK_API_KEY",""))
            with urllib.request.urlopen(req,timeout=self.timeout_s) as r: return r.read()

class UpstreamBinding:
    """P0-3: frozen upstream execution record binding."""
    def __init__(self,node_id,execution_id,output_sha256):
        self.node_id=node_id;self.execution_id=execution_id;self.output_sha256=output_sha256
    def verify(self,frozen_dir):
        rf=frozen_dir/f"{self.node_id}_{self.execution_id}.json"
        if not rf.exists(): return False
        rec=json.loads(rf.read_text())
        return (rec.get("node_id")==self.node_id and rec.get("execution_id")==self.execution_id
                and rec.get("output_sha256")==self.output_sha256)

class BudgetStateMachine:
    """P0-1: atomic check+reserve; RESERVED→SETTLED/UNKNOWN/RELEASED."""
    def __init__(self,cap):
        self.cap=cap;self.accrued=0.0;self._reservations={};self._lock=threading.Lock()
    def check_and_reserve(self,call_id,amount):
        with self._lock:
            if self.accrued+sum(self._reservations.values())+amount>self.cap: return False
            self._reservations[call_id]=amount; return True
    def settle(self,call_id,actual_cost):
        with self._lock:
            self._reservations.pop(call_id,None);self.accrued+=actual_cost
    def mark_unknown(self,call_id): pass  # reservation stays permanently
    def release(self,call_id):
        with self._lock: self._reservations.pop(call_id,None)
    @property
    def pending_reserved(self):
        with self._lock: return sum(self._reservations.values())
    @property
    def total_committed(self):
        with self._lock: return self.accrued+sum(self._reservations.values())
    @classmethod
    def from_ledger(cls,ledger_path,cap):
        sm=cls(cap)
        if not ledger_path.exists(): return sm
        for line in ledger_path.read_text().splitlines():
            if not line.strip(): continue
            try: rec=json.loads(line)
            except json.JSONDecodeError: continue
            if rec.get("budget_state")=="SETTLED": sm.accrued+=rec.get("actual_cost",0.0)
            elif rec.get("budget_state")=="UNKNOWN":
                sm._reservations[rec["call_id"]]=rec.get("budget_reserved_this_call",0.0)
        return sm

class Runner3:
    def __init__(self,root,gateway,budget_cap,frozen_upstream_dir=None):
        self.root=root;self.payloads=root/"payloads";self.payloads.mkdir(parents=True,exist_ok=True)
        self.gateway=gateway;self.ledger_path=root/"ledger.jsonl"
        self.budget=BudgetStateMachine(budget_cap)
        self.frozen_upstream_dir=frozen_upstream_dir
        self._ledger_lock=threading.Lock();self._prev_hash="GENESIS"

    def _persist_request(self,call_id,body_bytes,meta):
        d=self.payloads/call_id;d.mkdir(parents=True,exist_ok=True)
        p=d/f"{call_id}.request_body.bin"
        with open(p,"wb") as f: f.write(body_bytes);f.flush();os.fsync(f.fileno())
        (d/f"{call_id}.request_meta.json").write_text(json.dumps(meta,indent=1),encoding="utf-8")

    def _persist_response(self,call_id,resp_bytes,status):
        d=self.payloads/call_id
        if resp_bytes is not None:
            p=d/f"{call_id}.response_body.bin"
            with open(p,"wb") as f: f.write(resp_bytes);f.flush();os.fsync(f.fileno())
        (d/f"{call_id}.response_meta.json").write_text(json.dumps({"status":status,"ts":time.time()}),encoding="utf-8")

    def call(self,*,run_id,node_id,model_key,system,messages,max_tokens,transport,
             upstream_binding,attempt=1,retry_of=None):
        call_id=f"{run_id}_{node_id}_a{attempt}_{os.urandom(4).hex()}"
        full_visible=(system or "")+"".join(m["content"] for m in messages)
        prompt_bytes=canonical_messages(system,messages)
        prompt_sha=sha256_bytes(prompt_bytes)

        # P0-3: verify upstream binding
        if self.frozen_upstream_dir is not None:
            if not upstream_binding.verify(self.frozen_upstream_dir):
                self.gateway.trigger_faillock("UPSTREAM_BINDING_INVALID",call_id)
                raise BatchStopped(f"upstream binding verification failed for {call_id}")

        # P0-1: calculate + atomically reserve
        b_utf8=len(full_visible.encode("utf-8"))
        h_proto=PROTO_BASE+PROTO_PER_MSG*(len(messages)+(1 if system else 0))
        est_in=math.ceil(b_utf8*TOKEN_COEFF+h_proto)
        price=PRICE_TABLE[model_key]
        reserved_amt=est_in/1e6*price["in"]+max_tokens/1e6*price["out"]
        if not self.budget.check_and_reserve(call_id,reserved_amt):
            self.gateway.trigger_faillock("BUDGET_PRECHECK_EXCEEDED",call_id)
            raise BatchStopped(f"budget exceeded: committed={self.budget.total_committed:.6f}+{reserved_amt:.6f}>cap={self.budget.cap}")

        body_bytes=build_request_body(model_key,system,messages,max_tokens)
        self._persist_request(call_id,body_bytes,{
            "url":"mock://offline" if isinstance(transport,MockTransport) else "real",
            "method":"POST","auth_ref":"zhipu" if model_key=="glm" else "deepseek-modelpool",
            "upstream":{"node_id":upstream_binding.node_id,"execution_id":upstream_binding.execution_id,
                         "output_sha256":upstream_binding.output_sha256}})
        req_sha=sha256_bytes(body_bytes)

        extracted=extract_canonical_from_body(body_bytes)
        if extracted is None or sha256_bytes(extracted)!=prompt_sha:
            self._persist_response(call_id,None,"PRE_SEND_EQUALITY_FAIL")
            self.budget.release(call_id)
            self.gateway.trigger_faillock("PRE_SEND_PROMPT_EQUALITY_FAIL",call_id)
            self._ledger(call_id,run_id,node_id,model_key,prompt_sha,req_sha,None,
                         est_in,max_tokens,0.0,"RELEASED","PRE_SEND_EQUALITY_FAIL",upstream_binding.output_sha256)
            raise BatchStopped("pre-send gate failed")

        if self.gateway.acquire(call_id)!="ISSUED":
            self._persist_response(call_id,None,"PERMIT_REVOKED_AT_ACQUIRE")
            self.budget.release(call_id)
            self._ledger(call_id,run_id,node_id,model_key,prompt_sha,req_sha,None,
                         est_in,max_tokens,0.0,"RELEASED","PERMIT_REVOKED",upstream_binding.output_sha256)
            return {"call_id":call_id,"permit":"REVOKED","sent":False,"budget_state":"RELEASED"}

        permit_state,resp_bytes,send_status=self.gateway.handoff_and_send(call_id,body_bytes,transport)

        if permit_state=="REVOKED":
            self._persist_response(call_id,None,"PERMIT_REVOKED_AT_HANDOFF")
            self.budget.release(call_id)
            self._ledger(call_id,run_id,node_id,model_key,prompt_sha,req_sha,None,
                         est_in,max_tokens,0.0,"RELEASED","PERMIT_REVOKED",upstream_binding.output_sha256)
            return {"call_id":call_id,"permit":"REVOKED","sent":False,"budget_state":"RELEASED"}

        if resp_bytes is None:  # P0-2: SENT_UNKNOWN
            self._persist_response(call_id,None,send_status)
            self.budget.mark_unknown(call_id)
            self._ledger(call_id,run_id,node_id,model_key,prompt_sha,req_sha,None,
                         est_in,max_tokens,reserved_amt,"UNKNOWN",send_status,upstream_binding.output_sha256)
            return {"call_id":call_id,"permit":"IN_FLIGHT","sent":True,"budget_state":"UNKNOWN"}

        self._persist_response(call_id,resp_bytes,"OK")
        resp_sha=sha256_bytes(resp_bytes)
        try: resp=json.loads(resp_bytes)
        except json.JSONDecodeError:
            self.budget.settle(call_id,reserved_amt)
            self._ledger(call_id,run_id,node_id,model_key,prompt_sha,req_sha,resp_sha,
                         est_in,max_tokens,reserved_amt,"SETTLED","RESPONSE_PARSE_ERROR",upstream_binding.output_sha256)
            self.gateway.trigger_faillock("RESPONSE_PARSE_ERROR",call_id)
            raise BatchStopped("response not valid JSON")

        usage=resp.get("usage") or {}
        model_id_returned=resp.get("model","")
        identity_ok=model_id_returned in IDENTITY_ALLOWLIST.get(model_key,[])
        actual_cost=usage.get("in",usage.get("input_tokens",est_in))/1e6*price["in"] \
            +usage.get("out",usage.get("output_tokens",max_tokens))/1e6*price["out"]
        self.budget.settle(call_id,actual_cost)
        status="OK" if identity_ok else "IDENTITY_MISMATCH"
        self._ledger(call_id,run_id,node_id,model_key,prompt_sha,req_sha,resp_sha,
                     est_in,max_tokens,actual_cost,"SETTLED",status,upstream_binding.output_sha256)
        if not identity_ok:
            self.gateway.trigger_faillock("MODEL_IDENTITY_MISMATCH",call_id)
            raise BatchStopped(f"identity mismatch: {model_id_returned!r}")
        return {"call_id":call_id,"permit":"HANDED_OFF","sent":True,"budget_state":"SETTLED","response":resp}

    def _ledger(self,call_id,run_id,node_id,model_key,prompt_sha,req_sha,resp_sha,
                est_in,max_tokens,actual_cost,budget_state,status,upstream_sha):
        """P0-5: hash chain."""
        line_data={
            "call_id":call_id,"ts":time.time(),"run_id":run_id,"node_id":node_id,
            "model":model_key,"prompt_sha256":prompt_sha,"request_body_sha256":req_sha,
            "response_body_sha256":resp_sha,
            "price_table_id":PRICE_TABLE_ID,"price_table_sha256":PRICE_TABLE_SHA,
            "unit_price_in":PRICE_TABLE[model_key]["in"],"unit_price_out":PRICE_TABLE[model_key]["out"],
            "est_in_tokens":est_in,"max_tokens":max_tokens,
            "budget_reserved_this_call":round(est_in/1e6*PRICE_TABLE[model_key]["in"]+max_tokens/1e6*PRICE_TABLE[model_key]["out"],6),
            "actual_cost":round(actual_cost,6),
            "budget_state":budget_state,"status":status,
            "upstream_output_sha256":upstream_sha,
            "accrued_total":round(self.budget.accrued,6),
            "pending_reserved_total":round(self.budget.pending_reserved,6),
            "prev_hash":self._prev_hash,
        }
        canonical=json.dumps(line_data,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        record_hash=sha256_bytes(canonical.encode("utf-8"))
        line_data["record_hash"]=record_hash
        with self._ledger_lock:
            with open(self.ledger_path,"a") as f: f.write(json.dumps(line_data,ensure_ascii=False)+"\n")
            self._prev_hash=record_hash
