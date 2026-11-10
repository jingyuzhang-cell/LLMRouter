#!/usr/bin/env python3
"""P2-C 论文五图（零调用；仅读取冻结数据；M3 后口径为主口径）。
数据源：P2C_ANALYSIS.json（冻结分析）、P2C_AUDIT_RECHECK.json（精确 p）、P2C_TASK_MECHANISM_V2.json（V2.1 同源）、
P2C_FINAL_GOLD_MANIFEST_V3.json、FREEZE_P2C.json。输出 p2c_figures/fig1..fig5（PDF + 300dpi PNG）。"""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import matplotlib.font_manager as fm

FP = '/root/.local/share/fonts/NotoSansCJKsc-Regular.otf'
fm.fontManager.addfont(FP)
plt.rcParams.update({'font.family': fm.FontProperties(fname=FP).get_name(), 'axes.unicode_minus': False,
                     'figure.dpi': 120, 'savefig.dpi': 300, 'font.size': 9})
HERE = Path('/root/research_outputs/static_pi/p2_confirm')
OUT = HERE / 'p2c_figures'; OUT.mkdir(exist_ok=True)
AN = json.loads((HERE / 'p2c_analysis/P2C_ANALYSIS.json').read_text())
RK = json.loads((HERE / 'p2c_analysis/P2C_AUDIT_RECHECK.json').read_text())
ME = json.loads((HERE / 'p2c_analysis/P2C_TASK_MECHANISM_V2.json').read_text())

def box(ax, x, y, w, h, text, fc, fs=9, lw=1.0, ec='#333'):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.06',
                                fc=fc, ec=ec, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha='center', va='center', fontsize=fs)

def arrow(ax, x1, y1, x2, y2, style='-|>', color='#333', lw=1.2, rad=0.0, ls='-'):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=12,
                                 color=color, lw=lw, linestyle=ls,
                                 connectionstyle=f'arc3,rad={rad}'))

# ------------------------------------------------------------------ 图1 框架
fig, ax = plt.subplots(figsize=(9.2, 5.0))
ax.set_xlim(0, 10); ax.set_ylim(-0.5, 5.6); ax.axis('off')
ax.text(5, 5.35, '图1  执行反馈驱动的多智能体 DAG 动态联合恢复框架（P2-C 实例化）', ha='center', fontsize=11, weight='bold')
box(ax, 0.15, 4.28, 2.0, 0.78, '多文档任务输入\n(D1 告知书 / D2 决定书)', '#eef3fb')
box(ax, 2.55, 4.28, 2.0, 0.78, 'DAG 生成与静态分配\nE×2 → J1 → J2 → SINK', '#eef3fb')
box(ax, 4.95, 4.28, 2.0, 0.78, '多智能体执行\n(DeepSeek / GLM 异构路由)', '#eef3fb')
box(ax, 7.35, 4.28, 2.5, 0.78, '终端输出与评分\nQ（事实+证据支持）/ C / L', '#eef3fb')
arrow(ax, 2.15, 4.67, 2.55, 4.67); arrow(ax, 4.55, 4.67, 4.95, 4.67); arrow(ax, 6.95, 4.67, 7.35, 4.67)
box(ax, 3.6, 2.9, 3.0, 0.86, '执行反馈与异常检测（V5）\nS1 压制 / S2 未知标签 / S3 遗漏', '#fdf3e3', fs=8.5)
arrow(ax, 5.95, 4.28, 5.5, 3.76, color='#b06a00')
box(ax, 0.15, 1.28, 2.85, 1.06, 'Z：结构调整范围\na0 不动 | a1 终端编辑\na2 SINK 重跑 | a3 J2R+SINK', '#e9f5ec', fs=8.5)
box(ax, 3.2, 1.28, 2.85, 1.06, 'R：重执行节点集合\n∅+编辑 | {SINK} | {J2, SINK}', '#e9f5ec', fs=8.5)
box(ax, 6.25, 1.28, 3.6, 1.06, 'π：智能体分配（本文固定路由）\n恢复预算上限与回退机制', '#e9f5ec', fs=8.5)
box(ax, 2.6, 0.12, 4.9, 0.72, '动态联合决策（G6）：状态识别 → 恢复范围选择 → 资源约束下的执行', '#dceef7', fs=9)
arrow(ax, 4.2, 2.9, 2.0, 2.34, rad=0.12, color='#1f6f3f')
arrow(ax, 5.1, 2.9, 4.6, 2.34, color='#1f6f3f')
arrow(ax, 6.0, 2.9, 7.9, 2.34, rad=-0.12, color='#1f6f3f')
arrow(ax, 4.2, 1.28, 4.6, 0.84, color='#1f6f3f')
arrow(ax, 5.9, 1.28, 5.6, 0.84, color='#1f6f3f')
arrow(ax, 8.0, 1.28, 5.6, 0.84, color='#1f6f3f')
arrow(ax, 2.55, 0.55, 1.7, 1.26, rad=-0.18, ls='--', color='#888')
ax.text(1.45, 0.72, '重执行', fontsize=8, color='#555')
arrow(ax, 7.55, 0.62, 8.7, 1.27, rad=0.18, ls='--', color='#b06a00')
ax.text(9.9, 0.82, '恢复后\n再评分', fontsize=8, color='#b06a00', ha='right')
box(ax, 1.35, -0.34, 7.3, 0.52, '对照臂：G1 单体｜G2 静态管线（零动作）｜G3 固定恢复｜G4 仅Z｜G5 仅R｜G6 Z+R 联合', '#fafafa', fs=8.2)
fig.tight_layout(); fig.savefig(OUT / 'fig1_framework.pdf'); fig.savefig(OUT / 'fig1_framework.png'); plt.close(fig)

# ------------------------------------------------------------------ 图2 实验设计
fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 4.4), width_ratios=[1.15, 1])
a1.set_xlim(0, 10); a1.set_ylim(0, 7.4); a1.axis('off')
a1.text(5, 7.15, '(a) 六个实验臂与配对比较', ha='center', fontsize=10, weight='bold')
arms = [('G1  单智能体（一次性作答）', 6.3), ('G2  静态多智能体管线', 5.4), ('G3  固定恢复（触发即 J2R+SINK）', 4.5),
        ('G4  仅动态结构调整 Z', 3.6), ('G5  仅动态重执行集合 R', 2.7), ('G6  Z+R 联合动态恢复（本文方法）', 1.8)]
for txt, y in arms:
    fc = '#dceef7' if txt.startswith('G6') else '#f2f2f2'
    box(a1, 0.35, y, 6.45, 0.62, txt, fc, fs=8.3)
cent = {'G1': 6.61, 'G2': 5.71, 'G3': 4.81, 'G4': 3.91, 'G5': 3.01, 'G6': 2.11}
lanes = [('H1', 'G2', 'G1', 7.0, '#666', 1.0), ('H5', 'G6', 'G5', 7.35, '#888', 1.0),
         ('H4 ★', 'G6', 'G4', 7.7, '#c0392b', 1.6), ('H3', 'G6', 'G3', 8.05, '#888', 1.0),
         ('H2 ★', 'G6', 'G2', 8.4, '#c0392b', 1.8), ('交互', 'G6', 'G3', 8.78, '#1f6f3f', 1.2)]
for lab, lo, hi, x, col, lw in lanes:
    yl, yu = cent[lo], cent[hi]
    a1.plot([x, x], [yl, yu], color=col, lw=lw, solid_capstyle='butt')
    a1.plot([6.8, x], [yl, yl], color=col, lw=0.8, ls=':')
    a1.plot([6.8, x], [yu, yu], color=col, lw=0.8, ls=':')
    a1.text(x, yu + 0.09, lab, fontsize=7.6, rotation=90, va='bottom', ha='center', color=col,
            weight='bold' if ('★' in lab or lab == '交互') else 'normal')
a1.text(5, 0.95, '★ = Holm 族（α=0.05）下成立：H2（G6−G2）、H4（G6−G4）；交互 q=G6−G4−G5+G3（双侧）',
        ha='center', fontsize=8.2, color='#c0392b')
a1.text(5, 0.45, '每臂同一任务同一 Gold 与评分器；共享上游检查点分摊到各臂', ha='center', fontsize=8, color='#555')
a2.set_xlim(0, 10); a2.set_ylim(0, 7.4); a2.axis('off')
a2.text(5, 7.15, '(b) 区组结构（52 个，预登记随机化）', ha='center', fontsize=10, weight='bold')
box(a2, 1.6, 5.7, 6.8, 0.72, '26 个真实任务 × 2 次重复 = 52 区组\n（种子=int(冻结清单SHA[:8])=2756364533）', '#eef3fb', fs=8.4)
box(a2, 0.9, 4.5, 8.2, 0.66, '区组内：共享上游 E×2 → J1 → J2（检查点，先于全部分叉臂）', '#f7f2e8', fs=8.4)
seq = ['G2', 'G3', 'G6', 'G1', 'G5', 'G4']
for i, a_ in enumerate(seq):
    box(a2, 0.95 + i * 1.36, 3.2, 1.16, 0.6, a_, '#dceef7' if a_ == 'G6' else ('#f2dede' if a_ == 'G1' else '#f2f2f2'), fs=9)
a2.text(5, 2.55, 'G2 固定先行（检查点依赖）；G3–G6 随机排列；G1 独立随机插入', ha='center', fontsize=8.2, color='#555')
box(a2, 0.5, 1.0, 4.15, 1.15, '统计单位 = 26 个独立任务\n（k=2 重复取均值后\n做配对检验）', '#e9f5ec', fs=8.0)
box(a2, 4.9, 1.0, 4.6, 1.15, '硬预算（预执行门禁）：\n≤1300 次调用；≤15M tokens\n≤¥24（元，统一价格表）\n实际：507 次 / 4.23M / ¥6.94', '#e9f5ec', fs=7.5)
fig.subplots_adjust(wspace=0.5); fig.savefig(OUT / 'fig2_design.pdf', bbox_inches='tight'); fig.savefig(OUT / 'fig2_design.png', bbox_inches='tight'); plt.close(fig)

# ------------------------------------------------------------------ 图3 主检验森林图
P = AN['primary']
cons = [('H1  Q(G2)−Q(G1)  多智能体静态价值', P['H1'], RK['exact_recheck']['H1']['p_exact'], False),
        ('H2  Q(G6)−Q(G2)  联合动态恢复（主假设）', P['H2'], RK['exact_recheck']['H2']['p_exact'], True),
        ('H3  Q(G6)−Q(G3)  vs 固定恢复', P['H3'], RK['exact_recheck']['H3']['p_exact'], False),
        ('H4  Q(G6)−Q(G4)  R 的独立增量', P['H4'], RK['exact_recheck']['H4']['p_exact'], True),
        ('H5  Q(G6)−Q(G5)  Z 的增量', P['H5'], RK['exact_recheck']['H5']['p_exact'], False),
        ('交互  G6−G4−G5+G3（双侧）', P['interaction'], RK['exact_recheck']['interaction']['p_exact'], False)]
fig, ax = plt.subplots(figsize=(8.6, 3.9))
ypos = range(len(cons) - 1, -1, -1)
for y, (lab, d, p, sig) in zip(ypos, cons):
    m, ci = d.get('mean_diff', d.get('mean')), d['ci95_boot']
    ax.errorbar(m, y, xerr=[[m - ci[0]], [ci[1] - m]], fmt='o' if sig else 'o',
                color='#c0392b' if sig else '#7f8c8d', ms=7 if sig else 5,
                mfc='#c0392b' if sig else 'white', mec='#c0392b' if sig else '#7f8c8d',
                capsize=3, lw=1.4, markeredgewidth=1.6, zorder=5)
    ax.text(0.132, y, f"{m:+.4f}", va='center', fontsize=8.4)
    ax.text(0.176, y, f"[{ci[0]:+.3f}, {ci[1]:+.3f}]", va='center', fontsize=8.0, color='#555')
    ax.text(0.243, y, f"{p:.4f}" if p >= 1e-4 else f"{p:.6f}", va='center', fontsize=8.4,
            weight='bold' if sig else 'normal')
    ax.text(0.278, y, 'Holm 成立' if sig else ('探索性' if '交互' in lab else '不成立'), va='center', fontsize=8,
            color='#c0392b' if sig else '#555')
ax.axvline(0, color='#333', lw=0.9, ls='--')
ax.set_yticks(list(ypos)); ax.set_yticklabels([c[0] for c in cons], fontsize=8.8)
ax.set_xlim(-0.06, 0.30); ax.set_xlabel('任务级 Q 差值（26 个独立任务，重复取均值）', fontsize=9)
ax.set_title('图3  预注册配对检验：效应量、95% bootstrap CI 与精确 p（2^26 全枚举符号翻转）', fontsize=10, weight='bold')
for x, t in [(0.132, '均值差'), (0.176, '95% CI'), (0.243, '精确 p'), (0.278, '结论')]:
    ax.text(x, len(cons) - 0.35, t, fontsize=8, color='#333', weight='bold')
ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout(rect=[0, 0.045, 1, 1])
fig.text(0.58, 0.012, '注：CI 为任务级百分位 bootstrap（10⁴）；p 为精确枚举（与 CI 方法不同，故 p=0.052 与 CI 不含 0 可并存）；H1–H5 单侧、Holm 族 α=0.05；交互双侧（探索性，p=0.0520）。',
         ha='center', fontsize=7.6, color='#555')
fig.savefig(OUT / 'fig3_primary.pdf', bbox_inches='tight'); fig.savefig(OUT / 'fig3_primary.png', bbox_inches='tight'); plt.close(fig)

# ------------------------------------------------------------------ 图4 异质性 + 迁移
rows = sorted(ME['rows'], key=lambda r: r['H2'])
rename = {'证据/数值纠偏型': '证据支持链纠偏', '信息找回型': '信息找回', '信息找回型（含锚定损失）': '信息找回（含锚定损失）',
          '共享上游失效型': '共享上游失效', '无恢复目标型': '无恢复目标', '无恢复目标型（一次重复共享失效）': '无恢复目标（含一次共享失效）',
          '动作无净变化型': '动作无净变化', '证据错误锚定型': '证据错误锚定（负例）'}
cmap = {'证据支持链纠偏': '#2e7ebc', '信息找回': '#3aa76d', '信息找回（含锚定损失）': '#8fc79a', '共享上游失效': '#8a8a8a',
        '无恢复目标': '#b0b0b0', '无恢复目标（含一次共享失效）': '#c9c9c9', '动作无净变化': '#d8d8d8', '证据错误锚定（负例）': '#c0392b'}
fig, (b1, b2) = plt.subplots(1, 2, figsize=(9.8, 6.4), width_ratios=[1.6, 1], gridspec_kw={'wspace': 0.42})
ys = range(len(rows))
b1.barh(list(ys), [r['H2'] for r in rows], color=[cmap[rename[r['cls']]] for r in rows], height=0.72)
for y, r in zip(ys, rows):
    if r['H2'] != 0:
        b1.text(r['H2'] + (0.012 if r['H2'] > 0 else -0.012), y, f"{r['H2']:+.3f}", va='center',
                ha='left' if r['H2'] > 0 else 'right', fontsize=7.2)
b1.set_yticks(list(ys)); b1.set_yticklabels([r['task'] for r in rows], fontsize=7.6)
b1.axvline(0, color='#333', lw=0.9)
b1.set_xlabel('G6−G2（任务级，重复均值）', fontsize=9)
b1.set_title('(a) 26 个任务的质量收益与机制归类', fontsize=10, weight='bold')
b1.set_xlim(-0.26, 0.60)
b1.annotate('RSK_603803 — 唯一负例：证据阶段—文书错配\n（数值正确、引文漂移至 D1）', xy=(-0.179, 0), xytext=(0.14, 0.7),
            fontsize=7.6, color='#c0392b', arrowprops=dict(arrowstyle='->', color='#c0392b'))
handles = [plt.Rectangle((0, 0), 1, 1, color=v) for v in cmap.values()]
cats = ['LOC_WRONG→TP\n(证据定位纠正)', 'ABSENT→TP\n(信息找回)', 'TP→lost\n(其中阶段漂移 10)']
post = [45, 27, 10]; pre = [52, 24, 13]
x = range(3); w = 0.36
b2.bar([i - w / 2 for i in x], post, w, color='#2e7ebc', label='M3 后（主口径）')
b2.bar([i + w / 2 for i in x], pre, w, color='#b9cfe4', label='M3 前（对照）')
for i, (a_, b_) in enumerate(zip(post, pre)):
    b2.text(i - w / 2, a_ + 0.8, str(a_), ha='center', fontsize=8.6, weight='bold')
    b2.text(i + w / 2, b_ + 0.8, str(b_), ha='center', fontsize=8.6, color='#555')
b2.set_xticks(list(x)); b2.set_xticklabels(cats, fontsize=8)
b2.set_ylabel('事实级迁移次数（事件计数，非独立样本）', fontsize=8.4)
b2.set_title('(b) G2→G6 事实迁移（M3 前后口径）', fontsize=10, weight='bold')
b2.legend(fontsize=8); b2.spines[['top', 'right']].set_visible(False); b2.set_ylim(0, 63)
b2.text(1.0, 58.5, '正向合计：72（M3后）/ 79（M3前）', ha='center', fontsize=8, color='#333')
fig.suptitle('图4  任务异质性与证据迁移机制（统计单位：26 任务）', fontsize=11, weight='bold', y=0.995)
fig.tight_layout(rect=[0, 0.105, 1, 0.965])
fig.legend(handles, list(cmap.keys()), loc='lower center', ncol=4, fontsize=7.6, frameon=False,
           bbox_to_anchor=(0.5, 0.008), columnspacing=1.2, handlelength=1.2)
fig.savefig(OUT / 'fig4_heterogeneity.pdf', bbox_inches='tight'); fig.savefig(OUT / 'fig4_heterogeneity.png', bbox_inches='tight'); plt.close(fig)

# ------------------------------------------------------------------ 图5 可靠性与资源
rel = AN['reliability']; cost = AN['per_arm_cost']; bud = AN['budget']
fig, (c1, c2, c3) = plt.subplots(1, 3, figsize=(10.6, 3.7), gridspec_kw={'wspace': 0.34})
armsR = ['G3', 'G4', 'G5', 'G6']
kinds = [('OK', '#3aa76d'), ('OK_NO_TARGET', '#b0b0b0'), ('RECOVERY_FAILED_TRUNCATED', '#e2a33d'), ('EXECUTION_FAILED::shared', '#8a8a8a')]
bottom = [0] * 4
for k, col in kinds:
    vals = [rel['arm_status_counts'][a].get(k, 0) for a in armsR]
    c1.bar(armsR, vals, bottom=bottom, color=col, label=k.replace('OK_NO_TARGET', '无目标').replace('RECOVERY_FAILED_TRUNCATED', '恢复截断→回退').replace('EXECUTION_FAILED::shared', '共享上游失效').replace('OK', '恢复成功'))
    bottom = [b_ + v for b_, v in zip(bottom, vals)]
for i, a in enumerate(armsR):
    c1.text(i, 53.2, f"{rel['arm_status_counts'][a].get('RECOVERY_FAILED_TRUNCATED', 0)}", ha='center',
            va='bottom', fontsize=7.8, weight='bold', color='#a06a00')
c1.set_ylim(0, 70); c1.set_ylabel('区组数（共 52）', fontsize=8.6)
c1.set_title('(a) 恢复臂执行结果（数字=恢复截断次数）', fontsize=9, weight='bold')
c1.legend(fontsize=7, loc='upper right'); c1.spines[['top', 'right']].set_visible(False)
order = ['shared', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6']
lab = ['共享\n上游*', 'G1', 'G2', 'G3', 'G4', 'G5', 'G6']
c2.bar(lab, [cost[o]['calls'] for o in order], color='#7f5fa8', alpha=0.85)
for i, o in enumerate(order):
    c2.text(i, cost[o]['calls'] + 6, f"{cost[o]['tokens']/1e4:.0f}万", ha='center', fontsize=7.4, color='#444')
    c2.text(i, min(cost[o]['calls'], 228) - 9, f"{cost[o]['calls']}次", ha='center', fontsize=7.0, color='white')
c2.set_ylabel('调用次数（标注=tokens）', fontsize=8.6); c2.set_ylim(0, 235)
c2.set_title('(b) 各臂资源消耗（52 区组合计）', fontsize=9, weight='bold')
c2.text(0.02, 0.93, '*共享上游 202 次由六臂分摊', transform=c2.transAxes, fontsize=7, color='#555')
c2.spines[['top', 'right']].set_visible(False)
acc = [cost[o]['yuan'] for o in order]; mar = [cost[o]['yuan_marginal'] for o in order]
x = range(len(order)); w = 0.38
c3.bar([i - w / 2 for i in x], acc, w, color='#2e7ebc', label='核算成本（统一价格表）')
c3.bar([i + w / 2 for i in x], mar, w, color='#e2a33d', label='实际边际支出（GLM 订阅 ¥0）')
c3.set_xticks(list(x)); c3.set_xticklabels(['共享\n上游*' if l.startswith('共享') else l for l in lab], fontsize=7.6)
for i, (a_, m_) in enumerate(zip(acc, mar)):
    c3.text(i - w / 2, a_ + 0.02, f"{a_:.2f}", ha='center', fontsize=6.6, color='#2e7ebc')
    c3.text(i + w / 2, m_ + 0.02, f"{m_:.2f}", ha='center', fontsize=6.6, color='#b06a00')
c3.set_ylabel('¥（52 区组）', fontsize=8.6)
c3.set_title('(c) 双口径成本：G6 核算最省、边际略高', fontsize=9, weight='bold')
c3.legend(fontsize=7); c3.spines[['top', 'right']].set_visible(False)
fig.suptitle(f"图5  执行可靠性、资源与成本\n共享J2截断 12/52 区组；J2R 截断 23/100；总耗 {bud['wall']}，核算 ¥{bud['yuan_accounting']} / 预算 ¥24",
             fontsize=9.6, weight='bold', y=0.985)
fig.tight_layout(rect=[0, 0, 1, 0.87]); fig.savefig(OUT / 'fig5_reliability_cost.pdf', bbox_inches='tight'); fig.savefig(OUT / 'fig5_reliability_cost.png', bbox_inches='tight'); plt.close(fig)
print('figures written:', sorted(p.name for p in OUT.iterdir()))
