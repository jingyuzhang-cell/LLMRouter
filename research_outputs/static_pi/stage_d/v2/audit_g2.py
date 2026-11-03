"""G2 audit: per-node state transition table for S1 / S1b. Produces markdown."""
import sys, json
sys.path.insert(0, '.')
from engine_v22 import run_execution, ARMS

NODES = ('E1','E2','E1_pos','E1_rest','E1_merge','E2_pos','E2_rest','E2_merge','J1','J2','SINK')

def table(arm, scenario):
    r = run_execution(arm, scenario)
    snaps = r['snapshots']
    def st_at(phase, name):
        for s in snaps:
            if s['phase'] == phase and (s.get('node') == name or s['phase'] in ('init','U')):
                return s['states'].get(name, '—')
        return '—'
    # states at key phases for the anomaly-bearing node
    anomaly_node = 'E2' if scenario == 'S1' else 'E1'
    rows = []
    for n in NODES:
        if n not in r['states'] and not any(n in s['states'] for s in snaps):
            continue
        pre = snaps[0]['states'].get(n, '—')
        at_detect = next((s['states'].get(n,'—') for s in snaps if s['phase']=='detect' and s.get('node')==anomaly_node), '—')
        after_r0 = next((s['states'].get(n,'—') for s in snaps if s['phase']=='R0'), '—')
        after_z  = next((s['states'].get(n,'—') for s in snaps if s['phase']=='Z'), '—')
        U = next((s['U'] for s in snaps if s['phase']=='U'), [])
        in_u = n in U
        in_pi = n in r['pi_scope']
        reason = ''
        if not in_u:
            if n.endswith('_merge'): reason = 'code node (no model)'
            elif r['states'].get(n) == 'DELETED' or after_z == 'DELETED': reason = 'deleted by Z (topology changed)'
            elif r['states'].get(n) == 'RUNNING': reason = 'in flight (never reassigned)'
            elif r['states'].get(n) == 'COMPLETED': reason = 'completed before anomaly'
            elif r['states'].get(n) == 'FAILED': reason = 'failed terminally'
            else: reason = 'not in active DAG'
        rows.append((n, pre, at_detect, after_r0, after_z, in_u, in_pi, reason))
    return r, rows, U

if __name__ == '__main__':
    out = ['# G2 逐节点审计：π 作用域与依赖失效', '',
           '**性质**：离线 Mock（`simulated=true`），非真实模型结果。', '']
    for scenario in ('S1', 'S1b'):
        arm = 'Joint'
        r, rows, U = table(arm, scenario)
        out += [f'## {scenario}（异常节点 = {"E2" if scenario=="S1" else "E1"}，臂 = {arm}）', '',
                f'- dag_version: {r["dag_version"]}；calls: {r["call_count"]}；stop: {r["stop_reason"]}',
                f'- 最终 U（R₀ 与 Z 之后重算）: `{U}`',
                f'- pi_scope: `{r["pi_scope"]}`', '',
                '| 节点 | init | detect | R₀ 后 | Z 后 | 进入 U | 进入 π | 未进入 U 的原因 |',
                '|---|---|---|---|---|---|---|---|']
        for row in rows:
            out.append('| ' + ' | '.join([row[0]] + [str(x) for x in row[1:5]] + ['✓' if row[5] else '✗', '✓' if row[6] else '✗', row[7]]) + ' |')
        out.append('')
        # explicit checks
        desc = [n for n in ('J1','J2','SINK')]
        desc_states = [(n, r['states'].get(n)) for n in desc]
        out.append(f'- 后代 J1/J2/SINK 最终状态: {desc_states}')
        out.append(f'- 异常节点: {("E2","E2_pos","E2_rest","E2_merge") if scenario=="S1" else ("E1","E1_pos","E1_rest","E1_merge")} 状态: '
                   + str({k: r['states'].get(k) for k in (("E2","E2_pos","E2_rest","E2_merge") if scenario=="S1" else ("E1","E1_pos","E1_rest","E1_merge"))}))
        out.append('')
    out += ['## Running 节点保护', '',
            '- `compute_U` 仅接受 `PENDING`/`READY`；`RUNNING` 永不进入 U。',
            '- 在本实验的 S1/S1b/S4′ 中，异常检测发生在节点调用返回之后（同步），',
            '  而异常节点的后代因依赖门控**尚未派发**（J1 需 E1,E2 均 Completed），',
            '  因此**不存在 Running 后代**；该情形由单元测试 U-RUNNING 覆盖。',
            '- 若运行时真的观察到 Running 后代，引擎**不发明语义**：其上游版本变化会导致结果过期，',
            '  本方案**不定义**过期结果处理，标记为 BLOCKED 待裁定（见报告 §未解决）。', '']
    open('../G2_NODE_AUDIT.md','w').write('\n'.join(out))
    print('wrote ../G2_NODE_AUDIT.md')
