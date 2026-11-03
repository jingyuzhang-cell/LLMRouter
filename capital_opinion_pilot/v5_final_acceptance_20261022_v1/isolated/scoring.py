"""PILOT V2 fix #3: offline quality scoring closed loop (zero model calls).

Scores node/report outputs against the frozen silver facts:
- fact_coverage: verified silver facts whose normalized answer appears in the output;
- citation_accuracy: among covered facts whose output attaches a doc_id citation,
  the fraction citing the correct evidence doc (silver's evidence_doc);
- timeline_order: violations of chronological ordering among dated timeline items;
- unverified_dates: claimed dates absent from silver answers AND from evidence texts
  (hallucination-risk flag; NOT treated as automatic wrongness).
Silver labels only — NOT human gold. Parse success never implies factual correctness.
"""
import json
import re

from pilot_common import PILOT_DIR, all_dates

DOC_IDS = ['csrc_penalty_2024_41', 'st_announce_2024_020', 'st_announce_2024_021',
           'st_advance_notice_2023']
DATE_TYPES = ('date',)


def load_silver():
    d = json.loads((PILOT_DIR / 'facts_silver.json').read_text())
    return [f for f in d['facts'] if f['verification_status'].startswith('verified')]


def load_evidence_dates():
    dates = set()
    for d in DOC_IDS:
        dates |= set(all_dates(''.join((PILOT_DIR / 'evidence' / 'text' / f'{d}.txt').read_text())))
    return dates


def norm_amount(s):
    return re.sub(r'[,\s，]', '', str(s))


def fact_covered(fact, text):
    """Two-tier result for text facts: 'full' | 'partial' | False (deterministic)."""
    a = norm_amount(fact['answer'])
    t = norm_amount(text)
    if fact['answer_type'] == 'date':
        return 'full' if a in all_dates(text) else False
    if fact['answer_type'] == 'amount':
        return 'full' if (a in t or a.rstrip('元%') in t) else False
    if a in t:
        return 'full'
    # partial: any >=5-char punctuation-free segment of the answer appears verbatim
    import re as _re
    segs = [s for s in _re.split(r'[，,。;；:：、（）()\s]+', fact['answer']) if len(s) >= 5]
    return 'partial' if any(norm_amount(s) in t for s in segs) else False


def coverage_counts(facts_results, n_silver):
    full = sum(1 for v in facts_results if v == 'full')
    partial = sum(1 for v in facts_results if v == 'partial')
    return {'full': full, 'partial': partial,
            'coverage': round((full + 0.5 * partial) / n_silver, 4)}


def citations_in(text):
    return sorted({d for d in DOC_IDS if d in text})


def score_output(text, silver, evidence_dates):
    """Generic scorer for any node output or report text."""
    dates = all_dates(text)
    tier_results = {f['fact_id']: fact_covered(f, text) for f in silver}
    cc = coverage_counts(list(tier_results.values()), len(silver))
    covered = [f for f in silver if tier_results[f['fact_id']]]
    cites = citations_in(text)
    # citation accuracy: for each covered fact, is the CORRECT doc among the output's citations?
    cited_correct, cited_checked = 0, 0
    per_fact = []
    for f in covered:
        block = _fact_context(text, f)
        fact_cites = citations_in(block) or cites  # fall back to whole-output citations
        if not fact_cites:
            continue
        cited_checked += 1
        ok = f['evidence_doc'] in fact_cites
        cited_correct += int(ok)
        per_fact.append({'fact_id': f['fact_id'], 'cited': fact_cites, 'correct_doc': ok})
    unknown_cites = sorted(set(re.findall(r'[a-z]+_[0-9a-z_]+', text)) - set(DOC_IDS))
    return {
        'label': 'silver_auto (NOT human gold)',
        'fact_coverage': cc['coverage'],
        'coverage_full': cc['full'],
        'coverage_partial': cc['partial'],
        'covered_fact_ids': [f['fact_id'] for f in covered],
        'tier_results': {k: v for k, v in tier_results.items()},
        'citation_checked': cited_checked,
        'citation_accuracy': round(cited_correct / cited_checked, 4) if cited_checked else None,
        'per_fact_citations': per_fact,
        'unknown_doc_ids_cited': [c for c in unknown_cites if c.count('_') >= 2][:5],
        'n_dates_claimed': len(dates),
        'unverified_dates': [d for d in dates if d not in evidence_dates
                             and d not in {f['answer'] for f in silver}],
    }


def _fact_context(text, fact):
    """Window around the fact answer's occurrence, for citation attribution."""
    candidates = [fact['answer']]
    if fact['answer_type'] == 'date':
        candidates += [fact['answer'][2:], fact['answer'][:7]]
    else:
        import re as _re
        segs = sorted((s for s in _re.split(r'[，,。;；:：、（）()\s]+', fact['answer']) if len(s) >= 4),
                      key=len, reverse=True)
        candidates += [norm_amount(s) for s in segs]
    for frag in candidates:
        j = text.find(frag)
        if j >= 0:
            return text[max(0, j - 130):j + 170]
    return ''


def score_timeline(items, silver, evidence_dates):
    """items: list of dicts with 'date' (or date-bearing text) fields."""
    seq = []
    for it in items if isinstance(items, list) else []:
        ds = all_dates(json.dumps(it, ensure_ascii=False))
        if ds:
            seq.append(min(ds))
    violations = sum(1 for a, b in zip(seq, seq[1:]) if a > b)
    return {'dated_items': len(seq), 'order_violations': violations,
            'order_ok': violations == 0}


def score_unresolved_marking(report_text):
    return {'marks_unresolved': bool(re.search(r'UNRESOLVED|无法确认|未能确认|不确定', report_text))}
