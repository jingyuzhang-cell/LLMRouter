#!/usr/bin/env python3
"""V6 A/B/O 调节变量计算（预注册冻结版）。

在看到任何 V6 PD 数据之前冻结。输入：
  - 任务包 dag.nodes（V5 同构：[{node,kind,docs,upstream,role}] 拓扑序）
  - 金标槽（V6 面板槽 + slot['doc'] 或 slot['node'] 归属）
  - FC 基线 slot 级命中矩阵（reps × slots）

指标：
  A = 1 - mean(FC_TP_rep)/n_slots                      # 可恢复失败空间
  B = reachable_failure_nodes / total_failure_nodes     # 结构重构可达性
  O = A * B   （无失败节点时 B=None, O=0.0）

可达性规则（冻结；源自 V5 机制叙事，未用 V5 结果标签拟合）：
  failure node f 可达  <=>  dist_to_terminal(f) >= 2
                        AND  ({f} ∪ downstream(f)) 中存在 fan_in >= 2 的 join 节点
  依据：深层 Z_structure 重构 = 重建失败节点的下游闭包并重新汇合；
        距终端 1 跳的失败只能由终端补丁恢复（两臂同权，无 PD 优势）；
        无 join 的线性链没有可重构结构，恢复=重执行（两臂同权）。

槽→节点归属（冻结）：slot['node'] 优先；否则 slot['doc'] 匹配唯一
docs 含该文件的 extract 节点；无匹配时归终端 report 节点（记录 fallback=True）。
"""
import json, hashlib
from pathlib import Path

class DagIndex:
    def __init__(self, nodes):
        # nodes: 拓扑序 [{node, kind, docs, upstream, role}]
        self.nodes = nodes
        self.ids = [n['node'] for n in nodes]
        assert len(set(self.ids)) == len(self.ids), 'duplicate node ids'
        idset = set(self.ids)
        for n in nodes:
            for u in (n.get('upstream') or []):
                assert u in idset, f'unknown upstream {u}'
        self.up = {n['node']: list(n.get('upstream') or []) for n in nodes}
        self.down = {i: [] for i in self.ids}
        for n in nodes:
            for u in self.up[n['node']]:
                self.down[u].append(n['node'])
        self.fan_in = {i: len(self.up[i]) for i in self.ids}
        self.fan_out = {i: len(self.down[i]) for i in self.ids}
        # 源深度（最长路）：source=0
        self.depth = {}
        for i in self.ids:  # 拓扑序保证上游先算
            self.depth[i] = 0 if not self.up[i] else 1 + max(self.depth[u] for u in self.up[i])
        # 距终端（最短路）：terminal=0
        self.dist_t = {}
        for i in reversed(self.ids):
            self.dist_t[i] = 0 if not self.down[i] else 1 + min(self.dist_t[d] for d in self.down[i])
        # 下游闭包
        self.closure = {}
        for i in reversed(self.ids):
            self.closure[i] = set(self.down[i]) | set().union(*(self.closure[d] for d in self.down[i]))

    def reachable(self, nid):
        """冻结的可达性规则。"""
        if nid not in self.dist_t:
            return False
        if self.dist_t[nid] < 2:
            return False
        joins = [m for m in ({nid} | self.closure[nid]) if self.fan_in[m] >= 2]
        return len(joins) > 0

def slot_to_node(slot, idx):
    """槽→节点归属（冻结）。返回 (node_id, used_fallback)。"""
    if slot.get('node') and slot['node'] in idx.up:
        return slot['node'], False
    doc = slot.get('doc')
    if doc:
        cand = [n['node'] for n in idx.nodes
                if n.get('kind') == 'extract' and doc in (n.get('docs') or [])]
        if len(cand) == 1:
            return cand[0], False
        if len(cand) > 1:  # 多节点同文档：归最浅（最早）者
            return min(cand, key=lambda i: idx.depth[i]), False
    return idx.ids[-1], True  # 无匹配 → 终端节点

def compute_A(fc_hit_matrix):
    """fc_hit_matrix: [rep][slot] 0/1。返回 (A, fc_tp_mean, n_slots)。"""
    n = len(fc_hit_matrix[0])
    tps = [sum(rep) for rep in fc_hit_matrix]
    fc_tp_mean = sum(tps) / len(tps)
    A = 1.0 - fc_tp_mean / n if n else 0.0
    return round(A, 4), fc_tp_mean, n

def compute_B(fc_hit_matrix, slots, idx):
    """失败节点 = 在 >=1 rep 中 miss 的槽的归属节点集合。
    返回 (B, failure_nodes, reachable_set, fallback_count)。"""
    failure_nodes, fallbacks = set(), 0
    for si, slot in enumerate(slots):
        if any(rep[si] == 0 for rep in fc_hit_matrix):
            nid, fb = slot_to_node(slot, idx)
            failure_nodes.add(nid)
            fallbacks += int(fb)
    if not failure_nodes:
        return None, sorted(failure_nodes), [], fallbacks
    reach = sorted(f for f in failure_nodes if idx.reachable(f))
    B = len(reach) / len(failure_nodes)
    return round(B, 4), sorted(failure_nodes), reach, fallbacks

def compute_abo(fc_hit_matrix, slots, nodes):
    idx = DagIndex(nodes)
    A, fc_tp_mean, n = compute_A(fc_hit_matrix)
    B, fns, reach, fbs = compute_B(fc_hit_matrix, slots, idx)
    O = round(A * B, 4) if B is not None else 0.0
    return dict(A=A, B=B, O=O, fc_tp_mean=fc_tp_mean, n_slots=n,
                failure_nodes=fns, reachable_failure_nodes=reach,
                slot_fallbacks=fbs,
                _index=dict(depth={i: idx.depth[i] for i in idx.ids},
                            dist_to_terminal={i: idx.dist_t[i] for i in idx.ids},
                            fan_in=idx.fan_in, fan_out=idx.fan_out))

# ---------- 自检（合成用例 + 真实 fixture，全零调用） ----------
def self_test():
    R = []
    E = lambda node, kind, docs, up: dict(node=node, kind=kind, docs=docs, upstream=up, role='')

    # 1. 深层 join DAG：E1,E2→M(fan_in2)→R；E1 失败可达
    dag1 = [E('E1','extract',['d1'],[]), E('E2','extract',['d2'],[]),
            E('M','reason',[],['E1','E2']), E('R','report',[],['M'])]
    idx1 = DagIndex(dag1)
    R.append(('join-dag E1 reachable', idx1.reachable('E1') is True))
    R.append(('join-dag M dist_t=1 unreachable', idx1.reachable('M') is False))
    R.append(('join-dag R dist_t=0 unreachable', idx1.reachable('R') is False))

    # 2. 线性链 E→V→R：无 join，E 不可达
    dag2 = [E('E','extract',['d'],[]), E('V','reason',[],['E']), E('R','report',[],['V'])]
    R.append(('linear-chain unreachable', DagIndex(dag2).reachable('E') is False))

    # 3. A/B/O 端到端：4 槽、2 rep、槽2 恒 miss（归 E1，可达）
    slots3 = [dict(slot_id='s1', doc='d1'), dict(slot_id='s2', doc='d1'),
              dict(slot_id='s3', doc='d2'), dict(slot_id='s4', doc='d2')]
    hits = [[1,0,1,1],[1,0,1,1]]
    r = compute_abo(hits, slots3, dag1)
    R.append(('A=0.25', r['A'] == 0.25))
    R.append(('B=1.0 single failure node reachable', r['B'] == 1.0))
    R.append(('O=0.25', r['O'] == 0.25))
    R.append(('failure_nodes=[E1]', r['failure_nodes'] == ['E1']))

    # 4. 混合：E1(可达) 与 M(不可达) 同时失败 → B=0.5
    hits4 = [[0,0,1,0],[1,0,1,0]]  # E1 槽 miss + 一槽 fallback 到 R? 不：s4 归 E2。
    # 构造 M 失败：slot 无 doc/node 匹配 → fallback 终端 R（dist 0，不可达）
    slots4 = slots3 + [dict(slot_id='s5')]
    hits4 = [[0,0,1,1,0],[1,0,1,1,0]]
    r4 = compute_abo(hits4, slots4, dag1)
    R.append(('mixed B=0.5', r4['B'] == 0.5))
    R.append(('fallback counted', r4['slot_fallbacks'] >= 1))

    # 5. FC 满分：A=0, B=None, O=0
    r5 = compute_abo([[1,1,1,1],[1,1,1,1]], slots3, dag1)
    R.append(('ceiling A=0 B=None O=0', r5['A'] == 0.0 and r5['B'] is None and r5['O'] == 0.0))

    # 6. 真实 fixture：E06 V5 包（只读），槽→节点映射 + 深度索引
    p = Path('/root/research_outputs/RQ_DYN_V5_DESIGN_20261107/e06_huanrui/V5_GOLD_E06_DRAFT.json')
    if p.exists():
        pkg = json.load(open(p))
        idx6 = DagIndex(pkg['dag']['nodes'])
        ok_map = all(slot_to_node(s, idx6)[1] is False for s in pkg['slots'] if s.get('doc'))
        R.append(('E06 fixture: all doc-slots map w/o fallback', ok_map))
        R.append(('E06 N1 dist_t=2 reachable', idx6.dist_t['N1_case'] == 2 and idx6.reachable('N1_case')))
        R.append(('E06 N5 dist_t=0 unreachable', not idx6.reachable('N5_report')))
    return R

if __name__ == '__main__':
    results = self_test()
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(('PASS' if ok else 'FAIL'), name)
    print(f'{passed}/{len(results)} self-tests passed')
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    print('v6_abo.py sha256:', code_sha)
    raise SystemExit(0 if passed == len(results) else 1)
