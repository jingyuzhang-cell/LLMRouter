#!/usr/bin/env python3
"""CAL5 V2 判定器（零调用）：读取 runs_v2/CAL5_V2_REPORT_*.json，按预注册判据输出结论。

判据（操作员 2026-11-11 冻结）：
  Z1 成功 ≥ 8/10                      -> Z1 机制门槛
  Z0 成功 ≤ 6/10 且至少一个任务两次重复均失败 -> Z0 失败门槛
  Z0 成功 ≥ 7/10                      -> 无足够结构增量，停止确认性实验
  30 次测量中执行异常 > 2 次            -> 校准不结论
成功定义（与冻结校准器一致）：
  Z1 = loc 定位到注入字段并给出证据跨度 AND ver 返回 CONFLICT/UNSUPPORTED 且给出正确值
  Z0 = xc 返回 CONFLICT/UNSUPPORTED 且给出正确值
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'runs_v2'


def main(path=None):
    if path is None:
        files = sorted(RUNS.glob('CAL5_V2_REPORT_*.json'))
        if not files:
            print('NO_REPORT')
            return 2
        path = files[-1]
    rep = json.loads(Path(path).read_text())
    units = rep['units']
    n = len(units)
    z0 = sum(1 for u in units if u['z0']['success'])
    z1 = sum(1 for u in units if u['z1']['success'])
    both_fail = {}
    for u in units:
        if not u['z0']['success']:
            both_fail.setdefault(u['task_id'], set()).add(u['rep'])
    one_task_both = any(len(v) >= 2 for v in both_fail.values())
    anomalies = 0
    rows = []
    for u in units:
        bad = []
        if u['z0']['finish'] not in ('stop', 'end_turn') or u['z0']['why'] == 'NO_JSON':
            bad.append('Z0')
        if any(f not in ('stop', 'end_turn') for f in u['z1']['finish']) or 'NO_JSON' in (u['z1']['loc_why'], u['z1']['ver_why']):
            bad.append('Z1')
        if bad:
            anomalies += 1
        rows.append(dict(task=u['task_id'], rep=u['rep'], injection=u['injection'],
                         z0=u['z0']['success'], z1=u['z1']['success'],
                         z0_why=u['z0']['why'], z1_loc=u['z1']['loc_why'],
                         z1_ver=u['z1']['ver_why'], anomalies=bad))
    if anomalies > 2:
        verdict = 'INCONCLUSIVE_ANOMALIES'
    elif z0 >= 7:
        verdict = 'STOP_NO_INCREMENT'
    elif z1 >= 8 and z0 <= 6 and one_task_both:
        verdict = 'PASS_BOTH_GATES'
    elif z1 >= 8:
        verdict = 'Z1_PASS_Z0_GATE_FAIL'
    else:
        verdict = 'Z1_FAIL'
    out = dict(report=str(path), n_units=n, z0_success=z0, z1_success=z1,
               one_task_both_reps_fail=one_task_both, anomalies=anomalies,
               verdict=verdict, rows=rows)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
