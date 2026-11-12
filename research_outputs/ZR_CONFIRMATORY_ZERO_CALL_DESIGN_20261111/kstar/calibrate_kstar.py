#!/usr/bin/env python3
"""K* 零调用校准：容量边界 = 单次汇合在固定输出预算与安全余量下可完整完成合同的字段数上限。
输入：历史真实 xc 输出 token（账本）、历史任务事实数 K（合同）。
方法：tokens(K) ≈ overhead + per_field*K；K* = floor((B*(1-m) - overhead) / per_field)。
不使用任何模型效果结果，不做阈值搜索。"""
import json, glob, statistics as st, hashlib
from pathlib import Path
outs = []
for f in glob.glob('/root/r3_own_pool/**/*.jsonl', recursive=True) + glob.glob('/root/research_outputs/**/*.jsonl', recursive=True):
    try:
        for line in open(f, errors='ignore'):
            if '"node": "xc"' not in line: continue
            d = json.loads(line)
            if d.get('node') != 'xc': continue
            t = (d.get('usage') or {}).get('completion_tokens')
            if t and t > 64: outs.append(t)   # 排除注入截断
    except Exception: pass
outs.sort()
Ks = []
p2 = Path('/root/research_outputs/static_pi/p2_confirm/P2C_FINAL_GOLD_MANIFEST_V3.json')
if p2.exists():
    for c in json.loads(p2.read_text())['contracts']:
        try: Ks.append(len(json.loads(Path(c['file']).read_text()).get('required_facts', [])))
        except Exception: pass
g = Path('/root/research_outputs/static_pi/p2_confirm/g7_tasks/G7_TASKSET_FREEZE.json')
for t in json.loads(g.read_text())['tasks']: Ks.append(t['facts'])
Ks.sort()
def pct(xs, q): return xs[min(len(xs)-1, int(q*len(xs)))]
res = dict(
    method='tokens(K)=overhead+per_field*K; K*=floor((B*(1-m)-overhead)/per_field)',
    xc_output_tokens=dict(n=len(outs), median=st.median(outs), mean=round(st.mean(outs),1),
                          p90=pct(outs,.9), p95=pct(outs,.95), max=max(outs),
                          cap_hit_rate=round(sum(1 for t in outs if t>=2000)/len(outs),4)),
    K_distribution=dict(n=len(Ks), median=st.median(Ks), mean=round(st.mean(Ks),1), min=min(Ks), max=max(Ks),
                        p10=pct(Ks,.1), p25=pct(Ks,.25), p75=pct(Ks,.75), p90=pct(Ks,.9)),
    grids=[dict(per_field=pf, budget=B, margin=m,
                K_star=int((B*(1-m)-300)//pf))
           for pf in (33,45) for B,m in ((2048,.25),(4096,.25))],
    interpretation='真实容量边界 K*=27~37（预算2048/余量25%）。任务事实数中位19，仅少数任务超过K*；不得为制造Z失败而下调K*。',
    code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    seed='N/A（无随机性）')
Path('KSTAR_CALIBRATION.json').write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1))
