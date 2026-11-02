import json, sys, re, time
sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import Meter, BudgetExceeded

zeda = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
EV_TEXT_FULL = ' '.join(d['text'] for d in zeda['docs'])
EV_6000 = EV_TEXT_FULL[:6000]
silver = json.load(open('dd_v51_silver_facts.json'))
valid_silver = [f for f in silver if f['fid'] != 'A04']

meter = Meter(ledger_path='v8_n1_upgrade_LEDGER.jsonl', max_calls=10, max_guaranteed_actual=60000)

SYS = '你是资本市场文档分析助手。穷尽提取所有事实，不遗漏任何条目。只输出JSON。'
SYS_DOWN = '你是一个严谨的资本市场调查助手。只输出JSON。不要编造。无法确认的标UNKNOWN。'
norm = lambda s: re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))

N1_TEMPLATE = open('n1_revised_prompt.txt').read().split('文档：')[0]

def prompt_for(nid, role, upstream, n1_bypass=None):
    if role == 'extraction' and nid == 'n2':
        return f'{SYS_DOWN}\n基于以下初步提取结果，进一步补充遗漏的事实：\n{str(upstream.get("n1",""))[:3000]}\n输出JSON，字段 facts。'
    if role == 'timeline':
        return f'{SYS_DOWN}\n根据以下提取事实整理时间线（按日期排序）：\n{str(upstream.get("n2",""))[:3000]}\n输出JSON，字段 timeline。'
    if role == 'amounts':
        return f'{SYS_DOWN}\n汇总所有金额数据（虚增、罚款、关联交易、理财）：\n{str(upstream.get("n2",""))[:3000]}\n输出JSON，字段 amounts。'
    if role == 'penalties':
        return f'{SYS_DOWN}\n梳理处罚决定（处罚种类、对象、金额、依据）：\n{str(upstream.get("n2",""))[:2500]}\n输出JSON，字段 penalties。'
    if role == 'entity_graph':
        return f'{SYS_DOWN}\n识别涉事主体及关系：\n{str(upstream.get("n2",""))[:3000]}\n输出JSON，字段 entities。'
    if role == 'timeline_deep':
        t = str(upstream.get('n3',''))[:2000]; e = str(upstream.get('n6',''))[:1500]
        return f'{SYS_DOWN}\n时间线阶段复核与划分：\n时间线:{t}\n主体:{e}\n输出JSON，字段 stages。'
    if role == 'amounts_check':
        return f'{SYS_DOWN}\n金额交叉核验：\n{str(upstream.get("n4",""))[:2500]}\n输出JSON，字段 amounts_checked。'
    if role == 'cross_check':
        p = str(upstream.get('n5',''))[:1500]; s = str(upstream.get('n7',''))[:1500]; a = str(upstream.get('n8',''))[:1000]
        bypass = str(n1_bypass)[:3000] if n1_bypass else ''
        return (f'{SYS_DOWN}\n跨来源核验。你有两份输入：\n'
                f'【输入A：初始结构化提取（直接来自源头文档）】\n{bypass}\n\n'
                f'【输入B：中间节点核验结果】\n处罚:{p}\n阶段:{s}\n核验:{a}\n\n'
                f'请核验输入A中的全部事实（日期、金额、处罚、实体），结合输入B进行交叉验证。\n'
                f'输出JSON，字段 verified_facts，数组。每条事实保留原始值。')
    return (f'{SYS_DOWN}\n综合全部核验事实，输出完整调查报告。\n'
            f'要求：报告必须逐项包含以下内容——\n'
            f'1. 所有日期（事件日期 + 会计期间截止日）\n'
            f'2. 所有金额（虚增收入/利润 + 罚款 + 关联交易 + 理财余额）\n'
            f'3. 所有处罚类型（罚款/警告/市场禁入/责令改正）\n'
            f'4. 所有涉事公司\n'
            f'每项标注核验状态（已核验/UNKNOWN）。\n\n'
            f'核验事实：\n{str(upstream.get("n9",""))[:6000]}\n'
            f'输出JSON，字段 report。')

NODES = [('n1','extraction'),('n2','extraction'),('n3','timeline'),('n4','amounts'),
         ('n5','penalties'),('n6','entity_graph'),('n7','timeline_deep'),
         ('n8','amounts_check'),('n9','cross_check'),('n10','synthesis')]
DEPS = {'n1':[],'n2':['n1'],'n3':['n1'],'n4':['n1'],'n5':['n1','n2'],'n6':['n1','n2'],
        'n7':['n3','n6'],'n8':['n4'],'n9':['n5','n7','n8'],'n10':['n9']}

upstream = {}; node_status = {}
t0 = time.time()
print("=== V8-2: n1→glm53 + window 6000 ===\n")

for nid, role in NODES:
    if nid == 'n1':
        prompt = N1_TEMPLATE + '文档：\n' + EV_6000
        system = SYS; max_tok = 4000; model = 'glm53'
    elif nid == 'n9':
        max_tok = 2000; system = SYS_DOWN; model = 'glm53flash'
        ud = {d: upstream.get(d,'') for d in DEPS[nid]}
        prompt = prompt_for(nid, role, ud, upstream.get('n1',''))
    else:
        max_tok = 2000 if nid == 'n10' else 768
        system = SYS_DOWN; model = 'glm53flash'
        ud = {d: upstream.get(d,'') for d in DEPS[nid]}
        prompt = prompt_for(nid, role, ud)

    try:
        rec, text = meter.call(model, system, prompt, max_tokens=max_tok,
                              purpose=f'v8_n1_up:{nid}', timeout_s=120)
        out_tok = rec['usage'].get('output_tokens',0)
        stop = rec.get('stop_reason','')
        clean = text.strip()
        if clean.startswith('```'):
            ls = clean.split('\n')[1:]
            if ls and ls[-1].strip()=='```': ls = ls[:-1]
            clean = '\n'.join(ls).strip()
        usable = len(clean) > 10
        try: json.loads(clean); usable = True
        except: usable = len(clean) > 20
        upstream[nid] = text
        node_status[nid] = 'OK' if usable else 'DEGRADED'
        tag = ' [GLM53+6000]' if nid == 'n1' else ''
        trunc = ' [TRUNC]' if stop == 'max_tokens' else ''
        print(f"  {nid} ({role}): {len(text)} chars, out={out_tok}{trunc} → {'OK' if usable else 'DEGRADED'}{tag}")
    except BudgetExceeded:
        print(f"  BUDGET STOP at {nid}"); break
    except Exception as e:
        print(f"  ERROR {nid}: {e}"); upstream[nid]=''; node_status[nid]='FAILED'; continue

def check(fact, nt):
    nv = norm(fact['value'])
    if fact['kind']=='date':
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', fact['value'])
        if m:
            return any(p in nt for p in [nv, norm(f"{m.group(1)}年{int(m.group(2))}月{int(m.group(3))}日")])
    return nv in nt

report = upstream.get('n10','')
nr = norm(report)
tp, fn = 0, 0; tp_facts = []
for fact in valid_silver:
    if check(fact, nr): tp += 1; tp_facts.append(fact['fid'])
    else: fn += 1

claims = re.findall(r'[\u4e00-\u9fa5]{4,}(?:万元|亿元|元|日|公司|处罚)', report)
fp = min(sum(1 for c in claims if norm(c) not in norm(EV_TEXT_FULL) and len(c)>8), 50)
precision = tp / max(1, tp+fp)
recall = tp / max(1, tp+fn)
f1 = 2*precision*recall / max(0.001, precision+recall)

n1_text = upstream.get('n1','')
n1_tp = sum(1 for f in valid_silver if check(f, norm(n1_text)))

elapsed = time.time() - t0
total_tokens = sum(json.loads(l).get('usage',{}).get('input_tokens',0)+json.loads(l).get('usage',{}).get('output_tokens',0) for l in open('v8_n1_upgrade_LEDGER.jsonl') if l.strip())
total_calls = sum(1 for l in open('v8_n1_upgrade_LEDGER.jsonl') if l.strip())

print(f"\n{'='*70}")
print(f"V8-2 RESULT (n1→glm53 + window→6000)")
print(f"{'='*70}")
print(f"n1 extraction: {n1_tp}/22 Silver facts")
print(f"Terminal: TP={tp}, FN={fn}, FP={fp}")
print(f"TP facts: {tp_facts}")
print(f"Recall={recall:.4f} = {recall*100:.1f}%")
print(f"Precision={precision:.4f} = {precision*100:.1f}%")
print(f"Q_F1={f1:.4f} = {f1*100:.1f}%")
print(f"Calls: {total_calls}/10, Tokens: {total_tokens}, Time: {elapsed:.1f}s")

v7r = json.load(open('v7_repetition_RESULTS.json'))
v7_f1s = sorted([r['f1'] for r in v7r if r['arm']=='V7'])
v7_med = (v7_f1s[1]+v7_f1s[2])/2
print(f"\n--- V7 comparison ---")
print(f"V7 (flash@4000): Q_F1 median={v7_med:.4f}")
print(f"V8-2 (glm53@6000): Q_F1={f1:.4f}")
print(f"ΔQ_F1 = {f1 - v7_med:+.4f}")

print(f"\n--- Recovery targets ---")
for fid in ('A01','A03','A09','D07','D08','A08'):
    status = '✓ RECOVERED' if fid in tp_facts else '✗ missing'
    n1_status = '✓' if check(next(f for f in valid_silver if f['fid']==fid), norm(n1_text)) else '✗'
    print(f"  {fid}: terminal={status}  n1_extracted={n1_status}")

json.dump(dict(experiment='v8_n1_upgrade', tp=tp, fn=fn, fp=fp,
               recall=round(recall,4), precision=round(precision,4), f1=round(f1,4),
               tp_facts=tp_facts, n1_tp=n1_tp, tokens=total_tokens),
          open('v8_n1_upgrade_RESULT.json','w'), ensure_ascii=False, indent=1)
print(f"\nSaved: v8_n1_upgrade_RESULT.json")
