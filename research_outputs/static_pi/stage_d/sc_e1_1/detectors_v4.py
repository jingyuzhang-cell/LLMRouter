"""Node-output semantic consistency detectors, version 4. V2 and V3 are frozen and kept.

Only change from V3: the J2 status label is classified against two frozen lists instead of one.
  affirmed    a label that confirms the slot; the five seen in every real ledger so far
  suppressed  V2's suppression list plus not_found (seen in T1 A1 r3, where V2 and V3 reported NONE)
  unknown     any other non-empty label; reported as UNKNOWN_LABEL and never silently treated as NONE
M1 states: NONE (affirmed, or no candidate row), EXPLICIT_SUPPRESSION, OMISSION (no entry), UNKNOWN_LABEL.
M2 and M3 are V3's unchanged. Gold is never read.
"""
import hashlib
from pathlib import Path

import detectors_v2 as V2
import detectors_v3 as V3

VERSION = 'v4'
V2_SHA256 = 'c2c3384265b39aee6783eff407402c4c775d7eb0b18aea005442f80ec1548c24'
V3_SHA256 = '6f39b9af9f0405376b8bad71a8d685814fb34e05a4029b920f1da0256401cd30'
# Inventory of every J2 status label in the real ledgers (Stage A', T1) at freeze time.
AFFIRMED = frozenset({'已核验', 'correct', 'verified', 'supported', 'computed'})
SUPPRESSED = frozenset(V2.SUPPRESSION_STATUSES | {'not_found'})


def verify_pins():
    for module, pin in ((V2, V2_SHA256), (V3, V3_SHA256)):
        actual = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        if actual != pin:
            raise RuntimeError(f'{module.__name__} drifted: {actual[:16]}')


def classify(status):
    if status is None:
        return None
    s = V2.norm(status).lower()
    if s in AFFIRMED:
        return 'affirmed'
    if s in SUPPRESSED:
        return 'suppressed'
    return 'unknown'


slot_type = V3.slot_type


def detect_m1(slots, j2_obj, rows):
    st = V2.j2_statuses(j2_obj)
    out = {}
    for slot in slots:
        fid = slot['fact_id']
        kind = slot_type(slot)
        if kind == 'derived':
            out[fid] = dict(state='NOT_APPLICABLE', j2_status=st.get(fid), candidates=0, candidate_rows=[])
            continue
        cands = V3._polar_candidates(slot, rows) if kind == 'polar' else V2.candidate_rows(slot, rows)
        status = st.get(fid)
        label = classify(status)
        if not cands or label == 'affirmed':
            state = 'NONE'
        elif label is None:
            state = 'OMISSION'
        elif label == 'suppressed':
            state = 'EXPLICIT_SUPPRESSION'
        else:
            state = 'UNKNOWN_LABEL'
        out[fid] = dict(state=state, j2_status=status, label_class=label, candidates=len(cands),
                        candidate_rows=[r['row'] for r in cands])
    return out


def detect_m2(slots, j2_obj, base):
    return V3.detect_m2(slots, j2_obj, base)


def detect_m3(slots, sink_obj, rows, base):
    return V3.detect_m3(slots, sink_obj, rows, base)


def detect_all(slots, j2_obj, sink_obj, base, rows):
    verify_pins()
    return dict(version=VERSION, base_total=base, m1=detect_m1(slots, j2_obj, rows), m2=detect_m2(slots, j2_obj, base),
                m3=detect_m3(slots, sink_obj, rows, base))
