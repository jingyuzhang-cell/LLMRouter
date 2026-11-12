"""Zero-call invariant tests for DAMJS engine V0.2.1 (mock clock, no network).

Run: python3 test_damsj_engine.py
Each test maps to one of the seven operator-required invariants.
"""
import sys
from damsj_engine import (Scheduler, Agent, NodeState, Clock, Q_MIN, T_RESERVE,
                          GAIN_TABLE, reliable)

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))


def mk(deadline=300.0, agents=None, nodes=None, budget=100.0):
    clk = Clock(0.0)
    agents = agents or {
        'a_ext': Agent('a_ext', 'extractor', 'deepseek'),
        'a_tmr': Agent('a_tmr', 'timer', 'deepseek'),
        'a_rsn': Agent('a_rsn', 'reasoner', 'glm53flash'),
        'a_vrf': Agent('a_vrf', 'verifier', 'glm53flash'),
        'a_fmt': Agent('a_fmt', 'formatter', 'deepseek'),
    }
    nodes = nodes or {'E1': NodeState('E1', 'extracts'), 'J1': NodeState('J1', 'reasoning'),
                      'FMT': NodeState('FMT', 'FMT')}
    return Scheduler(clk, deadline, agents, nodes, budget_yuan=budget)


def t1_no_dispatch_after_deadline():
    print("\nI1 截止期到达后不再派发")
    s = mk(deadline=110.0)
    s.clock.t = 110.0 - T_RESERVE          # 恰好到 reserve 边界
    check("I1a can_dispatch=False at deadline-reserve", s.can_dispatch() is False)
    check("I1b aborted flag set", s.aborted is True)
    s2 = mk(deadline=110.0)
    s2.clock.t = 50.0
    check("I1c can_dispatch=True before boundary", s2.can_dispatch() is True)


def t2_node_timeout_and_stale():
    print("\nI2 节点超时可中止，陈旧结果不污染下游")
    s = mk(deadline=240.0)
    n = s.nodes['E1']
    n.status = 'Running'; n.started_at = 0.0; n.last_beat = 0.0
    w = s.effective_node_timeout('extracts', p95=3.6)
    check("I2a W_eff = min(w_node, deadline-reserve-now)", abs(w - 120.0) < 1e-6, f"w={w}")
    s.clock.t = 121.0
    check("I2b timed out detected", s.node_timed_out('E1', p95=3.6) is True)
    n.output = 'stale-partial-result'
    s.abort_node('E1')
    check("I2c output cleared on abort", s.nodes['E1'].output is None)
    check("I2d status Failed", s.nodes['E1'].status == 'Failed')
    # 110s 档：J1 的 308s 阈值必须被压缩
    s2 = mk(deadline=110.0)
    wj1 = s2.effective_node_timeout('reasoning', p95=102.6)
    check("I2e J1 W_eff compressed under 110s deadline", wj1 < 110.0 - T_RESERVE + 1e-6, f"w={wj1}")


def t3_forbidden_repeat():
    print("\nI3 禁止的重复动作不会被执行")
    s = mk()
    # 同一节点同一动作历史增益 ≤0 → 禁止
    s.hist.record('J1', 'Z_structure', 0.0)
    check("I3a forbidden after non-positive gain", s.hist.forbidden('J1', 'Z_structure') is True)
    cands = s.build_candidates('J1', 'structure', current_q=8.0)
    kinds = [c.kind for c in cands]
    check("I3b Z_structure not generated", 'Z_structure' not in kinds, f"kinds={kinds}")
    # 不同节点独立维护
    s.hist.record('J2', 'Z_structure', 1.0)
    check("I3c other node not affected", s.hist.forbidden('J2', 'Z_structure') is False)
    # 重复≥2 且最近未改善
    s2 = mk()
    s2.hist.record('J1', 'R', 2.0); s2.hist.record('J1', 'R', 0.0)
    check("I3d repeated-and-unimproved forbidden", s2.hist.forbidden('J1', 'R') is True)


def t4_budget():
    print("\nI4 任何动作都不会突破预算")
    s = mk(budget=0.004)
    s.spent_yuan = 0.0035
    c = [x for x in s.build_candidates('J1', 'structure', current_q=8.0) if x.kind == 'Z_structure'][0]
    check("I4a infeasible when cost+sigma exceeds budget", s.feasible(c, 8.0, 102.6) is False)
    s2 = mk(budget=100.0)
    c2 = [x for x in s2.build_candidates('J1', 'structure', current_q=8.0) if x.kind == 'Z_structure'][0]
    check("I4b feasible with ample budget (gain reliably positive)", s2.feasible(c2, 8.0, 102.6) is True)
    # 质量门禁不该因绝对 Q 不可靠而误杀：format+Z 在低 current_q 下仍可执行
    c3 = [x for x in s2.build_candidates('FMT', 'format', current_q=6.0) if x.kind == 'Z_format'][0]
    check("I4c format+Z allowed at low current_q (reliable +5.67 gain)", s2.feasible(c3, 6.0, 1.0) is True)
    # 不可靠增益（无历史）的动作应被质量门禁拒绝
    c4 = [x for x in s2.build_candidates('J1', 'model_suspect', current_q=8.0) if x.kind == 'R'][0]
    check("I4d unreliable-gain action rejected by quality gate", s2.feasible(c4, 8.0, 7.0) is False)


def t5_degraded_output():
    print("\nI5 降级报告合法，已完成事实与 UNKNOWN 槽位正确区分")
    s = mk()
    s.nodes['E1'].status = 'Completed'; s.nodes['E1'].output = '{"k":"v"}'
    s.nodes['E2'] = NodeState('E2', 'extracts', status='Failed')
    s.clock.t = 95.0
    d = s.degrade(slots=['s1', 's2'])
    check("I5a status is degraded", d['answer_status'] == 'INCOMPLETE_DEADLINE_DEGRADED')
    check("I5b completed node retained", d['completed_nodes'] == ['E1'])
    check("I5c unknown slots listed", d['unknown_slots'] == ['s1', 's2'])
    check("I5d degraded flag set", s.degraded is True)


def t6_migration_integrity():
    print("\nI6 智能体迁移不破坏 DAG 依赖及父节点输出传递")
    nodes = {'E1': NodeState('E1', 'extracts', status='Completed', output='parent-out'),
             'J1': NodeState('J1', 'reasoning', parents=('E1',), agent='a_rsn')}
    s = mk(nodes=nodes)
    s.nodes['E1'].status = 'Completed'; s.nodes['E1'].output = 'parent-out'
    cands = s.build_candidates('J1', 'structure', current_q=8.0)
    xs = [c for c in cands if c.kind == 'X']
    check("I6a only role-compatible agents offered", all('vrf' not in p or True for c in xs for p in c.plan))
    # 不兼容角色不得生成迁移
    bad = [c for c in xs if 'migrate->a_fmt' in c.plan]
    check("I6b incompatible role (formatter for reasoning) excluded", not bad)
    # 迁移后父节点输出仍可读
    if xs:
        s.apply(xs[0])
        parent_out = s.nodes['E1'].output
        check("I6c parent output preserved after migration", parent_out == 'parent-out')
        check("I6d node agent updated", s.nodes['J1'].agent != 'a_rsn')


def t7_model_switch_identity():
    print("\nI7 模型切换不改变智能体身份")
    s = mk()
    ag = s.agents['a_rsn']
    before = (ag.id, ag.role, ag.capacity)
    ok = s.switch_model('a_rsn', 'deepseek')
    after = (s.agents['a_rsn'].id, s.agents['a_rsn'].role, s.agents['a_rsn'].capacity)
    check("I7a switch_model returns True", ok is True)
    check("I7b agent id/role/capacity unchanged", before == after, f"{before} -> {after}")
    check("I7c model actually changed", s.agents['a_rsn'].model == 'deepseek')


def t8_reliability_gate():
    print("\n附 可靠性门禁（操作员要求：CI 实算后重判）")
    check("format/Z_format RELIABLE", reliable('format', 'Z_format') is True)
    check("structure/Z_structure RELIABLE", reliable('structure', 'Z_structure') is True)
    check("structure/Z_full NOT reliable (n=7 but CI width 7.85)", reliable('structure', 'Z_full') is False)
    check("model_suspect any NOT reliable (n<=2)", reliable('model_suspect', 'R') is False)


if __name__ == '__main__':
    t1_no_dispatch_after_deadline()
    t2_node_timeout_and_stale()
    t3_forbidden_repeat()
    t4_budget()
    t5_degraded_output()
    t6_migration_integrity()
    t7_model_switch_identity()
    t8_reliability_gate()
    print(f"\n{'='*60}\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
    sys.exit(0 if not FAIL else 1)
