"""RQ1: node-capability heterogeneity analysis on frozen observation copies.

DIAGNOSTIC, descriptive only. Compares model performance per DAG stage
(extraction e1/e2, reasoning r, verification v) using ONLY terminated,
version-explicit trajectory copies (offline_predictor_audit/copy_inputs —
frozen, committed). Zero LLM calls, no GPU, no TEST16, no production changes,
no active experiment directories touched.

Claim guards (review):
- Stage-level model differences do NOT imply node-level assignment beats
  query-level routing; that requires same-task, same-scoring-contract DIRECT
  comparisons, which this analysis partially provides (within-task pairing)
  but does not decide.
- Historical static/dynamic trajectories cannot cleanly separate DAG
  decomposition from recovery gains when model configs / prompts / tasks /
  fault conditions differ — this report DESCRIBES differences and makes no
  causal attribution to scheduling.

Node-correctness bases (proxies, explicit):
- e1/e2: no gold FACTS labels exist. Proxies: (a) parse_ok = facts JSON parses
  with >=1 numeric fact; (b) operand_recall = fraction of the gold
  derivation's non-trivial numeric literals (excluding 0/1/100) matched by
  extracted fact values within max(1e-4, 1e-4*|lit|).
- r: (a) expr_valid = expression parses and evaluates over ITS consumed facts
  without error; (b) gold_match = score_v21(expr_value, gold) — CONFLATED with
  upstream extraction quality unless conditioned; conditional variant reports
  only cells whose BOTH parents have full operand recall.
- v: (a) consistency = close(v_value, r-chain value); (b) gold_match under
  score_v21, conditional variant on upstream expr_valid.
Scoring contract: v2.1 (scoring_contract_final + contract_v2_gold) applied
UNIFORMLY to all sources regardless of each session's historical gold version
(recorded per source for provenance).
Pairing: within-task; r-stage pairs additionally require identical (m_e1,m_e2)
upstream context; v-stage pairs require identical (m_e1,m_e2,m_r).
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
JS = ROOT / 'collab_scheduler_v1/joint_search_v1'
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from collab_scheduler_v1.joint_search_v1.scoring_contract_final import (  # noqa
    score_v21)
from collab_scheduler_v1.joint_search_v1.task_contract_v2 import (  # noqa
    contract_v2_gold, load_native_answers)

SRC = JS / 'offline_predictor_audit/copy_inputs'
TRIVIAL = {0.0, 1.0, 100.0}

SOURCES = {
    'fullval_runs_fullval_authorized_1h_01': 'authorized_fullval_1h_v1 (historical gold: eval-derivation)',
    'fullval_runs_fullval_cont1_01': 'fullval_continuation_1_v1',
    'formal_campaign_proposed_state_incremental_20261009':
        'formal_launch_v1 (historical gold: eval-derivation; DIAGNOSTIC session)',
    'formal_campaign_v2_scalarized_bo_20261009':
        'formal_launch_v2 (historical gold: GOLD_CONTRACT_V1)',
}


def literals(derivation):
    out = []
    for m in re.finditer(r'(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])', derivation):
        v = float(m.group(1))
        if v not in TRIVIAL:
            out.append(v)
    return out


def close_v1(a, b):
    return a is not None and b is not None and abs(a - b) <= max(1e-4, 1e-4 * abs(b))


def parse_facts(ans):
    """Return list of numeric fact values or None if unparseable/empty."""
    if not isinstance(ans, str):
        return None
    try:
        m = re.search(r'\{.*\}', ans, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(ans)
        vals = [float(f['value']) for f in obj.get('facts', []) if f.get('value') is not None]
        return vals or None
    except Exception:
        return None


def _num(v):
    """Tolerant numeric conversion ('$24.7'->24.7, '85%'->85, 3->3.0); None on failure."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace('$', '').replace(',', '').rstrip('%')
        try:
            return float(t)
        except ValueError:
            return None
    return None


def classify_facts(ans):
    """(status, values): status in ok|empty|refusal|unparseable.
    refusal = natural-language decline without a facts JSON; string values
    like '$24.7' are tolerated (numeric content extracted)."""
    if not isinstance(ans, str):
        return 'unparseable', None
    try:
        m = re.search(r'\{.*\}', ans, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(ans)
        vals = [x for x in (_num(f.get('value')) for f in obj.get('facts', []))
                if x is not None]
        return ('ok', vals) if vals else ('empty', None)
    except Exception:
        return ('refusal', None)


def parse_expr(ans):
    if not isinstance(ans, str):
        return None
    try:
        m = re.search(r'\{.*\}', ans, re.S)
        obj = json.loads(m.group(0)) if m else json.loads(ans)
        e = obj.get('expression')
        return e.strip() if isinstance(e, str) and e.strip() else None
    except Exception:
        return None


def parse_value(ans):
    if not isinstance(ans, str):
        return None
    try:
        m = re.search(r'\{[^{}]*\}', ans, re.S)
        v = json.loads(m.group(0))['value']
        return float(v) if v is not None else None
    except Exception:
        return None


def eval_expr(expr, fact_vals):
    """Evaluate v0/v1/... expression over fact values; None on any failure."""
    try:
        e = expr
        for i, v in enumerate(fact_vals):
            e = re.sub(rf'\bv{i}\b', repr(float(v)), e)
        if re.search(r'\bv\d+\b', e):
            return None
        return float(eval(e, {'__builtins__': {}}))
    except Exception:
        return None


def e2_text_input():
    """uid -> the TEXT passage (e2's input) from the frozen manifests."""
    out = {}
    JS_DIR = ROOT / 'collab_scheduler_v1/joint_search_v1'
    for f, key in ((JS_DIR / 'FORMAL_LAUNCH_V2.json', 'tasks'),
                   (JS_DIR / 'FULLVAL_AUTHORIZED_1H.json', 'tasks'),
                   (JS_DIR / 'FULLVAL_CONTINUATION_1.json', 'tasks')):
        if not f.exists():
            continue
        for t in json.loads(f.read_text()).get(key, []):
            txt = t.get('ctx_text')
            if txt is None and 'para' in t:
                from static_dag_v0.multidag_dynamic import ctx_text
                txt = ctx_text(t['para'])
            if txt:
                out[t['uid']] = txt
    return out


def supported_fraction(values, text):
    """Fraction of extracted values that appear (tolerantly) in the text input.
    Values absent from the input are unsupported (hallucination risk) and an
    output containing them must NOT be auto-counted as success."""
    if not text:
        return None
    low = text.lower()
    hits = 0
    for v in values:
        if any(fmt in low for fmt in (f'{v:g}', f'{v:.2f}', f'{v:.1f}')):
            hits += 1
    return hits / len(values) if values else None


def gold21_for(uids):
    native = load_native_answers()
    out = {}
    for uid in uids:
        nat = native.get(uid, {})
        g = contract_v2_gold(nat.get('native_answer'), nat.get('native_scale'),
                             nat.get('raw_derivation', ''))
        out[uid] = dict(gold=g['gold'], derivation=nat.get('raw_derivation', ''))
    return out


def load_cells():
    """Node records per source: first planned base call per (scope, cid, uid, node)."""
    records = []
    for name in SOURCES:
        d = SRC / name
        first = {}
        for line in (d / 'WORKFLOW.jsonl').read_text().splitlines():
            r = json.loads(line)
            parts = r['key'].split(':')
            if len(parts) != 5 or parts[2] != 'base':
                continue
            k = (r['state'], r['cid'], parts[4], parts[3])
            if k not in first:
                first[k] = dict(source=name, scope=r['state'], cid=r['cid'],
                                uid=parts[4], node=parts[3], model=r['model'],
                                answer=r['response']['answer'],
                                usage=r['response'].get('usage', {}),
                                alias='alias_of' in r,
                                injected=bool(r['response'].get('injected_fault')))
        records.extend(first.values())
    return records


def main():
    recs_all = load_cells()
    acct = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))  # node -> model -> [executed, alias, injected]
    for r in recs_all:
        a = acct[r['node']][r['model']]
        if r['injected']:
            a[2] += 1
        elif r['alias']:
            a[1] += 1
        else:
            a[0] += 1
    # capability metrics use ONLY executed, non-injected records
    recs = [r for r in recs_all if not r['alias'] and not r['injected']]
    uids = sorted({r['uid'] for r in recs_all})
    gold = gold21_for(uids)

    # (source, scope, cid, uid) -> node -> record  (campaign cells are multi-task)
    cell_nodes = defaultdict(dict)
    for r in recs:
        cell_nodes[(r['source'], r['scope'], r['cid'], r['uid'])][r['node']] = r

    e2_text = e2_text_input()
    rows = []
    refusal_counts = defaultdict(int)
    for (src, scope, cid, uid), sub in cell_nodes.items():
        X = dict(zip(('e1', 'e2', 'r', 'v'), cid.split('__')[:4]))
        g = gold.get(uid, {})
        gvals = g.get('gold')
        lits = literals(g.get('derivation', ''))
        row = dict(source=src, scope=scope, cid=cid, uid=uid, X=X)
        # extraction
        for nd in ('e1', 'e2'):
            rec = sub.get(nd)
            if not rec:
                continue
            status, facts = classify_facts(rec['answer'])
            refusal_counts[f'{nd}:{status}'] += 1
            # support check (e2 only): extracted values must appear in the
            # TEXT input; unsupported numbers are NOT auto-successes
            supported = None
            if nd == 'e2' and facts:
                supported = supported_fraction(facts, e2_text.get(uid, ''))
            row[nd] = dict(
                model=rec['model'], status=status, parse_ok=status == 'ok',
                n_facts=len(facts) if facts else 0,
                operand_recall=(sum(1 for L in lits if any(
                    close_v1(f, L) for f in facts)) / len(lits)) if (facts and lits) else None,
                supported=supported,
                supported_ok=(status == 'ok' and supported is not None and supported >= 1.0
                              and all(any(fmt in (e2_text.get(uid, '') or '').lower()
                                          for fmt in (f'{f:g}', f'{f:.2f}')) for f in facts))
                if nd == 'e2' else None,
                tokens=rec['usage'].get('total_tokens'))
        # upstream completeness for conditioning
        e_recs = [row.get(nd) for nd in ('e1', 'e2')]
        upstream_complete = all(r_ and r_['operand_recall'] == 1.0 for r_ in e_recs)
        consumed = []
        for nd in ('e1', 'e2'):
            if row.get(nd) and row[nd]['parse_ok']:
                consumed.extend(parse_facts(sub[nd]['answer']) or [])
        rec = sub.get('r')
        if rec:
            expr = parse_expr(rec['answer'])
            val = eval_expr(expr, consumed) if expr else None
            row['r'] = dict(
                model=rec['model'], expr_ok=expr is not None,
                eval_ok=val is not None,
                gold_match=bool(gvals is not None and score_v21(val, gvals)) if val is not None else False,
                gold_match_cond=upstream_complete,
                tokens=rec['usage'].get('total_tokens'))
        rec = sub.get('v')
        if rec:
            vv = parse_value(rec['answer'])
            r_val = (row.get('r') or {}).get('eval_ok')
            r_chain_val = None
            if row.get('r'):
                rrec = sub['r']
                rexpr = parse_expr(rrec['answer'])
                r_chain_val = eval_expr(rexpr, consumed) if rexpr else None
            row['v'] = dict(
                model=rec['model'], parse_ok=vv is not None,
                consistency=close_v1(vv, r_chain_val),
                gold_match=bool(gvals is not None and score_v21(vv, gvals)) if vv is not None else False,
                upstream_valid=bool(r_val),
                tokens=rec['usage'].get('total_tokens'))
        rows.append(row)

    def agg(items, keys):
        n = len(items)
        if not n:
            return dict(n=0)
        out = dict(n=n)
        for k in keys:
            vals = [it[k] for it in items if it.get(k) is not None]
            out[k] = round(sum(1 for v in vals if v) / len(vals), 3) if vals else None
        return out

    # ---- per-stage per-model aggregates (all sources pooled; descriptive) ----
    stages = {}
    for nd in ('e1', 'e2'):
        per = defaultdict(list)
        for row in rows:
            if row.get(nd):
                per[row[nd]['model']].append(row[nd])
        metrics = ['parse_ok', 'operand_recall'] + (['supported_ok'] if nd == 'e2' else [])
        stages[f'extract_{nd}'] = {m: agg(v, metrics) for m, v in per.items()}
    per = defaultdict(list)
    for row in rows:
        if row.get('r'):
            per[row['r']['model']].append(row['r'])
    stages['reason_r'] = {m: agg(v, ['expr_ok', 'eval_ok', 'gold_match']) for m, v in per.items()}
    cond = defaultdict(list)
    for row in rows:
        if row.get('r') and row['r']['gold_match_cond']:
            cond[row['r']['model']].append(row['r'])
    stages['reason_r_cond_upstream_complete'] = {
        m: agg(v, ['gold_match']) for m, v in cond.items()}
    per = defaultdict(list)
    for row in rows:
        if row.get('v'):
            per[row['v']['model']].append(row['v'])
    stages['verify_v'] = {m: agg(v, ['parse_ok', 'consistency', 'gold_match']) for m, v in per.items()}

    # ---- within-task pairing (e: direct; r: same-upstream; v: same-chain) ----
    pairs = {}
    for nd in ('e1', 'e2'):
        by_task = defaultdict(lambda: defaultdict(list))
        for row in rows:
            if row.get(nd):
                by_task[row['uid']][row[nd]['model']].append(row[nd])
        pp = defaultdict(lambda: dict(tasks=0, cells=0, ok_a=0, ok_b=0,
                                      recall_diffs=[]))
        for uid, models in by_task.items():
            if len(models) < 2:
                continue
            (ma, va), (mb, vb) = sorted(models.items())
            key = f'{ma}_vs_{mb}'
            pp[key]['tasks'] += 1
            pp[key]['cells'] += min(len(va), len(vb))
            pp[key]['ok_a'] += sum(1 for r_ in va if r_['parse_ok'])
            pp[key]['ok_b'] += sum(1 for r_ in vb if r_['parse_ok'])
            ra = next((r_ for r_ in va if r_['operand_recall'] is not None), None)
            rb = next((r_ for r_ in vb if r_['operand_recall'] is not None), None)
            if ra and rb:
                pp[key]['recall_diffs'].append(ra['operand_recall'] - rb['operand_recall'])
        for v in pp.values():
            v['recall_diff_mean'] = round(sum(v['recall_diffs']) / len(v['recall_diffs']), 3) \
                if v['recall_diffs'] else None
            v['n_recall_pairs'] = len(v['recall_diffs'])
        pairs[f'extract_{nd}'] = dict(pp)
    # r pairing within same (m_e1, m_e2)
    by_ctx = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if row.get('r'):
            ctx = (row['X']['e1'], row['X']['e2'])
            by_ctx[ctx][row['uid']][(row['source'], row['scope'], row['cid'])] = row['r']
    rp = defaultdict(lambda: dict(n=0, gm_a=0, gm_b=0, tasks=0))
    for ctx, by_task in by_ctx.items():
        for uid, cells in by_task.items():
            models = defaultdict(list)
            for k, r_ in cells.items():
                models[r_['model']].append(r_)
            if len(models) == 2:
                (ma, va), (mb, vb) = sorted(models.items())
                key = f'{ma}_vs_{mb}__upstream_{ctx[0]}_{ctx[1]}'
                rp[key]['tasks'] += 1
                rp[key]['n'] += min(len(va), len(vb))
                rp[key]['gm_a'] += sum(1 for r_ in va if r_['gold_match'])
                rp[key]['gm_b'] += sum(1 for r_ in vb if r_['gold_match'])
    pairs['reason_r_same_upstream'] = dict(rp)
    # v pairing within same (m_e1, m_e2, m_r)
    by_ctx = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if row.get('v'):
            ctx = (row['X']['e1'], row['X']['e2'], row['X']['r'])
            by_ctx[ctx][row['uid']][(row['source'], row['scope'], row['cid'])] = row['v']
    vp = defaultdict(lambda: dict(n=0, gm_a=0, gm_b=0, tasks=0))
    for ctx, by_task in by_ctx.items():
        for uid, cells in by_task.items():
            models = defaultdict(list)
            for k, r_ in cells.items():
                models[r_['model']].append(r_)
            if len(models) == 2:
                (ma, va), (mb, vb) = sorted(models.items())
                key = f'{ma}_vs_{mb}__chain_{ctx[0]}_{ctx[1]}_{ctx[2]}'
                vp[key]['tasks'] += 1
                vp[key]['n'] += min(len(va), len(vb))
                vp[key]['gm_a'] += sum(1 for r_ in va if r_['gold_match'])
                vp[key]['gm_b'] += sum(1 for r_ in vb if r_['gold_match'])
    pairs['verify_v_same_chain'] = dict(vp)

    # missing-output accounting
    # per-task e2 outcome breakdown (capability vs task-difficulty distinction)
    e2_task = defaultdict(lambda: defaultdict(int))
    for row in rows:
        if row.get('e2'):
            e2_task[row['uid']][row['e2']['status']] += 1
    e2_by_task = {u: dict(v) for u, v in e2_task.items()}
    # mixed tasks (both ok and empty observed): empty-rate by MODEL — the
    # capability cut, separated from always-empty task properties
    mixed = [u for u, v in e2_by_task.items() if v.get('ok') and v.get('empty')]
    # operand-absent tasks: e2 input lacks the target operands; empty extraction
    # is an input-split property and is NOT counted as model failure
    operand_absent = sorted(u for u in e2_by_task
                            if all(not any(fmt in (e2_text.get(u, '') or '').lower()
                                           for fmt in (f'{L:g}', f'{L:.1f}'))
                                   for L in literals(gold.get(u, {}).get('derivation', '')))
                            and gold.get(u, {}).get('derivation'))
    # executed-level only (rows already filtered); injected observations were
    # excluded upstream (fault30 panel corrupts e2 on 08fbbc3f, v on 2f745dd1)
    e2_mixed_by_model = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for row in rows:
        if row.get('e2') and row['uid'] in mixed:
            m = row['e2']['model']
            e2_mixed_by_model[row['uid']][m][0] += int(bool(row['e2']['supported_ok']))
            e2_mixed_by_model[row['uid']][m][1] += 1

    missing = dict(cells=len(rows),
                   execution_accounting={nd: {m: dict(executed=a[0], alias=a[1], injected=a[2])
                                              for m, a in mm.items()}
                                         for nd, mm in acct.items()},
                   refusal_or_empty_by_node=dict(refusal_counts),
                   e2_by_task=e2_by_task,
                   e2_operand_absent_not_model_failure=operand_absent,
                   e2_mixed_tasks_by_model={u: {m: dict(ok=ok, n=n) for m, (ok, n) in v.items()}
                                            for u, v in e2_mixed_by_model.items()},
                   e_missing=sum(1 for row in rows for nd in ('e1', 'e2') if not row.get(nd)),
                   r_missing=sum(1 for row in rows if not row.get('r')),
                   v_missing=sum(1 for row in rows if not row.get('v')),
                   unparseable_e=sum(1 for row in rows for nd in ('e1', 'e2')
                                     if row.get(nd) and not row[nd]['parse_ok']),
                   unparseable_v=sum(1 for row in rows if row.get('v') and not row['v']['parse_ok']))

    out = dict(
        role='RQ1 node-capability heterogeneity — 冻结观测上的节点能力差异描述',
        status='DIAGNOSTIC, descriptive only — no causal attribution, no routing claim',
        claim_guards=[
            'stage-level model differences do NOT establish that node-level '
            'assignment beats query-level routing; that needs same-task, '
            'same-contract direct comparison and a routing baseline',
            'historical static/dynamic trajectories cannot separate DAG '
            'decomposition from recovery gains when configs/prompts/tasks/fault '
            'conditions differ — differences are described, not attributed'],
        inputs={k: dict(version=v, path=str(SRC / k),
                        sha=hashlib.sha256((SRC / k / 'WORKFLOW.jsonl').read_bytes()).hexdigest()[:16])
                for k, v in SOURCES.items()},
        scoring_contract='v2.1 applied uniformly (score_v21 + contract_v2_gold); '
                         'historical per-session gold versions recorded in inputs',
        correctness_bases=dict(
            extract='parse_ok + operand_recall proxy (gold FACTS labels do not exist)',
            reason='expr_ok/eval_ok + gold_match (conflated upstream; conditional '
                   'variant restricted to full operand-recall parents)',
            verify='consistency vs r-chain + gold_match (conditional on upstream valid)'),
        stage_aggregates=stages,
        within_task_pairs=pairs,
        missing_output_accounting=missing,
        evidence_gaps=[
            'no coder-model executions at e1/e2/r stages (config space assigns '
            'coder only to v) — extraction/reasoning comparisons cover medium vs large only',
            'extraction has no gold fact labels; operand_recall is a proxy, not fact correctness',
            'r/v gold_match conflates upstream quality; conditional samples are small '
            '(see within_task_pairs counts)',
            'calibration tasks (4) ran a single fixed config — no model contrast there'],
        hv_reference_point_sensitivity='PLAN ONLY (per review): pre-register a '
                                       'sensitivity grid over HV scales and reference '
                                       'points to be computed on FINAL reconciled '
                                       'curves; no re-selection of primary metric '
                                       'from in-flight results',
        zero_llm_calls=True, zero_gpu=True, test16_used=False,
        production_code_unchanged=True)
    (HERE / 'RQ1_NODE_CAPABILITY.json').write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps(stages, indent=1))
    print(json.dumps(missing))
    print('pairs:', json.dumps({k: {kk: vv for kk, vv in v.items()} if isinstance(v, dict) else v
                                for k, v in pairs.items()}, indent=1)[:1200])


if __name__ == '__main__':
    main()
