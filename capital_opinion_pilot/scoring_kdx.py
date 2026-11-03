"""KDX scoring adapter (zero-call): reuses the generic scoring engine with the KDX
seed facts / doc ids / evidence dates. Seeds are ground-truth-pending silver
(deterministic grounding only; AI cross-verification still awaits authorization) —
labelled as such in every output.
"""
import json

from pilot_common import PILOT_DIR, all_dates
import scoring

KDX_DOCS = ['kdx_inquiry_2018', 'kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020', 'kdx_inquiry_2019']
scoring.DOC_IDS = KDX_DOCS  # documented module-level retarget of the generic engine


def load_silver_kdx():
    seed = json.loads((PILOT_DIR / 'v3_evidence' / 'A_kangdexin' / 'facts_seed.json').read_text())
    return seed['facts']


def load_evidence_dates_kdx():
    dates = set()
    for d in KDX_DOCS:
        dates |= set(all_dates(''.join((PILOT_DIR / 'v3_evidence' / 'A_kangdexin' / 'text' / f'{d}.txt').read_text())))
    return dates


def score(text):
    silver = load_silver_kdx()
    edates = load_evidence_dates_kdx()
    s = scoring.score_output(text, silver, edates)
    s['label'] = 'kdx_seed_silver (deterministic grounding only; NOT AI-cross-verified; NOT gold)'
    s['marks_unresolved'] = bool(__import__('re').search(r'UNRESOLVED|无法确认|未能确认|不确定|存疑', text))
    return s
