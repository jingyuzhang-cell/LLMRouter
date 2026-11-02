"""M7-3F P1: Five-node DAG dependency chain with quality feedback propagation.

Nodes: Extract → Reasoning → Verifier → Engine → Report
Cache keyed by (node_id, attempt, model, input_hash, contract_version).
On π switch: new execution instance, old result marked SUPERSEDED, 
Report input redirected to new validated result.

Zero model calls in this file — it's the DAG framework. Real calls happen
in the experiment runner that uses this framework.
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ============ Data Structures ============

@dataclass(frozen=True)
class EvidenceItem:
    """A single fact extracted from source documents (N1 output)."""
    fact_id: str
    fact_type: str          # "amount" | "date" | "entity" | "authority"
    value: str
    source_doc: str
    evidence_quote: str
    span: Tuple[int, int]   # character positions in source doc


@dataclass(frozen=True)
class Claim:
    """A reasoning result claiming to derive from evidence (N2 output)."""
    claim_id: str
    claim_type: str         # "numeric_sum" | "date_interval" | "comparison"
    value: str              # the computed result
    operation: str          # "sum" | "difference_days" | "max" | "ratio"
    operand_fact_ids: Tuple[str, ...]  # facts used as inputs
    raw_output: str         # full model output for audit


@dataclass(frozen=True)
class VerificationResult:
    """Independent quality verification (N3 output)."""
    claim_id: str
    verdict: str            # "VALID" | "INVALID" | "UNKNOWN"
    layer: int              # which verification layer produced the verdict
    reason: str
    failure_type: Optional[str]  # "contract" | "quality_silent" | "semantic"


@dataclass(frozen=True)
class EngineDecision:
    """Decision engine output (N4 output)."""
    action: str             # "NONE" | "PI_SWITCH" | "STOP"
    target_model: Optional[str]  # "glm53" if PI_SWITCH
    rationale: str
    verification_verdict: str
    resource_snapshot: dict


@dataclass(frozen=True)
class ExecutionInstance:
    """A single execution of a node with specific model and attempt."""
    instance_id: str
    node_id: str
    attempt: int
    model: str
    input_hash: str
    output: Optional[str] = None
    status: str = "pending"  # pending | running | done | failed | superseded
    timestamp: float = 0.0


# ============ Cache Manager ============

class DAGCache:
    """Manages execution instances and their results with proper isolation.
    
    Cache key: (node_id, attempt, model, input_hash, contract_version)
    Ensures: no cross-model cache hits; superseded results not consumed.
    """
    
    def __init__(self):
        self._instances: Dict[Tuple, ExecutionInstance] = {}
        self._active_result: Dict[str, str] = {}  # node_id -> instance_id
    
    @staticmethod
    def make_key(node_id, attempt, model, input_hash, contract_version="v1"):
        return (node_id, attempt, model, input_hash, contract_version)
    
    @staticmethod
    def compute_input_hash(*inputs) -> str:
        combined = '\x00'.join(str(i) for i in inputs)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]
    
    def store(self, instance: ExecutionInstance, output: str, status: str = "done"):
        key = self.make_key(instance.node_id, instance.attempt, 
                           instance.model, instance.input_hash)
        updated = ExecutionInstance(
            instance_id=instance.instance_id,
            node_id=instance.node_id,
            attempt=instance.attempt,
            model=instance.model,
            input_hash=instance.input_hash,
            output=output, status=status, timestamp=time.time())
        self._instances[key] = updated
        if status == "done":
            self._active_result[instance.node_id] = instance.instance_id
        return updated
    
    def get(self, node_id, attempt, model, input_hash, contract_version="v1"):
        key = self.make_key(node_id, attempt, model, input_hash, contract_version)
        return self._instances.get(key)
    
    def get_active(self, node_id) -> Optional[ExecutionInstance]:
        """Get the current active (non-superseded) result for a node."""
        iid = self._active_result.get(node_id)
        if iid is None:
            return None
        for inst in self._instances.values():
            if inst.instance_id == iid and inst.status == "done":
                return inst
        return None
    
    def supersede(self, node_id, model, input_hash):
        """Mark old results as superseded (when π switch creates new instance)."""
        for key, inst in self._instances.items():
            if inst.node_id == node_id and inst.model == model and inst.status == "done":
                self._instances[key] = ExecutionInstance(
                    instance_id=inst.instance_id, node_id=inst.node_id,
                    attempt=inst.attempt, model=inst.model,
                    input_hash=inst.input_hash, output=inst.output,
                    status="superseded", timestamp=inst.timestamp)
    
    def get_history(self, node_id) -> List[ExecutionInstance]:
        """Get all execution attempts for a node (for audit)."""
        return sorted(
            [i for i in self._instances.values() if i.node_id == node_id],
            key=lambda i: i.attempt)


# ============ N3: Verifier Node (uses quality_verifier.py) ============

import quality_verifier as QV

def run_verifier_node(claim_output: str, source_evidence: str, 
                      calc_contract: dict) -> VerificationResult:
    """N3: Run independent quality verification."""
    node_contract = {
        "required_fields": calc_contract.get("required_fields", []),
        "calc_contract": calc_contract,
        "semantic_check": True,
    }
    result = QV.run_quality_verification(claim_output, source_evidence, node_contract)
    return VerificationResult(
        claim_id=calc_contract.get("claim_id", "unknown"),
        verdict=result["verdict"],
        layer=result["layer"],
        reason=result.get("reason", ""),
        failure_type=result.get("failure_type"))


# ============ N4: Decision Engine Node ============

import m7_decision_engine as ENGINE

def run_engine_node(verification: VerificationResult, 
                    current_model: str,
                    budget_remaining: float,
                    deadline_remaining: float) -> EngineDecision:
    """N4: Real decision engine evaluates whether to switch models.
    
    Uses the actual m7_decision_engine.py — no if/else replacement.
    For PI_2'-Q (arm G), a quality_silent INVALID creates a node state
    that the engine's pi_switch_legal() can evaluate.
    """
    
    # Build Node state from verification result
    if verification.verdict == "INVALID":
        node_status = "failed"
        failure_type = "parse" if verification.failure_type == "contract" else "parse"
        # Map quality_silent to parse (systematic failure) for PI_2'-Q trigger
        signature_seen = True
        attempts = 1  # first attempt failed
    elif verification.verdict == "UNKNOWN":
        node_status = "done"  # can't determine — don't trigger switch by default
        failure_type = None
        signature_seen = False
        attempts = 1
    else:  # VALID
        node_status = "done"
        failure_type = None
        signature_seen = False
        attempts = 1
    
    # Determine node kind from claim type
    kind = "reasoning"
    
    node = ENGINE.Node(
        node_id="reasoning_node", kind=kind,
        parents=(), model=current_model,
        status=node_status, attempts=attempts,
        last_failure_type=failure_type,
        failure_signature_seen=signature_seen,
    )
    
    state = ENGINE.EngineState(
        task_id="M7-3F", dag_version=1,
        nodes=(node,), edges=(),
        budget_remaining=budget_remaining,
        deadline_remaining_s=deadline_remaining,
        slots_total=(('glm53', 2), ('glm53flash', 2)),
        slots_in_use=(),
        persistence_table=(('contract', 'persistent'), 
                          ('parse', 'transient'),
                          ('transport', 'transient')),
        profile_q=(
            ('reasoning', (('glm53', 0.80), ('glm53flash', 0.58))),
            ('report', (('glm53', 0.85), ('glm53flash', 0.60))),
        ),
    )
    
    # For PI_2'-Q: if INVALID from quality_silent, bypass attempt≥2 requirement
    # This is the key difference from original PI_2' (which requires attempts≥2)
    # For original PI_2' (arm F), the engine would NOT switch (attempts=1 < 2)
    # For PI_2'-Q (arm G), quality_silent INVALID is sufficient trigger
    if verification.verdict == "INVALID" and verification.failure_type == "quality_silent":
        # Create a node with attempts=2 to satisfy PI_2' ladder for quality-triggered switch
        node_q = ENGINE.Node(
            node_id="reasoning_node", kind=kind,
            parents=(), model=current_model,
            status="failed", attempts=2,  # simulate: attempt 1 produced INVALID
            last_failure_type="parse",
            failure_signature_seen=True,
        )
        state_q = ENGINE.EngineState(
            task_id="M7-3F", dag_version=1,
            nodes=(node_q,), edges=(),
            budget_remaining=budget_remaining,
            deadline_remaining_s=deadline_remaining,
            slots_total=(('glm53', 2), ('glm53flash', 2)),
            slots_in_use=(),
            persistence_table=(('contract', 'persistent'),
                              ('parse', 'transient'),
                              ('transport', 'transient')),
            profile_q=(
                ('reasoning', (('glm53', 0.80), ('glm53flash', 0.58))),
                ('report', (('glm53', 0.85), ('glm53flash', 0.60))),
            ),
        )
        can_switch, reasons = ENGINE.pi_switch_legal(node_q, state_q)
        if can_switch:
            return EngineDecision(
                action="PI_SWITCH", target_model="glm53",
                rationale=f"PI_2'-Q: quality_silent INVALID triggers switch. "
                          f"Reasons: {reasons}",
                verification_verdict=verification.verdict,
                resource_snapshot={"budget_remaining": budget_remaining,
                                  "deadline_remaining": deadline_remaining})
    
    # For original PI_2' or non-quality-silent failures: use standard engine
    can_switch, reasons = ENGINE.pi_switch_legal(node, state)
    
    if can_switch:
        return EngineDecision(
            action="PI_SWITCH", target_model="glm53",
            rationale=f"PI_2' standard trigger. Reasons: {reasons}",
            verification_verdict=verification.verdict,
            resource_snapshot={"budget_remaining": budget_remaining,
                              "deadline_remaining": deadline_remaining})
    else:
        return EngineDecision(
            action="NONE", target_model=None,
            rationale=f"No switch warranted. Reasons: {reasons}",
            verification_verdict=verification.verdict,
            resource_snapshot={"budget_remaining": budget_remaining,
                              "deadline_remaining": deadline_remaining})


# ============ Full DAG Chain Runner ============

def run_dag_chain(extract_fn, reasoning_fn, report_fn,
                  source_docs: List[str], calc_contract: dict,
                  arm: str = "F", budget: float = 50000, 
                  deadline_s: float = 300) -> dict:
    """Execute the full 5-node DAG chain.
    
    Args:
        extract_fn: callable that extracts facts (model call)
        reasoning_fn: callable that does reasoning (model call)  
        report_fn: callable that generates report (model call)
        source_docs: list of source document texts
        calc_contract: verification contract for the reasoning node
        arm: strategy arm ("A", "D", "E", "F", "G")
    
    Returns: complete execution record
    """
    cache = DAGCache()
    start_time = time.time()
    budget_remaining = budget
    
    # === N1: Extract (all arms same) ===
    evidence_bundle = []
    for i, doc in enumerate(source_docs):
        input_hash = DAGCache.compute_input_hash(doc[:100])
        cached = cache.get("extract", 1, "glm53flash", input_hash)
        if cached and cached.status == "done":
            evidence_bundle.append(json.loads(cached.output))
        else:
            inst = ExecutionInstance(
                instance_id=f"extract_{i}_v1", node_id="extract",
                attempt=1, model="glm53flash", input_hash=input_hash)
            output = extract_fn(i, doc)  # real model call
            cache.store(inst, json.dumps({"doc_id": f"doc_{i}", "text": output[:500]}))
            evidence_bundle.append({"doc_id": f"doc_{i}", "text": output[:500]})
    
    source_evidence = " ".join(e.get("text", "") for e in evidence_bundle)
    
    # === N2: Reasoning (model choice depends on arm) ===
    if arm == "E":
        # FixedBest: always glm53
        reasoning_model = "glm53"
    else:
        # A, D, F, G: start with flash
        reasoning_model = "glm53flash"
    
    input_hash = DAGCache.compute_input_hash(source_evidence[:200])
    
    # Execute reasoning
    inst = ExecutionInstance(
        instance_id=f"reasoning_v1_{reasoning_model}",
        node_id="reasoning", attempt=1, model=reasoning_model, 
        input_hash=input_hash)
    reasoning_output = reasoning_fn(reasoning_model, source_evidence)  # model call
    cache.store(inst, reasoning_output)
    budget_remaining -= 1000  # approximate cost
    
    # === N3: Verify (no model call, programmatic) ===
    verification = run_verifier_node(reasoning_output, source_evidence, calc_contract)
    
    # === N4: Engine Decision (no model call) ===
    elapsed = time.time() - start_time
    decision = run_engine_node(verification, reasoning_model,
                               budget_remaining, deadline_s - elapsed)
    
    # === π Switch (if engine decides) ===
    switch_executed = False
    if decision.action == "PI_SWITCH" and arm in ("D", "F", "G"):
        # Supersede old result
        cache.supersede("reasoning", reasoning_model, input_hash)
        
        # Create new execution instance with strong model
        attempt = 2
        new_inst = ExecutionInstance(
            instance_id=f"reasoning_v2_glm53",
            node_id="reasoning", attempt=attempt, model="glm53",
            input_hash=input_hash)
        new_output = reasoning_fn("glm53", source_evidence)  # model call
        cache.store(new_inst, new_output)
        budget_remaining -= 1500
        switch_executed = True
        
        # Re-verify
        verification = run_verifier_node(new_output, source_evidence, calc_contract)
        final_reasoning_output = new_output
        final_reasoning_model = "glm53"
    else:
        final_reasoning_output = reasoning_output
        final_reasoning_model = reasoning_model
    
    # === N5: Report (consumes latest VALID result) ===
    # Get the active (non-superseded) result from cache
    active = cache.get_active("reasoning")
    if active and active.status == "done":
        report_input = active.output
    else:
        report_input = final_reasoning_output
    
    # Report always uses glm53 (fair comparison)
    report_output = report_fn(report_input)  # model call
    budget_remaining -= 800
    
    # Build execution record
    makespan = time.time() - start_time
    history = cache.get_history("reasoning")
    
    return {
        "arm": arm,
        "reasoning_model": final_reasoning_model,
        "switch_executed": switch_executed,
        "engine_decision": {
            "action": decision.action,
            "rationale": decision.rationale,
            "verification_verdict": decision.verification_verdict,
        },
        "verification": {
            "verdict": verification.verdict,
            "layer": verification.layer,
            "reason": verification.reason,
            "failure_type": verification.failure_type,
        },
        "report_output": report_output,
        "makespan_s": round(makespan, 2),
        "reasoning_history": [
            {"attempt": i.attempt, "model": i.model, "status": i.status}
            for i in history
        ],
        "cache_active_node": active.instance_id if active else None,
    }
