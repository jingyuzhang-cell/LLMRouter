"""zoran_unit.py — *ST卓然 F-sup2 D=70s 七策略配对（authorized 2026-10-27）。

Preflight (zero-call): D=70s from measured Flash/DS cross-event calibration.
- Prefix (3 Flash serial): ~51.5s (zoran docs are larger: 691/3272/2626c)
- targeted+DS total ~59.4s (margin 10.6s) FEASIBLE
- targeted+Flash total ~121.7s LATE
- accept+Flash total ~113.9s LATE (ALL Flash arms late at D=70!)
- accept+DS total ~56.9s FEASIBLE
- full+DS total ~69.7s (margin 0.3s borderline)
=> Only DS arms feasible; Flash forced late for ALL strategies.

Admission: 18 attempts <= 30; DS 10 calls off-peak worst ¥0.08 <= ¥0.20.
Serial executor K=1; per-arm clock (isolated, fault_clk + own latency).
"""
import fcntl, json, re, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import call_ds as call_flash
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_executor import load_env_creds

D=70.0; CAP_ATTEMPTS=30; CAP_CNY=0.20
DS_URL='https://api.deepseek.com/chat/completions'
PRICE_IN,PRICE_OUT=1.065e-6,4.26e-6  # off-peak
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
     '## 上游核验输出（唯一信息来源）：\\n{verified}\\n\\n'
     '## 任务要求：综合三份公告输出事件调查结论，输出JSON数组，每条含 conclusion, '
     'timeline[], amounts[], penalties[], entities[], cross_doc_verdicts[]；'
     '每个条目标注 evidence_doc_id；未确认事项标注 UNRESOLVED。\\n'
     '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
GARBAGE='[{"fact":"占位","evidence_doc_id":"?"}]'

# Zoran key_facts (CT01+CT02, 30 unique)
KEYS=['2025年12月20日','2025年12月19日','2026年9月10日','2026年10月12日','2026年10月13日',
      '2026年10月9日','2026年9月11日','2026年9月12日','2026年9月18日','2026年9月23日',
      '2026年9月24日','2026年9月25日','0.96元','1.16元','2.24亿元','2.71亿元',
      '1,372.33万元','12.25%','12.96%','148.33%','22,429.51万元','23,142.16万元',
      '36,256.34万元','4,383.65万元','5.13%','556.72万元','8.15%',
      '立案','虚假','退市']
def silver(text):
    c=re.sub(r'[\s,，]','',str(text))
    h=sum(1 for k in KEYS if re.sub(r'[\s,，]','',k) in c)
    return h/len(KEYS),h,len(KEYS)
def parse_a(t):
    t=t.strip(); m=re.search(r'```(?:json)?\s*(.+?)```',t,re.S)
    if m: t=m.group(1).strip()
    i=t.find('[')
    if i>0: t=t[i:]
    return json.loads(t)
def call_ds_api(prompt,creds):
    import urllib.request
    body={'model':'deepseek-flash','max_tokens':OUT_CAP,
          'messages':[{'role':'user','content':prompt}],'thinking':{'type':'disabled'}}
    req=urllib.request.Request(DS_URL,data=json.dumps(body).encode(),method='POST')
    req.add_header('Content-Type','application/json')
    req.add_header('Authorization','Bearer '+creds['DEEPSEEK_API_KEY'])
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=180) as r:
        d=json.loads(r.read().decode())
    u=d['usage']
    return {'answer':d['choices'][0]['message'].get('content',''),
            'in':u.get('prompt_tokens',0),'out':u.get('completion_tokens',0),
            'lat':round(time.monotonic()-t0,2),'stop':d['choices'][0].get('finish_reason',''),
            'cash':(u.get('prompt_tokens',0)*PRICE_IN+u.get('completion_tokens',0)*PRICE_OUT)}
def eU(q,tok,clk):
    late=clk>D
    return (q*(0 if late else 1)-0.5*tok/60000-((clk-D)/D if late else 0)-(2.0 if late else 0))

def main():
    lock=open(HERE/'zoran_unit.lock','w')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError: raise SystemExit('lock held')
    att_worst=3+3+2+3+2+5; cash_worst=10*0.008
    assert att_worst<=CAP_ATTEMPTS and cash_worst<=CAP_CNY
    print(f'admission(off-peak): {att_worst} att<={CAP_ATTEMPTS}, ¥{cash_worst:.3f}<={CAP_CNY}')
    creds=load_env_creds(); docs=load_docs()
    texts=[docs[s]['text'] for s in ('*ST卓然#E04-zhuoran:E04-zhuoran',
        '*ST卓然#E04-zhuoran:E04-zhuoran_sup1','*ST卓然#E04-zhuoran:E04-zhuoran_sup2')]
    ledger=open(HERE/'ZORAN_UNIT_LEDGER.jsonl','a')
    attempts=0;spend=0.0
    def rec(a,n,m,r,fault=False):
        nonlocal attempts,spend
        attempts+=1;spend+=r.get('cash',r.get('cash_cny',0.0))
        assert attempts<=CAP_ATTEMPTS and spend<=CAP_CNY
        ledger.write(json.dumps({'attempt':attempts,'arm':a,'node':n,'model':m,
            'in':r.get('in',r.get('tokens_in',0)),'out':r.get('out',r.get('tokens_out',0)),
            'lat':r.get('lat',r.get('latency_s',0)),'cash':r.get('cash',r.get('cash_cny',0.0)),
            'fault':fault},ensure_ascii=False)+'\n');ledger.flush()

    # === PREFIX (serial, K=1) ===
    T0=time.monotonic()
    o=call_flash(EXT.format(doc_id='main',doc=texts[0]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_main','flash',o); main_out=o['answer']
    print(f'n_main {o["latency_s"]}s'); time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup1',doc=texts[1]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup1','flash',o); sup1_out=o['answer']
    print(f'n_sup1 {o["latency_s"]}s'); time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup2',doc=texts[2]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup2','flash',o,fault=True)
    fault_clk=time.monotonic()-T0
    print(f'n_sup2 FAILED. fault_clk={fault_clk:.1f}s (D={D}s rem={D-fault_clk:.1f}s)')
    time.sleep(1.1)

    # === predictions ===
    FL={'n_main':9.6,'n_sup1':19.2,'n_sup2':19.4,'verify':23.7,'sink':28.0}
    DSL={'n_main':2.9,'n_sup1':5.3,'n_sup2':5.0,'verify':1.8,'sink':1.5}
    ACC=['verify','sink']; TAR=['n_sup2','verify','sink']; FUL=['n_main','n_sup1','n_sup2','verify','sink']
    rem=D-fault_clk
    feas={}
    for R,ns in [('accept',ACC),('targeted',TAR),('full',FUL)]:
        for m in ('Flash','DS'):
            p=sum((DSL if m=='DS' else FL)[n] for n in ns)
            feas[(R,m)]=p<=rem
    QH={'accept':0.35,'targeted':0.65,'full':0.65}
    TK={'accept':2500,'targeted':4000,'full':9000}
    def uh(R,m):
        l=not feas[(R,m)]
        return QH[R]*(0 if l else 1)-0.5*TK[R]/60000-(2.0 if l else 0)
    # Strategy rules (frozen, unchanged from huanrui)
    st={'STATIC':('targeted','Flash'),'SD-FC':('targeted','Flash'),
        'R-only':(('targeted' if feas[('targeted','Flash')] else 'accept'),'Flash'),
        'pi-only':('targeted','DS' if not feas[('targeted','Flash')] and feas[('targeted','DS')] else 'Flash'),
        'SEQ':(('targeted' if feas[('targeted','Flash')] else 'accept'),
               'Flash' if feas[(('targeted' if feas[('targeted','Flash')] else 'accept'),'Flash')] else 'DS'),
        'JOINT':max(((R,m) for R in QH for m in ('Flash','DS')),key=lambda rm:uh(rm[0],rm[1])),
        'SINGLE-DS':('full','DS')}
    print(f'\nfeasibility(rem={rem:.1f}s): '+', '.join(f'{R}+{m}={v}' for (R,m),v in sorted(feas.items())))
    print('choices:')
    for s,(R,m) in st.items(): print(f'  {s:10s} {R}+{m} (Uh={uh(R,m):+.3f})')

    # === execute (per-arm isolated clock) ===
    execs={}
    NODES={'accept':ACC,'targeted':TAR,'full':FUL}
    for strat in ('STATIC','SD-FC','R-only','pi-only','SEQ','JOINT','SINGLE-DS'):
        R,m=st[strat]; key=(R,m)
        if key in execs:
            print(f'  {strat:10s} -> SHARED ({execs[key]["shared_by"]})'); continue
        nodes=NODES[R]; outputs={'n_main':main_out,'n_sup1':sup1_out}
        if R=='full': outputs={}
        tok=0; stopped=None; arm_start=time.monotonic()
        for n in nodes:
            if n.startswith('n_'):
                di={'main':0,'sup1':1,'sup2':2}[n.replace('n_','')]
                p=EXT.format(doc_id=n.replace('n_',''),doc=texts[di])
            elif n=='verify':
                mg='\n\n'.join(f'### {k}的输出：\n{v}' for k,v in outputs.items() if k.startswith('n_'))
                p=VER.format(merged=mg[:4000])
            else:
                p=SNK.format(verified=str(outputs.get('verify',''))[:3000])
            if m=='DS':
                try: r=call_ds_api(p,creds)
                except Exception as e:
                    rec(strat,n,'DS',{'in':0,'out':0,'lat':0,'cash':0,'stop':f'ERR:{type(e).__name__}'})
                    stopped=f'{n}:{type(e).__name__}';break
            else:
                try: r=call_flash(p,creds,max_out_tokens=OUT_CAP)
                except Exception as e:
                    rec(strat,n,'flash',{'tokens_in':0,'tokens_out':0,'latency_s':0,'cash_cny':0})
                    stopped=f'{n}:{type(e).__name__}';break
            rn={'in':r.get('in',r.get('tokens_in',0)),'out':r.get('out',r.get('tokens_out',0)),
                'lat':r.get('lat',r.get('latency_s',0)),'cash':r.get('cash',r.get('cash_cny',0.0)),
                'stop':r.get('stop',r.get('finish_reason',''))}
            rec(strat,n,'DS' if m=='DS' else 'flash',rn)
            if rn['stop'] in ('length','max_tokens'): stopped=f'{n}:TRUNC';break
            outputs[n]=r.get('answer','')
            tok+=rn['in']+rn['out']
            time.sleep(1.1)
        clk=fault_clk+(time.monotonic()-arm_start)  # ISOLATED CLOCK
        if stopped:
            execs[key]={'stopped':stopped,'tokens':tok,'clock':round(clk,1),'shared_by':strat}
            print(f'  {strat:10s} STOPPED {stopped}'); break
        q,h,nr=silver(outputs.get('sink',''))
        eu=eU(q,tok,clk)
        execs[key]={'t_q':round(q,4),'hits':h,'n_ref':nr,'tokens':tok,'clock':round(clk,1),
                    'met':clk<=D,'eU':round(eu,4),'shared_by':strat}
        print(f'  {strat:10s} {R:8s}+{m:5s} q={q:.3f}({h}/{nr}) tok={tok} clk={clk:.1f}s met={clk<=D} eU={eu:+.4f}')

    # === table ===
    print('\n'+'='*80)
    print(f"{'Strategy':11s} {'R':8s} {'pi':6s} {'t_q':>6s} {'hits':>6s} {'tok':>6s} {'clk':>6s} {'met':>4s} {'eU':>8s}")
    rows=[]
    for s in ('STATIC','SD-FC','R-only','pi-only','SEQ','JOINT','SINGLE-DS'):
        R,m=st[s];e=execs.get((R,m),{})
        if 'stopped' in e:
            print(f'{s:11s} {R:8s} {m:6s} STOPPED:{e["stopped"]}')
            rows.append({'arm':s,'R':R,'pi':m,'stopped':e['stopped']})
        else:
            print(f'{s:11s} {R:8s} {m:6s} {e.get("t_q",0):6.3f} {e.get("hits",0):4d}/{e.get("n_ref",0):2d} {e.get("tokens",0):6d} {e.get("clock",0):6.1f} {str(e.get("met",False)):>4s} {e.get("eU",0):+8.4f}')
            rows.append({'arm':s,'R':R,'pi':m,'t_q':e.get('t_q'),'hits':e.get('hits'),
                'n_ref':e.get('n_ref'),'tokens':e.get('tokens'),'clock':e.get('clock'),
                'met':e.get('met'),'eU':e.get('eU')})
    by={r['arm']:r for r in rows if r.get('eU') is not None}
    if by.get('JOINT'):
        J=by['JOINT']['eU']
        print('\nJOINT differences:')
        for a in ('SEQ','pi-only','R-only','SD-FC','SINGLE-DS'):
            v=by.get(a,{}).get('eU')
            print(f'  JOINT - {a:10s} = {J-v:+.4f}' if v is not None else f'  JOINT - {a:10s} = N/A')
    json.dump({'unit':'zoran F-sup2 D=70s SERIAL K=1',
        'fault_clk':round(fault_clk,1),'feasibility':{str(k):v for k,v in feas.items()},
        'strategies':{k:list(v) for k,v in st.items()},
        'executions':{str(list(k)):v for k,v in execs.items()},'rows':rows,
        'attempts':attempts,'cash':round(spend,4)},
        open(HERE/'ZORAN_UNIT_RESULT.json','w'),ensure_ascii=False,indent=1)
    print(f'\nUNIT DONE: {attempts}/{CAP_ATTEMPTS} attempts, ¥{spend:.4f}/{CAP_CNY}')

if __name__=='__main__': main()
