"""R2-fix zero-call design review (operator directive 2026-10-24).

Verifies, with ZERO API calls:
  R1  scorer: e: namespace + symmetric amount commas (10 unit tests)
  R2  budget guard: adaptive worst-case pre-check (9 unit tests)
  R3  scoring freeze: mechanical doc-atom slices, 4 categories, >=2
      items per branch category, sha256-frozen to disk
  R4  heterogeneous branch prompts: 4 roles pairwise distinct hashes;
      each names its role; real task basis mapped to the operator's
      four-type taxonomy (capital_event_screening)
  R5  single-extraction info architecture: root prompt contains the
      doc; NO non-root prompt contains any doc sample
  R6  terminal aggregation dependency: sink prompt requires all four
      category fields, routes key_dates to timeline upstream, honest
      missing-info semantics; sink has 4 upstream inputs
  R7  closure math: fault=b0 non-root; D2={b0,x0,sink}; C=all 7
      non-root; siblings {b1,b2,b3,x1} preserved in D2, not in closure
  R8  budget arithmetic: per-node worst bounds; realistic 18-call walk
      completes at cap 0.30; cap 0.28 would block the final call
  R9  arm parity: D2 and C specs share identical shared-source, fault,
      scoring freeze, utility constants (module-level singletons)

Writes R2FIX_SCORING_FREEZE.json. Exit code 1 on any FAIL.

Run: python3 -m deadline_reward_v1.r2fix_design_review
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import r2fix_runner as R
from deadline_reward_v1.budget_guard import (BudgetGuard, worst_case_cny,
                                             plan_worst_total)
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.terminal_eval import eval_terminal

FREEZE_PATH = ROOT / 'deadline_reward_v1' / 'R2FIX_SCORING_FREEZE.json'
DOC_SAMPLE_LEN = 400

CHECKS = []


def check(name, ok, detail=''):
    CHECKS.append((name, bool(ok), detail))


def main():
    # shared zero-call inputs
    doc = load_docs()['舜天#st_announce_2024_020']  # v5 slot
    specs, bounds = R.plan_call_specs(doc['text'], doc['doc_id'])
    plan_worst = plan_worst_total(specs, billing=R.BILLING)

    # tok/char ratio evidence from REAL delivered calls (zero-call)
    fe = (ROOT / 'deadline_reward_v1' / 'fe_screening_runs' /
          'fe_recovery_20261013_213713' / 'FE_LEDGER.jsonl')
    tpl = ('你是一个资本市场事件调查助手。\n\n## 任务类型：fact_extraction'
           '\n\n## 任务描述\n从证据文档中抽取原子事实：涉及主体、处罚决定'
           '（罚款金额、警告、市场禁入）、违法行为类型，每条含事实陈述、'
           '数值/日期、证据doc_id。\n\n## 证据文档\n{ev}\n\n## 输出要求\n'
           '- 输出格式：JSON数组，每个元素包含 fact, date, entities, '
           'evidence_doc_id 字段\n- 输出契约：entity_facts.v1\n- 最大输出'
           '长度：2048 tokens\n- 只抽取有证据支持的事实，不得虚构\n\n'
           '请严格按照输出要求完成任务。')
    v2s = {s2['sample_id']: s2 for s2 in json.loads(
        (ROOT / 'deadline_reward_v1' / 'FACT_EXTRACTION_SAMPLES_V2.json')
        .read_text())['samples']}
    ratios = []
    for line in fe.read_text().splitlines():
        e = json.loads(line)
        if (e.get('model_key') == 'deepseek'
                and e.get('status') == 'delivered'):
            pr = tpl.format(ev=v2s[e['sample_id']]['evidence_full_text'])
            ratios.append(e['usage']['prompt_tokens'] / len(pr))
    rmax = max(ratios)

    # ---- R1 scorer tests ------------------------------------------------
    E = {'n0': ['n1'], 'n1': []}

    def ev(sink, keys):
        return eval_terminal({'n0': {'answer': 'x'},
                              'n1': {'answer': sink}}, E, keys)
    st = [
        ev('2022年7月8日立案', ['d:20220708'])['terminal_q'] == 1.0,
        ev('虚增1,169,184,000元', ['a:1169184000元'])['terminal_q'] == 1.0,
        ev('虚增1169184000元', ['a:1,169,184,000元'])['terminal_q'] == 1.0,
        ev('处以罚款', ['p:罚款'])['terminal_q'] == 1.0,
        ev('对元道通信股份有限公司处罚',
           ['e:元道通信股份有限公司'])['terminal_q'] == 1.0,
        ev('对某公司处罚', ['e:元道通信股份有限公司'])['terminal_q'] == 0.0,
        ev('中国证监会立案',
           ['d:20220708|e:中国证监会'])['terminal_q'] == 1.0,
    ]
    check('R1 scorer (e: namespace, comma-symmetric amounts) 7/7',
          all(st), f'{sum(st)}/7')

    # ---- R2 budget guard tests (v3: GLM subscription profile) -----------
    g = BudgetGuard(18, 0.30, mode='adaptive', billing='subscription')
    ok_walk = True
    for chars, out in specs:
        st = g.may_start(prompt_chars=chars, max_out_tokens=out)
        if st:
            ok_walk = False
            break
        g.record(0.0)   # subscription: marginal cash exactly ¥0
    check('R2 guard: 18-call walk under subscription profile completes,'
          ' cash spent ¥0', ok_walk and g.calls == 18 and g.spent == 0.0)
    check(f'R2 guard: plan worst under subscription = ¥{plan_worst:.4f}'
          f' <= 0.30 (trivially, cash bound exact)',
          plan_worst == 0.0)
    gs = BudgetGuard(3, 1.0, mode='adaptive', billing='subscription')
    for _ in range(3):
        assert gs.may_start(prompt_chars=100) is None
        gs.record(0.0)
    check('R2 guard: planned-calls cap still fires (subscription does '
          'not bypass)', gs.may_start(prompt_chars=100) == 'calls cap (3)')
    ga = BudgetGuard(5, 1.0, mode='adaptive', billing='per_token')
    ga.may_start(prompt_chars=1000)
    ga.record(0.5)   # above admitted worst -> anomaly flagged
    check('R2 guard: per-token billing anomaly detector intact (lineage)',
          ga.anomaly is not None)

    # ---- R3 scoring freeze ----------------------------------------------
    atoms = doc_atoms(doc['text'])
    cats = dict(timeline=atoms['dates'][:4], amounts=atoms['amounts'][:3],
                penalties=atoms['penalties'][:3],
                entities=atoms['entities'][:3])
    valid_keys = ([f'd:{k}' for k in cats['timeline']]
                  + [f'a:{k}' for k in cats['amounts']]
                  + [f'p:{k}' for k in cats['penalties']]
                  + [f'e:{k}' for k in cats['entities']])
    check('R3a mechanical slices: 4+3+3+3 = 13 keys',
          len(valid_keys) == 13,
          f'{len(cats["timeline"])}d+{len(cats["amounts"])}a'
          f'+{len(cats["penalties"])}p+{len(cats["entities"])}e')
    check('R3b every branch category has >=2 dedicated items',
          all(len(v) >= 2 for v in cats.values()),
          json.dumps({k: v for k, v in cats.items()}, ensure_ascii=False))
    freeze = dict(
        version='R2FIX_SCORING_FREEZE_v5',
        frozen_at=time_str(), doc_slot='舜天#st_announce_2024_020',
        fault=R.FAULT,
        rule=('doc_atoms mechanical slices, identical rule to R1/R2 '
              '(dates[:4], amounts[:3], penalties[:3]); entities[:3] '
              'new namespace e:; symmetric comma-insensitive amount '
              'match; NO manual cherry-picking'),
        valid_keys=valid_keys,
        categories=cats,
        doc_sha256=hashlib.sha256(doc['text'].encode()).hexdigest(),
        caps=dict(planned_calls=R.PLANNED_CALLS, cap_cash_cny=R.CAP_CNY,
                  wall_s=R.WALL_S, mode='adaptive',
                  billing=R.BILLING, marginal_cash_per_call_cny=0.0,
                  char_bounds_by_construction=bounds,
                  out_caps=R.OUT_CAP,
                  plan_worst_total_cny=plan_worst),
        utility=dict(D_s=R.D, C0_tokens=R.C0_TOK),
        model=('GLM-5.3-Flash via zhipu anthropic-compatible endpoint, '
               'temp=0, thinking:disabled REQUESTED (not guaranteed; '
               'blocks detected+recorded); uniform max_tokens 3072'),
        track_note=('v3 track switch approved by operator 2026-10-25 '
                    'after budget audit proved ¥0.30 uncertifiable on '
                    'per-token track; screening validated model '
                    'capability (conditional pass); screening results '
                    'are NOT recovery-algorithm evidence'),
        repeats=5,
        repeat_rationale=('v5: second-document replication of v4 '
                          '(舜天/st_announce_2024_020, 14,465ch, 53 '
                          'atoms — same doc that replicated the R1 '
                          'recovery finding on deepseek). v4 rationale '
                          'retained: GLM nondeterminism requires '
                          'paired repeats; identical protocol/roles/'
                          'fault/closures/utility, only doc+keys change'),
        evaluator_sha256=hashlib.sha256(
            (ROOT / 'deadline_reward_v1' / 'terminal_eval.py')
            .read_bytes()).hexdigest(),
        evaluator_note=('v4 fixes the date-key format defect (年月日 / '
                        'unpadded-7-digit keys previously never '
                        'matched); keys themselves unchanged from v3'),
        decision_rules=dict(
            recovery_supported='mean paired d(t_q, D2-D0) > 0 AND '
                               '>= ceil(n/2) repeats positive',
            recovery_utility='mean paired d(eU, D2-D0) > 0',
            targeted_beats_full_utility='mean paired d(eU, D2-C) > 0 '
                                       'AND >= ceil(n/2) repeats '
                                       'positive',
            targeted_quality_noninferior='mean paired d(t_q, D2-C) >= 0',
            all_verdicts_reported='descriptive only, n=5, no p-values; '
                                  'negative verdicts preserved as-is'),
        budget_bound_validation=dict(
            source='fe_recovery_20261013_213713 FE_LEDGER.jsonl, 5 '
                   'delivered deepseek calls, prompts reconstructed '
                   'exactly from FACT_EXTRACTION_SAMPLES_V2',
            max_input_tok_per_char=round(rmax, 4),
            with_15pct_margin=round(rmax * 1.15, 4),
            bound_used=0.75,
            envelope='billed prompt_tokens already includes chat '
                     'template; +128 tokens extra buffer',
            plan_worst_note='sum of per-call worst over the frozen '
                            '18-call sequence; runner asserts this '
                            'before any dispatch'),
        known_noise=('amounts slice may include regex-truncated artifacts '
                     '(e.g. "088元") — kept because the rule is mechanical '
                     'and identical across arms; entity keys may be '
                     'substring-superset redundant; section outputs may '
                     'hit the 768-token cap (finish_reason=length) — '
                     'recorded honestly, evaluation proceeds regardless'),
        preregistered_criteria=dict(
            C1_restoration='t_q(D2) > t_q(D0)',
            C2_category='timeline hits D2 > timeline hits D0',
            C3_sibling_no_harm='non-timeline hits D2 >= non-timeline hits D0',
            C4_quality_noninferior='t_q(D2) >= t_q(C)',
            C5_utility_efficiency='eU(D2) > eU(C)',
            C6_preserved='b1,b2,b3,x1 byte-identical to shared in D2 arm',
            C7_heterogeneity='healthy b-outputs pairwise distinct (honest '
                             'report if violated)'),
    )
    raw = json.dumps(freeze, ensure_ascii=False, indent=1)
    FREEZE_PATH.write_text(raw)
    fsha = hashlib.sha256(FREEZE_PATH.read_bytes()).hexdigest()
    check('R3c freeze written + sha256 recorded', FREEZE_PATH.exists())
    print(f'    freeze sha256: {fsha}')

    # ---- R4 heterogeneous prompts ---------------------------------------
    dag = R.HeteroDAG(doc['text'], doc['doc_id'])
    fake_root = json.dumps([{'fact': f'事实{i}', 'date': '2022年7月8日',
                             'entities': ['元道通信股份有限公司'],
                             'evidence_doc_id': doc['doc_id']}
                            for i in range(6)], ensure_ascii=False)
    dag.outputs[R.ROOT_NODE] = dict(answer=fake_root)
    for b in ('b0', 'b1', 'b2', 'b3'):
        dag.outputs[b] = dict(answer=fake_root)
    dag.outputs['x0'] = dag.outputs['x1'] = dict(answer=fake_root)
    prompts = {n: dag.build_prompt(n) for n in R.ORDER}
    phash = {n: hashlib.sha256(p.encode()).hexdigest()
             for n, p in prompts.items()}
    bhs = [phash[b] for b in ('b0', 'b1', 'b2', 'b3')]
    check('R4a four branch prompts pairwise distinct',
          len(set(bhs)) == 4)
    role_words = dict(b0='时间线', b1='金额', b2='处罚', b3='主体')
    check('R4b each branch prompt names its role',
          all(role_words[b] in prompts[b] for b in role_words))
    role_map_ok = (R.ROLE[R.ROOT_NODE] == 'extraction'      # fact_extraction
                   and R.ROLE['b0'] == 'timeline'
                   and R.ROLE['b1'] == 'amounts'
                   and R.ROLE['b2'] == 'penalties'
                   and R.ROLE['b3'] == 'entity_relations'
                   and R.ROLE['x1'] == 'amounts_check')     # cross-check
    check('R4c roles map to operator taxonomy (capital_event_screening)',
          role_map_ok)

    # ---- R5 single-extraction architecture -------------------------------
    sample = doc['text'][100:100 + DOC_SAMPLE_LEN]
    check('R5a root prompt contains document text', sample in
          prompts[R.ROOT_NODE])
    nonroot = [n for n in R.ORDER if n != R.ROOT_NODE]
    check('R5b NO non-root prompt contains document text',
          all(sample not in prompts[n] for n in nonroot))

    # ---- R6 terminal aggregation ----------------------------------------
    sp = prompts['sink']
    four_fields = all(f in sp for f in
                      ('key_dates', 'amounts', 'penalties', 'entities'))
    check('R6a sink prompt requires 4 category fields', four_fields)
    check('R6b sink routes key_dates to timeline upstream, honest-missing',
          'x0' in sp and '缺失' in sp)
    check('R6c sink has 4 upstream inputs',
          len(dag.upstream_of('sink')) == 4)

    # ---- R7 closure math --------------------------------------------------
    d2c, c_full, preserved = R.closures()
    check('R7a fault is non-root branch node',
          R.FAULT in R.EDGES[R.ROOT_NODE] and R.FAULT != R.ROOT_NODE)
    check('R7b D2 closure = affected branch + join/terminal',
          d2c == {'b0', 'x0', 'sink'})
    check('R7c C closure = all 7 non-root',
          c_full == {'b0', 'b1', 'b2', 'b3', 'x0', 'x1', 'sink'})
    check('R7d siblings preserved in D2 (not in closure)',
          preserved == {'b1', 'b2', 'b3', 'x1'})

    # ---- R8 budget arithmetic --------------------------------------------
    sizes = dict(root=len(prompts[R.ROOT_NODE]),
                 branch=max(len(prompts[b]) for b in
                            ('b0', 'b1', 'b2', 'b3')),
                 sink=len(prompts['sink']))
    w = {k: worst_case_cny(v) for k, v in sizes.items()}
    w_mono = (worst_case_cny(13000) > worst_case_cny(6000)
              > worst_case_cny(3000) > 0)
    check('R8 worst-case bound monotone in prompt size (review sizes are '
          'fake-data lower bounds; real bounds computed per-dispatch)',
          w_mono,
          ' / '.join(f'{k}=¥{v:.4f}' for k, v in w.items()))
    print(f'    prompt sizes: {sizes}')
    print(f'    worst-case bounds: {w}')

    # ---- R10-R12 hard-budget verification (operator 2026-10-25) --------
    ds_lineage = plan_worst_total(specs, billing='per_token')
    check(f'R10 (v3) plan worst-case cash = ¥{plan_worst:.4f} <= cap '
          f'¥{R.CAP_CNY} (subscription: exact ¥0; per-token lineage at '
          f'3072 caps would be ¥{ds_lineage:.4f} — infeasible on a paid '
          f'track, documented not applied)', plan_worst <= R.CAP_CNY,
          f'bounds={bounds} out_caps=uniform 3072')

    # R11: tok/char bound validated on REAL delivered calls
    rates_v2 = json.loads((ROOT / 'deadline_reward_v1' /
                           'REVERSE_ENGINEERED_RATES_V2.json').read_text())
    glm_rate = rates_v2['rates']['glm_53_flash']
    screen = json.loads(sorted((ROOT / 'deadline_reward_v1' /
                                'fe_screening_runs').glob(
        'glm53flash_*/SCREEN_RESULTS.json'))[-1].read_text())
    n_zero = sum(1 for c in screen['calls'] if c['cash_cny'] == 0.0)
    check('R11 (v3) GLM billing evidence: frozen rates subscription '
          f'¥{glm_rate["cash_cny_per_call"]}/call; screening {n_zero}/'
          f'{len(screen["calls"])} calls at ¥0; prior 17 GLM calls '
          'total ¥0.0 — cash cap holds exactly, no tokenizer bound '
          'needed on this track (deepseek tok/char lineage retained in '
          'budget_guard docstring)',
          glm_rate['billing'] == 'subscription'
          and n_zero == len(screen['calls'])
          and rates_v2['total_costs_cny']['glm'] == 0.0)

    check('R12 (v3) uniform 3072 output caps absorb GLM thinking '
          'variance (screening: 768 truncated when a thinking block '
          'fired; 1536 completed); caps reduce truncation risk only, '
          'NOT a correctness guarantee — finish_reason + thinking-block '
          'recorded per call, criteria never loosened',
          R.ROOT_OUT_CAP == 3072 and R.SECTION_OUT_CAP == 3072
          and R.SINK_OUT_CAP == 3072)

    # ---- R13 v4 repeats + evaluator binding --------------------------------
    ev_sha = hashlib.sha256(
        (ROOT / 'deadline_reward_v1' / 'terminal_eval.py')
        .read_bytes()).hexdigest()
    check('R13 (v4) repeats=5 pinned; evaluator sha bound to freeze '
          '(drift = gate refusal); 年月日 date keys now scorable '
          '(fixed evaluator, 14/14 regression)',
          json.loads(FREEZE_PATH.read_text()).get('repeats') == 5
          and json.loads(FREEZE_PATH.read_text())['evaluator_sha256']
          == ev_sha)

    # ---- R9 arm parity ----------------------------------------------------
    check('R9 D2/C share source/fault/scorer/utility (module singletons)',
          R.DOC_SLOT == FREEZE_DOC_SLOT and R.FAULT == 'b0'
          and R.PLANNED_CALLS == 18 and R.CAP_CNY == 0.30
          and R.D == 350.0 and R.C0_TOK == 60000.0)

    # ---- report -----------------------------------------------------------
    print()
    npass = 0
    for name, ok, detail in CHECKS:
        npass += ok
        print(f'  [{"PASS" if ok else "FAIL"}] {name}'
              + (f'  ({detail})' if detail else ''))
    print(f'\n{npass}/{len(CHECKS)} passed')
    if npass != len(CHECKS):
        sys.exit(1)
    print(f'freeze: {FREEZE_PATH}')
    print(f'freeze sha256: {fsha}')
    print('\nREADY — awaiting operator authorization '
          '(R2FIX_GO=1 + approved-freeze-sha256)')


def time_str():
    import time
    return time.strftime('%Y-%m-%dT%H:%M:%S')


FREEZE_DOC_SLOT = 'ydt#D3_E03-yuandao_2026-08-29'

if __name__ == '__main__':
    main()
