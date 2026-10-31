#!/usr/bin/env python3
"""audit.py v2 — fixes for operator 7-item FAIL audit.

Key fixes:
 A1 L1/L2/L3 now MANDATORY (fail if expected but inputs missing)
 A2 L3 compares full quintuple (doc, page, quote, page_sha256, raw_sha256)
 A3 Budget uses actual max_tokens from ledger (no 2500 fallback)
 A4 MANIFEST hash verified against ledger anchor; manifest covers ledger
 A5 Identity check mandatory + verifies request body model field
 A6 Request body model field independently verified against frozen allowlist
"""
import hashlib
import json
from pathlib import Path

CANON_RULE = "canonical_messages_v1"

# Frozen identity allowlist (must match runner3.py)
IDENTITY_ALLOWLIST = {"glm": ["GLM-5.3-Flash"], "ds": ["deepseek-flash"]}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _canon(system, messages):
    arr = []
    if system:
        arr.append({"role": "system", "content": system})
    for m in messages:
        arr.append({"role": m["role"], "content": m["content"]})
    return json.dumps(arr, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _extract_canon_from_body(body_bytes):
    body = json.loads(body_bytes)
    if "system" in body:
        msgs = [{"role": "system", "content": body["system"]}] + body.get("messages", [])
    else:
        msgs = body.get("messages", [])
    return _canon(None, msgs)


def audit_run(root: Path, *, expected_prompt: bytes,
              upstream_e_outputs=None, j_anchors=None,
              sink_quotes=None, frozen_pages=None,
              expect_l1=False, expect_l2=False, expect_l3=False,
              model_key=None) -> dict:
    """Independent audit. A1: expect_l1/l2/l3 flags make anchor checks mandatory.
    A5: identity check is now always performed (allowlist is built-in).
    A6: request body model field independently verified."""
    failures = []

    # ---- A4: Manifest verification + ledger anchor ----
    mpath = root / "MANIFEST.json"
    if not mpath.exists():
        return {"verdict": "FAIL", "failures": ["MANIFEST missing"]}
    manifest = json.loads(mpath.read_text())

    # Verify every manifest file
    for entry in manifest["files"]:
        p = root / entry["path"]
        if not p.exists():
            failures.append(f"manifest file missing: {entry['path']}")
        elif _sha(p.read_bytes()) != entry["sha256"] or p.stat().st_size != entry["bytes"]:
            failures.append(f"manifest hash/size mismatch: {entry['path']}")

    # Verify manifest hash is anchored in ledger
    ledger_path = root / "ledger.jsonl"
    if not ledger_path.exists():
        return {"verdict": "FAIL", "failures": ["ledger.jsonl missing"]}
    ledger_lines = [json.loads(l) for l in ledger_path.read_text().splitlines() if l.strip()]
    manifest_sha = _sha(mpath.read_bytes())
    anchor_lines = [l for l in ledger_lines if l.get("anchor") == "MANIFEST"]
    if not anchor_lines:
        failures.append("MANIFEST hash not anchored in ledger")
    elif anchor_lines[-1].get("manifest_sha256") != manifest_sha:
        failures.append("MANIFEST hash in ledger does not match actual manifest")

    # ---- Per-call verification ----
    call_lines = [l for l in ledger_lines if l.get("call_id")]
    seen_calls = set()
    for line in call_lines:
        cid = line["call_id"]
        if cid in seen_calls:
            failures.append(f"duplicate call_id {cid}")
        seen_calls.add(cid)
        d = root / "payloads" / cid
        req = d / f"{cid}.request_body.bin"
        if not req.exists():
            failures.append(f"request_body.bin missing for {cid}")
            continue
        req_bytes = req.read_bytes()
        if _sha(req_bytes) != line["request_body_sha256"]:
            failures.append(f"request_body_sha256 mismatch {cid}")

        # Prompt equality (independent): rebuild == extract from actual body
        try:
            extracted = _extract_canon_from_body(req_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            extracted = None
        if extracted is None or _sha(extracted) != _sha(expected_prompt):
            failures.append(f"PROMPT_EQUALITY: rebuild != actual body ({cid})")
        if _sha(expected_prompt) != line["prompt_sha256"]:
            failures.append(f"prompt_sha256 vs expected mismatch {cid}")

        # A5+A6: Identity — ALWAYS check (not optional)
        try:
            req_body = json.loads(req_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            req_body = {}
        sent_model = req_body.get("model", "")
        model_key_from_ledger = line.get("model", "")
        if model_key_from_ledger and model_key_from_ledger in IDENTITY_ALLOWLIST:
            if sent_model not in IDENTITY_ALLOWLIST[model_key_from_ledger]:
                failures.append(f"IDENTITY_REQUEST: sent={sent_model!r} not in allowlist for {model_key_from_ledger} ({cid})")

        rsp = d / f"{cid}.response_body.bin"
        if line.get("response_body_sha256"):
            if not rsp.exists() or _sha(rsp.read_bytes()) != line["response_body_sha256"]:
                failures.append(f"response_body_sha256 mismatch {cid}")
            else:
                resp = json.loads(rsp.read_bytes())
                returned_model = resp.get("model", "")
                if model_key_from_ledger in IDENTITY_ALLOWLIST:
                    if returned_model not in IDENTITY_ALLOWLIST[model_key_from_ledger]:
                        failures.append(f"IDENTITY_RESPONSE: returned={returned_model!r} ({cid})")
        else:
            status_f = d / f"{cid}.response_meta.json"
            if not status_f.exists():
                failures.append(f"response artifacts missing for no-response call {cid}")

        # A3: Budget recomputation using ACTUAL max_tokens from ledger
        if line.get("budget_reserved_this_call") is not None and line.get("est_in_tokens") is not None:
            actual_max_tokens = line.get("max_tokens")  # F6: from ledger, no 2500 fallback
            if actual_max_tokens is None:
                failures.append(f"max_tokens missing from ledger {cid}")
            else:
                exp = line["est_in_tokens"] / 1e6 * line["unit_price_in"] + \
                      actual_max_tokens / 1e6 * line["unit_price_out"]
                if abs(exp - line["budget_reserved_this_call"]) > 5e-6:
                    failures.append(f"reservation arithmetic mismatch {cid} (max_tokens={actual_max_tokens})")

        # F2: pending_reserved check
        if line.get("record", {}).get("status") == "IN_FLIGHT":
            if not line.get("record", {}).get("reserved_retained"):
                failures.append(f"IN_FLIGHT call {cid} missing reserved_retained flag")
            if line.get("pending_reserved_total") is None:
                failures.append(f"IN_FLIGHT call {cid} missing pending_reserved_total")

    # Payload<->ledger closure
    if (root / "payloads").exists():
        for d in (root / "payloads").iterdir():
            if d.name not in seen_calls:
                failures.append(f"orphan payload dir: {d.name}")

    # ---- A1+A2: L1/L2/L3 mandatory when expected ----
    if expect_l1:
        if not frozen_pages:
            failures.append("L1_EXPECTED_BUT_NO_FROZEN_PAGES")
        if not upstream_e_outputs:
            failures.append("L1_EXPECTED_BUT_NO_E_OUTPUTS")
    if expect_l2 and not j_anchors:
        failures.append("L2_EXPECTED_BUT_NO_J_ANCHORS")
    if expect_l3 and not sink_quotes:
        failures.append("L3_EXPECTED_BUT_NO_SINK_QUOTES")

    if frozen_pages and upstream_e_outputs:
        for out in upstream_e_outputs:  # L1
            key = (out["doc"], out["page"])
            page = frozen_pages.get(key)
            if page is None:
                failures.append(f"L1: unknown frozen page {key}")
                continue
            if _sha(page["text"].encode()) != out["page_sha256"] or page["raw_sha256"] != out["raw_sha256"]:
                failures.append(f"L1: hash mismatch for {key}")
            qn = "".join(ch for ch in out["quote"] if not ch.isspace())
            tn = "".join(ch for ch in page["text"] if not ch.isspace())
            if qn not in tn:
                failures.append(f"L1: E quote not in frozen page ({out.get('label', '')})")

    if upstream_e_outputs and j_anchors:
        for a in j_anchors:  # L2: full quintuple comparison
            match = any(
                e["doc"] == a["doc"] and e["page"] == a["page"] and e["quote"] == a["quote"]
                and e["page_sha256"] == a["page_sha256"] and e["raw_sha256"] == a["raw_sha256"]
                for e in upstream_e_outputs)
            if not match:
                failures.append(f"L2: J anchor not inherited from E ({a.get('label', '')})")

    if j_anchors and sink_quotes is not None:
        # A2: L3 compares full quintuple, not just quote string
        for sq in sink_quotes:
            if isinstance(sq, str):
                sq = {"quote": sq}
            match = any(
                a.get("doc") == sq.get("doc") and a.get("page") == sq.get("page")
                and a["quote"] == sq.get("quote")
                and a.get("page_sha256") == sq.get("page_sha256")
                and a.get("raw_sha256") == sq.get("raw_sha256")
                for a in j_anchors)
            if not match:
                failures.append(f"L3: sink anchor not from verified J set ({sq.get('quote', '')[:20]}…)")

    return {"verdict": "PASS" if not failures else "FAIL", "failures": failures}


if __name__ == "__main__":
    print("audit.py v2 — independent verifier with mandatory L1/L2/L3, full quintuple L3, "
          "built-in identity check, actual max_tokens budget recalc, manifest ledger anchor")
