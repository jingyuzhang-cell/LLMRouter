#!/usr/bin/env python3
"""audit.py v4.1 — independent verifier.

P0-4: L1 independently reads frozen PDF; L2/L3 mandatory; judgment_item_id.
P0-5: Ledger hash chain verification; manifest reverse-check; identity mandatory.
"""
import hashlib, json
from pathlib import Path

IDENTITY_ALLOWLIST = {"glm": ["GLM-5.3-Flash"], "ds": ["deepseek-flash"]}
PRICE_TABLE = {"glm": {"in": 0.80, "out": 2.80}, "ds": {"in": 0.30*7.5, "out": 1.20*7.5}}
PRICE_TABLE_SHA = hashlib.sha256(json.dumps(PRICE_TABLE, sort_keys=True).encode()).hexdigest()

def _sha(b): return hashlib.sha256(b).hexdigest()

def _canon(system, messages):
    arr = []
    if system: arr.append({"role":"system","content":system})
    for m in messages: arr.append({"role":m["role"],"content":m["content"]})
    return json.dumps(arr, ensure_ascii=False, sort_keys=True, separators=(",",":")).encode()

def _extract_canon(body_bytes):
    body = json.loads(body_bytes)
    if "system" in body:
        msgs = [{"role":"system","content":body["system"]}] + body.get("messages",[])
    else: msgs = body.get("messages",[])
    return _canon(None, msgs)

def audit_run(root, *, expected_prompt,
              upstream_e_outputs=None, j_anchors=None, sink_quotes=None,
              frozen_pages=None, frozen_pdf_dir=None,
              expect_l1=False, expect_l2=False, expect_l3=False):
    failures = []

    # ---- P0-5: Ledger hash chain verification ----
    ledger_path = root / "ledger.jsonl"
    if not ledger_path.exists():
        return {"verdict":"FAIL","failures":["ledger missing"]}
    ledger_lines = [json.loads(l) for l in ledger_path.read_text().splitlines() if l.strip()]
    prev_hash = "GENESIS"
    for i, line in enumerate(ledger_lines):
        if line.get("prev_hash") != prev_hash:
            failures.append(f"HASH_CHAIN: line {i} prev_hash mismatch")
        if "record_hash" in line:
            rec = {k:v for k,v in line.items() if k != "record_hash"}
            canonical = json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",",":"))
            expected = _sha(canonical.encode("utf-8"))
            if line["record_hash"] != expected:
                failures.append(f"HASH_CHAIN: line {i} record_hash mismatch")
            prev_hash = line["record_hash"]
        else:
            prev_hash = "GENESIS"  # non-chained line (e.g. anchor)

    # ---- Manifest verification + reverse check ----
    mpath = root / "MANIFEST.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text())
        manifest_paths = set()
        for entry in manifest.get("files", []):
            p = root / entry["path"]
            manifest_paths.add(entry["path"])
            if not p.exists():
                failures.append(f"manifest file missing: {entry['path']}")
            elif _sha(p.read_bytes()) != entry["sha256"]:
                failures.append(f"manifest hash mismatch: {entry['path']}")
        # P0-5: reverse check — actual payload files ⊆ manifest
        if (root / "payloads").exists():
            for d in (root / "payloads").iterdir():
                for f in d.iterdir():
                    rel = str(f.relative_to(root))
                    if rel not in manifest_paths:
                        failures.append(f"orphan file not in manifest: {rel}")

    # ---- Per-call verification ----
    call_lines = [l for l in ledger_lines if l.get("call_id")]
    seen = set()
    for line in call_lines:
        cid = line["call_id"]
        if cid in seen: failures.append(f"duplicate call_id {cid}")
        seen.add(cid)
        d = root / "payloads" / cid
        req = d / f"{cid}.request_body.bin"
        if not req.exists():
            failures.append(f"request_body.bin missing for {cid}"); continue
        req_bytes = req.read_bytes()
        if _sha(req_bytes) != line["request_body_sha256"]:
            failures.append(f"request hash mismatch {cid}")
        try:
            extracted = _extract_canon(req_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            extracted = None
        if extracted is None or _sha(extracted) != _sha(expected_prompt):
            failures.append(f"PROMPT_EQUALITY: rebuild != body ({cid})")

        # P0-5: identity mandatory (no skip)
        try:
            req_body = json.loads(req_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            req_body = {}
        mk = line.get("model","")
        if mk not in IDENTITY_ALLOWLIST:
            failures.append(f"IDENTITY: unknown model_key {mk!r} in ledger ({cid})")
        else:
            sent = req_body.get("model","")
            if sent not in IDENTITY_ALLOWLIST[mk]:
                failures.append(f"IDENTITY_REQUEST: sent={sent!r} ({cid})")

        rsp = d / f"{cid}.response_body.bin"
        if line.get("response_body_sha256"):
            if not rsp.exists() or _sha(rsp.read_bytes()) != line["response_body_sha256"]:
                failures.append(f"response hash mismatch {cid}")
            else:
                resp = json.loads(rsp.read_bytes())
                ret = resp.get("model","")
                if mk in IDENTITY_ALLOWLIST and ret not in IDENTITY_ALLOWLIST[mk]:
                    failures.append(f"IDENTITY_RESPONSE: returned={ret!r} ({cid})")
        # Budget: use actual max_tokens + frozen price table
        if line.get("budget_reserved_this_call") is not None:
            mt = line.get("max_tokens")
            if mt is None:
                failures.append(f"max_tokens missing {cid}")
            else:
                # P0-5: verify against frozen price table, not ledger's self-reported prices
                frozen_price = PRICE_TABLE.get(mk, {})
                if frozen_price:
                    exp = line["est_in_tokens"]/1e6*frozen_price["in"] + mt/1e6*frozen_price["out"]
                    if abs(exp - line["budget_reserved_this_call"]) > 5e-6:
                        failures.append(f"budget mismatch {cid}")
                if line.get("price_table_sha256") != PRICE_TABLE_SHA:
                    failures.append(f"price table SHA mismatch {cid}")

    # ---- P0-4: L1/L2/L3 mandatory checks ----
    if expect_l1:
        if not frozen_pages and not frozen_pdf_dir:
            failures.append("L1_EXPECTED: no frozen pages or PDF dir")
        if not upstream_e_outputs:
            failures.append("L1_EXPECTED: no E outputs")
    if expect_l2:
        if not upstream_e_outputs:
            failures.append("L2_EXPECTED: no upstream E outputs")
        if not j_anchors:
            failures.append("L2_EXPECTED: no J anchors")

    if frozen_pages and upstream_e_outputs:
        for out in upstream_e_outputs:
            key = (out.get("doc"), out.get("page"))
            page = frozen_pages.get(key)
            if page is None:
                failures.append(f"L1: unknown page {key}"); continue
            # P0-4: if PDF dir provided, independently verify raw hash
            if frozen_pdf_dir and out.get("raw_sha256"):
                pdf_path = frozen_pdf_dir / f"{out['doc']}.pdf"
                if pdf_path.exists():
                    actual_raw = _sha(pdf_path.read_bytes())
                    if actual_raw != out["raw_sha256"]:
                        failures.append(f"L1: PDF raw hash mismatch for {out['doc']}")
            if page.get("page_sha256") and _sha(page["text"].encode()) != out.get("page_sha256"):
                failures.append(f"L1: page hash mismatch {key}")
            qn = "".join(c for c in out.get("quote","") if not c.isspace())
            tn = "".join(c for c in page["text"] if not c.isspace())
            if qn and qn not in tn:
                failures.append(f"L1: quote not in page ({out.get('label','')})")

    if upstream_e_outputs and j_anchors:
        for a in j_anchors:  # P0-4: include judgment_item_id
            match = any(
                e.get("doc")==a.get("doc") and e.get("page")==a.get("page")
                and e.get("quote")==a.get("quote")
                and e.get("page_sha256")==a.get("page_sha256")
                and e.get("raw_sha256")==a.get("raw_sha256")
                and e.get("judgment_item_id")==a.get("judgment_item_id")
                for e in upstream_e_outputs)
            if not match:
                failures.append(f"L2: anchor not inherited ({a.get('label','')})")

    if expect_l3 and not sink_quotes:
        failures.append("L3_EXPECTED: no sink quotes")
    if expect_l3 and not j_anchors:
        failures.append("L3_EXPECTED: no J anchors (upstream for L3)")
    if j_anchors and sink_quotes is not None:
        for sq in sink_quotes:
            if isinstance(sq, str): sq = {"quote": sq}
            match = any(
                a.get("doc")==sq.get("doc") and a.get("page")==sq.get("page")
                and a.get("quote")==sq.get("quote")
                and a.get("judgment_item_id")==sq.get("judgment_item_id")
                for a in j_anchors)
            if not match:
                failures.append(f"L3: unverified anchor ({sq.get('quote','')[:20]})")

    # Payload-ledger closure
    if (root/"payloads").exists():
        for d in (root/"payloads").iterdir():
            if d.name not in seen:
                failures.append(f"orphan payload: {d.name}")

    return {"verdict":"PASS" if not failures else "FAIL", "failures": failures}
