"""huanrui_cash_constrained_unit.py — D=60s + cash_cap=¥0.005 七策略配对。

AUTHORIZED: validates the Q/C/L re-enumeration finding that mixed π is
optimal under tight cash budgets. JOINT should choose repair_sup2 +
{n_sup2:Flash, verify:DS, sink:DS} (¥0.0036 ≤ ¥0.005).

Caps: <=25 HTTP attempts, cash <= ¥0.08 (includes DS calls in strategies).
"""
import fcntl, json, re, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import call_ds as call_flash
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_executor import load_env_creds

D=60.0; CASH_CAP=0.005; CAP_ATTEMPTS=25; CAP_CNY=0.08
DS_URL='https://api.deepseek.com/chat/completions'
PRICE_IN,PRICE_OUT=2.13e-6,8.52e-6  # peak (running now)
OUT_CAP=3072

EXT=('你是一个资本市场事件调查助手。\\n## 节点任务类型：extraction（信息入口）\\n'
     '## 证据文档 doc_id：{doc_id}\\n## 文档内容：\\n{doc}\\n\\n'
     '## 任务要求：从证据文档抽取原子事实（事实陈述、日期、数值、涉事主体），'
     '每条须含 fact, date, entities, evidence_doc_id 字段。\\n'
     '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
VER=('你是一个资本市场事件调查助手。\\n## 节点任务类型：verify（跨公告一致性核验）\\n'
     '## 上游三份抽取输出（唯一信息来源）：\\n{merged}\\n\\n'
     '## 任务要求：核验同一事件在三份公告中的日期、金额、处罚/风险状态是否一致、'
     '互补或冲突。输出每条含 item, doc_a, doc_b, verdict(CONSISTENT|COMPLEMENT|CONFLICT|UNRESOLVED), note。\\n'
     '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
SNK=('你是一个资本市场事件调查助手。\\n## 节点任务类型：synthesis（最终事件分析）\\n'
     '## 完整事实集（来自merge节点，直接传入）：\\n{facts_json}\\n\\n'
     '## 核验判定（来自verify节点）：\\n{verdicts_json}\\n\\n'
     '## 任务要求：综合事实集与核验判定输出事件调查结论。'
     '金额、日期等具体数值必须来自事实集原文。未核验事实标注 UNVERIFIED。\\n'
     '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
GARBAGE='[{"fact":"占位","evidence_doc_id":"?"}]'
KEYS=['2026年4月21日','2026年4月22日','2026年9月18日','2026年9月23日','2026年1月1日',
      '2026年6月30日','2026年7月14日','12,500.00万元','12,300.00万元','19,804.88万元',
      '24,500.00万元','2,187.21万元','639.38万元','200.00万元','0.01元','0.13元',
      '告知书','处罚','立案','虚假']
def silver(t):
    c=re.sub(r'[\s,，]','',str(t))
    h=sum(1 for k in KEYS if re.sub(r'[\s,，]','',k) in c)
    return h/len(KEYS),h,len(KEYS)
def parse_a(t):
    t=t.strip();m=re.search(r'```(?:json)?\s*(.+?)```',t,re.S)
    if m:t=m.group(1).strip()
    i=t.find('[')
    if i>0:t=t[i:]
    return json.loads(t)
def call_ds_api(p,c):
    import urllib.request
    body={'model':'deepseek-flash','max_tokens':OUT_CAP,
          'messages':[{'role':'user','content':p}],'thinking':{'type':'disabled'}}
    req=urllib.request.Request(DS_URL,data=json.dumps(body).encode(),method='POST')
    req.add_header('Content-Type','application/json')
    req.add_header('Authorization','Bearer '+c['DEEPSEEK_API_KEY'])
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r:
        d=json.loads(r.read().decode())
    u=d['usage']
    return {'answer':d['choices'][0]['message'].get('content',''),
            'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),
            'lat':round(time.monotonic()-t0,2),
            'cash':(u.get('prompt_tokens',0)*PRICE_IN+u.get('completion_tokens',0)*PRICE_OUT)}

# Measured stats for predictions
FL_LAT={'n_sup2':13.1,'verify':12.1,'sink':10.2}
DS_LAT={'n_sup2':3.2,'verify':1.7,'sink':2.4}
DS_CASH={'n_sup2':0.0037,'verify':0.0015,'sink':0.0021}

def main():
    lock=open(HERE/'cash_unit.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise SystemExit('lock held')
    att_worst=3+3+2+3+2+5  # prefix + 5 distinct physical actions
    assert att_worst<=CAP_ATTEMPTS
    print(f'admission: {att_worst} attempts<={CAP_ATTEMPTS}, DS budget¥{CAP_CNY}')
    creds=load_env_creds();docs=load_docs()
    texts=[docs[s]['text'] for s in ('欢瑞世纪#E06-huanrui:E06-huanrui',
        '欢瑞世纪#E06-huanrui:E06-huanrui_sup1','欢瑞世纪#E06-huanrui:E06-huanrui_sup2')]
    ledger=open(HERE/'CASH_UNIT_LEDGER.jsonl','a')
    attempts=0;spend=0.0
    def rec(a,n,m,r,fault=False):
        nonlocal attempts,spend
        attempts+=1;spend+=r.get('cash',r.get('cash_cny',0.0))
        assert attempts<=CAP_ATTEMPTS and spend<=CAP_CNY
        ledger.write(json.dumps({'attempt':attempts,'arm':a,'node':n,'model':m,
            'in':r.get('in',r.get('tokens_in',0)),'out':r.get('out',r.get('tokens_out',0)),
            'lat':r.get('lat',r.get('latency_s',0)),'cash':r.get('cash',r.get('cash_cny',0.0)),
            'fault':fault},ensure_ascii=False)+'\n');ledger.flush()

    # === PREFIX ===
    T0=time.monotonic()
    o=call_flash(EXT.format(doc_id='main',doc=texts[0]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_main','flash',o);main_out=o['answer']
    print(f'n_main {o["latency_s"]}s');time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup1',doc=texts[1]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup1','flash',o);sup1_out=o['answer']
    print(f'n_sup1 {o["latency_s"]}s');time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup2',doc=texts[2]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup2','flash',o,fault=True)
    fault_clk=time.monotonic()-T0
    print(f'n_sup2 FAILED. fault_clk={fault_clk:.1f}s rem={D-fault_clk:.1f}s cash_rem=¥{CASH_CAP:.4f}')
    time.sleep(1.1)

    # === STRATEGY DECISIONS (with CASH budget) ===
    rem=D-fault_clk; rem_cash=CASH_CAP
    # Predicted lat/cash per action
    def pred(R,pi):
        ns={'accept':['verify','sink'],
            'repair_sup2':['n_sup2','verify','sink'],
            'repair_both':['n_sup1','n_sup2','verify','sink'],
            'full':['n_main','n_sup1','n_sup2','verify','sink']}[R]
        lat=sum((DS_LAT if pi.get(n)=='DS' else FL_LAT).get(n,10) for n in ns)+1.1*len(ns)
        cash=sum(DS_CASH.get(n,0) if pi.get(n)=='DS' else 0 for n in ns)
        return lat,cash

    # Quality estimates (v2 contract)
    QH={'accept':0.150,'repair_sup2':0.700,'repair_both':0.750,'full':0.200}
    def uh(R,pi):
        lat,cash=pred(R,pi)
        late=fault_clk+lat>D
        over=cash>rem_cash
        q=QH.get(R,0.150)
        # sink model bonus
        if pi.get('sink')=='DS':q+=0.100
        elif pi.get('sink')=='Flash':q+=0.050
        return q*(0 if late or over else 1)-(2.0 if late or over else 0)

    # Enumerate all (R,pi) combos
    from itertools import product
    all_actions=[]
    for R in ('accept','repair_sup2','repair_both','full'):
        ns={'accept':['verify','sink'],'repair_sup2':['n_sup2','verify','sink'],
            'repair_both':['n_sup1','n_sup2','verify','sink'],
            'full':['n_main','n_sup1','n_sup2','verify','sink']}[R]
        for c in product(['Flash','DS'],repeat=len(ns)):
            pi=dict(zip(ns,c))
            lat,cash=pred(R,pi)
            feas=(fault_clk+lat<=D)and(cash<=rem_cash)
            eu=uh(R,pi)
            all_actions.append({'R':R,'pi':pi,'lat':round(lat,1),'cash':round(cash,6),
                                'feas':feas,'eU':round(eu,4)})
    joint=max([a for a in all_actions if a['feas']],key=lambda a:a['eU'])

    # Strategy choices
    # R-only: all-Flash, feasibility check
    r_R='accept'
    for R in ('repair_sup2','repair_both'):
        lat,cash=pred(R,{n:'Flash' for n in ['n_sup2','verify','sink']})
        if fault_clk+lat<=D:r_R=R;break
    # π-only: fixed repair_both, DS first if affordable
    pi_R='repair_both';pi_pi={}
    rc=rem_cash
    for n in ['n_sup2','verify','sink']:
        if rc>=DS_CASH[n]:pi_pi[n]='DS';rc-=DS_CASH[n]
        else:pi_pi[n]='Flash'
    pi_lat,pi_cash=pred(pi_R,pi_pi)
    if fault_clk+pi_lat>D or pi_cash>rem_cash:pi_R='accept';pi_pi={}
    # SEQ-R→π: R with Flash, then optimize
    seq1_R=r_R
    seq1_ns={'accept':['verify','sink'],'repair_sup2':['n_sup2','verify','sink'],
             'repair_both':['n_sup1','n_sup2','verify','sink']}[seq1_R]
    seq1_best=None
    for c in product(['Flash','DS'],repeat=len(seq1_ns)):
        pi=dict(zip(seq1_ns,c))
        lat,cash=pred(seq1_R,pi)
        if fault_clk+lat<=D and cash<=rem_cash:
            eu=uh(seq1_R,pi)
            if seq1_best is None or eu>seq1_best[0]:seq1_best=(eu,pi)
    # SEQ-π→R: DS to important nodes first, then optimize R
    best_s2=None
    for R in ('repair_sup2','repair_both','accept'):
        ns={'accept':['verify','sink'],'repair_sup2':['n_sup2','verify','sink'],
            'repair_both':['n_sup1','n_sup2','verify','sink']}[R]
        pi={};rc=rem_cash
        for n in ['n_sup2','sink','verify']:  # importance order
            if n in ns and rc>=DS_CASH.get(n,0):
                pi[n]='DS';rc-=DS_CASH[n]
            elif n in ns:pi[n]='Flash'
        for n in ns:
            if n not in pi:pi[n]='Flash'
        lat,cash=pred(R,pi)
        if fault_clk+lat<=D and cash<=rem_cash:
            eu=uh(R,pi)
            if best_s2 is None or eu>best_s2[0]:best_s2=(eu,R,pi)

    strategies={
        'STATIC':('repair_sup2',{n:'Flash' for n in ['n_sup2','verify','sink']}),
        'SD-FC':('repair_sup2',{n:'Flash' for n in ['n_sup2','verify','sink']}),
        'R-only':(r_R,{n:'Flash' for n in ['verify','sink']}),
        'π-only':(pi_R,pi_pi),
        'SEQ-R→π':(seq1_R,seq1_best[1] if seq1_best else {}),
        'SEQ-π→R':(best_s2[1],best_s2[2]) if best_s2 else ('accept',{}),
        'JOINT':(joint['R'],joint['pi']),
    }
    print(f'\nstrategy choices:')
    for s,(R,pi) in strategies.items():
        mixed='[MIXED]' if pi and len(set(pi.values()))>1 else ''
        print(f'  {s:12s}: {R:14s} {pi} {mixed}')

    # === EXECUTE (shared same-action) ===
    execs={}
    NODE_MAP={'accept':['verify','sink'],'repair_sup2':['n_sup2','verify','sink'],
              'repair_both':['n_sup1','n_sup2','verify','sink'],'full':['n_main','n_sup1','n_sup2','verify','sink']}
    for strat in ('STATIC','SD-FC','R-only','π-only','SEQ-R→π','SEQ-π→R','JOINT'):
        R,pi=strategies[strat];key=(R,tuple(sorted(pi.items())))
        if key in execs:
            print(f'  {strat:12s} -> SHARED ({execs[key]["by"]})');continue
        nodes=NODE_MAP[R];outputs={'n_main':main_out,'n_sup1':sup1_out}
        tok=0;arm_cash=0;stopped=None;arm_start=time.monotonic()
        for n in nodes:
            m=pi.get(n,'Flash')
            if n.startswith('n_'):
                di={'main':0,'sup1':1,'sup2':2}[n.replace('n_','')]
                p=EXT.format(doc_id=n.replace('n_',''),doc=texts[di])
            elif n=='verify':
                mg='\n\n'.join(f'### {k}的输出：\n{v}' for k,v in outputs.items() if k.startswith('n_'))
                p=VER.format(merged=mg[:4000])
            else:
                # FIX: properly parse extraction JSON into individual facts (v2 contract)
                all_facts = []
                for doc_key, doc_text in outputs.items():
                    if not doc_key.startswith('n_'): continue
                    try:
                        items = json.loads(doc_text)
                        if isinstance(items, list):
                            for j, item in enumerate(items):
                                if isinstance(item, dict):
                                    all_facts.append({'fact_id': f'{doc_key}_f{j}',
                                                      'fact': str(item.get('fact',''))[:200],
                                                      'doc_id': doc_key.replace('n_',''),
                                                      'date': str(item.get('date','')),
                                                      'quote': str(item.get('quote',''))[:80]})
                    except (json.JSONDecodeError, TypeError):
                        pass
                facts_json = json.dumps(all_facts, ensure_ascii=False)[:6000]
                verdicts_json = str(outputs.get('verify',''))[:2000] if outputs.get('verify') else '[]'
                p=SNK.format(facts_json=facts_json, verdicts_json=verdicts_json)
            if m=='DS':
                est_cash=int(len(p)*0.721)*PRICE_IN+OUT_CAP*PRICE_OUT
                
                try:r=call_ds_api(p,creds)
                except Exception as e:
                    rec(strat,n,'DS',{'in':0,'out':0,'lat':0,'cash':0,'stop':f'ERR:{type(e).__name__}'})
                    stopped=f'{n}:{type(e).__name__}';break
            else:
                try:r=call_flash(p,creds,max_out_tokens=OUT_CAP)
                except Exception as e:
                    rec(strat,n,'flash',{'tokens_in':0,'tokens_out':0,'latency_s':0,'cash_cny':0})
                    stopped=f'{n}:{type(e).__name__}';break
            rn={'in':r.get('in',r.get('tokens_in',0)),'out':r.get('out',r.get('tokens_out',0)),
                'lat':r.get('lat',r.get('latency_s',0)),'cash':r.get('cash',r.get('cash_cny',0.0))}
            rec(strat,n,'DS' if m=='DS' else 'flash',rn)
            if r.get('stop',r.get('finish_reason','')) in('length','max_tokens'):
                stopped=f'{n}:TRUNC';break
            outputs[n]=r.get('answer','')
            tok+=rn['in']+rn['out'];arm_cash+=rn['cash']
            time.sleep(1.1)
        clk=fault_clk+(time.monotonic()-arm_start)
        if stopped:
            execs[key]={'stopped':stopped,'tokens':tok,'clock':round(clk,1),'cash':round(arm_cash,6),'by':strat}
            print(f'  {strat:12s} STOPPED {stopped}');break
        q,h,nr=silver(outputs.get('sink',''))
        eu=q*(0 if clk>D else 1)-0.5*tok/60000-(2.0 if clk>D else 0)
        execs[key]={'t_q':round(q,4),'hits':h,'n_ref':nr,'tokens':tok,'clock':round(clk,1),
                    'met':clk<=D,'cash':round(arm_cash,6),'eU':round(eu,4),'by':strat}
        print(f'  {strat:12s} {R:14s} q={q:.3f}({h}/{nr}) tok={tok} clk={clk:.1f}s cash=¥{arm_cash:.4f} eU={eu:+.4f}')

    # === TABLE ===
    print('\n'+'='*90)
    print(f"{'Strategy':12s} {'R':14s} {'pi':30s} {'t_q':>6s} {'tok':>6s} {'clk':>6s} {'cash':>8s} {'eU':>8s}")
    rows=[]
    for s in ('STATIC','SD-FC','R-only','π-only','SEQ-R→π','SEQ-π→R','JOINT'):
        R,pi=strategies[s];key=(R,tuple(sorted(pi.items())))
        e=execs.get(key,{})
        pi_s=str({k:v[:2] for k,v in sorted(pi.items())}) if pi else '{}'
        if 'stopped'in e:
            print(f'{s:12s} {R:14s} {pi_s:30s} STOPPED:{e["stopped"]}')
            rows.append({'arm':s,'R':R,'stopped':e['stopped']})
        else:
            print(f'{s:12s} {R:14s} {pi_s:30s} {e.get("t_q",0):6.3f} {e.get("tokens",0):6d} {e.get("clock",0):6.1f} ¥{e.get("cash",0):7.4f} {e.get("eU",0):+8.4f}')
            rows.append({'arm':s,'R':R,'pi':pi,'t_q':e.get('t_q'),'hits':e.get('hits'),
                'tokens':e.get('tokens'),'clock':e.get('clock'),'cash':e.get('cash'),'eU':e.get('eU')})
    by={r['arm']:r for r in rows if r.get('eU') is not None}
    if by.get('JOINT'):
        J=by['JOINT']['eU']
        print('\nJOINT differences:')
        for a in ('SEQ-π→R','SEQ-R→π','π-only','R-only','SD-FC'):
            v=by.get(a,{}).get('eU')
            print(f'  JOINT - {a:12s} = {J-v:+.4f}' if v is not None else f'  JOINT - {a:12s} = N/A')
        # Mixed pi check
        jp=by.get('JOINT',{}).get('pi',{})
        if jp and len(set(jp.values()))>1:
            print(f'\n★ JOINT chose MIXED π: Flash={[k for k,v in jp.items() if v=="Flash"]} DS={[k for k,v in jp.items() if v=="DS"]}')
    json.dump({'unit':'huanrui D=60s cash_cap=¥0.005',
        'fault_clk':round(fault_clk,1),'cash_rem':rem_cash,
        'strategies':{k:{'R':v[0],'pi':v[1]} for k,v in strategies.items()},
        'rows':rows,'attempts':attempts,'cash':round(spend,4)},
        open(HERE/'CASH_UNIT_RESULT.json','w'),ensure_ascii=False,indent=1)
    print(f'\nUNIT DONE: {attempts}/{CAP_ATTEMPTS} attempts, ¥{spend:.4f}/{CAP_CNY}')

if __name__=='__main__':main()
