"""Conservative Parser — SPEC v2.6 implementation (frozen sha e5aebd52).

Implements all five rules, dual-layer verdict, typed value system, and
contradiction tri-state detection per the frozen specification.
Zero model calls; operates on historical node output for offline regression.
"""
import hashlib, json, re, unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
# Typed Value System (SPEC §4)
# ============================================================
class FactKind(str, Enum):
    RATIO = "ratio"
    PRICE = "price"
    DATE = "date"
    INTERVAL_DAYS = "interval_days"
    AMOUNT = "amount"
    ENTITY = "entity"
    TEXT = "text"


@dataclass
class TypedValue:
    kind: str
    value: str
    unit: Optional[str] = None

    def typed_equal(self, other: 'TypedValue') -> bool:
        if self.kind != other.kind:
            return False
        if self.kind in ("ratio", "interval_days"):
            try:
                return Decimal(self.value) == Decimal(other.value)
            except InvalidOperation:
                return False
        if self.kind in ("price", "amount"):
            try:
                return (Decimal(self.value) == Decimal(other.value)
                        and self.unit == other.unit)
            except InvalidOperation:
                return False
        # entity, text: NFC-normalized exact match
        return (unicodedata.normalize("NFC", self.value)
                == unicodedata.normalize("NFC", other.value))


def _norm_ratio(s: str) -> Optional[str]:
    """Extract ALL ratio candidates (both 1:X and bare 0.X); multiple → ValueError."""
    # Collect from both patterns simultaneously to avoid missing candidates
    all_candidates = []
    for m in re.finditer(r'1\s*[:：]\s*(0\.\d+)', s):
        all_candidates.append(m.group(1))
    for m in re.finditer(r'(0\.\d+)', s):
        # Only add if not already captured by 1:X pattern (check overlap)
        span = (m.start(1), m.end(1))
        already = any(abs(m2.start(1) - span[0]) < 2 for m2 in
                      re.finditer(r'1\s*[:：]\s*(0\.\d+)', s))
        if not already:
            all_candidates.append(m.group(1))
    if not all_candidates:
        return None
    vals = {str(Decimal(m).normalize()) for m in all_candidates}
    if len(vals) > 1:
        raise ValueError("ambiguous_parse: multiple ratio candidates")
    return vals.pop()


def _norm_price_multi(s: str) -> Optional[Tuple[str, str]]:
    """Extract price/amount preserving negative sign; multiple → ValueError."""
    matches = re.findall(r'([-−–]?[\d,]+(?:\.\d+)?)\s*(元/股|万元|亿元|元)', s)
    if not matches:
        return None
    vals = {(str(Decimal(m[0].replace(',', '').replace('−', '-').replace('–', '-')).normalize()), m[1])
            for m in matches}
    if len(vals) > 1:
        raise ValueError("ambiguous_parse: multiple price candidates")
    return vals.pop()


def _norm_date_multi(s: str) -> Optional[str]:
    """Extract date with real calendar validation; multiple → ValueError."""
    from datetime import date as _date
    matches = re.findall(r'(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})', s)
    if not matches:
        return None
    dates = set()
    for y, mo, d in matches:
        try:
            dt = _date(int(y), int(mo), int(d))  # real calendar validation
            dates.add(dt.isoformat())
        except ValueError:
            continue  # invalid calendar date → not a valid candidate
    if not dates:
        return None
    if len(dates) > 1:
        raise ValueError("ambiguous_parse: multiple date candidates")
    return dates.pop()


def _norm_price(s: str) -> Optional[Tuple[str, str]]:
    m = re.search(r'([\d,]+(?:\.\d+)?)\s*(元/股|万元|亿元|元)', s)
    if m:
        val = str(Decimal(m.group(1).replace(',', '')).normalize())
        return val, m.group(2)
    return None


def _norm_date(s: str) -> Optional[str]:
    m = re.search(r'(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})', s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _norm_interval_days(s: str) -> Optional[str]:
    m = re.search(r'(\d+)\s*天', s)
    if m:
        return str(int(m.group(1)))
    return None


def typed_parse(fragment: str, kind: str) -> Optional[TypedValue]:
    """Parse a text fragment into a TypedValue of the given kind.
    Returns None if parsing fails or is ambiguous (Fix 4: all types detect multi-candidates)."""
    try:
        if kind == "ratio":
            v = _norm_ratio(fragment)
            return TypedValue("ratio", v) if v else None
        if kind == "price":
            r = _norm_price_multi(fragment)
            return TypedValue("price", r[0], r[1]) if r else None
        if kind == "date":
            v = _norm_date_multi(fragment)
            return TypedValue("date", v) if v else None
        if kind == "interval_days":
            v = _norm_interval_days(fragment)
            return TypedValue("interval_days", v) if v else None
        if kind == "amount":
            r = _norm_price_multi(fragment)
            return TypedValue("amount", r[0], r[1]) if r else None
    except ValueError:
        return None  # ambiguous → treated as parse failure (INSUFFICIENT)
    if kind == "entity":
        return TypedValue("entity", unicodedata.normalize("NFC", fragment.strip()))
    if kind == "text":
        return TypedValue("text", unicodedata.normalize("NFC", fragment))
    return None


# ============================================================
# Binding & DocumentSnapshot (SPEC §4)
# ============================================================
@dataclass
class Binding:
    fid: str
    source_doc: str
    source_doc_version: str
    fact_kind: str
    canonical_value: TypedValue
    span: Optional[List[int]]
    operand_role: Optional[str] = None
    document_role: Optional[str] = None
    time_stage: Optional[str] = None


@dataclass
class DocumentSnapshot:
    raw_bytes: bytes
    doc_text: str
    sha256: str

    @classmethod
    def from_file(cls, path):
        raw = Path(path).read_bytes()
        text = raw.decode("utf-8", errors="replace")  # preserve BOM
        return cls(raw, text, hashlib.sha256(raw).hexdigest())


# ============================================================
# Claim structures (SPEC §5 Rule 1)
# ============================================================
@dataclass
class RawClaim:
    source_layer: str
    item: Optional[str]
    conclusion: Optional[str]
    operand_values: Optional[List[str]]
    comparison_scope: Optional[str]
    model_declared_scope: Optional[str]
    doc_a: Optional[str] = None  # source doc for operand_a (from structured field)
    doc_b: Optional[str] = None  # source doc for operand_b


@dataclass
class ParsedClaim:
    claim_id: str
    item: Optional[str]
    comparison_scope: Optional[str]
    factual_verdict: str  # CREDITED | REFUSED | INSUFFICIENT_EVIDENCE | AMBIGUOUS
    task_relevance: Optional[str]  # RELEVANT | NOT_RELEVANT | UNKNOWN_SCOPE | CONTRACT_CONFLICT | None
    scoring_verdict: str
    conclusion: Optional[str]
    operands: List[Optional[Binding]]
    refusal_reasons: List[str]
    source_layer: str
    model_stated_conclusion: Optional[str]
    model_declared_scope: Optional[str]


# ============================================================
# Conservative Parser (SPEC §5 all rules)
# ============================================================
class ConservativeParser:
    ITEM_KIND_REGISTRY = {
        "exchange_ratio": "ratio",
        "signing_date": "date",
        "penalty_amount": "amount",
        "entity_identity": "entity",
        "interval_days": "interval_days",
    }

    def __init__(self, evidence_docs: List[str], doc_snapshots: Dict[str, DocumentSnapshot]):
        self.evidence_docs = evidence_docs
        self.doc_snapshots = doc_snapshots

    # ---- Rule 1: Extract claims ----
    def extract_claims(self, node_output: dict) -> List[RawClaim]:
        claims = []
        # Source 1: structured comparisons
        for cmp_ in node_output.get("comparisons", []):
            if not isinstance(cmp_, dict):
                continue
            claims.append(RawClaim(
                source_layer="structured_comparison",
                item=cmp_.get("item"),
                conclusion=cmp_.get("conclusion"),
                operand_values=[str(cmp_.get("operand_a", "")),
                                str(cmp_.get("operand_b", ""))],
                comparison_scope=cmp_.get("comparison_scope"),
                model_declared_scope=cmp_.get("declared_scope", cmp_.get("comparison_scope")),
                doc_a=cmp_.get("doc_a"),
                doc_b=cmp_.get("doc_b")))
        # Source 2: free text in report
        report_text = str(node_output.get("report", ""))
        for m in re.finditer(r'([\u4e00-\u9fa5\w]+?)\s*(一致|不一致)', report_text):
            item_text = m.group(1)
            conclusion = m.group(2)
            # extract operand values if present in parentheses
            paren = report_text[max(0, m.start()-200):m.end()+200]
            vals = re.findall(r'0\.\d+|[\d,]+(?:\.\d+)?(?:元|万元|亿元)', paren)
            claims.append(RawClaim(
                source_layer="free_text",
                item=self._classify_item(item_text),
                conclusion=conclusion,
                operand_values=vals[:2] if len(vals) >= 2 else None,
                comparison_scope=self._infer_scope(item_text, paren),
                model_declared_scope=self._infer_scope(item_text, paren)))
        # Source 3: new_facts
        for nf in node_output.get("new_facts", []):
            if not isinstance(nf, dict):
                continue
            content = str(nf.get("content", ""))
            if "一致" in content or "不一致" in content:
                claims.append(RawClaim(
                    source_layer="derived_fact",
                    item=self._classify_item(content),
                    conclusion="不一致" if "不一致" in content else "一致",
                    operand_values=None,
                    comparison_scope=None,
                    model_declared_scope=None))
        return self._dedup_claims(claims)

    def _classify_item(self, text: str) -> Optional[str]:
        if any(k in text for k in ("换股比例", "比例", "ratio")):
            return "exchange_ratio"
        if any(k in text for k in ("日期", "签署", "date")):
            return "signing_date"
        if any(k in text for k in ("金额", "罚款", "amount")):
            return "penalty_amount"
        return None

    def _infer_scope(self, item_text: str, context: str) -> Optional[str]:
        if "初始" in context or "最早" in context:
            return "initial_plan_vs_implementation"
        if "调整后" in context or "最终" in context:
            return "adjusted_plan_vs_implementation"
        return None

    def _dedup_claims(self, claims: List[RawClaim]) -> List[RawClaim]:
        """Six-condition dedup (SPEC Rule 1 F24).
        Conservative: if ANY condition cannot be determined, do NOT dedup."""
        result = []
        for c in claims:
            is_dup = False
            for existing in result:
                if self._can_dedup(existing, c):
                    is_dup = True
                    break
            if not is_dup:
                result.append(c)
        return result

    def _can_dedup(self, a: RawClaim, b: RawClaim) -> bool:
        """True only when ALL six conditions are determinable and identical."""
        # Condition 1: item
        if a.item is None or b.item is None or a.item != b.item:
            return False
        # Condition 6: conclusion
        if a.conclusion is None or b.conclusion is None or a.conclusion != b.conclusion:
            return False
        # Condition 3: comparison_scope (proxy for time_stage)
        if a.comparison_scope is None or b.comparison_scope is None:
            return False  # missing metadata → cannot confirm duplicate
        if a.comparison_scope != b.comparison_scope:
            return False
        # Condition 2: operand values (role-paired)
        if not a.operand_values or not b.operand_values:
            return False  # missing values → cannot confirm
        if sorted(a.operand_values) != sorted(b.operand_values):
            return False
        # Conditions 4-5: doc roles (proxy for document_role)
        if a.doc_a is None or b.doc_a is None:
            return False  # missing doc metadata → cannot confirm
        if not ((a.doc_a == b.doc_a and a.doc_b == b.doc_b) or
                (a.doc_a == b.doc_b and a.doc_b == b.doc_a)):
            return False
        return True  # all six conditions determinable and identical

    # ---- Rule 2: Operand binding + span verification ----
    def verify_operands(self, claim: RawClaim, ledger_facts: List[dict]) -> Tuple[str, List[Optional[Binding]], List[str]]:
        if not claim.operand_values or len(claim.operand_values) < 2:
            return "INSUFFICIENT_EVIDENCE", [None, None], ["operands_not_extracted"]

        required_kind = self.ITEM_KIND_REGISTRY.get(claim.item)
        if required_kind is None:
            return "INSUFFICIENT_EVIDENCE", [None, None], ["item_not_registered"]

        bindings = []
        reasons = []
        worst = "CREDITED"
        preferred_docs = [claim.doc_a, claim.doc_b]

        for idx, val_str in enumerate(claim.operand_values[:2]):
            binding, reason = self._bind_operand(
                val_str, required_kind, ledger_facts,
                preferred_doc=preferred_docs[idx] if idx < len(preferred_docs) else None)
            bindings.append(binding)
            if reason:
                reasons.append(reason)
                if reason.startswith(("span_value", "role_type", "type_mismatch",
                                       "wrong_source", "duplicate_role")):
                    worst = "REFUSED"
                elif worst != "REFUSED":
                    worst = "INSUFFICIENT_EVIDENCE"

        # Cross-document check
        if (bindings[0] and bindings[1]
                and bindings[0].source_doc == bindings[1].source_doc):
            reasons.append("same_source_doc")
            worst = "REFUSED"

        return worst, bindings, reasons

    def _bind_operand(self, val_str: str, kind: str, facts: List[dict],
                      preferred_doc: Optional[str] = None) -> Tuple[Optional[Binding], Optional[str]]:
        """Bind a single operand to a ledger fact."""
        # Parse the value
        tv = typed_parse(val_str, kind)
        if tv is None:
            # Check if value parses as a DIFFERENT kind → type mismatch → REFUSED
            for other_kind in ("ratio", "price", "amount", "date", "interval_days"):
                if other_kind != kind:
                    other_tv = typed_parse(val_str, other_kind)
                    if other_tv is not None:
                        return None, f"type_mismatch: value_is_{other_kind}_not_{kind}"
            return None, "operand_type_indeterminable"

        # Find matching facts, verifying original fact_kind (Fix 2A)
        candidates = []
        for f in facts:
            original_kind = f.get("fact_kind", "")
            if not original_kind:
                continue  # missing fact_kind → cannot verify type, skip
            if original_kind != kind:
                continue  # type mismatch → skip
            f_tv = typed_parse(str(f.get("content", "")), kind)
            if f_tv and f_tv.typed_equal(tv):
                candidates.append(f)

        if len(candidates) == 0:
            return None, "operand_not_in_ledger"

        # Enforce preferred_doc strictly (Fix 2B): if preferred_doc is specified,
        # only candidates from that doc are valid; others are wrong-source
        if preferred_doc:
            narrowed = [f for f in candidates
                        if f.get("source", f.get("source_doc", "")) == preferred_doc]
            if len(narrowed) == 0:
                return None, f"wrong_source_doc: expected={preferred_doc}"
            candidates = narrowed

        if len(candidates) > 1:
            return None, "ambiguous_binding"

        f = candidates[0]
        # Verify fid exists (Fix 6)
        fid = f.get("fid", "")
        if not fid:
            return None, "fid_missing"

        # Verify version exists and matches (Fix 6)
        source_doc_version = f.get("source_doc_version", "")
        source_doc = f.get("source", f.get("source_doc", ""))
        if not source_doc:
            return None, "source_doc_missing"

        # Build binding
        binding = Binding(
            fid=fid,
            source_doc=source_doc,
            source_doc_version=source_doc_version,
            fact_kind=kind,
            canonical_value=tv,
            span=f.get("span"),
            operand_role=f.get("operand_role"),
            document_role=f.get("document_role"),
            time_stage=f.get("time_stage"))

        # Verify source_doc in evidence_docs
        if binding.source_doc not in self.evidence_docs:
            return binding, "doc_not_in_evidence"

        # Verify document version (mandatory, Fix 6)
        snapshot = self.doc_snapshots.get(binding.source_doc)
        if snapshot is None:
            return binding, "document_unavailable"
        if not binding.source_doc_version:
            return binding, "version_missing"
        if binding.source_doc_version != snapshot.sha256:
            return binding, "doc_version_mismatch"

        # Verify span
        if binding.span is None:
            return binding, "span_missing"

        doc_len = len(snapshot.doc_text)
        if binding.span[0] < 0 or binding.span[1] > doc_len or binding.span[0] >= binding.span[1]:
            return binding, "span_out_of_bounds"

        # Typed span verification
        fragment = snapshot.doc_text[binding.span[0]:binding.span[1]]
        parsed = typed_parse(fragment, kind)
        if parsed is None:
            return binding, "span_ambiguous_parse"  # Fix 4: ambiguous → INSUFFICIENT not REFUSED
        if not parsed.typed_equal(tv):
            return binding, "span_value_mismatch"

        return binding, None

    # ---- Rule 3: Role validation ----
    def role_check(self, claim: RawClaim, binding_a: Optional[Binding],
                   binding_b: Optional[Binding]) -> Tuple[str, Optional[str]]:
        required_kind = self.ITEM_KIND_REGISTRY.get(claim.item)
        if required_kind is None:
            return "INSUFFICIENT", "item_not_registered"
        roles_seen = set()
        for b in (binding_a, binding_b):
            if b is None:
                return "INSUFFICIENT", "binding_missing"
            if b.fact_kind != required_kind:
                return "FAIL", f"fact_kind_mismatch: need={required_kind} got={b.fact_kind}"
            if not b.document_role:
                return "INSUFFICIENT", "document_role_missing"
            if not b.operand_role:
                return "INSUFFICIENT", "operand_role_missing"
            # Fix 3: check role uniqueness
            if b.operand_role in roles_seen:
                return "FAIL", f"duplicate_operand_role: {b.operand_role} appears twice"
            roles_seen.add(b.operand_role)
        return "PASS", None

    # ---- Rule 4: Contradiction detection ----
    def check_contradictions(self, claims: List[ParsedClaim]) -> List[dict]:
        checks = []
        same_item = {}
        for c in claims:
            if c.item:
                same_item.setdefault(c.item, []).append(c)

        for item, group in same_item.items():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    result, failed_cond = self._contradiction(a, b)
                    if result == "TRUE":
                        prop = {a.claim_id: "refused", b.claim_id: "refused"}
                        a.factual_verdict = "REFUSED"
                        b.factual_verdict = "REFUSED"
                        a.refusal_reasons.append("true_contradiction")
                        b.refusal_reasons.append("true_contradiction")
                    elif result == "UNKNOWN":
                        prop = {a.claim_id: "held_pending_resolution",
                                b.claim_id: "held_pending_resolution"}
                        if a.factual_verdict == "CREDITED":
                            a.factual_verdict = "INSUFFICIENT_EVIDENCE"
                            a.refusal_reasons.append("unresolved_contradiction_check")
                        if b.factual_verdict == "CREDITED":
                            b.factual_verdict = "INSUFFICIENT_EVIDENCE"
                            b.refusal_reasons.append("unresolved_contradiction_check")
                    else:
                        prop = {a.claim_id: "unaffected", b.claim_id: "unaffected"}
                    checks.append(dict(claim_a=a.claim_id, claim_b=b.claim_id,
                                       result=result, failed_condition=failed_cond,
                                       propagation=prop))
        return checks

    def _contradiction(self, a: ParsedClaim, b: ParsedClaim) -> Tuple[str, Optional[str]]:
        results = []
        # C1: item
        c1 = "MATCH" if a.item == b.item else ("UNKNOWN" if not a.item or not b.item else "MISMATCH")
        results.append(("C1", c1))
        # C2: operands by role
        c2 = self._c2_check(a, b)
        results.append(("C2", c2))
        # C3: time_stage
        c3 = self._c3_check(a, b)
        results.append(("C3", c3))
        # C4: document_role pattern
        c4 = self._c4_check(a, b)
        results.append(("C4", c4))
        # C5: comparison_scope
        c5 = "MATCH" if a.comparison_scope == b.comparison_scope else (
            "UNKNOWN" if not a.comparison_scope or not b.comparison_scope else "MISMATCH")
        results.append(("C5", c5))
        # R1: conclusion opposite
        if a.conclusion and b.conclusion:
            r1 = "OPPOSITE" if a.conclusion != b.conclusion else "SAME"
        else:
            r1 = "UNKNOWN"

        # Tri-state priority (SPEC F26)
        for name, val in results:
            if val == "MISMATCH":
                return "FALSE", f"{name}_mismatch"
        for name, val in results:
            if val == "UNKNOWN":
                return "UNKNOWN", f"{name}_unknown"
        if r1 == "UNKNOWN":
            return "UNKNOWN", "R1_unknown"
        if r1 == "OPPOSITE":
            return "TRUE", None
        return "FALSE", None

    def _c2_check(self, a: ParsedClaim, b: ParsedClaim) -> str:
        """Compare operands by operand_role correspondence, not array index (Fix 3)."""
        if not a.operands or not b.operands:
            return "UNKNOWN"
        # Build role→value maps
        a_map = {}
        for op in a.operands:
            if op is not None and op.operand_role:
                a_map[op.operand_role] = op.canonical_value
        b_map = {}
        for op in b.operands:
            if op is not None and op.operand_role:
                b_map[op.operand_role] = op.canonical_value
        if not a_map or not b_map:
            return "UNKNOWN"  # can't compare without roles
        # Compare values for each shared role
        for role in set(a_map) | set(b_map):
            if role not in a_map or role not in b_map:
                return "UNKNOWN"  # role missing on one side
            if not a_map[role].typed_equal(b_map[role]):
                return "MISMATCH"
        return "MATCH"

    def _c3_check(self, a: ParsedClaim, b: ParsedClaim) -> str:
        """Compare time_stages by operand_role correspondence."""
        if not a.operands or not b.operands:
            return "UNKNOWN"
        a_map = {}
        for op in a.operands:
            if op is not None and op.operand_role:
                a_map[op.operand_role] = op.time_stage
        b_map = {}
        for op in b.operands:
            if op is not None and op.operand_role:
                b_map[op.operand_role] = op.time_stage
        if not a_map or not b_map:
            return "UNKNOWN"
        for role in set(a_map) | set(b_map):
            if role not in a_map or role not in b_map:
                return "UNKNOWN"
            if a_map[role] is None or b_map[role] is None:
                return "UNKNOWN"
            if a_map[role] != b_map[role]:
                return "MISMATCH"
        return "MATCH"

    def _c4_check(self, a: ParsedClaim, b: ParsedClaim) -> str:
        """Compare document_roles by operand_role correspondence."""
        if not a.operands or not b.operands:
            return "UNKNOWN"
        a_map = {}
        for op in a.operands:
            if op is not None and op.operand_role:
                a_map[op.operand_role] = op.document_role
        b_map = {}
        for op in b.operands:
            if op is not None and op.operand_role:
                b_map[op.operand_role] = op.document_role
        if not a_map or not b_map:
            return "UNKNOWN"
        for role in set(a_map) | set(b_map):
            if role not in a_map or role not in b_map:
                return "UNKNOWN"
            if a_map[role] is None or b_map[role] is None:
                return "UNKNOWN"
            if a_map[role] != b_map[role]:
                return "MISMATCH"
        return "MATCH"

    # ---- Rule 5: Contract scope + task relevance ----
    def resolve_scope(self, task_contract: Optional[dict], silver_ref: Optional[dict]) -> dict:
        tc_scope = task_contract.get("comparison_scope") if task_contract else None
        sr_scope = silver_ref.get("comparison_scope") if silver_ref else None

        if tc_scope and sr_scope:
            if tc_scope == sr_scope:
                return dict(scope=tc_scope, specified=True, conflict=False, source="both")
            return dict(scope=None, specified=False, conflict=True, source="conflicting")
        if tc_scope:
            return dict(scope=tc_scope, specified=True, conflict=False, source="task_contract")
        if sr_scope:
            return dict(scope=sr_scope, specified=True, conflict=False, source="silver_reference")
        return dict(scope=None, specified=False, conflict=False, source="none")

    def determine_task_relevance(self, claim_scope: Optional[str], resolved: dict) -> str:
        if resolved["conflict"]:
            return "CONTRACT_CONFLICT"
        if resolved["specified"]:
            if claim_scope is None:
                return "UNKNOWN_SCOPE"
            if claim_scope == resolved["scope"]:
                return "RELEVANT"
            return "NOT_RELEVANT"
        return "UNKNOWN_SCOPE"

    def verify_model_operands(self, claim: RawClaim, bindings: List[Optional[Binding]]) -> Tuple[str, Optional[str]]:
        """Check if the model's declared scope matches the actual binding time_stages."""
        if claim.model_declared_scope is None:
            return "SKIP", None
        # Map declared scope to expected time_stage for the plan-side operand
        scope_stage_map = {
            "initial_plan_vs_implementation": "initial_pricing",
            "adjusted_plan_vs_implementation": "post_adjustment",
        }
        expected_stage = scope_stage_map.get(claim.model_declared_scope)
        if expected_stage is None:
            return "SKIP", None  # unknown scope, can't check

        # Find the plan-side binding (first operand typically)
        for b in bindings:
            if b is None:
                continue
            if b.operand_role in ("initial_plan", "adjusted_plan"):
                actual_stage = b.time_stage
                if actual_stage and actual_stage != expected_stage:
                    return "FAIL", (f"internal_inconsistency: declared="
                                    f"{claim.model_declared_scope} "
                                    f"but operand_stage={actual_stage}")
        return "PASS", None

    # ---- Main parse function ----
    def parse(self, node_output: dict, ledger_facts: List[dict],
              task_contract: Optional[dict] = None,
              silver_ref: Optional[dict] = None) -> dict:
        raw_claims = self.extract_claims(node_output)
        resolved_scope = self.resolve_scope(task_contract, silver_ref)

        parsed_claims = []
        for i, rc in enumerate(raw_claims):
            factual, bindings, reasons = self.verify_operands(rc, ledger_facts)
            role_result, role_reason = self.role_check(rc, bindings[0] if bindings else None,
                                                        bindings[1] if len(bindings) > 1 else None)
            if role_result == "FAIL":
                factual = "REFUSED"
                reasons.append(role_reason)
            elif role_result == "INSUFFICIENT" and factual == "CREDITED":
                factual = "INSUFFICIENT_EVIDENCE"
                reasons.append(role_reason)

            # Internal consistency check (Rule 5 Process 2)
            model_check, model_reason = self.verify_model_operands(rc, bindings)
            if model_check == "FAIL":
                factual = "REFUSED"
                reasons.append(model_reason or "internal_inconsistency")

            # Task relevance
            relevance = self.determine_task_relevance(rc.comparison_scope, resolved_scope)

            # Scoring verdict
            if factual == "CREDITED" and relevance == "RELEVANT":
                scoring = "SCORED"
            elif factual == "CREDITED" and relevance == "NOT_RELEVANT":
                scoring = "NOT_SCORED_VERIFIED"
            elif factual == "CREDITED" and relevance == "UNKNOWN_SCOPE":
                scoring = "NOT_SCORED_SCOPE_UNKNOWN"
            elif factual == "CREDITED" and relevance == "CONTRACT_CONFLICT":
                scoring = "NOT_SCORED_CONTRACT_CONFLICT"
            else:
                scoring = factual

            parsed_claims.append(ParsedClaim(
                claim_id=f"C{i+1}",
                item=rc.item,
                comparison_scope=rc.comparison_scope,
                factual_verdict=factual,
                task_relevance=relevance,
                scoring_verdict=scoring,
                conclusion=rc.conclusion,
                operands=bindings,
                refusal_reasons=reasons,
                source_layer=rc.source_layer,
                model_stated_conclusion=rc.conclusion,
                model_declared_scope=rc.model_declared_scope))

        # Contradiction checks (may modify factual_verdict)
        contradiction_checks = self.check_contradictions(parsed_claims)

        # Recompute scoring after contradictions
        for c in parsed_claims:
            if c.factual_verdict == "CREDITED" and c.task_relevance == "RELEVANT":
                c.scoring_verdict = "SCORED"
            elif c.factual_verdict == "CREDITED" and c.task_relevance == "NOT_RELEVANT":
                c.scoring_verdict = "NOT_SCORED_VERIFIED"
            elif c.factual_verdict != "CREDITED":
                c.scoring_verdict = c.factual_verdict

        return dict(
            parser_version="2.6",
            contract_scope=resolved_scope,
            claims=[dict(
                claim_id=c.claim_id,
                item=c.item,
                comparison_scope=c.comparison_scope,
                factual_verdict=c.factual_verdict,
                task_relevance=c.task_relevance,
                scoring_verdict=c.scoring_verdict,
                conclusion=c.conclusion,
                operands=[self._binding_to_dict(b) for b in c.operands if b],
                refusal_reasons=c.refusal_reasons,
                source_layer=c.source_layer,
                model_stated_conclusion=c.model_stated_conclusion,
                model_declared_scope=c.model_declared_scope,
            ) for c in parsed_claims],
            contradiction_checks=contradiction_checks)

    def _binding_to_dict(self, b: Binding) -> dict:
        return dict(
            fid=b.fid, source_doc=b.source_doc,
            source_doc_version=b.source_doc_version,  # Fix 6: full SHA256, no truncation
            fact_kind=b.fact_kind,
            canonical_value=dict(kind=b.canonical_value.kind,
                                 value=b.canonical_value.value,
                                 unit=b.canonical_value.unit),
            span=b.span, operand_role=b.operand_role,
            document_role=b.document_role, time_stage=b.time_stage)
