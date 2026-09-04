"""Engineering-only execution controls for frozen E4.0-B collection."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SUCCESS = "SUCCESS"
PERMANENT_FAILURE = "PERMANENT_FAILURE"
PENDING = "PENDING"
RETRYABLE = {401, 408, 409, 425, 429, 500, 502, 503, 504}
REQUIRED_TELEMETRY = (
    "requested_model_alias",
    "provider_returned_model",
    "provider",
    "provider_endpoint",
    "execution_control_version",
    "configured_context_limit",
    "max_tokens",
    "thinking_mode",
    "finish_reason",
    "attempt",
    "provider_latency_ms",
    "retry_backoff_ms",
    "scheduler_queue_wait_ms",
    "timeout_seconds",
    "tokens",
    "cost_usd",
    "execution_timestamp",
)
STATE_VOCABULARY = (
    "upstream_provider_success",
    "upstream_schema_valid",
    "upstream_evidence_count",
    "upstream_extraction_field_count",
    "upstream_confidence",
    "upstream_output_length",
    "upstream_latency_ms",
    "cumulative_cost_usd",
    "remaining_budget_usd",
    "retry_count",
)
DEFAULT_UNOBSERVED_STRATUM_COST_USD = 0.01


def outcome_key(row):
    return row["task_id"], row["trajectory_id"], row["node_id"]


def http_status(error):
    text = error or ""
    for pattern in (r"status_code\s*=\s*(\d{3})", r"\b(\d{3})\s*:", r"HTTP\s+(\d{3})\b"):
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def classify(record, attempts, max_attempts=3):
    if record and record.get("post_action_outcome", {}).get("provider_success"):
        return SUCCESS
    return PERMANENT_FAILURE if attempts >= max_attempts else PENDING


def latest_by_key(records):
    latest = {}
    for record in records:
        latest[outcome_key(record)] = record
    return latest


def attempts_by_key(events):
    return Counter(outcome_key(event) for event in events)


def generation_ceiling_binding(finish_reason, usage=None, max_tokens=None, *, explicit_binding=False, empty_output=False):
    """Return binding only when provider telemetry supplies engineering evidence."""
    if explicit_binding or finish_reason == "length":
        return True
    if empty_output and finish_reason in {"length", "max_tokens"}:
        return True
    if finish_reason == "stop" and isinstance(usage, dict):
        completion = usage.get("completion_tokens")
        if completion is not None and max_tokens is not None and completion >= max_tokens:
            return True
    return False


def ceiling_escalation_allowed(event):
    return generation_ceiling_binding(
        event.get("finish_reason"),
        event.get("tokens") or event.get("usage"),
        event.get("max_tokens"),
        explicit_binding=event.get("generation_ceiling_binding") is True,
        empty_output=event.get("empty_output") is True,
    )


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def canonicalize_node_output(node, parsed):
    """Apply only registered, deterministic, lossless representation changes."""
    if not isinstance(parsed, dict):
        return parsed, []
    result = json.loads(json.dumps(parsed, ensure_ascii=False))
    operations = []
    confidence = result.get("confidence")
    if isinstance(confidence, str):
        try:
            converted = float(confidence)
        except ValueError:
            converted = None
        if converted is not None and math.isfinite(converted):
            result["confidence"] = converted
            operations.append("confidence_numeric_string_to_float")

    scalar_list_fields = {
        "N2": "missing",
        "N4": "citations",
    }
    field = scalar_list_fields.get(node)
    if field in result and isinstance(result[field], list):
        converted_items = []
        changed = False
        for item in result[field]:
            if isinstance(item, (str, int, float, bool)):
                value = str(item) if not isinstance(item, str) else item
                changed = changed or value != item
                converted_items.append(value)
            else:
                converted_items.append(item)
        result[field] = converted_items
        if changed:
            operations.append(f"{node}_{field}_scalar_member_to_string")

    if node == "N4" and "answer" in result and isinstance(result["answer"], (int, float, bool)):
        result["answer"] = str(result["answer"])
        operations.append("answer_scalar_to_string")
    return result, operations


def parse_json_object(answer):
    if not isinstance(answer, str) or not answer.strip():
        return {}, False, []
    text = answer.strip()
    if text.startswith("```") or text.endswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return {}, False, []
        text = match.group(1).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, False, []
    if not isinstance(parsed, dict):
        return {}, False, []
    return parsed, True, []


def _schema_failure_reasons(node, parsed, json_valid):
    if not json_valid:
        return ["json_parse_invalid"]
    if not isinstance(parsed, dict):
        return ["response_not_object"]
    reasons = []
    confidence = parsed.get("confidence")
    if not _is_number(confidence) or not 0 <= confidence <= 1:
        reasons.append("confidence_type_or_range")
    if node == "N1":
        items = parsed.get("evidence_items")
        if not isinstance(items, list):
            reasons.append("evidence_items_not_list")
        else:
            for item in items:
                if not (
                    isinstance(item, dict)
                    and set(item) == {"quote", "source_hint"}
                    and isinstance(item["quote"], str)
                    and bool(item["quote"].strip())
                    and isinstance(item["source_hint"], str)
                    and bool(item["source_hint"].strip())
                ):
                    reasons.append("evidence_item_keys_or_types")
                    break
    elif node == "N2":
        if set(parsed) != {"fields", "missing", "confidence"}:
            reasons.append("required_or_unexpected_keys")
        if not isinstance(parsed.get("fields"), dict):
            reasons.append("fields_not_object")
        missing = parsed.get("missing")
        if not isinstance(missing, list):
            reasons.append("missing_not_list")
        elif not all(isinstance(item, str) for item in missing):
            reasons.append("missing_member_not_string")
    elif node == "N3":
        if set(parsed) != {"intermediate_result", "assumptions", "evidence_links", "confidence"}:
            reasons.append("required_or_unexpected_keys")
        if not isinstance(parsed.get("intermediate_result"), (dict, int, float, str)) or isinstance(parsed.get("intermediate_result"), bool):
            reasons.append("intermediate_result_type")
        if not isinstance(parsed.get("assumptions"), list):
            reasons.append("assumptions_not_list")
        if not isinstance(parsed.get("evidence_links"), list):
            reasons.append("evidence_links_not_list")
    elif node == "N4":
        if set(parsed) != {"answer", "citations", "confidence"}:
            reasons.append("required_or_unexpected_keys")
        if not isinstance(parsed.get("answer"), str) or not parsed.get("answer", "").strip():
            reasons.append("answer_not_nonempty_string")
        citations = parsed.get("citations")
        if not isinstance(citations, list):
            reasons.append("citations_not_list")
        elif not all(isinstance(item, str) for item in citations):
            reasons.append("citation_member_not_string")
    return reasons


def node_schema_valid(node, parsed, json_valid=True):
    if not json_valid or not isinstance(parsed, dict):
        return False
    confidence = parsed.get("confidence")
    if not _is_number(confidence) or not 0 <= confidence <= 1:
        return False
    if node == "N1":
        items = parsed.get("evidence_items")
        return isinstance(items, list) and all(
            isinstance(item, dict)
            and set(item) == {"quote", "source_hint"}
            and isinstance(item["quote"], str)
            and bool(item["quote"].strip())
            and isinstance(item["source_hint"], str)
            and bool(item["source_hint"].strip())
            for item in items
        )
    if node == "N2":
        return (
            set(parsed) == {"fields", "missing", "confidence"}
            and isinstance(parsed["fields"], dict)
            and isinstance(parsed["missing"], list)
            and all(isinstance(item, str) for item in parsed["missing"])
        )
    if node == "N3":
        return (
            set(parsed) == {"intermediate_result", "assumptions", "evidence_links", "confidence"}
            and isinstance(parsed["intermediate_result"], (dict, int, float, str))
            and not isinstance(parsed["intermediate_result"], bool)
            and isinstance(parsed["assumptions"], list)
            and isinstance(parsed["evidence_links"], list)
        )
    if node == "N4":
        return (
            set(parsed) == {"answer", "citations", "confidence"}
            and isinstance(parsed["answer"], str)
            and bool(parsed["answer"].strip())
            and isinstance(parsed["citations"], list)
            and all(isinstance(item, str) for item in parsed["citations"])
        )
    return False
def validator_contract_audit():
    """Check frozen validators against independent positive/negative vectors."""
    vectors = (
        ("N1", {"evidence_items": [], "confidence": 0.5}, True),
        ("N1", {"answer": "wrong", "confidence": 0.5}, False),
        ("N2", {"fields": {}, "missing": [], "confidence": 0.5}, True),
        ("N2", {"fields": {}, "missing": [], "confidence": 2}, False),
        ("N3", {"intermediate_result": 1, "assumptions": [], "evidence_links": [], "confidence": 0.5}, True),
        ("N3", {"intermediate_result": True, "assumptions": [], "evidence_links": [], "confidence": 0.5}, False),
        ("N4", {"answer": "1", "citations": [], "confidence": 0.5}, True),
        ("N4", {"answer": "", "citations": [], "confidence": 0.5}, False),
    )
    checks = []
    for node, value, expected in vectors:
        actual = node_schema_valid(node, value, True)
        reasons_consistent = bool(_schema_failure_reasons(node, value, True)) is (not actual)
        checks.append({
            "node_id": node,
            "expected": expected,
            "actual": actual,
            "failure_reasons_consistent": reasons_consistent,
            "pass": actual is expected and reasons_consistent,
        })
    return {"verified": all(item["pass"] for item in checks), "check_count": len(checks), "checks": checks}



def percentile(values, p):
    if not values:
        return None
    values = sorted(float(value) for value in values)
    position = (len(values) - 1) * p
    low = math.floor(position)
    high = math.ceil(position)
    value = values[low] if low == high else values[low] * (high - position) + values[high] * (position - low)
    return round(value, 2)


@dataclass
class ProviderHealth:
    cooldown_seconds: int = 600
    consecutive_429: Counter = field(default_factory=Counter)
    cooldown_until: dict = field(default_factory=dict)

    def observe(self, provider, status, now):
        self.consecutive_429[provider] = self.consecutive_429[provider] + 1 if status == 429 else 0
        if self.consecutive_429[provider] >= 3:
            self.cooldown_until[provider] = now + self.cooldown_seconds
            self.consecutive_429[provider] = 0
            return True
        return False

    def available(self, provider, now):
        return now >= self.cooldown_until.get(provider, 0)


def balanced(model, completed, models, max_gap=20):
    floor = min(completed.get(candidate, 0) for candidate in models)
    return completed.get(model, 0) < floor + max_gap


def dependency_ready(plan, outcomes, attempts, nodes, max_attempts=3):
    previous = []
    for node in nodes:
        key = (plan["task_id"], plan["trajectory_id"], node)
        record = outcomes.get(key)
        if classify(record, attempts.get(key, 0), max_attempts) in {SUCCESS, PERMANENT_FAILURE}:
            previous.append(record)
            continue
        return node, key, previous
    return None


def select_provider_limited_batch(candidates, global_limit=4, per_provider_limit=1):
    batch = []
    trajectories = set()
    provider_counts = Counter()
    for candidate in sorted(candidates, key=lambda item: item["priority"]):
        trajectory = candidate["plan"]["trajectory_id"]
        provider = candidate["provider"]
        if trajectory in trajectories or provider_counts[provider] >= per_provider_limit:
            continue
        batch.append(candidate)
        trajectories.add(trajectory)
        provider_counts[provider] += 1
        if len(batch) >= global_limit:
            break
    return batch


def _records_by_key(records):
    if isinstance(records, dict):
        return records, 0
    grouped = defaultdict(list)
    for record in records:
        grouped[outcome_key(record)].append(record)
    return {key: values[-1] for key, values in grouped.items()}, sum(max(0, len(values) - 1) for values in grouped.values())


def plan_reconciliation(plans, outcomes, nodes):
    expected_assignments = {}
    duplicate_plan_keys = 0
    for plan in plans:
        for node in nodes:
            key = (plan["task_id"], plan["trajectory_id"], node)
            if key in expected_assignments:
                duplicate_plan_keys += 1
            expected_assignments[key] = plan["assignment"][node]
    actual, duplicate_observed_keys = _records_by_key(outcomes)
    actual_keys = set(actual)
    expected_keys = set(expected_assignments)
    mismatches = []
    for key in sorted(actual_keys & expected_keys):
        selected = actual[key].get("selected_model")
        expected = expected_assignments[key]
        if selected != expected:
            mismatches.append({"key": list(key), "expected": expected, "actual": selected})

    transition_progress = Counter()
    transition_expected = Counter()
    for plan in plans:
        for upstream, downstream in zip(nodes, nodes[1:]):
            pair = f"{upstream}>{downstream}|{plan['assignment'][upstream]}>{plan['assignment'][downstream]}"
            transition_expected[pair] += 1
            upstream_key = (plan["task_id"], plan["trajectory_id"], upstream)
            downstream_key = (plan["task_id"], plan["trajectory_id"], downstream)
            if upstream_key in actual and downstream_key in actual:
                transition_progress[pair] += 1

    trajectory_nodes = Counter((key[0], key[1]) for key in actual_keys)
    incomplete_trajectories = sum(count != len(nodes) for count in trajectory_nodes.values())
    complete = actual_keys == expected_keys
    transition_balance = all(value == 10 for value in transition_expected.values())
    transition_gate = complete and transition_balance and transition_progress == transition_expected
    assignment_gate = (
        duplicate_plan_keys == 0
        and duplicate_observed_keys == 0
        and not mismatches
        and not (actual_keys - expected_keys)
    )
    return {
        "expected_key_count": len(expected_keys),
        "observed_key_count": len(actual_keys),
        "missing_key_count": len(expected_keys - actual_keys),
        "unexpected_key_count": len(actual_keys - expected_keys),
        "duplicate_plan_key_count": duplicate_plan_keys,
        "duplicate_observed_key_count": duplicate_observed_keys,
        "incomplete_trajectory_count": incomplete_trajectories,
        "assignment_mismatch_count": len(mismatches),
        "assignment_mismatches": mismatches[:20],
        "transition_progress": dict(sorted(transition_progress.items())),
        "transition_expected": dict(sorted(transition_expected.items())),
        "transition_balance_gate_pass": transition_balance,
        "complete_assignment_gate_pass": assignment_gate,
        "complete_transition_gate_pass": transition_gate,
    }


def stratified_cost_projection(events, nodes, models, expected_per_stratum=40, conservative_estimate_usd=DEFAULT_UNOBSERVED_STRATUM_COST_USD):
    strata = {}
    total_observed_cost = 0.0
    for node in nodes:
        for model in models:
            values = [
                float(event.get("cost_usd") or 0.0)
                for event in events
                if event.get("node_id") == node and event.get("selected_model") == model
            ]
            mean = sum(values) / len(values) if values else None
            estimate = mean if mean is not None else float(conservative_estimate_usd)
            projected = expected_per_stratum * estimate
            uncertainty = (max(values) - min(values)) / 2 if values else float(conservative_estimate_usd)
            strata[f"{node}|{model}"] = {
                "node": node,
                "model": model,
                "observed_attempt_count": len(values),
                "observed_mean_cost_usd": round(mean, 8) if mean is not None else None,
                "conservative_estimate_cost_usd": round(estimate, 8),
                "uncertainty_half_range_usd": round(uncertainty, 8),
                "projected_cost_usd": round(projected, 8),
            }
            total_observed_cost += sum(values)
    projected_total = sum(item["projected_cost_usd"] for item in strata.values())
    uncertainty_total = sum(item["uncertainty_half_range_usd"] * expected_per_stratum for item in strata.values())
    return {
        "method": "frozen_16_node_model_strata",
        "expected_per_stratum": expected_per_stratum,
        "unobserved_stratum_estimate_method": "pre_registered_fixed_conservative_engineering_estimate",
        "unobserved_stratum_estimate_usd": conservative_estimate_usd,
        "observed_attempt_cost_usd": round(total_observed_cost, 8),
        "projected_total_cost_usd": round(projected_total, 8),
        "uncertainty_half_range_total_usd": round(uncertainty_total, 8),
        "strata": strata,
    }


def classify_recollection(record, events, amendment_version):
    key = outcome_key(record)
    key_events = [event for event in events if outcome_key(event) == key]
    attempts = [int(event.get("attempt") or 0) for event in key_events]
    current_post = record.get("post_action_outcome", {})
    current_binding = current_post.get("generation_ceiling_binding") is True
    engineering_reasons = []
    if current_binding or any(
        ceiling_escalation_allowed(event)
        and int(event.get("attempt") or 0) >= int(current_post.get("attempt") or 0)
        for event in key_events
    ):
        engineering_reasons.append("demonstrated_generation_ceiling_binding")
    if current_post.get("execution_defect") is True or any(
        event.get("execution_defect") is True
        and int(event.get("attempt") or 0) >= int(current_post.get("attempt") or 0)
        for event in key_events
    ):
        engineering_reasons.append("execution_implementation_defect")
    success = current_post.get("provider_success") is True
    if success and not engineering_reasons:
        category = "KEEP"
        allowed = False
    elif engineering_reasons:
        category = "RECOLLECT"
        allowed = True
    else:
        category = "INVALIDATE_ENGINEERING"
        allowed = False
    return {
        "key": list(key),
        "old_attempt_ids": sorted(attempts),
        "invalidation_reason": engineering_reasons[0] if engineering_reasons else None,
        "amendment_version": amendment_version,
        "recollection_allowed": allowed,
        "classification": category,
    }


def build_recollection_manifest(records, events, amendment_version):
    latest, duplicates = _records_by_key(records)
    entries = [classify_recollection(record, events, amendment_version) for _, record in sorted(latest.items())]
    return {
        "version": "E4.0-B-v2-recollection-manifest-v1",
        "amendment_version": amendment_version,
        "outcome_blind": True,
        "semantic_quality_inspected": False,
        "existing_formal_key_count": len(entries),
        "duplicate_record_count": duplicates,
        "recollection_allowed_count": sum(item["recollection_allowed"] for item in entries),
        "entries": entries,
    }


def revalidate_record(record):
    raw_output = record.get("raw_output")
    parsed, json_valid, _ = parse_json_object(raw_output)
    canonicalized, operations = canonicalize_node_output(record["node_id"], parsed)
    schema_valid = node_schema_valid(record["node_id"], canonicalized, json_valid)
    schema_failure_reasons = _schema_failure_reasons(record["node_id"], canonicalized, json_valid)
    if not json_valid:
        reason = "json_parse_invalid"
    elif not schema_valid:
        reason = schema_failure_reasons[0] if schema_failure_reasons else "node_schema_invalid"
    else:
        reason = None
    return {
        "key": list(outcome_key(record)),
        "node_id": record["node_id"],
        "selected_model": record["selected_model"],
        "json_parse_valid": json_valid,
        "node_schema_valid": schema_valid,
        "canonicalization_operations": operations,
        "failure_reason": reason,
        "schema_failure_reasons": schema_failure_reasons,
    }


def revalidate_records(records):
    results = [revalidate_record(record) for record in records]
    return {
        "completed": len(results) == len(records),
        "record_count": len(results),
        "results": results,
        "historical_format_valid_rate": (
            sum(bool(record.get("post_action_outcome", {}).get("format_valid")) for record in records) / len(records)
            if records else None
        ),
        "current_revalidated_json_parse_valid_rate": (
            sum(item["json_parse_valid"] for item in results) / len(results) if results else None
        ),
        "current_revalidated_node_schema_valid_rate": (
            sum(item["node_schema_valid"] for item in results) / len(results) if results else None
        ),
        "genuine_model_schema_invalid_count": sum(
            not item["node_schema_valid"] for item in results
        ),
        "failure_reasons_by_node": {
            node: dict(
                Counter(
                    item["failure_reason"]
                    for item in results
                    if item["node_id"] == node and item["failure_reason"] is not None
                )
            )
            for node in ("N1", "N2", "N3", "N4")
        },
        "failure_reasons_by_model": {
            model: dict(Counter(
                item["failure_reason"] for item in results
                if item["selected_model"] == model and item["failure_reason"] is not None
            ))
            for model in sorted({item["selected_model"] for item in results})
        },
    }


def truncation_reconciliation(records, events, recollection_entries):
    latest = latest_by_key(records)
    classifications = {
        tuple(entry["key"]): entry["classification"] for entry in recollection_entries
    }
    reasons = {
        tuple(entry["key"]): entry.get("invalidation_reason")
        for entry in recollection_entries
    }
    terminal_attempts = {
        key: int(record.get("post_action_outcome", {}).get("attempt") or 0)
        for key, record in latest.items()
    }
    table = []
    for event in events:
        key = outcome_key(event)
        attempt = int(event.get("attempt") or 0)
        classification = classifications.get(key, "PENDING_NO_TERMINAL_RECORD")
        superseded = key in terminal_attempts and attempt != terminal_attempts[key]
        binding = event.get("generation_ceiling_binding") is True
        if binding:
            reason = reasons.get(key) or "demonstrated_generation_ceiling_binding"
        elif superseded:
            reason = "superseded_by_later_attempt"
        else:
            reason = "retained_terminal_attempt"
        table.append(
            {
                "attempt_id": "|".join((*key, f"attempt-{attempt}")),
                "canonical_outcome_key": list(key),
                "generation_ceiling_binding": binding,
                "terminal_or_superseded": "superseded" if superseded else "terminal",
                "classification": classification,
                "reason": reason,
            }
        )
    historical_binding_count = sum(item["generation_ceiling_binding"] for item in table)
    historical_attempt_count = len(table)
    eligible = [item for item in table if item["classification"] == "KEEP"]
    eligible_binding_count = sum(item["generation_ceiling_binding"] for item in eligible)
    keep_keys = [key for key, value in classifications.items() if value == "KEEP"]
    terminal_retained = [
        item for item in table
        if item["classification"] == "KEEP" and item["terminal_or_superseded"] == "terminal"
    ]
    terminal_binding_count = sum(item["generation_ceiling_binding"] for item in terminal_retained)
    return {
        "table": table,
        "historical_truncation_attempt_count": historical_binding_count,
        "historical_truncation_rate": historical_binding_count / historical_attempt_count if historical_attempt_count else 0.0,
        "truncated_canonical_keys": sorted({tuple(item["canonical_outcome_key"]) for item in table if item["generation_ceiling_binding"]}),
        "eligible_attempt_count": len(eligible),
        "eligible_truncation_attempt_count": eligible_binding_count,
        "eligible_truncation_rate": eligible_binding_count / len(eligible) if eligible else 0.0,
        "terminal_retained_artificial_binding_count": terminal_binding_count,
        "terminal_retained_artificial_binding_rate": terminal_binding_count / len(terminal_retained) if terminal_retained else 0.0,
        "keep_key_count": len(keep_keys),
    }


def health_audit(
    events, outcomes, models, nodes, expected, max_cost=10, *, plans=None, records=None,
    model_to_provider=None, revalidation_completed=False, validator_implementation_verified=False,
    engineering_superseded_keys=None,
):
    finals = list(outcomes.values())
    attempts = len(events)
    model_to_provider = model_to_provider or {model: model for model in models}

    def summary(items):
        runtime = [item["post_action_outcome"].get("node_runtime_latency_ms", item["post_action_outcome"].get("total_latency_ms", 0)) for item in items]
        provider_latency = [item["post_action_outcome"].get("node_provider_latency_ms", item["post_action_outcome"].get("provider_latency_ms", 0)) for item in items]

        def engineering_flag(post, field, compatibility_field):
            value = post.get(field)
            return post.get(compatibility_field) if value is None else value

        return {
            "final_outcomes": len(items),
            "provider_success_rate": sum(bool(item["post_action_outcome"].get("provider_success")) for item in items) / len(items) if items else None,
            "json_parse_valid_rate": sum(bool(engineering_flag(item["post_action_outcome"], "json_parse_valid", "format_valid")) for item in items) / len(items) if items else None,
            "node_schema_valid_rate": sum(bool(engineering_flag(item["post_action_outcome"], "node_schema_valid", "format_valid")) for item in items) / len(items) if items else None,
            "runtime_latency_p50_ms": percentile(runtime, 0.5),
            "runtime_latency_p95_ms": percentile(runtime, 0.95),
            "provider_latency_p50_ms": percentile(provider_latency, 0.5),
            "provider_latency_p95_ms": percentile(provider_latency, 0.95),
        }

    per_model = {model: summary([item for item in finals if item["selected_model"] == model]) for model in models}
    per_node = {node: summary([item for item in finals if item["node_id"] == node]) for node in nodes}
    providers = sorted(set(model_to_provider.values()))
    per_provider = {provider: summary([item for item in finals if model_to_provider[item["selected_model"]] == provider]) for provider in providers}
    statuses = Counter(str(status) for event in events if (status := http_status(event.get("provider_error"))) is not None)
    truncated = sum(bool(event.get("generation_ceiling_binding")) for event in events)
    timeouts = sum("timeout" in str(event.get("provider_error") or "").lower() for event in events)
    model_counts = [per_model[model]["final_outcomes"] for model in models]
    projection = stratified_cost_projection(events, nodes, models)
    cost = sum(float(event.get("cost_usd") or 0) for event in events)
    overall = summary(finals)
    engineering_superseded_keys = set(engineering_superseded_keys or ())
    historical_success_counts = Counter(outcome_key(event) for event in events if event.get("provider_success"))
    historical_duplicate_success_count = sum(count - 1 for count in historical_success_counts.values() if count > 1)
    final_records = records if records is not None else finals
    _, historical_duplicate_record_count = _records_by_key(final_records)

    def active_duplicates(rows, nested_post=False):
        grouped = defaultdict(list)
        for row in rows:
            grouped[outcome_key(row)].append(row)
        duplicates = 0
        for values in grouped.values():
            def post(row):
                return row.get("post_action_outcome", {}) if nested_post else row
            highest = max(int(post(row).get("attempt") or 0) for row in values)
            active = [
                row for row in values
                if int(post(row).get("attempt") or 0) == highest
                and post(row).get("generation_ceiling_binding") is not True
                and post(row).get("execution_defect") is not True
            ]
            duplicates += max(0, len(active) - 1)
        return duplicates

    active_record_duplicates = active_duplicates(final_records, nested_post=True)
    active_success_duplicates = active_duplicates(
        [event for event in events if event.get("provider_success")], nested_post=False
    )
    active_duplicate_terminal_count = max(active_record_duplicates, active_success_duplicates)
    missing_telemetry = Counter(field for event in events for field in REQUIRED_TELEMETRY if field not in event)
    provider_outages = [provider for provider, values in per_provider.items() if values["final_outcomes"] >= 5 and values["provider_success_rate"] < 0.5]
    reconciliation = plan_reconciliation(plans, outcomes, nodes) if plans is not None else None
    actual_cost_pass = cost <= max_cost
    projected_cost_pass = projection["projected_total_cost_usd"] <= max_cost
    balance_pass = not model_counts or max(model_counts) - min(model_counts) <= 20
    parse_pass = overall["json_parse_valid_rate"] is None or overall["json_parse_valid_rate"] >= 0.95
    schema_pass = overall["node_schema_valid_rate"] is None or overall["node_schema_valid_rate"] >= 0.95
    truncation_rate = truncated / attempts if attempts else 0
    terminal_binding_count = sum(
        record.get("post_action_outcome", {}).get("generation_ceiling_binding") is True
        for record in finals
    )
    terminal_binding_rate = terminal_binding_count / len(finals) if finals else 0.0
    truncation_pass = terminal_binding_count == 0
    duplicate_pass = active_duplicate_terminal_count == 0
    telemetry_pass = not missing_telemetry
    provider_outage_pass = not provider_outages
    execution_defect_pass = not any(
        item.get("execution_defect") is True for item in events
    ) and not any(
        item.get("post_action_outcome", {}).get("execution_defect") is True for item in finals
    )
    plan_pass = reconciliation is None or reconciliation["complete_assignment_gate_pass"]
    completion_pass = True
    if len(finals) == expected and reconciliation is not None:
        completion_pass = reconciliation["missing_key_count"] == 0 and reconciliation["complete_transition_gate_pass"]
    gate_reasons = []
    for passed, reason in (
        (actual_cost_pass, "actual cost exceeds hard cap"),
        (projected_cost_pass, "stratified projected total cost exceeds hard cap"),
        (balance_pass, "model progress gap exceeds 20"),
        (revalidation_completed, "deterministic revalidation is incomplete"),
        (validator_implementation_verified, "validator implementation is not verified against the frozen schema"),
        (truncation_pass, "a retained terminal outcome is affected by an artificial generation ceiling"),
        (duplicate_pass, "duplicate formal success or final record detected"),
        (telemetry_pass, "required execution telemetry is missing"),
        (provider_outage_pass, "provider success rate is below 50% after at least 5 finals"),
        (execution_defect_pass, "an execution implementation defect is present"),
        (plan_pass, "observed assignment does not match frozen plan"),
        (completion_pass, "formal outcome key or transition integrity check failed"),
    ):
        if not passed:
            gate_reasons.append(reason)

    return {
        "status": "COLLECTION_HEALTH_ONLY_ENGINEERING",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "expected_outcomes": expected,
        "unique_final_outcomes": len(finals),
        "api_attempts": attempts,
        "total_cost_usd": round(cost, 8),
        "retry_rate": round(max(0, attempts - len(finals)) / attempts, 6) if attempts else 0,
        "http_status_counts": dict(statuses),
        "timeout_rate": round(timeouts / attempts, 6) if attempts else 0,
        "truncation_rate": round(truncation_rate, 6),
        "historical_attempt_truncation_rate": round(truncation_rate, 6),
        "terminal_engineering_binding_count": terminal_binding_count,
        "terminal_engineering_binding_rate": round(terminal_binding_rate, 6),
        "overall": overall,
        "per_model": per_model,
        "per_provider": per_provider,
        "per_node": per_node,
        "model_progress_gap": max(model_counts) - min(model_counts) if model_counts else 0,
        "historical_duplicate_success_count": historical_duplicate_success_count,
        "historical_duplicate_record_count": historical_duplicate_record_count,
        "active_duplicate_terminal_count": active_duplicate_terminal_count,
        "duplicate_success_count": active_success_duplicates,
        "duplicate_final_record_count": active_record_duplicates,
        "missing_telemetry_counts": dict(missing_telemetry),
        "provider_outages": provider_outages,
        "plan_reconciliation": reconciliation,
        "stratified_cost_projection": projection,
        "balance_gate_pass": balance_pass,
        "json_parse_gate_pass": parse_pass,
        "node_schema_gate_pass": schema_pass,
        "format_gate_pass": parse_pass and schema_pass,
        "json_parse_diagnostic_pass": parse_pass,
        "node_schema_diagnostic_pass": schema_pass,
        "revalidation_gate_pass": revalidation_completed,
        "validator_implementation_gate_pass": validator_implementation_verified,
        "truncation_gate_pass": truncation_pass,
        "duplicate_gate_pass": duplicate_pass,
        "telemetry_gate_pass": telemetry_pass,
        "provider_outage_gate_pass": provider_outage_pass,
        "actual_cost_gate_pass": actual_cost_pass,
        "projected_total_cost_usd": projection["projected_total_cost_usd"],
        "projected_cost_uncertainty_half_range_usd": projection["uncertainty_half_range_total_usd"],
        "cost_gate_pass": actual_cost_pass and projected_cost_pass,
        "checkpoint_gate_pass": not gate_reasons,
        "execution_defect_gate_pass": execution_defect_pass,
        "checkpoint_gate_failure_reasons": gate_reasons,
        "outcome_blind": True,
        "semantic_quality_inspected": False,
        "semantic_quality_accessed": False,
        "reserved_holdout_accessed": False,
    }
