#!/usr/bin/env python3
"""Controlled entry point for frozen E4.0-B-v2 collection."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from phase_e4_0.execution_controls import (
    PENDING,
    ProviderHealth,
    attempts_by_key,
    balanced,
    build_recollection_manifest,
    canonicalize_node_output,
    classify,
    dependency_ready,
    generation_ceiling_binding,
    health_audit,
    http_status,
    latest_by_key,
    node_schema_valid,
    revalidate_records,
    truncation_reconciliation,
    validator_contract_audit,
    outcome_key,
    parse_json_object,
    select_provider_limited_batch,
)
from run_e4_0_b_exploration import (
    API,
    CONFIG,
    MAX_COST,
    NODES,
    PROJECT,
    ROOT,
    SOURCE,
    load_env,
    parse,
    prompt,
    rows,
    state_from,
)

OUT = ROOT / "phase_e4_0_v2"
PLAN = OUT / "E4_0_B_V2_EXPLORATION_PLAN.jsonl"
SPLIT = OUT / "E4_0_B_V2_SPLIT.json"
EVENTS = OUT / "E4_0_B_V2_EXPLORATION_EVENTS.jsonl"
LOG = OUT / "E4_0_B_V2_EXPLORATION_NODE_LOG.jsonl"
PREFLIGHT = OUT / "E4_0_B_V2_LONG_N1_PREFLIGHT.json"
EFFECTIVE_PREFLIGHT = OUT / "E4_0_B_V2_EFFECTIVE_PREFLIGHT.json"
PREFLIGHT_AMENDMENT = ROOT / "phase_e4_0" / "E4_0_B_EXECUTION_AMENDMENT_007.json"
RECOVERY_AMENDMENT = ROOT / "phase_e4_0" / "E4_0_B_EXECUTION_AMENDMENT_008.json"
EXECUTION_CLOSURE_AMENDMENT = ROOT / "phase_e4_0" / "E4_0_B_EXECUTION_AMENDMENT_009.json"
CEILING_POLICY_AMENDMENT = ROOT / "phase_e4_0" / "E4_0_B_EXECUTION_AMENDMENT_010.json"
FINAL_CEILING_AMENDMENT = ROOT / "phase_e4_0" / "E4_0_B_EXECUTION_AMENDMENT_012.json"
CALIBRATION = OUT / "E4_0_B_V2_DS_GLM_CALIBRATION.json"
AUDITS = OUT / "collection_health_audits"
AMENDMENT = ROOT / "phase_e4_0" / "E4_0_B_EXECUTION_AMENDMENT_006.json"
RECOLLECTION_MANIFEST = OUT / "E4_0_B_V2_AMENDMENT_006_RECOLLECTION_MANIFEST.json"
MODELS = ("deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo")
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (30, 120)
MAX_GAP = 20
GLOBAL_CONCURRENCY = 4
PER_PROVIDER_CONCURRENCY = 1
CHECKPOINTS = (50, 100, 200, 400, 640)
EXECUTION_CONTROL_VERSION = "E4.0-B-execution-amendment-006"
PENDING_INITIAL_RECOVERY_KEY = (
    "c9_d3ff77c9870ceda4a8e5",
    "c9_d3ff77c9870ceda4a8e5:V2T2",
    "N1",
)
F124_N2_KEY = ("c9_f124a01f37f67ae49cdb", "c9_f124a01f37f67ae49cdb:V2T3", "N2")
AUTHORIZED_RECOLLECT_KEYS = {
    ("c9_8399c2ea076354fdaf6d", "c9_8399c2ea076354fdaf6d:V2T2", "N1"),
    F124_N2_KEY,
}
AMENDMENT_010_RECOVERY_KEYS = {
    ("c9_8399c2ea076354fdaf6d", "c9_8399c2ea076354fdaf6d:V2T1", "N4"),
    ("c9_fbb620acce40675a352b", "c9_fbb620acce40675a352b:V2T1", "N3"),
}

def recovery_scope(recollect_keys):
    """Outcome-blind recovery scope from the engineering recollection manifest."""
    scope = set(recollect_keys)
    if not scope:
        raise RuntimeError("recovery-only requires at least one manifest-authorized RECOLLECT key")
    if any(len(key) != 3 or key[2] not in NODES for key in scope):
        raise RuntimeError("invalid canonical key in recollection manifest")
    return scope

THINKING_MODE = "provider_default_unchanged"


def in_execution_scope(key, recovery_keys, recovery_only):
    return not recovery_only or key in recovery_keys


def amendment_009_escalation_count(key, key_events):
    if key != F124_N2_KEY:
        return 0
    return sum(
        event.get("execution_reason") == "ENGINEERING_CEILING_ESCALATION"
        for event in key_events
    )


def amendment_009_escalation_allowed(key, key_events):
    return (
        key == F124_N2_KEY
        and amendment_009_escalation_count(key, key_events) < 2
        and any(
            event.get("finish_reason") == "length"
            and event.get("generation_ceiling_binding") is True
            for event in key_events
        )
    )


def amendment_010_escalation_count(key_events):
    return sum(
        event.get("execution_reason") == "ENGINEERING_CEILING_ESCALATION"
        and event.get("execution_control_version") == "E4.0-B-execution-amendment-010"
        for event in key_events
    )


def amendment_010_escalation_allowed(node, key_events):
    return (
        node in {"N3", "N4"}
        and amendment_010_escalation_count(key_events) < 2
        and any(
            event.get("finish_reason") == "length"
            and event.get("generation_ceiling_binding") is True
            for event in key_events
        )
    )


AMENDMENT_011_VERSION = "E4.0-B-execution-amendment-012"
CEILING_LADDERS = {
    "N1": (16384, 32768, 65536),
    "N2": (4096, 8192, 16384, 32768),
    "N3": (1600, 3200, 6400, 12800),
    "N4": (1200, 2400, 4800, 9600),
}

def amendment_011_next_level(node, key_events):
    ladder = CEILING_LADDERS[node]
    binding_ceilings = [
        int(event.get("max_tokens") or 0) for event in key_events
        if event.get("generation_ceiling_binding") is True
    ]
    if not binding_ceilings:
        return 0
    last = max(binding_ceilings)
    return next((i for i, ceiling in enumerate(ladder) if ceiling > last), len(ladder))

def amendment_011_escalation_allowed(node, key_events):
    return amendment_011_next_level(node, key_events) < len(CEILING_LADDERS[node]) and any(
        event.get("generation_ceiling_binding") is True
        for event in key_events
    )

def amendment_011_binding_can_continue(node, event):
    return (
        event.get("generation_ceiling_binding") is True
        and int(event.get("max_tokens") or 0) < CEILING_LADDERS[node][-1]
    )

_ENGINEERING_ONLY_DROP_KEYS = frozenset(
    {
        "semantic_quality",
        "reference_answer",
        "gold_answer",
        "gold_evidence",
        "judge_score",
        "candidate_quality",
        "internal_holdout_outcome",
        "c10_outcome",
    }
)


def _engineering_projection(value):
    if isinstance(value, dict):
        return {
            key: _engineering_projection(item)
            for key, item in value.items()
            if key not in _ENGINEERING_ONLY_DROP_KEYS
        }
    if isinstance(value, list):
        return [_engineering_projection(item) for item in value]
    return value


def screened_rows(path):
    if not path.exists():
        return [], {"path": str(path), "exists": False}
    return [_engineering_projection(row) for row in rows(path)], {
        "path": str(path),
        "exists": True,
        "engineering_projection": True,
    }


def finish_reason(result):
    try:
        return result["choices"][0].get("finish_reason")
    except Exception:
        return None


def append(path, row):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_json_atomic(path, payload):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def preflight_passed(effective_path=EFFECTIVE_PREFLIGHT, root=ROOT):
    effective_path = Path(effective_path)
    if not effective_path.exists():
        return False
    try:
        data = json.loads(effective_path.read_text())
        models = data["models"]
        required = {"deepseek-chat", "glm-5.2", "qwen-plus", "qwen-turbo"}
        if data.get("status") != "PASS" or set(models) != required:
            return False
        if not all(item.get("status") == "PASS" and item.get("model") == model for model, item in models.items()):
            return False
        for item in models.values():
            source = Path(root) / item["source_path"]
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != item["source_sha256"]:
                return False
        return data.get("outcome_blind") is True and data.get("semantic_quality_accessed") is False
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def node_ceiling(node, model, *, escalation_level=0):
    ladder = CEILING_LADDERS[node]
    return ladder[min(escalation_level, len(ladder) - 1)]


def node_timeout(node):
    return 240.0 if node == "N1" else 120.0


def endpoint(llm):
    path = (llm.chat_path or "/chat/completions").strip()
    if not path.startswith("/"):
        path = "/" + path
    return f"{llm.base_url.rstrip('/')}{path}"


def frozen_state_from(previous, spent, budget):
    if not previous:
        return {
            "upstream_provider_success": None,
            "upstream_schema_valid": None,
            "upstream_evidence_count": 0,
            "upstream_extraction_field_count": 0,
            "upstream_confidence": None,
            "upstream_output_length": 0,
            "upstream_latency_ms": 0.0,
            "cumulative_cost_usd": 0.0,
            "remaining_budget_usd": budget,
            "retry_count": 0,
        }
    last = previous[-1]
    parsed = last.get("parsed_output") or {}
    evidence = parsed.get("evidence_items", []) if isinstance(parsed, dict) else []
    fields = parsed.get("fields", {}) if isinstance(parsed, dict) else {}
    confidence = parsed.get("confidence") if isinstance(parsed, dict) else None
    post = last["post_action_outcome"]
    schema_valid = post.get("node_schema_valid")
    if schema_valid is None:
        schema_valid = post.get("format_valid")
    return {
        "upstream_provider_success": post["provider_success"],
        "upstream_schema_valid": schema_valid,
        "upstream_evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "upstream_extraction_field_count": len(fields) if isinstance(fields, dict) else 0,
        "upstream_confidence": confidence if isinstance(confidence, (int, float)) and 0 <= confidence <= 1 else None,
        "upstream_output_length": len(last.get("raw_output", "")),
        "upstream_latency_ms": sum(item["post_action_outcome"]["total_latency_ms"] for item in previous),
        "cumulative_cost_usd": sum(item["post_action_outcome"]["cost_usd"] for item in previous),
        "remaining_budget_usd": max(0, budget - spent),
        "retry_count": sum(max(0, item["post_action_outcome"]["attempt"] - 1) for item in previous),
    }


def checkpoint_target(completed, target):
    later = [checkpoint for checkpoint in CHECKPOINTS if completed < checkpoint <= target]
    return min(later) if later else target


def retry_state(events, attempts, outcomes):
    latest_event = {}
    for event in events:
        latest_event[outcome_key(event)] = event
    now_wall = time.time()
    now_mono = time.monotonic()
    next_attempt_at = {}
    retry_backoff_ms = {}
    for key, count in attempts.items():
        if key in outcomes or count <= 0:
            continue
        delay = BACKOFF_SECONDS[min(count - 1, len(BACKOFF_SECONDS) - 1)]
        timestamp = latest_event[key].get("timestamp")
        try:
            completed_at = datetime.fromisoformat(timestamp).timestamp()
        except (TypeError, ValueError):
            completed_at = now_wall
        remaining = max(0.0, completed_at + delay - now_wall)
        next_attempt_at[key] = now_mono + remaining
        retry_backoff_ms[key] = delay * 1000.0
    return next_attempt_at, retry_backoff_ms


def write_recollection_manifest(records, events):
    payload = build_recollection_manifest(records, events, EXECUTION_CONTROL_VERSION)
    write_json_atomic(RECOLLECTION_MANIFEST, payload)
    return payload


def recover_missing_events(records, events):
    identities = {(outcome_key(event), int(event.get("attempt") or 0)) for event in events}
    recovered = 0
    for record in records:
        post = record["post_action_outcome"]
        identity = (outcome_key(record), int(post.get("attempt") or 0))
        if identity in identities:
            continue
        event = {
            "task_id": record["task_id"],
            "trajectory_id": record["trajectory_id"],
            "node_id": record["node_id"],
            "selected_model": record["selected_model"],
            **post,
        }
        append(EVENTS, event)
        events.append(event)
        identities.add(identity)
        recovered += 1
    return recovered


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-outcomes", type=int)
    parser.add_argument("--recovery-only", action="store_true")
    args = parser.parse_args()

    load_env()
    sys.path.insert(0, str(PROJECT))
    from openclaw_router.config import OpenClawConfig
    from openclaw_router.server import LLMBackend
    from scripts.run_finance_model_evaluation import answer_from_result, cost_usd, usage_from_result

    cfg = OpenClawConfig.from_yaml(str(CONFIG))
    backend = LLMBackend(cfg)
    plans = rows(PLAN)
    tasks = {task["task_id"]: task for task in rows(SOURCE)}
    expected = len(plans) * len(NODES)
    model_metadata = {}
    for model in MODELS:
        llm = cfg.llms[API[model]]
        model_metadata[model] = {
            "provider": llm.provider,
            "provider_endpoint": endpoint(llm),
            "configured_context_limit": llm.context_limit,
        }
    model_to_provider = {model: metadata["provider"] for model, metadata in model_metadata.items()}

    records, record_screen = screened_rows(LOG)
    event_rows, event_screen = screened_rows(EVENTS)
    logged_records = records
    events = event_rows
    if not args.audit_only:
        write_recollection_manifest(logged_records, events)
        recover_missing_events(logged_records, events)
    attempts = attempts_by_key(events)
    logged = latest_by_key(logged_records)
    recollection = build_recollection_manifest(logged_records, events, EXECUTION_CONTROL_VERSION)
    recollect_keys = {
        tuple(entry["key"])
        for entry in recollection["entries"]
        if entry["recollection_allowed"]
    }
    outcomes = {
        key: record
        for key, record in logged.items()
        if key not in recollect_keys and classify(record, attempts[key], MAX_ATTEMPTS) != PENDING
    }

    def audit_payload():
        entries = recollection["entries"]
        keep_keys = {tuple(entry["key"]) for entry in entries if entry["classification"] == "KEEP"}
        keep_records = [record for key, record in logged.items() if key in keep_keys]
        revalidation = revalidate_records(keep_records)
        truncation = truncation_reconciliation(logged_records, events, entries)
        validator_audit = validator_contract_audit()
        effective_preflight = json.loads(EFFECTIVE_PREFLIGHT.read_text()) if EFFECTIVE_PREFLIGHT.exists() else {}
        engineering_superseded_keys = {
            outcome_key(record) for record in logged_records
            if record.get("post_action_outcome", {}).get("recovery_execution_class") == "RECOLLECT"
        }
        payload = health_audit(
            events, outcomes, MODELS, NODES, expected, MAX_COST,
            plans=plans, records=logged_records, model_to_provider=model_to_provider,
            revalidation_completed=revalidation["completed"],
            validator_implementation_verified=validator_audit["verified"],
            engineering_superseded_keys=engineering_superseded_keys,
        )
        payload.update({
            "audit_screening": {"record_log": record_screen, "event_log": event_screen},
            "keep_count": sum(entry["classification"] == "KEEP" for entry in entries),
            "recollect_count": sum(entry["classification"] == "RECOLLECT" for entry in entries),
            "generation_ceiling_affected_key_count": sum(
                entry["invalidation_reason"] == "demonstrated_generation_ceiling_binding"
                for entry in entries
            ),
            "validator_contract_audit": validator_audit,
            "revalidation": revalidation,
            "truncation_reconciliation": truncation,
            "engineering_gate_status": "PASS" if payload["checkpoint_gate_pass"] else "FAIL",
            "ready_to_resume_collection": payload["checkpoint_gate_pass"],
            "ready_to_resume_normal_collection": payload["checkpoint_gate_pass"],
            "effective_preflight_status": effective_preflight.get("status"),
            "effective_preflight_all_models_pass": preflight_passed(),
            "original_long_n1_preflight_status": json.loads(PREFLIGHT.read_text()).get("status"),
            "semantic_quality_accessed": False,
            "reserved_holdout_accessed": False,
            "external_api_calls_during_audit": 0,
        })
        return payload

    if args.audit_only:
        print(json.dumps(audit_payload(), ensure_ascii=False, indent=2))
        return

    if not AMENDMENT.exists():
        raise RuntimeError("Amendment 006 must be frozen before formal collection")
    amendment = json.loads(AMENDMENT.read_text())
    if amendment.get("version") != EXECUTION_CONTROL_VERSION or amendment.get("status") != "FROZEN_ENGINEERING_REPAIR_BEFORE_RESUME":
        raise RuntimeError("Amendment 006 is not in the required frozen state")
    frozen_artifacts = amendment.get("frozen_artifact_sha256", {})
    for path in (PLAN, SPLIT):
        relative = str(path.relative_to(ROOT))
        expected_digest = frozen_artifacts.get(relative)
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected_digest or actual_digest != expected_digest:
            raise RuntimeError(f"frozen artifact hash mismatch: {relative}")
    frozen_code = amendment.get("frozen_execution_code_sha256", {})
    if not PREFLIGHT_AMENDMENT.exists():
        raise RuntimeError("Amendment 007 preflight evidence reconciliation is missing")
    preflight_amendment = json.loads(PREFLIGHT_AMENDMENT.read_text())
    if preflight_amendment.get("status") != "FROZEN_PREFLIGHT_EVIDENCE_RECONCILIATION":
        raise RuntimeError("Amendment 007 is not frozen")
    if not RECOVERY_AMENDMENT.exists():
        raise RuntimeError("Amendment 008 recovery-only control is missing")
    recovery_amendment = json.loads(RECOVERY_AMENDMENT.read_text())
    if recovery_amendment.get("status") != "FROZEN_RECOVERY_ONLY_CONTROL":
        raise RuntimeError("Amendment 008 is not frozen")
    if not EXECUTION_CLOSURE_AMENDMENT.exists():
        raise RuntimeError("Amendment 009 execution-control closure is missing")
    execution_closure_amendment = json.loads(EXECUTION_CLOSURE_AMENDMENT.read_text())
    if execution_closure_amendment.get("status") != "FROZEN_EXECUTION_CONTROL_CLOSURE":
        raise RuntimeError("Amendment 009 is not frozen")
    if not CEILING_POLICY_AMENDMENT.exists():
        raise RuntimeError("Amendment 010 generation-ceiling policy closure is missing")
    ceiling_policy_amendment = json.loads(CEILING_POLICY_AMENDMENT.read_text())
    if ceiling_policy_amendment.get("status") != "FROZEN_GENERATION_CEILING_POLICY_CLOSURE":
        raise RuntimeError("Amendment 010 is not frozen")
    if not FINAL_CEILING_AMENDMENT.exists():
        raise RuntimeError("Amendment 012 provider-normalized generation-ceiling closure is missing")
    final_ceiling_amendment = json.loads(FINAL_CEILING_AMENDMENT.read_text())
    if final_ceiling_amendment.get("status") != "FROZEN_PROVIDER_NORMALIZED_CEILING_CLOSURE":
        raise RuntimeError("Amendment 012 is not frozen")
    amended_code = final_ceiling_amendment.get("frozen_execution_code_sha256", {})
    for path in (Path(__file__).resolve(), ROOT / "phase_e4_0" / "execution_controls.py", ROOT / "phase_e4_0" / "interfaces.py"):
        relative = str(path.relative_to(ROOT))
        expected_digest = amended_code.get(relative)
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected_digest or actual_digest != expected_digest:
            raise RuntimeError(f"frozen execution code hash mismatch: {relative}")
    if not preflight_passed():
        raise RuntimeError("frozen four-model long-N1 gate is missing or failed; no new preflight is permitted")

    split = json.loads(SPLIT.read_text())
    allowed = set(split["exploration_train_task_ids"])
    if not {plan["task_id"] for plan in plans} <= allowed:
        raise RuntimeError("plan contains a task outside the frozen exploration split")
    if expected != 640:
        raise RuntimeError(f"frozen plan must contain 640 outcome keys, found {expected}")

    recovery_keys_to_run = recovery_scope(recollect_keys) if args.recovery_only else set()
    if args.recovery_only:
        if args.max_outcomes is not None:
            raise RuntimeError("--recovery-only cannot be combined with --max-outcomes")
        target = len(outcomes) + len(recovery_keys_to_run - set(outcomes))
    else:
        target = min(expected, args.max_outcomes or expected)
        if target not in CHECKPOINTS:
            raise RuntimeError(f"formal collection may stop only at frozen checkpoints {CHECKPOINTS}")
        if target < len(outcomes):
            raise RuntimeError("max outcomes is below already completed formal outcomes")
    spent = sum(float(event.get("cost_usd") or 0) for event in events)
    health = ProviderHealth(cooldown_seconds=600)
    next_attempt_at, retry_backoff_for_next = retry_state(events, attempts, outcomes)
    ready_since = {}
    events_by_key = defaultdict(list)
    for event in events:
        events_by_key[outcome_key(event)].append(event)

    def checkpoint_audit(count):
        if count not in CHECKPOINTS:
            return
        AUDITS.mkdir(exist_ok=True)
        path = AUDITS / f"health_{count:04d}.json"
        payload = audit_payload()
        write_json_atomic(path, payload)
        if not payload["checkpoint_gate_pass"]:
            reasons = "; ".join(payload["checkpoint_gate_failure_reasons"])
            raise RuntimeError(f"checkpoint {count} engineering gate failed: {reasons}")

    if len(outcomes) in CHECKPOINTS:
        checkpoint_audit(len(outcomes))

    while (recovery_keys_to_run - set(outcomes)) if args.recovery_only else len(outcomes) < target:
        completed = Counter(record["selected_model"] for record in outcomes.values())
        now_mono = time.monotonic()
        now_wall = time.time()
        boundary = checkpoint_target(len(outcomes), 100 if args.recovery_only else target)
        candidates = []
        scheduling_attempts = Counter(attempts)
        if args.recovery_only:
            for recovery_key in recovery_keys_to_run - set(outcomes):
                if amendment_011_escalation_allowed(recovery_key[2], events_by_key.get(recovery_key, [])):
                    scheduling_attempts[recovery_key] = min(scheduling_attempts[recovery_key], MAX_ATTEMPTS - 1)
        else:
            for scheduled_key, history in events_by_key.items():
                if amendment_011_escalation_allowed(scheduled_key[2], history):
                    scheduling_attempts[scheduled_key] = min(scheduling_attempts[scheduled_key], MAX_ATTEMPTS - 1)
        for plan in plans:
            candidate = dependency_ready(plan, outcomes, scheduling_attempts, NODES, MAX_ATTEMPTS)
            if not candidate:
                continue
            node, key, previous = candidate
            if args.recovery_only and key not in recovery_keys_to_run:
                continue
            model = plan["assignment"][node]
            provider = model_to_provider[model]
            ready_since.setdefault(key, now_mono)
            available_at = next_attempt_at.get(key, ready_since[key])
            if now_mono < available_at:
                continue
            if not health.available(provider, now_wall):
                continue
            if not balanced(model, completed, MODELS, MAX_GAP):
                continue
            priority = hashlib.sha256(f"{plan['ready_queue_priority_seed']}|{node}".encode()).hexdigest()
            candidates.append(
                {
                    "priority": priority,
                    "plan": plan,
                    "node": node,
                    "key": key,
                    "previous": previous,
                    "model": model,
                    "provider": provider,
                    "queue_anchor": available_at,
                    "collection_block": boundary,
                    "pre_action_state": frozen_state_from(previous, spent, MAX_COST),
                }
            )

        remaining = (
            len(recovery_keys_to_run - set(outcomes)) if args.recovery_only
            else target - len(outcomes)
        )
        batch_limit = min(GLOBAL_CONCURRENCY, remaining, boundary - len(outcomes))
        batch = select_provider_limited_batch(
            candidates,
            global_limit=batch_limit,
            per_provider_limit=PER_PROVIDER_CONCURRENCY,
        )
        if not batch:
            waits = [until - now_wall for until in health.cooldown_until.values() if until > now_wall]
            waits.extend(until - now_mono for until in next_attempt_at.values() if until > now_mono)
            if waits:
                await asyncio.sleep(min(min(waits), 60.0))
                continue
            raise RuntimeError("no schedulable node; inspect balance, dependency, and terminal states")

        async def call(candidate):
            plan = candidate["plan"]
            node = candidate["node"]
            key = candidate["key"]
            previous = candidate["previous"]
            model = candidate["model"]
            request = prompt(tasks[plan["task_id"]], node, previous)
            key_history = events_by_key.get(key, [])
            engineering_escalation = amendment_011_escalation_allowed(node, key_history)
            escalation_level = amendment_011_next_level(node, key_history)
            ceiling = node_ceiling(node, model, escalation_level=escalation_level)
            timeout = node_timeout(node)
            dispatch = time.monotonic()
            queue_wait_ms = max(0.0, (dispatch - candidate["queue_anchor"]) * 1000)
            retry_backoff_ms = retry_backoff_for_next.get(key, 0.0)
            provider_started = time.perf_counter()
            answer = ""
            usage = {}
            error = None
            result = {}
            try:
                result = await backend.call(
                    API[model],
                    [{"role": "user", "content": request}],
                    max_tokens=ceiling,
                    temperature=0,
                    stream=False,
                    timeout=timeout,
                )
                answer = answer_from_result(result)
                usage = usage_from_result(result, request, answer)
                if not answer.strip():
                    raise RuntimeError("empty answer")
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc!r}"[:1200]
            provider_latency_ms = round((time.perf_counter() - provider_started) * 1000, 2)
            parsed, json_valid, _ = parse_json_object(answer) if error is None else ({}, False, [])
            parsed, canonicalization_operations = canonicalize_node_output(node, parsed)
            schema_valid = node_schema_valid(node, parsed, json_valid)
            reason = finish_reason(result)
            empty_output = not answer.strip()
            billed = float(cost_usd(cfg, API[model], usage)) if usage else 0.0
            timestamp = datetime.now(timezone.utc).isoformat()
            metadata = model_metadata[model]
            post = {
                "provider_success": error is None,
                "provider_error": error,
                "json_parse_valid": json_valid,
                "node_schema_valid": schema_valid,
                "format_valid": schema_valid,
                "canonicalization_operations": canonicalization_operations,
                "first_token_latency_ms": None,
                "provider_latency_ms": provider_latency_ms,
                "retry_backoff_ms": retry_backoff_ms,
                "scheduler_queue_wait_ms": round(queue_wait_ms, 2),
                "total_latency_ms": round(provider_latency_ms + retry_backoff_ms, 2),
                "cost_usd": billed,
                "tokens": usage,
                "timestamp": timestamp,
                "execution_timestamp": timestamp,
                "attempt": attempts[key] + 1,
                "finish_reason": reason,
                "max_tokens": ceiling,
                "timeout_seconds": timeout,
                "generation_ceiling_binding": generation_ceiling_binding(
                    reason,
                    usage,
                    ceiling,
                    explicit_binding=False,
                    empty_output=empty_output,
                ),
                "requested_model_alias": model,
                "provider_returned_model": result.get("model") if isinstance(result, dict) else None,
                "provider": metadata["provider"],
                "provider_endpoint": metadata["provider_endpoint"],
                "execution_control_version": EXECUTION_CONTROL_VERSION,
                "configured_context_limit": metadata["configured_context_limit"],
                "thinking_mode": THINKING_MODE,
                "collection_block": candidate["collection_block"],
            }
            if args.recovery_only:
                post["recovery_execution_class"] = (
                    "RECOLLECT" if key in recollect_keys else "PENDING_INITIAL"
                )
                post["recovery_control_version"] = AMENDMENT_011_VERSION
            if engineering_escalation:
                post["execution_reason"] = "ENGINEERING_CEILING_ESCALATION"
                post["execution_control_version"] = AMENDMENT_011_VERSION
                post["previous_max_tokens"] = key_history[-1].get("max_tokens")
                post["new_max_tokens"] = ceiling
            return candidate, post, parsed, answer

        results = await asyncio.gather(*(call(candidate) for candidate in batch))
        for candidate, event_post, parsed, answer in results:
            plan = candidate["plan"]
            node = candidate["node"]
            key = candidate["key"]
            model = candidate["model"]
            provider = candidate["provider"]
            attempts[key] += 1
            spent += event_post["cost_usd"]
            status = http_status(event_post["provider_error"])
            health.observe(provider, status, time.time())
            final = event_post["provider_success"] or attempts[key] >= MAX_ATTEMPTS
            continue_engineering_escalation = amendment_011_binding_can_continue(node, event_post)
            accepted_terminal = final and not continue_engineering_escalation
            event = {
                "task_id": plan["task_id"],
                "trajectory_id": plan["trajectory_id"],
                "node_id": node,
                "selected_model": model,
                **event_post,
            }

            if final:
                attempt_history = events_by_key[key] + [event]
                post = dict(event_post)
                post.update({
                    "node_provider_latency_ms": round(sum(item["provider_latency_ms"] for item in attempt_history), 2),
                    "node_retry_backoff_ms": round(sum(item["retry_backoff_ms"] for item in attempt_history), 2),
                    "node_scheduler_queue_wait_ms": round(sum(item["scheduler_queue_wait_ms"] for item in attempt_history), 2),
                    "outcome_status": "SUCCESS" if event_post["provider_success"] else "PERMANENT_FAILURE",
                    "semantic_quality": "NOT_ACCESSED_DURING_COLLECTION" if event_post["provider_success"] else None,
                    "delivered_quality": "NOT_ACCESSED_DURING_COLLECTION" if event_post["provider_success"] else 0,
                })
                post["node_runtime_latency_ms"] = round(post["node_provider_latency_ms"] + post["node_retry_backoff_ms"], 2)
                post["total_latency_ms"] = post["node_runtime_latency_ms"]
                record = {
                    "task_id": plan["task_id"],
                    "trajectory_id": plan["trajectory_id"],
                    "node_id": node,
                    "node_type": {"N1": "evidence_localization", "N2": "structured_extraction", "N3": "financial_reasoning", "N4": "final_synthesis"}[node],
                    "request_features": tasks[plan["task_id"]]["observable_features"],
                    "pre_action_state": candidate["pre_action_state"],
                    "selected_model": model,
                    "behavior_probability": 0.25,
                    "randomization_seed": plan["randomization_seed"],
                    "post_action_outcome": post,
                    "parsed_output": parsed,
                    "raw_output": answer,
                }
                append(LOG, record)
                logged_records.append(record)
                if accepted_terminal:
                    outcomes[key] = record
                append(EVENTS, event)
            else:
                append(EVENTS, event)
                delay = BACKOFF_SECONDS[min(attempts[key] - 1, len(BACKOFF_SECONDS) - 1)]
                next_attempt_at[key] = time.monotonic() + delay
                retry_backoff_for_next[key] = delay * 1000.0

            events.append(event)
            events_by_key[key].append(event)
            if accepted_terminal:
                ready_since.pop(key, None)
                next_attempt_at.pop(key, None)
                retry_backoff_for_next.pop(key, None)
            print(json.dumps({
                "key": key, "model": model, "attempt": attempts[key],
                "final": accepted_terminal, "success": event_post["provider_success"],
                "format_valid": event_post["format_valid"],
                "engineering_escalation_continues": continue_engineering_escalation,
                "unique_outcomes": len(outcomes), "target": target, "cost_usd": round(spent, 4),
            }, ensure_ascii=False), flush=True)

        if spent > MAX_COST:
            raise RuntimeError(f"$10 hard cost cap exceeded: {spent:.4f}")
        if not args.recovery_only and len(outcomes) in CHECKPOINTS:
            checkpoint_audit(len(outcomes))

    print(
        json.dumps(
            {
                "status": "TARGET_COMPLETE",
                "unique_outcomes": len(outcomes),
                "api_attempts": sum(attempts.values()),
                "cost_usd": round(spent, 4),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
