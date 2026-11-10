#!/usr/bin/env python3
"""P2-C zero-call scoring acceptance gate.

Gate A: for each v1.1 contract, submit the contract's own evidence spans (all of them, one answer per span
        round-robin so multi-span slots are exercised) -> Q_all must be exactly 1.0.
Gate B: all-wrong answers (values corrupted per kind) -> Q_all must be exactly 0.0.
Gate C: adversarial classes on a per-contract sample (up to 40 slots per contract, first critical slots):
        wrong doc / wrong subject quote / fabricated quote / negated / D1-D2 flip / wrong amount / duration swap;
        each corrupted answer must NOT be TP.
Exit 0 only if all gates pass. Writes nothing except stdout.
"""
import json, random, re, sys
from pathlib import Path

sys.path.insert(0, '/root/research_outputs/static_pi/p2_confirm')
import p2c_scorer as S

GOLD = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
MAN = json.loads(Path(sys.argv[1] if len(sys.argv) > 1 else '/root/research_outputs/static_pi/p2_confirm/P2C_G11_BUILD_LOG.json').read_text())
rng = random.Random(20261108)


def support_spans(f):
    return [e for e in f['source_evidence'] if e.get('role') == 'support']


def perfect_sinks(c):
    """One sink per round r: every slot answered with its r-th support span (cycled) -> covers every support span."""
    scored = [f for f in c['required_facts'] if f['status'] != 'GOLD_DRAFT_UNKNOWN']
    rounds = max(len(support_spans(f)) for f in scored)
    for r in range(rounds):
        yield [dict(fact_id=f['fact_id'], value=f['value'], quote=support_spans(f)[r % len(support_spans(f))]['quote'],
                    doc=support_spans(f)[r % len(support_spans(f))]['doc_id']) for f in scored]


def corrupt_value(f):
    """A semantically wrong value of the same kind (not a surface perturbation)."""
    g, v, k = f['g11'], str(f['value']), f['g11']['kind']
    if k in ('amount', 'sum'):
        n = float(v.lstrip('约'))
        return f'{n * 2 + 1:g}' + (f.get('unit') or '')
    if k == 'date':
        return '1999-01-01' if g['precision'] == 'day' else '1999-01'
    if k == 'docno':
        return '[1999]99号'
    if k == 'ban':
        return '3年市场禁入' if g['duration'] == '终身' else '终身市场禁入'
    forb = g.get('forbidden') or []
    if forb:                                   # proposition reversed with a forbidden (negating/contradicting) phrase
        return v + '；' + forb[0]
    return '无相关事实'                         # required elements absent


def negations(f):
    """Polarity/stage reversals that keep surface overlap with the gold value."""
    g, v = f['g11'], str(f['value'])
    out = []
    if g['kind'] == 'text':
        for x in (g.get('forbidden') or [])[:3]:
            out.append(v + '，' + x)
        out.append(re.sub(r'未再载明|未载明', '已载明', v) if re.search('未再载明|未载明', v) else '与上述相反：' + '不' + v)
    if g['kind'] == 'ban':
        out.append(v + '，后被撤销')
    return out


def main():
    fails = []
    tallies = {}
    for r in MAN['contracts']:
        c = json.loads(Path(r['file']).read_text())
        docs = S.doc_index(c)
        scored = [f for f in c['required_facts'] if f['status'] != 'GOLD_DRAFT_UNKNOWN']
        qa = [S.score(dict(answers=a, unknown_slots=[]), c)['Q_all'] for a in perfect_sinks(c)]
        okA = all(q == 1.0 for q in qa)
        wrong = [dict(fact_id=f['fact_id'], value=corrupt_value(f), quote=support_spans(f)[0]['quote'],
                      doc=support_spans(f)[0]['doc_id']) for f in scored]
        qb = S.score(dict(answers=wrong, unknown_slots=[]), c)['Q_all']
        okB = qb == 0.0
        bad = []
        header = docs['D1'][:30]
        for f in scored:
            g = f['g11']
            for e in support_spans(f):
                q, d = e['quote'], e['doc_id']
                other = 'D2' if d == 'D1' else 'D1'
                cases = [('wrong_value', dict(value=corrupt_value(f), quote=q, doc=d)),
                         ('fabricated_quote', dict(value=f['value'], quote=q + '并另行追加处罚一百万元', doc=d)),
                         ('irrelevant_quote', dict(value=f['value'], quote=header, doc='D1'))]
                if other not in g['support_docs'] or S.nt(q) not in docs[other]:
                    cases.append(('wrong_doc', dict(value=f['value'], quote=q, doc=other)))
                for x in negations(f):
                    cases.append(('negation', dict(value=x, quote=q, doc=d)))
                if g['kind'] in ('amount', 'ban') and g.get('subject_any'):
                    hit = [sbj for sbj in g['subject_any'] if S.nt(sbj) in S.nt(q)]
                    if hit:
                        qq = S.nt(q)
                        for sbj in hit:
                            qq = qq.replace(S.nt(sbj), '张三某某')
                        cases.append(('wrong_subject', dict(value=f['value'], quote=qq, doc=d)))
                for name, a in cases:
                    tallies[name] = tallies.get(name, 0) + 1
                    st = S.score(dict(answers=[dict(fact_id=f['fact_id'], **a)], unknown_slots=[]), c)
                    if next(x for x in st['rows'] if x['fact_id'] == f['fact_id'])['status'] == 'TP':
                        bad.append((f['fact_id'], name))
            # D1/D2 stage confusion: answer the other stage's value where the two stages differ
            ds = f.get('dual_stage') or {}
            if g['kind'] in ('amount',) and ds.get('change') == 'reduced':
                m1, m2 = (re.search(r'(\d+(?:\.\d+)?)万', ds.get(k) or '') for k in ('d1_proposed', 'd2_final'))
                if m1 and m2:
                    alt = m2.group(1) if S.amount_value_ok(f, m1.group(1)) else m1.group(1)
                    for e in f['source_evidence']:
                        tallies['stage_flip'] = tallies.get('stage_flip', 0) + 1
                        st = S.score(dict(answers=[dict(fact_id=f['fact_id'], value=alt, quote=e['quote'], doc=e['doc_id'])], unknown_slots=[]), c)
                        if next(x for x in st['rows'] if x['fact_id'] == f['fact_id'])['status'] == 'TP':
                            bad.append((f['fact_id'], 'stage_flip'))
        ok = okA and okB and not bad
        if not ok:
            fails.append(r['task'])
        print(f"{r['task']:11} A(min over {len(qa)} span rounds)={min(qa):.3f} B={qb:.3f} N={len(scored)} adversarial_TP={bad or 'none'}")
    print('adversarial cases run:', tallies, 'total', sum(tallies.values()))
    print('GATE', 'PASS' if not fails else f'FAIL {fails}')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
