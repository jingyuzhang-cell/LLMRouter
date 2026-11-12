"""DAMJS engine (V0.2.1) — zero-call scheduler core.

Pure decision logic + watchdog + agent layer. No network calls, no file mutation
of frozen assets. Designed to be driven by a mock clock in tests and by the
executor wrapper in real runs.

Invariants encoded here (tested in test_damsj_engine.py):
  I1 no dispatch after deadline
  I2 node timeout aborts and stale results do not pollute downstream
  I3 forbidden repeat actions are never emitted
  I4 no action exceeds remaining budget
  I5 degraded output separates completed facts from UNKNOWN slots
  I6 migration preserves DAG deps and parent outputs
  I7 model switch does not change agent identity
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import statistics as _st

# ────────────────────────────── 常量（预注册） ──────────────────────────────
Q_MIN = 12                 # 终端 TP 门限
T_RESERVE = 15.0           # 降级输出预留秒数
W_MIN = 120.0              # 节点看门狗下限
RELIABLE_MIN_N = 5
RELIABLE_MAX_CI_WIDTH = 3.0
U_W = dict(q=1.0, c=0.3, l=0.5)   # 冻结效用权重

ROLL_KINDS = {
    'extracts':   {'extractor', 'timer'},
    'timeline':   {'extractor', 'timer'},
    'reasoning':  {'reasoner'},
    'verification': {'verifier'},
    'report':     {'reporter'},
    'FMT':        {'formatter'},
}

# 历史 (family, action_type) 增益统计 —— 来自运行时校准表，非测试 Gold
GAIN_TABLE = {
    ('format', 'Z_format'):       dict(mu=+5.67, sd=0.50, n=9,  ci=(-0.0, 0.0)),
    ('structure', 'Z_structure'): dict(mu=+1.29, sd=0.95, n=7,  ci=(0.0, 0.0)),
    ('none', 'NONE'):             dict(mu=+0.18, sd=0.73, n=17, ci=(0.0, 0.0)),
    ('structure', 'Z_full'):      dict(mu=-1.86, sd=5.81, n=7,  ci=(0.0, 0.0)),
}
CI_WIDTH = {('format', 'Z_format'): 0.67, ('structure', 'Z_structure'): 1.29,
            ('none', 'NONE'): 0.71, ('structure', 'Z_full'): 7.85}


def reliable(family: str, action: str) -> bool:
    g = GAIN_TABLE.get((family, action))
    if not g:
        return False
    return g['n'] >= RELIABLE_MIN_N and CI_WIDTH.get((family, action), 99) <= RELIABLE_MAX_CI_WIDTH


# ────────────────────────────── 数据结构 ──────────────────────────────
@dataclass
class Agent:
    id: str
    role: str
    model: str
    capacity: int = 2
    state: str = 'idle'
    workload: int = 0
    calls_left: int = 10_000
    yuan_left: float = 100.0

    def can_take(self, node_kind: str) -> bool:
        return self.role in ROLL_KINDS.get(node_kind, set()) and self.workload < self.capacity


@dataclass
class NodeState:
    id: str
    kind: str
    parents: Tuple[str, ...] = ()
    status: str = 'Ready'
    output: Optional[str] = None
    started_at: Optional[float] = None
    last_beat: Optional[float] = None
    agent: Optional[str] = None


@dataclass
class History:
    """H_t[(node, action_type)] = {count, gains[]} — 统一表示，消除 R3 冲突。"""
    rec: Dict[Tuple[str, str], dict] = field(default_factory=dict)

    def count(self, node: str, action: str) -> int:
        return self.rec.get((node, action), {}).get('count', 0)

    def mean_gain(self, node: str, action: str) -> Optional[float]:
        g = self.rec.get((node, action), {}).get('gains', [])
        return _st.mean(g) if g else None

    def record(self, node: str, action: str, gain: float):
        e = self.rec.setdefault((node, action), {'count': 0, 'gains': []})
        e['count'] += 1
        e['gains'].append(gain)

    def forbidden(self, node: str, action: str) -> bool:
        """C3-a: 同类动作历史增益 ≤0 → 禁止；C3-b: 重复≥2 且最近未改善 → 禁止。"""
        g = self.rec.get((node, action))
        if not g:
            return False
        if g['gains'] and _st.mean(g['gains']) <= 0:
            return True
        if g['count'] >= 2 and g['gains'][-1] <= 0:
            return True
        return False


@dataclass
class Clock:
    t: float = 0.0

    def now(self) -> float:
        return self.t


@dataclass
class Candidate:
    kind: str                 # NONE | Z_format | Z_structure | R | PI | X
    node: str
    calls: int
    plan: List[str]
    delta_q: float = 0.0
    sigma_q: float = 0.0
    cost: float = 0.0
    sigma_c: float = 0.0
    lat: float = 0.0
    sigma_l: float = 0.0


class Scheduler:
    def __init__(self, clock: Clock, deadline: float, agents: Dict[str, Agent],
                 nodes: Dict[str, NodeState], budget_yuan: float = 100.0,
                 reserve: float = T_RESERVE):
        self.clock = clock
        self.deadline = deadline
        self.agents = agents
        self.nodes = nodes
        self.hist = History()
        self.budget_yuan = budget_yuan
        self.spent_yuan = 0.0
        self.reserve = reserve
        self.aborted = False
        self.degraded = False
        self.log: List[dict] = []

    # ── L3/L4 全局截止期 ───────────────────────────────────────────
    def deadline_exceeded(self) -> bool:
        return self.clock.now() >= self.deadline - self.reserve

    def can_dispatch(self) -> bool:
        """I1: 截止期到达后不再派发。"""
        if self.deadline_exceeded():
            self.aborted = True
            return False
        return not self.aborted

    # ── L2 节点级超时 ─────────────────────────────────────────────
    def effective_node_timeout(self, kind: str, p95: float) -> float:
        w_node = max(3.0 * p95, W_MIN)
        w_dead = self.deadline - self.reserve - self.clock.now()
        return min(w_node, max(0.0, w_dead))

    def node_timed_out(self, node_id: str, p95: float) -> bool:
        n = self.nodes[node_id]
        if n.started_at is None:
            return False
        return (self.clock.now() - n.started_at) > self.effective_node_timeout(n.kind, p95)

    def abort_node(self, node_id: str):
        """I2: 中止节点；其陈旧输出不得污染下游。"""
        n = self.nodes[node_id]
        n.status = 'Failed'
        n.output = None            # 明确清空，防止污染
        self.log.append(dict(ev='abort_node', node=node_id, t=self.clock.now()))

    # ── 增益查询 ─────────────────────────────────────────────────
    def gain(self, family: str, action: str) -> Tuple[float, float, bool]:
        g = GAIN_TABLE.get((family, action))
        if not g:
            return 0.0, 0.0, False
        return g['mu'], g['sd'], reliable(family, action)

    # ── 候选生成（L2） ────────────────────────────────────────────
    def build_candidates(self, node_id: str, family: str,
                         current_q: float, swaps_used: int = 0) -> List[Candidate]:
        n = self.nodes[node_id]
        out: List[Candidate] = [Candidate('NONE', node_id, 0, ['noop'], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)]
        fam_action = []
        if family == 'format':
            fam_action.append(('Z_format', ['reset_fmt', 'rerun_FMT'], 'FMT'))
        elif family == 'structure':
            fam_action.append(('Z_structure', ['swap_spec', f'rerun_{node_id}'], node_id))
            fam_action.append(('R', [f'rerun_{node_id}'], node_id))
        elif family == 'model_suspect':
            fam_action.append(('R', [f'rerun_{node_id}'], node_id))
            # PI 仅在有可靠历史时加入
        for act, plan, tgt in fam_action:
            mu, sd, rel = self.gain(family, act)
            if self.hist.forbidden(tgt, act):
                continue                                   # I3
            if act.startswith('PI') and not rel:
                continue
            calls = len([p for p in plan if p.startswith(('reset', 'rerun', 'swap'))])
            out.append(Candidate(act, node_id, calls, plan, mu, sd,
                                 cost=0.003 * calls, sigma_c=0.001 * calls,
                                 lat=2.0 * calls, sigma_l=3.0 * calls))
        # X' 迁移（角色兼容 + 容量 + 交接成本）
        for aid, ag in self.agents.items():
            if aid == n.agent:
                continue
            if not ag.can_take(n.kind):
                continue
            out.append(Candidate('X', node_id, 2, ['summarize_ctx', f'migrate->{aid}', f'rerun_{node_id}'],
                                 delta_q=0.0, sigma_q=0.0, cost=0.006, sigma_c=0.002,
                                 lat=3.0, sigma_l=4.0))
        return out

    # ── L3 门禁 + Pareto + 效用（修正 3/4） ──────────────────────
    def feasible(self, c: Candidate, current_q: float, node_p95: float) -> bool:
        # 质量门禁（V0.2.1-R2 修正）：Q̂_current 本身是金盲估计，绝对终端质量不可靠，
        # 故门禁改为"动作增益可靠为正"；Q̂_final 仅用于 Pareto 排序与报告。
        if c.kind != 'NONE' and (c.delta_q - c.sigma_q) <= 0:
            return False
        if self.spent_yuan + c.cost + c.sigma_c > self.budget_yuan:   # I4
            return False
        d_rem = self.deadline - self.clock.now()
        if c.lat + c.sigma_l + self.reserve > d_rem:          # 时延上界门禁
            return False
        return True

    def _dominates(self, a: Candidate, b: Candidate) -> bool:
        return (a.delta_q >= b.delta_q and a.cost <= b.cost and a.lat <= b.lat and
                (a.delta_q > b.delta_q or a.cost < b.cost or a.lat < b.lat))

    def select(self, cands: List[Candidate], current_q: float,
               node_p95: float) -> Optional[Candidate]:
        feas = [c for c in cands if self.feasible(c, current_q, node_p95)]
        if not feas:
            return None
        front = [c for c in feas if not any(self._dominates(o, c) for o in feas if o is not c)]
        d_rem = max(1e-6, self.deadline - self.clock.now())
        b_rem = max(1e-6, self.budget_yuan - self.spent_yuan)

        def U(c):
            return (U_W['q'] * ((current_q + c.delta_q) - Q_MIN)
                    - U_W['c'] * (c.cost / b_rem)
                    - U_W['l'] * (c.lat / d_rem))
        return max(front, key=U)

    # ── 执行语义（修正 4：候选 → 调用数/影响集） ─────────────────
    def apply(self, c: Candidate) -> dict:
        n = self.nodes[c.node]
        self.spent_yuan += c.cost
        if c.kind == 'R' or c.kind == 'Z_structure' or c.kind == 'Z_format':
            n.status = 'Ready'
        elif c.kind == 'X':
            tgt = next((p.split('->')[1] for p in c.plan if p.startswith('migrate->')), None)
            if tgt and tgt in self.agents:                    # I6: 迁移不破坏 DAG
                self.agents[tgt].workload += 1
                if n.agent and n.agent in self.agents:
                    self.agents[n.agent].workload = max(0, self.agents[n.agent].workload - 1)
                n.agent = tgt
        self.hist.record(c.node, c.kind, c.delta_q)
        self.log.append(dict(ev='apply', kind=c.kind, node=c.node, t=self.clock.now()))
        return dict(kind=c.kind, node=c.node, calls=c.calls, cost=c.cost)

    # ── I7：模型切换不改变智能体身份 ─────────────────────────────
    def switch_model(self, agent_id: str, new_model: str) -> bool:
        ag = self.agents.get(agent_id)
        if ag is None:
            return False
        old_role, old_cap = ag.role, ag.capacity
        ag.model = new_model
        return ag.role == old_role and ag.capacity == old_cap and ag.id == agent_id

    # ── L4 降级输出（I5） ────────────────────────────────────────
    def degrade(self, slots: List[str]) -> dict:
        self.degraded = True
        completed = {nid: n.output for nid, n in self.nodes.items()
                     if n.status == 'Completed' and n.output}
        unknown = [s for s in slots if s not in completed]
        return dict(answer_status='INCOMPLETE_DEADLINE_DEGRADED',
                    completed_nodes=sorted(completed), unknown_slots=unknown,
                    elapsed=self.clock.now(), deadline=self.deadline)
