"""M8 P1 DAG Optimizer validation tests (ZERO model calls).

Run: python3 m8_p1_optimizer_tests.py  (exit 0 iff all pass)

T1  Reference DAG preserved — optimizer must make 0 changes on the
    operator-approved E04 reference structure (freeze candidate).
T2  Duplicate merge — same kind + same docs + high task similarity merges
    (mixed CJK/English reordering case from LLM generation practice).
T3  False edge removal — extracts→extracts edge with no doc flow removed.
T4  Orphan removal — no-consumer non-terminal node removed.
T5  Near-miss veto — digit-bearing token mismatch (2023 vs 2024, doc2 vs
    doc5) must NEVER merge even when all other characters are identical.
T6  Idempotence — a second optimize pass over already-optimized output
    makes 0 further changes.
T7  Merge redirect — merged node's edges redirect correctly with no
    parallel-duplicate edges and no self-loops.
"""
import copy
import json
import sys

from dag_optimizer import (DAG, DAGNode, optimize_dag, parse_llm_dag,
                           _task_similarity)

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))


def load_reference():
    with open('E04_reference_dag.json', encoding='utf-8') as f:
        return json.load(f)


def t1_reference_preserved():
    print('T1 Reference DAG preserved (0 changes)')
    ref = parse_llm_dag(load_reference())
    opt, changes = optimize_dag(copy.deepcopy(ref), ['doc1', 'doc2', 'doc3'])
    check('no changes on reference DAG', changes == [], str(changes))
    check('stats unchanged', opt.stats() == ref.stats(),
          f"{opt.stats()} vs {ref.stats()}")
    exp = load_reference()['expected_stats']
    check('matches frozen expected_stats', opt.stats() == exp, str(opt.stats()))


def t2_duplicate_merge():
    print('T2 Duplicate merge (mixed CJK/English reordering)')
    dag = DAG(
        nodes=[
            DAGNode('x1', '提取财务数据 from doc2', 'extracts', ('doc2',)),
            DAGNode('x2', '提取doc2财务数据', 'extracts', ('doc2',)),
            DAGNode('r', '生成终端报告', 'report', ()),
        ],
        edges=[('x1', 'r'), ('x2', 'r')])
    opt, changes = optimize_dag(dag, ['doc2'])
    check('one MERGE_NODES fired',
          len(changes) == 1 and changes[0]['action'] == 'MERGE_NODES',
          str(changes))
    check('2 extract nodes -> 1', len(opt.nodes) == 2 and
          {n.node_id for n in opt.nodes} == {'x1', 'r'})
    check('edges deduped, no parallel duplicates',
          sorted(opt.edges) == [('x1', 'r')], str(opt.edges))


def t3_false_edge_removed():
    print('T3 False edge removal')
    dag = DAG(
        nodes=[
            DAGNode('e1', '提取doc1公告信息', 'extracts', ('doc1',)),
            DAGNode('e2', '提取doc2处罚条款', 'extracts', ('doc2',)),
            DAGNode('r', '生成终端报告', 'report', ()),
        ],
        edges=[('e1', 'e2'), ('e2', 'r'), ('e1', 'r')])
    opt, changes = optimize_dag(dag, ['doc1', 'doc2'])
    check('REMOVE_EDGE e1->e2 fired',
          any(c['action'] == 'REMOVE_EDGE' and 'e1' in c['detail']
              for c in changes), str(changes))
    check('depth 3 -> 2', dag.depth() == 3 and opt.depth() == 2,
          f"{dag.depth()}->{opt.depth()}")
    check('all 3 nodes retained (both still feed report)',
          len(opt.nodes) == 3)


def t4_orphan_removed():
    print('T4 Orphan removal')
    dag = DAG(
        nodes=[
            DAGNode('o', '提取doc5无关数据', 'extracts', ('doc5',)),
            DAGNode('e', '提取doc2财务数据', 'extracts', ('doc2',)),
            DAGNode('r', '生成终端报告', 'report', ()),
        ],
        edges=[('e', 'r')])
    opt, changes = optimize_dag(dag, ['doc2', 'doc5'])
    check('REMOVE_NODE o fired',
          any(c['action'] == 'REMOVE_NODE' and 'o' in c['detail']
              for c in changes), str(changes))
    check('3 -> 2 nodes', len(opt.nodes) == 2 and
          {n.node_id for n in opt.nodes} == {'e', 'r'})


def t5_near_miss_veto():
    print('T5 Near-miss veto (quantity/time-range expressions)')
    sim_year = _task_similarity('提取2023年财务数据', '提取2024年财务数据')
    sim_doc = _task_similarity('提取doc2财务数据', '提取doc5财务数据')
    sim_cjk_year = _task_similarity('提取近三年财务数据', '提取近五年财务数据')
    sim_ordinal = _task_similarity('提取第四次风险提示内容', '提取首次风险提示内容')
    check('year mismatch scores 0', sim_year == 0.0, f'{sim_year:.3f}')
    check('doc-id mismatch scores 0', sim_doc == 0.0, f'{sim_doc:.3f}')
    check('CJK-numeral range mismatch scores 0 (近三/近五)',
          sim_cjk_year == 0.0, f'{sim_cjk_year:.3f}')
    check('ordinal mismatch scores 0 (第四次/首次)',
          sim_ordinal == 0.0, f'{sim_ordinal:.3f}')
    check('same CJK numeral range passes veto gate (not zeroed)',
          0.5 < _task_similarity('提取近三年财务数据', '提取近三年财务指标') <= 0.7,
          'gate passes; 数据/指标 stay unmerged by design (conservative)')
    check('digit-bearing match still merges duplicate pair',
          _task_similarity('提取财务数据 from doc2', '提取doc2财务数据') > 0.7)
    dag = DAG(
        nodes=[
            DAGNode('y23', '提取2023年财务数据', 'extracts', ('doc2',)),
            DAGNode('y24', '提取2024年财务数据', 'extracts', ('doc2',)),
            DAGNode('r', '生成终端报告', 'report', ()),
        ],
        edges=[('y23', 'r'), ('y24', 'r')])
    opt, changes = optimize_dag(dag, ['doc2'])
    check('no merge on year near-miss',
          not any(c['action'] == 'MERGE_NODES' for c in changes), str(changes))
    check('both year nodes survive', len(opt.nodes) == 3)


def t6_idempotence():
    print('T6 Idempotence')
    ref = parse_llm_dag(load_reference())
    messy = DAG(
        nodes=[
            DAGNode('a1', '提取财务数据 from doc2', 'extracts', ('doc2',)),
            DAGNode('a2', '提取doc2财务数据', 'extracts', ('doc2',)),
            DAGNode('c', '构建doc1与doc2监管时间线', 'timeline', ('doc1', 'doc2')),
            DAGNode('b', '计算财务异常指标', 'reasoning', ()),
            DAGNode('e', '交叉核验一致性', 'verification', ()),
            DAGNode('f', '生成终端报告', 'report', ()),
        ],
        edges=[('a1', 'a2'), ('a1', 'b'), ('a2', 'b'), ('a1', 'e'),
               ('c', 'e'), ('b', 'e'), ('e', 'f')])
    opt1, ch1 = optimize_dag(messy, ['doc1', 'doc2'])
    opt2, ch2 = optimize_dag(copy.deepcopy(opt1), ['doc1', 'doc2'])
    # The duplicate merge subsumes the false a1->a2 edge (redirect yields a
    # self-loop that is dropped), so one MERGE_NODES is the full fix.
    check('first pass fires the merge',
          any(c['action'] == 'MERGE_NODES' for c in ch1), str(ch1))
    check('survivor feeds b (chain intact)',
          ('a1', 'b') in opt1.edges, str(opt1.edges))
    check('second pass is a no-op', ch2 == [], str(ch2))
    check('fixed point stable', opt2.to_dict() == opt1.to_dict())


def t7_merge_redirect():
    print('T7 Merge redirect edge cases')
    # n2 sits mid-chain: p -> n2 -> c ; merging n2 into n1 must redirect both
    # sides without creating self-loops or parallel edges, keeping the
    # p -> n1 -> c -> r path connected.
    dag = DAG(
        nodes=[
            DAGNode('p', '提取doc2原始公告', 'extracts', ('doc2',)),
            DAGNode('n1', '提取doc2财务数据', 'extracts', ('doc2',)),
            DAGNode('n2', '提取财务数据 from doc2', 'extracts', ('doc2',)),
            DAGNode('c', '计算财务异常指标', 'reasoning', ()),
            DAGNode('r', '生成终端报告', 'report', ()),
        ],
        edges=[('p', 'n2'), ('n2', 'c'), ('p', 'n1'), ('n1', 'c'), ('c', 'r')])
    opt, changes = optimize_dag(dag, ['doc2'])
    check('merge fired', any(c['action'] == 'MERGE_NODES' for c in changes),
          str(changes))
    check('no self-loops', all(f != t for f, t in opt.edges), str(opt.edges))
    check('no parallel duplicates',
          len(opt.edges) == len(set(opt.edges)), str(opt.edges))
    check('path p -> n1 -> c -> r connected',
          sorted(opt.edges) == [('c', 'r'), ('n1', 'c'), ('p', 'n1')],
          str(opt.edges))


def main():
    for t in (t1_reference_preserved, t2_duplicate_merge, t3_false_edge_removed,
              t4_orphan_removed, t5_near_miss_veto, t6_idempotence,
              t7_merge_redirect):
        t()
    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{n_pass}/{len(RESULTS)} checks passed")
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
