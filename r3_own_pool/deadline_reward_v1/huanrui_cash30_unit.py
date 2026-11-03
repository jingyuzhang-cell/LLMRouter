"""huanrui_cash30_unit.py — ¥0.030/arm 8-strategy paired unit (authorized).

D=60s, DAG v2, dual fault (n_sup1+n_sup2), CashGuard enforced.
All 8 strategies: STATIC, SD-FC, R-only, π-only, SEQ-R→π, SEQ-π→R, Alternating, JOINT.
"""
import fcntl, json, re, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import call_ds as call_flash
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_executor import load_env_creds
from cash_guard import CashGuard

D=60.0; CASH_ARM=0.030; CAP_ATTEMPTS=25; CAP_CNY=0.10
DS_URL='https://api.deepseek.com/chat/completions'
PRICE_IN,PRICE_OUT=2.13e-6,8.52e-6  # peak
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
    c=re.sub(r'[\s,，]','',str(t));h=sum(1 for k in KEYS if re.sub(r'[\s,，]','',k) in c)
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

FL_LAT={'n_sup1':7.6,'n_sup2':13.1,'verify':12.1,'sink':10.2}
DS_LAT={'n_sup1':2.4,'n_sup2':3.2,'verify':1.7,'sink':2.4}
RO={'accept':[],'repair_sup1':['n_sup1','verify','sink'],'repair_sup2':['n_sup2','verify','sink'],
    'repair_both':['n_sup1','n_sup2','verify','sink'],'full':['n_main','n_sup1','n_sup2','verify','sink']}
def nodes(R):return sorted(set(RO[R]+[n for n in['verify','sink'] if n not in RO[R]]))
def eq(R,pi):
    if R=='accept':return 0.150
    if R=='full':return 0.200
    b=0.150
    if'n_sup2'in RO[R]:b+=0.550 if pi.get('n_sup2')=='DS' else 0.500
    if'n_sup1'in RO[R]:b+=0.050 if pi.get('n_sup1')=='DS' else 0.040
    if pi.get('sink')=='DS':b+=0.100
    elif pi.get('sink')=='Flash':b+=0.050
    return min(b,0.900)

def main():
    lock=open(HERE/'cash30.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise SystemExit('lock held')
    print(f'admission: 8 strategies, budget ¥{CASH_ARM}/arm, batch cap ¥{CAP_CNY}')
    creds=load_env_creds();docs=load_docs()
    texts=[docs[s]['text'] for s in ('欢瑞世纪#E06-huanrui:E06-huanrui',
        '欢瑞世纪#E06-huanrui:E06-huanrui_sup1','欢瑞世纪#E06-huanrui:E06-huanrui_sup2')]
    ledger=open(HERE/'CASH30_LEDGER.jsonl','a')
    attempts=0;spend=0.0
    def rec(a,n,m,r,fault=False):
        nonlocal attempts,spend
        attempts+=1;spend+=r.get('cash',r.get('cash_cny',0.0))
        assert attempts<=CAP_ATTEMPTS and spend<=CAP_CNY
        ledger.write(json.dumps({'attempt':attempts,'arm':a,'node':n,'model':m,
            'in':r.get('in',r.get('tokens_in',0)),'out':r.get('out',r.get('tokens_out',0)),
            'lat':r.get('lat',r.get('latency_s',0)),'cash':r.get('cash',r.get('cash_cny',0.0)),
            'fault':fault},ensure_ascii=False)+'\n');ledger.flush()

    # PREFIX
    T0=time.monotonic()
    o=call_flash(EXT.format(doc_id='main',doc=texts[0]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_main','flash',o);main_out=o['answer']
    print(f'n_main {o["latency_s"]}s');time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup1',doc=texts[1]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup1','flash',o,fault=True);sup1_out=GARBAGE
    print(f'n_sup1 FAILED');time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup2',doc=texts[2]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup2','flash',o,fault=True);sup2_out=GARBAGE
    fault_clk=time.monotonic()-T0
    print(f'n_sup2 FAILED. fault_clk={fault_clk:.1f}s rem={D-fault_clk:.1f}s')
    time.sleep(1.1)

    # STRATEGY DECISIONS (with CashGuard budget check)
    from itertools import product
    rem=D-fault_clk
    all_actions=[]
    for R in RO:
        ns=nodes(R)
        for c in product(['Flash','DS'],repeat=len(ns)):
            pi=dict(zip(ns,c))
            lat=sum((DS_LAT if pi.get(n,'Flash')=='DS' else FL_LAT).get(n,10) for n in ns)+1.1*len(ns)
            cash=sum(CashGuard.DS_WORST.get(n,0.020) if pi.get(n,'Flash')=='DS' else 0 for n in ns)
            tok=sum({'n_sup1':800,'n_sup2':1300,'verify':2000,'sink':1200,'n_main':1000}[n]*
                    (1.5 if pi.get(n,'Flash')=='Flash' and n in('verify','sink') else 1.0) for n in ns)
            q=eq(R,pi);clk=fault_clk+lat;feas=(clk<=D)and(cash<=CASH_ARM)
            eu=q*(0 if clk>D else 1)-0.5*tok/60000-(2.0 if clk>D else 0)
            all_actions.append({'R':R,'pi':pi,'q':round(q,3),'cash':round(cash,6),
                                'clk':round(clk,1),'feas':feas,'eU':round(eu,4)})
    feas_acts=[a for a in all_actions if a['feas']]
    joint=max(feas_acts,key=lambda a:a['eU']) if feas_acts else None

    # All 8 strategies
    # R-only: best R with all-Flash
    r_only=max([a for a in feas_acts if all(v=='Flash' for v in a['pi'].values())],
               key=lambda a:a['eU'],default=None)
    # π-only: repair_both, DS→Flash fallback (CashGuard-checked)
    pi_only=max([a for a in feas_acts if a['R']=='repair_both'],key=lambda a:a['eU'],default=None)
    if not pi_only: pi_only=max([a for a in feas_acts if a['R']=='accept'],key=lambda a:a['eU'],default=None)
    # SEQ-R→π: R with Flash, then optimize pi
    seq1_R=r_only['R'] if r_only else 'accept'
    seq1=max([a for a in feas_acts if a['R']==seq1_R],key=lambda a:a['eU'],default=None)
    # SEQ-π→R: DS to important nodes, then optimize R
    seq2_cands=[a for a in feas_acts if a['R']=='repair_sup2' and a['pi'].get('n_sup2')=='DS']
    seq2=max(seq2_cands,key=lambda a:a['eU'],default=None) if seq2_cands else None
    if not seq2: seq2=max([a for a in feas_acts if a['R']=='repair_sup2'],key=lambda a:a['eU'],default=None)
    if not seq2: seq2=max(feas_acts,key=lambda a:a['eU'],default=None)
    # Alternating: iterate R and pi
    alt_R='accept'
    for _ in range(5):
        alt_cands=[a for a in feas_acts if a['R']==alt_R]
        if not alt_cands:break
        alt_pi=max(alt_cands,key=lambda a:a['eU'])['pi']
        new_R=max([a for a in feas_acts if all(a['pi'].get(k)==v for k,v in alt_pi.items() if k in nodes(a['R']))],
                  key=lambda a:a['eU'])['R']
        if new_R==alt_R:break
        alt_R=new_R
    alt=max([a for a in feas_acts if a['R']==alt_R],key=lambda a:a['eU'],default=None)

    strategies={
        'STATIC':('repair_sup2',{n:'Flash' for n in nodes('repair_sup2')}),
        'SD-FC':('repair_sup2',{n:'Flash' for n in nodes('repair_sup2')}),
        'R-only':(r_only['R'],r_only['pi']) if r_only else ('accept',{}),
        'π-only':(pi_only['R'],pi_only['pi']) if pi_only else ('accept',{}),
        'SEQ-R→π':(seq1['R'],seq1['pi']) if seq1 else ('accept',{}),
        'SEQ-π→R':(seq2['R'],seq2['pi']) if seq2 else ('accept',{}),
        'Alternating':(alt['R'],alt['pi']) if alt else ('accept',{}),
        'JOINT':(joint['R'],joint['pi']) if joint else ('accept',{}),
    }
    print('\nstrategy choices:')
    for s,(R,pi) in strategies.items():
        mixed='[MIXED]' if pi and len(set(pi.values()))>1 else ''
        print(f'  {s:14s}: {R:14s} {pi} {mixed}')

    # EXECUTE (shared same-action, with CashGuard)
    execs={}
    for strat in ('STATIC','SD-FC','R-only','π-only','SEQ-R→π','SEQ-π→R','Alternating','JOINT'):
        R,pi=strategies[strat];key=(R,tuple(sorted(pi.items())))
        if key in execs:
            print(f'  {strat:14s} -> SHARED ({execs[key]["by"]})');continue
        ns=nodes(R);outputs={'n_main':main_out}
        guard=CashGuard(cap=CASH_ARM)
        tok=0;stopped=None;arm_start=time.monotonic()
        for i,n in enumerate(ns):
            m=pi.get(n,'Flash')
            remaining_after=ns[i+1:]
            ok,action=guard.admit(n,m,remaining_after,pi)
            if not ok:
                if action[0]=='fallback':
                    m=action[2];print(f'    CashGuard: {n} DS→Flash fallback')
                elif action[0]=='degrade_R':
                    stopped=f'{n}:cash_degrade_R';break
                else:
                    stopped=f'{n}:cash_refused';break
            if n.startswith('n_'):
                di={'main':0,'sup1':1,'sup2':2}[n.replace('n_','')]
                p=EXT.format(doc_id=n.replace('n_',''),doc=texts[di])
            elif n=='verify':
                mg='\n\n'.join(f'### {k}的输出：\n{v}' for k,v in outputs.items() if k.startswith('n_'))
                p=VER.format(merged=mg[:4000])
            else:
                all_facts=[]
                for dk,dv in outputs.items():
                    if not dk.startswith('n_'):continue
                    try:
                        items=parse_a(dv)  # FIX: strips markdown fences before parsing
                        if isinstance(items,list):
                            for j,item in enumerate(items):
                                if isinstance(item,dict):
                                    all_facts.append({'fact_id':f'{dk}_f{j}','fact':str(item.get('fact',''))[:200],
                                                      'doc_id':dk.replace('n_',''),'date':str(item.get('date',''))})
                    except:pass
                fj=json.dumps(all_facts,ensure_ascii=False)[:6000]
                vj=str(outputs.get('verify',''))[:2000] if outputs.get('verify') else '[]'
                p=SNK.format(facts_json=fj,verdicts_json=vj)
            if m=='DS':
                try:r=call_ds_api(p,creds)
                except Exception as e:
                    rec(strat,n,'DS',{'in':0,'out':0,'lat':0,'cash':0,'stop':f'ERR:{type(e).__name__}'})
                    stopped=f'{n}:{type(e).__name__}';break
                guard.record(n,'DS',r['cash'])
            else:
                try:r=call_flash(p,creds,max_out_tokens=OUT_CAP)
                except Exception as e:
                    rec(strat,n,'flash',{'tokens_in':0,'tokens_out':0,'latency_s':0,'cash_cny':0})
                    stopped=f'{n}:{type(e).__name__}';break
                guard.record(n,'Flash',0.0)
            rn={'in':r.get('in',r.get('tokens_in',0)),'out':r.get('out',r.get('tokens_out',0)),
                'lat':r.get('lat',r.get('latency_s',0)),'cash':r.get('cash',r.get('cash_cny',0.0))}
            rec(strat,n,'DS' if m=='DS' else 'flash',rn)
            if r.get('stop',r.get('finish_reason',''))in('length','max_tokens'):
                stopped=f'{n}:TRUNC';break
            outputs[n]=r.get('answer','')
            tok+=rn['in']+rn['out']
            time.sleep(1.1)
        clk=fault_clk+(time.monotonic()-arm_start)
        if stopped:
            execs[key]={'stopped':stopped,'tokens':tok,'clock':round(clk,1),'by':strat,
                        'cash':guard.summary()}
            print(f'  {strat:14s} STOPPED {stopped}');break
        q,h,nr=silver(outputs.get('sink',''))
        eu=q*(0 if clk>D else 1)-0.5*tok/60000-(2.0 if clk>D else 0)
        execs[key]={'t_q':round(q,4),'hits':h,'n_ref':nr,'tokens':tok,'clock':round(clk,1),
                    'met':clk<=D,'eU':round(eu,4),'by':strat,'cash':guard.summary()}
        print(f'  {strat:14s} {R:14s} q={q:.3f}({h}/{nr}) tok={tok} clk={clk:.1f}s '
              f'cash=¥{guard.spent:.4f}/{CASH_ARM} eU={eu:+.4f}')

    # TABLE
    print('\n'+'='*100)
    print(f"{'Strategy':14s} {'R':14s} {'pi':36s} {'t_q':>6s} {'tok':>6s} {'clk':>6s} {'cash':>8s} {'eU':>8s}")
    rows=[]
    for s in ('STATIC','SD-FC','R-only','π-only','SEQ-R→π','SEQ-π→R','Alternating','JOINT'):
        R,pi=strategies[s];key=(R,tuple(sorted(pi.items())));e=execs.get(key,{})
        pi_s=str({k:v[:2] for k,v in sorted(pi.items())}) if pi else '{}'
        if'stopped'in e:
            print(f'{s:14s} {R:14s} {pi_s:36s} STOPPED:{e["stopped"]}')
            rows.append({'arm':s,'R':R,'stopped':e['stopped']})
        else:
            cs=e.get('cash',{})
            print(f'{s:14s} {R:14s} {pi_s:36s} {e.get("t_q",0):6.3f} {e.get("tokens",0):6d} '
                  f'{e.get("clock",0):6.1f} ¥{cs.get("spent",0):7.4f} {e.get("eU",0):+8.4f}')
            rows.append({'arm':s,'R':R,'pi':pi,'t_q':e.get('t_q'),'hits':e.get('hits'),
                'tokens':e.get('tokens'),'clock':e.get('clock'),'cash':cs.get('spent'),
                'compliant':cs.get('compliant'),'eU':e.get('eU')})
    by={r['arm']:r for r in rows if r.get('eU') is not None}
    if by.get('JOINT'):
        J=by['JOINT']['eU']
        print('\nJOINT differences:')
        for a in ('Alternating','SEQ-π→R','SEQ-R→π','π-only','R-only','SD-FC'):
            v=by.get(a,{}).get('eU')
            print(f'  JOINT - {a:14s} = {J-v:+.4f}' if v is not None else f'  JOINT - {a:14s} = N/A')
        jp=by.get('JOINT',{}).get('pi',{})
        if jp and len(set(jp.values()))>1:
            print(f'\n★ JOINT MIXED π: Flash={[k for k,v in jp.items() if v=="Flash"]} DS={[k for k,v in jp.items() if v=="DS"]}')
        jc=by.get('JOINT',{}).get('compliant')
        print(f'★ JOINT cash compliant: {jc}')
    all_compliant=all(r.get('compliant',True) for r in rows if 'compliant' in r)
    print(f'\n★ ALL ARMS CASH COMPLIANT: {all_compliant}')
    json.dump({'unit':f'huanrui D=60s cash=¥{CASH_ARM}/arm 8-strategy',
        'fault_clk':round(fault_clk,1),'strategies':{k:{'R':v[0],'pi':v[1]} for k,v in strategies.items()},
        'rows':rows,'attempts':attempts,'cash':round(spend,4)},
        open(HERE/'CASH30_RESULT.json','w'),ensure_ascii=False,indent=1)
    print(f'\nUNIT DONE: {attempts}/{CAP_ATTEMPTS} attempts, ¥{spend:.4f}/{CAP_CNY}')

if __name__=='__main__':main()
