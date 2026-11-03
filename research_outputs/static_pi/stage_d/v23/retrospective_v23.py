"""Apply the V2.3 candidate scoring pipeline to the 36 stored SINK outputs of
Pilot V2. Zero provider calls: SINK texts are read from PILOT_V2_LEDGER.jsonl.

This is a RETROSPECTIVE mechanism check, not a new experiment: the
canonicalization table was authored after these outputs existed, so the numbers
below must not be used as confirmatory evidence. They show which blockers the
candidate clears and how much of the frozen TP gap was formatting.
"""
import json, re, statistics as st, sys
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23')
import executor as SA
import scorer_v23_candidate as C
from terminal_quality import evaluate_terminal_quality

LEDGER = '/root/research_outputs/static_pi/stage_d/v2/PILOT_V2_LEDGER.jsonl'
ARMS = ['Static-GLM', 'Static-DS', 'Retry-only', 'Z-only', 'pi-only', 'Joint']


def parse_json(t):
    dec = json.JSONDecoder()
    c = (t or '').strip()
    if c.startswith('```'):
        c = '\n'.join(c.split('\n')[1:]).replace('```', '').strip()
    try:
        return json.loads(c)
    except Exception:
        pass
    for i, ch in enumerate(c):
        if ch in '{[':
            try:
                return dec.raw_decode(c[i:])[0]
            except Exception:
                continue
    return None


def collect_sinks():
    cells = {}
    for line in open(LEDGER):
        r = json.loads(line)
        p = r.get('purpose', '')
        if not p.endswith(':SINK:SINK'):
            continue
        m = re.match(r'^(?P<tag>.*?)(?P<sc>S1b|S1):SINK:SINK$', p)
        if not m:
            continue
        tag, sc = m.group('tag'), m.group('sc')
        arm = tag.split('|')[0]
        rm = re.search(r'\|r(\d)\|', tag)
        rep = int(rm.group(1)) if rm else 1
        cells[(sc, rep, arm)] = parse_json(r['text'])   # last record wins = final SINK
    return cells


def main():
    cells = collect_sinks()
    assert len(cells) == 36, f'expected 36 cells, got {len(cells)}'
    con = C.load_contract()
    src = con['source_pages']
    rows = []
    for (sc, rep, arm), sink in sorted(cells.items()):
        # frozen v1.2.3 path
        term_f = SA.build_terminal_output(json.loads(json.dumps(sink)))
        res_f = evaluate_terminal_quality(SA.CONTRACT, term_f, SA.SRC)
        tp_f = sum(1 for c in res_f['claim_results'] if c['status'].startswith('CORRECT'))
        # candidate path
        res_c, audit, term_c = C.score(sink, con, src, relevance=None)
        tp_c = sum(1 for c in res_c['claim_results'] if c['status'].startswith('CORRECT'))
        ev_c = sum(1 for c in res_c['claim_results'] if c['status'] in
                   ('CORRECT_GOLD', 'SEMANTICALLY_CORRECT'))
        msum = C.metrics_summary(res_c, term_c, con)
        rows.append(dict(scenario=sc, repeat=rep, arm=arm, metrics=msum,
                         tp_frozen=tp_f, tp_candidate=tp_c, evid_candidate=ev_c,
                         q_frozen=res_f['Q_final'], q_candidate=res_c['Q_final'],
                         q_partial_candidate=res_c['Q_partial_diagnostic'],
                         q_partial_frozen=res_f['Q_partial_diagnostic'],
                         critical_frozen=res_f['critical_gate']['status'],
                         critical_candidate=res_c['critical_gate']['status'],
                         blocking_frozen=res_f['blocking_reasons'],
                         blocking_candidate=res_c['blocking_reasons'],
                         canonicalizations=len(audit)))

    summary = {}
    for arm in ARMS:
        g = [r for r in rows if r['arm'] == arm]
        summary[arm] = dict(
            tp_frozen=[r['tp_frozen'] for r in g], tp_frozen_median=st.median([r['tp_frozen'] for r in g]),
            tp_candidate=[r['tp_candidate'] for r in g], tp_candidate_median=st.median([r['tp_candidate'] for r in g]),
            evid_candidate=[r['evid_candidate'] for r in g], evid_median=st.median([r['evid_candidate'] for r in g]),
            q_partial_median=st.median([r['q_partial_candidate'] for r in g]),
            critical_pass=sum(1 for r in g if r['critical_candidate'] == 'PASS'),
            critical_fail=sum(1 for r in g if r['critical_candidate'] == 'FAIL'),
            critical_unknown=sum(1 for r in g if r['critical_candidate'] == 'UNKNOWN'),
            canonicalizations=sum(r['canonicalizations'] for r in g),
            blockers_remaining=sorted({b for r in g for b in r['blocking_candidate']}),
        )
    out = dict(batch='PHASE_PI_V23_RETROSPECTIVE (mechanism check, NOT confirmatory)',
               new_calls=0, cells=rows, summary=summary,
               note=('Canonicalization authored after V2 outputs existed; retrospective only. '
                     'Q_final remains NULL until an external relevance adjudication is supplied.'))
    json.dump(out, open('/root/research_outputs/static_pi/stage_d/v23/RETROSPECTIVE_V23.json', 'w'),
              ensure_ascii=False, indent=1)
    print(f'{"arm":12s} {"TPfroz":7s} {"TPcand":7s} {"evid":5s} {"Qpart":6s} gate(P/F/U)  canon  remaining blockers')
    for arm in ARMS:
        s = summary[arm]
        print(f"{arm:12s} {s['tp_frozen_median']:7} {s['tp_candidate_median']:7} "
              f"{s['evid_median']:5} {s['q_partial_median']:.3f}  "
              f"({s['critical_pass']}/{s['critical_fail']}/{s['critical_unknown']})       "
              f"{s['canonicalizations']:2d}  {s['blockers_remaining']}")


if __name__ == '__main__':
    main()
