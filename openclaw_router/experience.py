"""Persistent verified routing experience and feedback-loop utilities."""
from __future__ import annotations

import json
import math
import re
import threading
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

VALID_STATUSES = {"pending", "verified_positive", "verified_negative", "disputed", "expired"}
POSITIVE_REASONS = {"answer_correct", "correct_model", "helpful"}
NEGATIVE_REASONS = {"answer_wrong", "incomplete", "refusal", "wrong_model"}
ROUTING_NEGATIVE_REASONS = {"too_slow", "too_expensive", "wrong_model"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
    words = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", normalized))
    words.update(normalized[i:i + 2] for i in range(max(0, len(normalized) - 1)) if " " not in normalized[i:i + 2])
    return words


def _similarity(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def utility_score(*, quality: float, cost_reward: float, latency_reward: float, reliability: float) -> float:
    return max(0.0, min(1.0,
        0.45 * quality + 0.20 * cost_reward + 0.15 * latency_reward + 0.20 * reliability
    ))


def feedback_reward(*, automatic_quality: float, user_feedback: Optional[float], cost_reward: float,
                    latency_reward: float, reliability: float, fallback_count: int = 0,
                    constraint_violation: bool = False) -> float:
    # Missing user feedback is not treated as implicit approval: redistribute its weight to automatic evidence.
    if user_feedback is None:
        reward = 0.70 * automatic_quality + 0.15 * cost_reward + 0.10 * latency_reward + 0.05 * reliability
    else:
        reward = 0.50 * automatic_quality + 0.20 * user_feedback + 0.15 * cost_reward + 0.10 * latency_reward + 0.05 * reliability
    reward -= min(0.20, 0.08 * max(0, int(fallback_count)))
    if constraint_violation:
        reward -= 0.25
    return round(max(0.0, min(1.0, reward)), 4)


def automatic_verification(*, api_success: bool, quality_score: float, quality_threshold: float,
                           risk_level: str, objective_score: Optional[float],
                           constraint_violation: bool, estimated_regret: float,
                           regret_epsilon: float, manual_review_required: bool,
                           cost_reward: float, latency_reward: float, reliability: float,
                           fallback_count: int = 0) -> Dict[str, Any]:
    """Turn automatic evidence into a retrievable state without assuming missing feedback is approval."""
    reward = feedback_reward(
        automatic_quality=quality_score, user_feedback=None, cost_reward=cost_reward,
        latency_reward=latency_reward, reliability=reliability,
        fallback_count=fallback_count, constraint_violation=constraint_violation,
    )
    if not api_success:
        return {"verification_status": "verified_negative", "routing_correct": False, "reward": 0.0}
    if manual_review_required or (risk_level == "high" and objective_score is None):
        return {"verification_status": "disputed", "routing_correct": None, "reward": reward}
    objective_ok = not (risk_level == "high" and float(objective_score) < 0.999)
    correct = bool(
        quality_score >= quality_threshold
        and not constraint_violation
        and estimated_regret <= regret_epsilon
        and objective_ok
    )
    return {
        "verification_status": "verified_positive" if correct else "verified_negative",
        "routing_correct": correct,
        "reward": reward if correct else min(reward, 0.35),
    }


class RoutingExperienceStore:
    """Append-only snapshots keyed by request_id; latest snapshot is authoritative."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._events: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                rid = str(item.get("request_id") or "")
                if rid:
                    self._events[rid] = item
            except Exception:
                continue

    def _append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        event = dict(event)
        event["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._events[event["request_id"]] = event
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                handle.flush()
        return dict(event)

    def create(self, **payload: Any) -> Dict[str, Any]:
        request_id = str(payload.pop("request_id", "") or uuid.uuid4())
        event = {
            "request_id": request_id,
            "created_at": _now(),
            "verification_status": "pending",
            "routing_correct": None,
            "user_rating": None,
            "feedback_reason": None,
            **payload,
        }
        return self._append(event)

    def get(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._events.get(str(request_id))
            return dict(item) if item else None

    def expire(self, request_id: str, reason: str = "expired_by_operator") -> Dict[str, Any]:
        event = self.get(request_id)
        if not event:
            raise KeyError(request_id)
        event.update({"verification_status": "expired", "routing_correct": None, "expiry_reason": reason})
        return self._append(event)

    def apply_feedback(self, request_id: str, *, rating: str, reason: Optional[str] = None,
                       corrected_answer: Optional[str] = None, preferred_model: Optional[str] = None,
                       feedback_text: Optional[str] = None) -> Dict[str, Any]:
        event = self.get(request_id)
        if not event:
            raise KeyError(request_id)
        positive = rating == "up"
        reason = (reason or ("answer_correct" if positive else "answer_wrong")).strip()
        user_score = 1.0 if positive else 0.0
        quality = float(event.get("quality_score") or 0.0)
        api_success = bool(event.get("api_success"))
        constraints_ok = not bool(event.get("constraint_violation"))
        regret_ok = float(event.get("estimated_regret") or 0.0) <= float(event.get("regret_epsilon") or 0.10)
        objective = event.get("objective_score")
        high_risk_objective_ok = not (event.get("risk_level") == "high" and objective is not None and float(objective) < 0.999)
        routing_correct = bool(api_success and quality >= float(event.get("quality_threshold") or 0.60)
                               and constraints_ok and regret_ok and high_risk_objective_ok
                               and positive and reason not in ROUTING_NEGATIVE_REASONS)
        if positive and reason in POSITIVE_REASONS and routing_correct:
            status = "verified_positive"
        elif (not positive) or reason in NEGATIVE_REASONS or reason in ROUTING_NEGATIVE_REASONS:
            status = "verified_negative"
        else:
            status = "disputed"
        computed_reward = feedback_reward(
            automatic_quality=quality, user_feedback=user_score,
            cost_reward=float(event.get("cost_reward") or 0.0),
            latency_reward=float(event.get("latency_reward") or 0.0),
            reliability=float(event.get("reliability") or 0.0),
            fallback_count=int(event.get("fallback_count") or 0),
            constraint_violation=bool(event.get("constraint_violation")),
        )
        if status == "verified_negative" and reason in {"answer_wrong", "incomplete", "refusal", "wrong_model"}:
            computed_reward = 0.0
        elif status == "verified_negative" and reason in {"too_slow", "too_expensive"}:
            computed_reward = min(computed_reward, 0.35)
        event.update({
            "user_rating": rating,
            "user_feedback_score": user_score,
            "feedback_reason": reason,
            "feedback_text": feedback_text,
            "corrected_answer": corrected_answer,
            "preferred_model": preferred_model,
            "routing_correct": routing_correct,
            "verification_status": status,
            "reward": computed_reward,
            "feedback_at": _now(),
        })
        return self._append(event)

    def retrieve(self, query: str, *, user_id: Optional[str] = None, top_k: int = 10,
                 include_negative: bool = True, config_version: Optional[str] = None) -> List[Dict[str, Any]]:
        allowed = {"verified_positive"}
        if include_negative:
            allowed.add("verified_negative")
        with self._lock:
            values = list(self._events.values())
        results = []
        for event in values:
            if event.get("verification_status") not in allowed:
                continue
            if user_id and event.get("user_id") not in {None, "", user_id}:
                continue
            if config_version is not None and event.get("config_version") != config_version:
                continue
            score = _similarity(query, str(event.get("query") or ""))
            if score <= 0:
                continue
            results.append({**event, "similarity": round(score, 4)})
        results.sort(key=lambda item: (item["similarity"], item.get("updated_at", "")), reverse=True)
        return results[:max(1, int(top_k))]

    def model_statistics(self, query: str, candidates: Iterable[str], *, user_id: Optional[str] = None,
                         config_version: Optional[str] = None) -> Dict[str, Dict[str, float]]:
        candidate_set = set(candidates)
        accum: Dict[str, Dict[str, float]] = defaultdict(lambda: {"weight": 0.0, "reward": 0.0, "positive": 0.0, "negative": 0.0})
        for event in self.retrieve(query, user_id=user_id, top_k=50, include_negative=True, config_version=config_version):
            model = str(event.get("selected_model") or "")
            if model not in candidate_set:
                continue
            weight = max(0.05, float(event.get("similarity") or 0.0))
            status = event.get("verification_status")
            reward = float(event.get("reward") if event.get("reward") is not None else (1.0 if status == "verified_positive" else 0.0))
            accum[model]["weight"] += weight
            accum[model]["reward"] += weight * reward
            accum[model]["positive"] += weight if status == "verified_positive" else 0.0
            accum[model]["negative"] += weight if status == "verified_negative" else 0.0
        output = {}
        for model in candidate_set:
            item = accum[model]
            weight = item["weight"]
            output[model] = {
                "history_count": round(weight, 4),
                "historical_reward": round(item["reward"] / weight, 4) if weight else 0.5,
                "positive_weight": round(item["positive"], 4),
                "negative_weight": round(item["negative"], 4),
            }
        return output

    def metrics(self) -> Dict[str, Any]:
        with self._lock:
            audit_values = list(self._events.values())
        statuses = Counter(str(x.get("verification_status") or "unknown") for x in audit_values)
        values = [x for x in audit_values if x.get("verification_status") != "expired"]
        feedback_count = sum(x.get("user_rating") in {"up", "down"} for x in values)
        negative_feedback_count = sum(x.get("user_rating") == "down" for x in values)
        correct = sum(x.get("routing_correct") is True for x in values)
        verified = statuses["verified_positive"] + statuses["verified_negative"]
        regrets = [float(x.get("estimated_regret") or 0.0) for x in values if x.get("api_success")]
        return {
            "events": len(values), "audit_events": len(audit_values), "expired_events": statuses["expired"],
            "statuses": dict(statuses), "feedback_count": feedback_count,
            "feedback_coverage": round(feedback_count / max(1, len(values)), 4),
            "routing_accuracy": round(correct / max(1, verified), 4),
            "negative_feedback_rate": round(negative_feedback_count / max(1, feedback_count), 4),
            "negative_experience_rate": round(statuses["verified_negative"] / max(1, len(values)), 4),
            "average_estimated_regret": round(sum(regrets) / max(1, len(regrets)), 4),
        }
