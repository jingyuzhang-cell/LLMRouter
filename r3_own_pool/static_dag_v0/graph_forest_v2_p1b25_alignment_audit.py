"""P1b-2.5: Semantic Alignment Audit — ZERO model calls.

Decides the post-P1b-2 route by separating three hypotheses:
  A  gold is supported by data-side evidence (unit/table/schema)
     -> P1b-3 Data-Grounded Intent Resolver
  B  gold follows a benchmark-specific convention (learnable from train/dev,
     frozen before test) -> Benchmark Semantics Adapter (honestly named)
  C  gold conflicts with BOTH natural language and dataset convention
     -> annotation ambiguity strata

Components:
 1. CONVENTION PROBE: MultiHiertt train (7830) — for percent-cue questions,
    does the gold program multiply by 100 (const_100 / multiply(.., const_100))?
 2. EVIDENCE TABLE (76 held-out): question cue / unit-table evidence /
    gold operation family (structural) / contract family.
 3. ERROR ENCODING (wrong + abstain contracts): language-gold conflict /
    unit-gold conflict / denominator ambiguity / operand ambiguity /
    true model misread / other.
 4. Strata preview: Q_reuse on aligned vs ambiguous tasks (P0-2 outcomes).
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, '/root/r3_own_pool')
from static_dag_v0.graph_forest_v2_diagnostic import gold_expression

ROOT = Path('/root/r3_own_pool')
TRAIN = Path('/root/phase_c9_0/external/MultiHiertt-data/multihiertt_data/train.json')
OUT = ROOT / 'static_dag_v0/graph_forest_v2_p1b2'
P02 = ROOT / 'static_dag_v0/graph_forest_v2_p02'

PCT_WORDS = ('percent', 'percentage')
RATIO_WORDS = ('ratio', 'how many times')
AVG_WORDS = ('average', 'mean')
SUM_WORDS = ('sum', 'total', 'combined', 'altogether')
DIFF_WORDS = ('difference', 'how much more', 'how much greater', 'exceed', 'how much did')


def gold_family(node):
    e = gold_expression(node)
    if e is None:
        return 'unmappable'
    flat = e.replace(' ', '')
    if '100*' in flat:
        return 'percentage_family'
    if '/' in flat:
        inner = re.sub(r'\)\+\(', '', flat)
        # average: ends with /k and k terms summed
        m = re.search(r'/(\d+)$', flat)
        if m:
            k = int(m.group(1))
            n_terms = len(re.findall(r'v\d+', flat[:flat.rfind('/k'.replace('k', str(k)))].replace(f'/ {k}', '')))
            if flat.count(')+(') >= k - 1 and k in (2, 3, 4, 5):
                return 'average'
        return 'ratio'
    if '-' in flat:
        return 'difference'
    return 'sum'


def question_cues(q):
    ql = q.lower()
    return dict(pct=any(w in ql for w in PCT_WORDS) or '%' in ql,
                ratio=any(w in ql for w in RATIO_WORDS),
                avg=any(w in ql for w in AVG_WORDS),
                sum=any(w in ql for w in SUM_WORDS),
                diff=any(w in ql for w in DIFF_WORDS),
                growth=('growth' in ql or 'increase' in ql or 'decrease' in ql
                        or 'change' in ql or 'rate' in ql))


def unit_pct_evidence(task, node):
    """'%' appears in the raw table/text context as a unit marker."""
    ctx = task.get('context', '')
    return ('%' in ctx) or bool(re.search(r'\bpercent\b', ctx, re.I))


def convention_probe():
    train = json.loads(TRAIN.read_text())
    stats = Counter()
    for row in train:
        qa = row['qa']
        q = qa['question'].lower()
        prog = qa.get('program', '')
        if not prog:
            continue
        has_pct_word = ('percent' in q) or ('percentage' in q)
        has_100 = 'const_100' in prog or bool(re.search(r'multiply\([^)]*const_100', prog))
        if has_pct_word:
            stats[('pct_question', 'x100_program' if has_100 else 'raw_program')] += 1
        elif has_100:
            stats[('no_pct_question', 'x100_program')] += 1
    return dict(n_train=sum(1 for _ in train),
                pct_questions=stats[('pct_question', 'x100_program')] + stats[('pct_question', 'raw_program')],
                pct_with_x100=stats[('pct_question', 'x100_program')],
                pct_raw=stats[('pct_question', 'raw_program')],
                no_pct_with_x100=stats[('no_pct_question', 'x100_program')])


def run():
    ct = json.loads((OUT / 'CONTRACTS_test_v1.json').read_text())['contracts']
    dry = json.loads((P02 / 'DRYRUN.json').read_text())
    rows = {r['uid']: r for r in dry['fresh_rows'] if r['ok']}
    p02 = {p['uid']: p for p in json.loads((P02 / 'RESULTS.json').read_text())['per_task']}
    dev = {r['task_uid'] for r in json.loads(
        (ROOT / 'static_dag_v0/graph_forest_v1/RESULTS.json').read_text())['rows']}
    nodes = json.loads((ROOT / 'static_dag_v0/fresh_static_confirmation/NODES.json').read_text())
    rs = {n['task_uid']: n for n in nodes if n['node_id'].endswith(':rs')}
    tasks = {t['uid']: t for t in json.loads(
        (ROOT / 'static_dag_v0/fresh_static_confirmation/TASKS.json').read_text())}

    probe = convention_probe()
    table, encoding = [], Counter()
    aligned_q, ambiguous_q = [], []
    n_ambiguous = 0
    for uid, r in rows.items():
        if uid in dev:
            continue
        node, task = rs[uid], tasks[uid]
        cues = question_cues(node['question'])
        gf = gold_family(node)
        cf = ct[uid]['family']
        unit_pct = unit_pct_evidence(task, node)
        pct_like = cues['pct'] or (cues['growth'] and not cues['ratio'])
        lang_gold_conflict = (pct_like and gf in ('ratio', 'average', 'sum', 'difference')
                              and cf in ('percentage', 'percentage_change'))
        unit_gold_conflict = (unit_pct and cues['pct'] and gf == 'ratio'
                              and not lang_gold_conflict)
        ambiguous = lang_gold_conflict or unit_gold_conflict
        n_ambiguous += ambiguous
        okA = p02[uid]['A0'] is not None and p02[uid]['target'] is not None and \
            abs(p02[uid]['A0'] - p02[uid]['target']) <= max(1e-4, 1e-4 * abs(p02[uid]['target']))
        (ambiguous_q if ambiguous else aligned_q).append(float(okA))
        # error encoding for wrong contracts
        from static_dag_v0.graph_forest_v2_p1b_contract import equiv
        gexpr = gold_expression(node)
        eq_gold = equiv(ct[uid]['expr'], gexpr, node['gold_facts']) if ct[uid]['expr'] else None
        if eq_gold is True:
            code = None
        elif ct[uid]['abstain']:
            code = 'schema_inexpressible(abstain)'
        elif lang_gold_conflict:
            code = 'language_gold_conflict'
        elif unit_gold_conflict:
            code = 'unit_gold_conflict'
        else:
            cexpr, er = ct[uid]['expr'], gexpr or ''
            rc = set(re.findall(r'v\d+', cexpr))
            rg = set(re.findall(r'v\d+', er))
            if rc != rg and (cf.split('_')[0] in ('ratio', 'average', 'sum', 'percentage')
                             and gf == cf or gf.replace('_family', '') == cf):
                code = 'denominator_or_operand_ambiguity'
            elif cues.get(gf.replace('_family', ''), False) or (
                    gf == 'average' and cues['avg']) or (gf == 'sum' and cues['sum']):
                code = 'true_model_misread'   # cue pointed at gold family, model chose another
            else:
                code = 'other'
        if code:
            encoding[code] += 1
        table.append(dict(uid=uid, pct=cues['pct'], ratio=cues['ratio'], avg=cues['avg'],
                          sum_cue=cues['sum'], growth=cues['growth'], unit_pct=unit_pct,
                          gold_family=gf, contract_family=cf, ambiguous=ambiguous,
                          code=code, reuse_ok=okA))
    out = dict(convention_probe_train=probe,
               n_heldout=len(table), n_ambiguous=n_ambiguous,
               error_encoding=dict(encoding),
               strata=dict(Q_reuse_aligned=f'{sum(aligned_q):.0f}/{len(aligned_q)}'
                           f' = {sum(aligned_q)/max(1,len(aligned_q)):.3f}',
                           Q_reuse_ambiguous=f'{sum(ambiguous_q):.0f}/{len(ambiguous_q)}'
                           f' = {sum(ambiguous_q)/max(1,len(ambiguous_q)):.3f}'),
               table=table)
    (OUT / 'ALIGNMENT_AUDIT.json').write_text(json.dumps(out, indent=1))
    print(json.dumps(dict(probe=probe, n_ambiguous=n_ambiguous,
                          encoding=dict(encoding), strata=out['strata']), indent=1))


if __name__ == '__main__':
    run()
