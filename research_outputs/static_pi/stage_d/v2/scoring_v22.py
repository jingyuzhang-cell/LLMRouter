"""C3: terminal scoring via the FROZEN terminal_quality scorer (same for all arms)."""
import json, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
import executor as SA
from terminal_quality import evaluate_terminal_quality

def score_terminal_record(rec):
    """Score one execution's SINK output with the frozen contract scorer."""
    sink = rec['outputs'].get('SINK')
    if not isinstance(sink, dict):
        return dict(tp=0, q=0.0, claims=0, reason='no_sink_object')
    try:
        term = SA.build_terminal_output(json.loads(json.dumps(sink)))
        res = evaluate_terminal_quality(SA.CONTRACT, term, SA.SRC)
    except Exception as e:
        return dict(tp=0, q=0.0, claims=0, reason=f'scorer_error:{type(e).__name__}')
    tp = sum(1 for c in res['claim_results'] if c['status'].startswith('CORRECT'))
    return dict(tp=tp, q=round(tp/23, 4), claims=len(res['claim_results']),
                statuses=sorted({c['status'] for c in res['claim_results']}))
