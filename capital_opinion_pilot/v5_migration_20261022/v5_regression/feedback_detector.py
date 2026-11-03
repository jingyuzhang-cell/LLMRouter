"""feedback_detector.py — minimal runtime feedback detection prototype (zero-pay).

Detects OBSERVABLE execution feedback from node outputs + injected evidence,
with NO access to reference answers (T1/Gold/Silver). Two severity classes:
  CONFIRMED-INVALID : contract violation (parse/shape fail, truncation) or
                      upstream input change (cache invalid by dependency rule)
  SEMANTIC-SUSPICIOUS: format-valid but evidence-flagged —
                      (a) extraction fact whose quote is not a verbatim span of
                          the node's OWN injected pack (deterministic check),
                      (b) cross-source verdict UNRESOLVED from a verify node.

(a) is computable at runtime with ZERO model calls (string containment on the
node's own input evidence) — this makes the extraction-cache trigger free and
deterministic; model-call verification is only needed for (b)-class conflicts.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pilot_common import PILOT_DIR, norm
from json_compat import parse_layers, node_contract

P = PILOT_DIR


def pack_norm(pack_text):
    return norm(pack_text)


def check_extraction_grounded(node_output_text, pack_text, min_quote_chars=6):
    """Deterministic per-fact grounding check for t1/t2 outputs.
    Returns (n_grounded, n_total, flagged_facts)."""
    pl = parse_layers(node_output_text)
    if not pl['compat_ok']:
        return None  # contract-level failure, not a grounding question
    facts = (pl['value'] or {}).get('facts', [])
    if not isinstance(facts, list):
        return None
    hay = pack_norm(pack_text)
    g, flagged = 0, []
    for i, f in enumerate(facts):
        if not isinstance(f, dict):
            flagged.append({'idx': i, 'why': 'malformed_fact'})
            continue
        q = norm(str(f.get('quote', '') or ''))
        if q and len(q) >= min_quote_chars and q in hay:
            g += 1
        else:
            flagged.append({'idx': i, 'why': 'quote_not_in_own_pack',
                            'quote': str(f.get('quote', ''))[:40],
                            'fact_key': f.get('fact_key', '')})
    return g, len(facts), flagged


def check_verdict_conflicts(node_output_text):
    """UNRESOLVED/UNSUPPORTED verdicts from a cross-source verify node."""
    pl = parse_layers(node_output_text)
    if not pl['compat_ok']:
        return None
    vs = (pl['value'] or {}).get('verdicts', [])
    if not isinstance(vs, list):
        return None
    out = []
    for v in vs:
        if isinstance(v, dict) and str(v.get('verdict', '')).upper() in ('UNRESOLVED', 'UNSUPPORTED'):
            out.append({'fact': str(v.get('fact', ''))[:60],
                        'verdict': v.get('verdict'),
                        'doc_id': v.get('doc_id')})
    return out


def detect(run_outputs, packs, node_kind):
    """run_outputs: {node: raw_text}; packs: {t1: pack_text, t2: pack_text};
    node_kind: {node: 'extract'|'verify'|...}. Returns feedback list."""
    fb = []
    for node, text in run_outputs.items():
        k = node_kind.get(node)
        pl = parse_layers(text)
        if not pl['compat_ok']:
            fb.append({'node': node, 'class': 'CONFIRMED-INVALID',
                       'kind': 'contract_violation', 'detail': pl['error'][:120]})
            continue
        if k == 'extract':
            r = check_extraction_grounded(text, packs[node])
            if r and r[0] < r[1]:
                fb.append({'node': node, 'class': 'SEMANTIC-SUSPICIOUS',
                           'kind': 'ungrounded_extraction_facts',
                           'grounded': r[0], 'total': r[1],
                           'flagged': r[2][:5], 'rate': round(r[0] / r[1], 3)})
        elif k == 'verify':
            c = check_verdict_conflicts(text)
            if c:
                fb.append({'node': node, 'class': 'SEMANTIC-SUSPICIOUS',
                           'kind': 'cross_source_conflicts', 'n': len(c),
                           'items': c[:5]})
    return fb


def apply_verify_outcome(verdicts, target, feedback, lineage, current_fps):
    """Propagate a verify.v1 annotation outcome into execution state.

    - all grounded  -> NO state change: downstream caches stay valid (the
      annotation must not gratuitously invalidate anything);
    - any flagged   -> the target cache is SEMANTICALLY invalidated: target
      enters feedback['confirmed'], so a subsequent v5 decision re-executes
      its closure; lineage marks the target cache invalid (health annotated).
    Returns a record of what changed (for the audit log).
    """
    valid = [v for v in (verdicts or []) if isinstance(v, dict) and isinstance(v.get('grounded'), bool)]
    flagged = [v for v in valid if v['grounded'] is False]
    rec = {'target': target, 'flagged': len(flagged), 'of': len(verdicts or []),
           'state_changed': bool(flagged),
           'status': 'CONFIRMED_EVIDENCE_FLAG' if flagged else ('CLEAN' if valid else 'UNKNOWN')}
    if flagged:
        # SEMANTIC invalidation: output remains contract-usable, so the node
        # enters 'confirmed' (re-exec candidate) while KEEP stays score-legal;
        # contract-level invalidation (missing output) is a separate channel
        # carried by state['missing_outputs'].
        if target not in feedback['confirmed']:
            feedback['confirmed'] = sorted(set(feedback['confirmed']) | {target})
        feedback['suspicious'].pop(target, None)
        rec['effect'] = (f'{target} -> semantic-invalid (re-exec candidate; '
                         'KEEP stays score-legal since output is contract-usable)')
    else:
        rec['effect'] = 'no change; downstream caches remain valid'
    return rec


def recovery_feedback(records):
    """Normalize only observed detector records, with no quality/Gold access."""
    result = {'confirmed': [], 'hard_invalid': [], 'suspicious': {},
              'cache_anomalies': {}, 'verify_targets': []}
    for rec in records:
        node = rec['node']
        if rec['class'] == 'CONFIRMED-INVALID':
            result['confirmed'].append(node)
            result['hard_invalid'].append(node)
        elif rec.get('kind') == 'cross_source_conflicts':
            # The implicated target must be explicit, never guessed from Gold.
            if rec.get('target'):
                result['verify_targets'].append(rec['target'])
        elif rec['class'] == 'SEMANTIC-SUSPICIOUS':
            result['suspicious'][node] = (rec.get('grounded'), rec.get('total'))
    return result
