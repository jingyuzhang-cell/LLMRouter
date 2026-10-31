#!/usr/bin/env python3
"""audit.py — INDEPENDENT verifier (per spec E5: no reuse of runner3 functions).

Reimplements from scratch: canonical serialization, hash recomputation, manifest
verification, prompt-equality chain, identity exact-match, budget recomputation,
L1/L2/L3 anchor verification. Self-regression on tamper samples is driven by
dryrun_tests.py; audit exits non-zero on any FAIL.
"""
import hashlib
import json
import sys
from pathlib import Path

CANON_RULE = "canonical_messages_v1"  # reimplemented independently below


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


def audit_run(root: Path, *, expected_prompt: bytes, upstream_e_outputs=None, j_anchors=None,
              sink_quotes=None, frozen_pages=None, allowlist=None) -> dict:
    """Audit one run directory. frozen_pages: {(doc,page): {"text_norm_source": str,
    "page_sha256":..., "raw_sha256":...}} for L1. Returns report dict with pass/fail."""
    failures = []

    # manifest verification (no self-hash by construction)
    mpath = root / "MANIFEST.json"
    if not mpath.exists():
        return {"verdict": "FAIL", "failures": ["MANIFEST missing"]}
    manifest = json.loads(mpath.read_text())
    for entry in manifest["files"]:
        p = root / entry["path"]
        if not p.exists():
            failures.append(f"manifest file missing: {entry['path']}")
        elif _sha(p.read_bytes()) != entry["sha256"] or p.stat().st_size != entry["bytes"]:
            failures.append(f"manifest mismatch: {entry['path']}")

    # per-call: four files, hash classes, prompt equality, identity, budget
    ledger = [json.loads(l) for l in (root / "ledger.jsonl").read_text().splitlines() if l.strip()]
    seen_calls = set()
    for line in ledger:
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
        # prompt equality (independent): ledger prompt hash == canon(rebuild expected)
        if _sha(expected_prompt) != line["prompt_sha256"]:
            failures.append(f"prompt_sha256 vs expected rebuild mismatch {cid}")
        # extract from ACTUAL body and compare with expected rebuild
        extracted = _extract_canon_from_body(req_bytes)
        if extracted is None or _sha(extracted) != _sha(expected_prompt):
            failures.append(f"PROMPT_EQUALITY: rebuild != actual body ({cid})")
        rsp = d / f"{cid}.response_body.bin"
        if line.get("response_body_sha256"):
            if not rsp.exists() or _sha(rsp.read_bytes()) != line["response_body_sha256"]:
                failures.append(f"response_body_sha256 mismatch {cid}")
            resp = json.loads(rsp.read_bytes())
            if allowlist is not None and line.get("record", {}).get("identity"):
                if resp.get("model") not in allowlist:
                    failures.append(f"IDENTITY mismatch {cid}: {resp.get('model')!r}")
        else:
            status = (d / f"{cid}.response_meta.json")
            if not status.exists():
                failures.append(f"response artifacts missing for no-response call {cid}")
        # budget recomputation (independent): reservation formula
        if line.get("budget_reserved_this_call") is not None and line.get("est_in_tokens") is not None:
            exp = line["est_in_tokens"] / 1e6 * line["unit_price_in"] + \
                  (line.get("max_tokens") or 2500) / 1e6 * line["unit_price_out"]
            if abs(exp - line["budget_reserved_this_call"]) > 5e-6:  # ledger stores 6dp
                failures.append(f"reservation arithmetic mismatch {cid}")

    # payload<->ledger closure
    for d in (root / "payloads").iterdir():
        if d.name not in seen_calls:
            failures.append(f"orphan payload dir: {d.name}")

    # L1/L2/L3 anchors (independent)
    if frozen_pages and upstream_e_outputs:
        for out in upstream_e_outputs:  # L1: E quote must exist in frozen page text
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
                failures.append(f"L1: E quote not found in frozen page text ({out.get('label','')})")
    if upstream_e_outputs and j_anchors:
        for a in j_anchors:  # L2: J anchor must equal upstream E anchor field-by-field
            match = any(
                e["doc"] == a["doc"] and e["page"] == a["page"] and e["quote"] == a["quote"]
                and e["page_sha256"] == a["page_sha256"] and e["raw_sha256"] == a["raw_sha256"]
                for e in upstream_e_outputs)
            if not match:
                failures.append(f"L2: J anchor not inherited verbatim from E ({a.get('label','')})")
    if j_anchors and sink_quotes:
        for q in sink_quotes:  # L3: sink quote must come from J-verified anchors
            if not any(a["quote"] == q for a in j_anchors):
                failures.append(f"L3: sink cites unverified anchor ({q[:20]}…)")

    return {"verdict": "PASS" if not failures else "FAIL", "failures": failures}


if __name__ == "__main__":
    print("audit.py is a library verifier; driven by dryrun_tests.py (T-matrix + tamper samples)")
