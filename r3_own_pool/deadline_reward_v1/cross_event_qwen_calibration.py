"""cross_event_qwen_calibration.py — Qwen-plus third-model calibration (10 calls).

PURPOSE: Test whether a third model breaks the quality monotonicity
(DS >= Flash on every dimension) that causes JOINT ≡ π-only.

If qwen has DIFFERENT strengths (e.g., better extraction but worse sink),
the quality model becomes non-monotone → mixed π truly optimal → JOINT has
unique value that sequential/alternating strategies cannot find.

Authorized: <=10 calls, ~50K tokens, ~¥0.15 cash (qwen ¥0.8/M in, ¥2/M out).
Same prompts/inputs as Flash/DS calibration (input-comparable).
"""
import fcntl, json, re, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_executor import load_env_creds

DS_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
PRICE_IN, PRICE_OUT = 0.8e-6, 2.0e-6  # CNY per token
OUT_CAP = 3072
CAP_ATTEMPTS = 10
CAP_CNY = 0.15

EXT = ('你是一个资本市场事件调查助手。\\n## 节点任务类型：extraction（信息入口）\\n'
       '## 证据文档 doc_id：{doc_id}\\n## 文档内容：\\n{doc}\\n\\n'
       '## 任务要求：从证据文档抽取原子事实（事实陈述、日期、数值、涉事主体），'
       '每条须含 fact, date, entities, evidence_doc_id 字段。\\n'
       '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
VER = ('你是一个资本市场事件调查助手。\\n## 节点任务类型：verify（跨公告一致性核验）\\n'
       '## 上游三份抽取输出（唯一信息来源）：\\n{merged}\\n\\n'
       '## 任务要求：核验同一事件在三份公告中的日期、金额、处罚/风险状态是否一致、'
       '互补或冲突。输出每条含 item, doc_a, doc_b, verdict(CONSISTENT|COMPLEMENT|CONFLICT|UNRESOLVED), note。\\n'
       '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
SNK = ('你是一个资本市场事件调查助手。\\n## 节点任务类型：synthesis（最终事件分析）\\n'
       '## 上游核验输出（唯一信息来源）：\\n{verified}\\n\\n'
       '## 任务要求：综合三份公告输出事件调查结论，输出JSON数组，每条含 conclusion, '
       'timeline[], amounts[], penalties[], entities[], cross_doc_verdicts[]；'
       '每个条目标注 evidence_doc_id；未确认事项标注 UNRESOLVED。\\n'
       '## 输出要求：JSON数组，禁止输出任何非JSON文本。')

# Silver scoring keys (same as Flash/DS validation)
KEYS_HUANRUI = ['2026年4月21日','2026年4月22日','2026年9月18日','2026年9月23日','2026年1月1日',
                '2026年6月30日','2026年7月14日','12,500.00万元','12,300.00万元','19,804.88万元',
                '24,500.00万元','2,187.21万元','639.38万元','200.00万元','0.01元','0.13元',
                '告知书','处罚','立案','虚假']
KEYS_ZORAN = ['2025年12月20日','2025年12月19日','2026年9月10日','2026年10月12日','2026年10月13日',
              '2026年10月9日','2026年9月11日','2026年9月12日','2026年9月18日','2026年9月23日',
              '2026年9月24日','2026年9月25日','0.96元','1.16元','2.24亿元','2.71亿元',
              '1,372.33万元','12.25%','12.96%','148.33%','22,429.51万元','23,142.16万元',
              '36,256.34万元','4,383.65万元','5.13%','556.72万元','8.15%','立案','虚假','退市']

def silver(text, keys):
    c = re.sub(r'[\s,，]', '', str(text))
    h = sum(1 for k in keys if re.sub(r'[\s,，]', '', k) in c)
    return h / len(keys), h, len(keys)

def parse_a(t):
    t = t.strip(); m = re.search(r'```(?:json)?\s*(.+?)```', t, re.S)
    if m: t = m.group(1).strip()
    i = t.find('[')
    if i > 0: t = t[i:]
    return json.loads(t)

def call_qwen(prompt, creds):
    import urllib.request
    body = {'model': 'qwen-plus', 'max_tokens': OUT_CAP,
            'messages': [{'role': 'user', 'content': prompt}],
            'response_format': {'type': 'json_object'}}
    req = urllib.request.Request(DS_URL, data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + creds['DASHSCOPE_API_KEY'])
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    content = d['choices'][0]['message'].get('content', '')
    if isinstance(content, list):
        content = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
    u = d['usage']
    return {'answer': content,
            'in': u.get('prompt_tokens', 0), 'out': u.get('completion_tokens', 0),
            'lat': round(time.monotonic() - t0, 2),
            'stop': d['choices'][0].get('finish_reason', ''),
            'cash': (u.get('prompt_tokens', 0) * PRICE_IN + u.get('completion_tokens', 0) * PRICE_OUT)}

def main():
    lock = open(HERE / 'qwen_calib.lock', 'w')
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError: raise SystemExit('lock held')
    creds = load_env_creds()
    docs = load_docs()

    # Load Flash/DS calibration _texts for chain wiring (use DS extractions)
    ds_cal = json.loads(open(HERE / 'CROSS_DS_CALIB_RESULT.json').read())
    ds_texts = {ev: ds_cal['results'].get(ev, {}).get('_texts', {}) for ev in ('huanrui', 'zoran')}

    ledger = open(HERE / 'QWEN_CALIB_LEDGER.jsonl', 'a')
    results = {}
    attempts = 0; spend = 0.0

    for ev, slots, keys in [
        ('huanrui', ['欢瑞世纪#E06-huanrui:E06-huanrui',
                     '欢瑞世纪#E06-huanrui:E06-huanrui_sup1',
                     '欢瑞世纪#E06-huanrui:E06-huanrui_sup2'], KEYS_HUANRUI),
        ('zoran', ['*ST卓然#E04-zhuoran:E04-zhuoran',
                   '*ST卓然#E04-zhuoran:E04-zhuoran_sup1',
                   '*ST卓然#E04-zhuoran:E04-zhuoran_sup2'], KEYS_ZORAN),
    ]:
        texts = [docs[s]['text'] for s in slots]
        ev_results = {}
        qwen_outputs = {}

        for node, doc_id, doc in [('n_main','main',texts[0]), ('n_sup1','sup1',texts[1]), ('n_sup2','sup2',texts[2])]:
            attempts += 1
            if attempts > CAP_ATTEMPTS:
                print(f'CAP reached at {ev}/{node}'); break
            prompt = EXT.format(doc_id=doc_id, doc=doc)
            est = int(len(prompt)*0.721)*PRICE_IN + OUT_CAP*PRICE_OUT
            assert spend + est <= CAP_CNY, f'cash cap: {spend}+{est}>{CAP_CNY}'
            try:
                r = call_qwen(prompt, creds)
            except Exception as e:
                ledger.write(json.dumps({'attempt':attempts,'event':ev,'node':node,
                    'anomaly':f'{type(e).__name__}'},ensure_ascii=False)+'\n')
                print(f'  {ev}/{node}: ANOMALY {type(e).__name__} — STOP'); return
            spend += r['cash']
            try:
                items = parse_a(r['answer']); n = len(items); parsed = True
            except: items, n, parsed = None, 0, False
            rec = {'event':ev,'node':node,'in':r['in'],'out':r['out'],'lat':r['lat'],
                   'parsed':parsed,'n_items':n,'cash':round(r['cash'],6),
                   'truncated':r['stop'] in ('length','max_tokens')}
            ev_results[node] = rec; qwen_outputs[node] = r['answer']
            ledger.write(json.dumps({'attempt':attempts,**rec},ensure_ascii=False)+'\n'); ledger.flush()
            print(f"  {ev:8s}/{node:14s} in={r['in']:5d} out={r['out']:4d} lat={r['lat']:5.1f}s "
                  f"parsed={parsed} n={n:3d} ¥{r['cash']:.4f} cum=¥{spend:.4f}")
            time.sleep(1.1)

        # verify on qwen extractions
        if len(qwen_outputs) >= 3:
            attempts += 1
            merged = '\n\n'.join(f'### {k}的输出：\n{v}' for k,v in qwen_outputs.items() if k.startswith('n_'))
            prompt = VER.format(merged=merged[:4000])
            est = int(len(prompt)*0.721)*PRICE_IN + OUT_CAP*PRICE_OUT
            assert spend + est <= CAP_CNY
            try:
                r = call_qwen(prompt, creds)
            except Exception as e:
                print(f'  {ev}/verify: ANOMALY {type(e).__name__} — STOP'); return
            spend += r['cash']
            try: items = parse_a(r['answer']); n = len(items); parsed = True
            except: n, parsed = 0, False
            rec = {'event':ev,'node':'verify','in':r['in'],'out':r['out'],'lat':r['lat'],
                   'parsed':parsed,'n_items':n if parsed else 0,'cash':round(r['cash'],6)}
            ev_results['verify'] = rec; qwen_outputs['verify'] = r['answer']
            ledger.write(json.dumps({'attempt':attempts,**rec},ensure_ascii=False)+'\n'); ledger.flush()
            print(f"  {ev:8s}/{'verify':14s} in={r['in']:5d} out={r['out']:4d} lat={r['lat']:5.1f}s parsed={parsed} n={n}")
            time.sleep(1.1)

            # sink
            attempts += 1
            prompt = SNK.format(verified=r['answer'][:3000])
            est = int(len(prompt)*0.721)*PRICE_IN + OUT_CAP*PRICE_OUT
            assert spend + est <= CAP_CNY
            try:
                r2 = call_qwen(prompt, creds)
            except Exception as e:
                print(f'  {ev}/sink: ANOMOLY {type(e).__name__} — STOP'); return
            spend += r2['cash']
            q, h, n_ref = silver(r2['answer'], keys)
            rec = {'event':ev,'node':'sink','in':r2['in'],'out':r2['out'],'lat':r2['lat'],
                   'parsed':True,'silver':round(q,4),'hits':h,'n_ref':n_ref,'cash':round(r2['cash'],6)}
            ev_results['sink'] = rec
            ledger.write(json.dumps({'attempt':attempts,**rec},ensure_ascii=False)+'\n'); ledger.flush()
            print(f"  {ev:8s}/{'sink':14s} in={r2['in']:5d} out={r2['out']:4d} lat={r2['lat']:5.1f}s "
                  f"Silver={q:.3f}({h}/{n_ref}) ¥{r2['cash']:.4f}")
            # Store _texts for later use
            ev_results['_texts'] = {k:v for k,v in qwen_outputs.items() if k.startswith('n_')}

        results[ev] = ev_results

    json.dump({'results':results,'attempts':attempts,'cash':round(spend,4),
               'note':'qwen-plus third-model calibration; same prompts as Flash/DS'},
              open(HERE/'QWEN_CALIB_RESULT.json','w'),ensure_ascii=False,indent=1)
    print(f'\nDONE: {attempts} attempts, ¥{spend:.4f}/{CAP_CNY}')

if __name__ == '__main__':
    main()
