"""Terminal quality and safety metrics (operator decision 2026-11-06), computed from a scorer result.

Q_all is primary. Safety is reported separately and never folded into Q_all. Error rate is undefined
(None) when nothing is asserted, so an all-abstain policy cannot look safe; the frozen scorer's own
error_rate field reports 0.0 in that case and is not used here.
"""
SAFETY_MARGIN = 0.05


def metrics(score):
    n = score['total']
    rows = score['rows']
    absent = [r for r in rows if r['status'] == 'ABSENT']
    declared = sum(1 for r in absent if r.get('declared_unknown'))
    asserted, wrong = score['asserted'], score['wrong']
    return dict(
        Q_all=score['Q_all'],
        error_rate=round(wrong / asserted, 6) if asserted else None,
        error_burden=round(wrong / n, 6),
        coverage=round(asserted / n, 6),
        abstention_rate=round(declared / n, 6),
        silent_omission_rate=round((len(absent) - declared) / n, 6),
        asserted=asserted, wrong=wrong, tp=score['tp'], total=n,
    )


def safety_gate(treatment, baseline, margin=SAFETY_MARGIN):
    """PASS / FAIL / UNDEFINED; UNDEFINED is never a pass."""
    t, b = treatment['error_rate'], baseline['error_rate']
    if t is None or b is None:
        return 'UNDEFINED'
    return 'PASS' if t <= b + margin + 1e-12 else 'FAIL'
