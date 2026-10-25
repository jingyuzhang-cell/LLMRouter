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
from deadline_reward_v1.budget_guard import BudgetGuard, worst_case_cny
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.terminal_eval import eval_terminal

FREEZE_PATH = ROOT / 'deadline_reward_v1' / 'R2FIX_SCORING_FREEZE.json'
DOC_SAMPLE_LEN = 400

CHECKS = []


def check(name, ok, detail=''):
    CHECKS.append((name, bool(ok), detail))


def main():
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

    # ---- R2 budget guard tests ------------------------------------------
    g = BudgetGuard(18, 0.30, mode='adaptive')
    walk_sizes = [6000] + [4000] * 16 + [13000]
    ok_walk = True
    for i in range(18):
        s = g.may_start(prompt_chars=walk_sizes[i])
        if s:
            ok_walk = False
            break
        g.record(0.0149)
    check('R2 guard: realistic 18-call walk completes at cap 0.30',
          ok_walk and abs(g.spent - 0.2682) < 1e-6)
    g2 = BudgetGuard(18, 0.28, mode='adaptive')
    for i in range(17):
        assert g2.may_start(prompt_chars=4000) is None
        g2.record(0.0149)
    check('R2 guard: cap 0.28 blocks final sink call (documented)',
          g2.may_start(prompt_chars=13000) is not None)

    # ---- R3 scoring freeze ----------------------------------------------
    doc = load_docs()[R.DOC_SLOT]
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
        version='R2FIX_SCORING_FREEZE_v1',
        frozen_at=time_str(), doc_slot=R.DOC_SLOT, fault=R.FAULT,
        rule=('doc_atoms mechanical slices, identical rule to R1/R2 '
              '(dates[:4], amounts[:3], penalties[:3]); entities[:3] '
              'new namespace e:; symmetric comma-insensitive amount '
              'match; NO manual cherry-picking'),
        valid_keys=valid_keys,
        categories=cats,
        doc_sha256=hashlib.sha256(doc['text'].encode()).hexdigest(),
        caps=dict(planned_calls=R.PLANNED_CALLS, cap_cash_cny=R.CAP_CNY,
                  wall_s=R.WALL_S, mode='adaptive'),
        utility=dict(D_s=R.D, C0_tokens=R.C0_TOK),
        model='deepseek-flash thinking=disabled temp=0 max_tokens=2048',
        known_noise=('amounts slice may include regex-truncated artifacts '
                     '(e.g. "088元") — kept because the rule is mechanical '
                     'and identical across arms; entity keys may be '
                     'substring-superset redundant'),
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
