"""huanrui_unit.py — Huanrui D=60s paired unit (authorized 2026-10-27, exploratory replay).

Off-peak only; SERIAL executor K=1; task clock from start (prefix included).
D=50s: prefix ~32s + targeted+DS ~11s = 43s FEASIBLE; targeted+Flash 71s LATE.
This IS the pi-enables-R interaction window.
"""
import fcntl, json, re, sys, time
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.r2fix_runner import call_ds as call_flash
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_executor import load_env_creds

D=60.0; CAP_ATTEMPTS=25; CAP_CNY=0.15
DS_URL='https://api.deepseek.com/chat/completions'
PRICE_IN,PRICE_OUT=2.13e-6,8.52e-6  # PEAK (user override run now)
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

KEYS=['2026年4月21日','2026年4月22日','2026年9月18日','2026年9月23日','2026年1月1日',
      '2026年6月30日','2026年7月14日','12,500.00万元','12,300.00万元','19,804.88万元',
      '24,500.00万元','2,187.21万元','639.38万元','200.00万元','0.01元','0.13元',
      '告知书','处罚','立案','虚假']
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
    lock=open(HERE/'huanrui_unit.lock','w')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError: raise SystemExit('lock held')
    att_worst=3+3+2+3+2+5; cash_worst=10*0.012
    assert att_worst<=CAP_ATTEMPTS and cash_worst<=CAP_CNY
    print(f'admission(peak): {att_worst} att<=30, ¥{cash_worst:.3f}<=0.10 [user override: run now]')
    creds=load_env_creds(); docs=load_docs()
    texts=[docs[s]['text'] for s in ('欢瑞世纪#E06-huanrui:E06-huanrui',
        '欢瑞世纪#E06-huanrui:E06-huanrui_sup1','欢瑞世纪#E06-huanrui:E06-huanrui_sup2')]
    ledger=open(HERE/'HUANRUI_UNIT_LEDGER.jsonl','a')
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
    rec('PREFIX','n_main','flash',o); main_out=o['answer']
    print(f'n_main {o["latency_s"]}s'); time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup1',doc=texts[1]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup1','flash',o); sup1_out=o['answer']
    print(f'n_sup1 {o["latency_s"]}s'); time.sleep(1.1)
    o=call_flash(EXT.format(doc_id='sup2',doc=texts[2]),creds,max_out_tokens=OUT_CAP)
    rec('PREFIX','n_sup2','flash',o,fault=True)
    fault_clk=time.monotonic()-T0
    print(f'n_sup2 FAILED. Task clock at decision: {fault_clk:.1f}s (D={D}s -> remaining={D-fault_clk:.1f}s)')
    time.sleep(1.1)

    # === predictions ===
    FL={'n_main':8.3,'n_sup1':7.6,'n_sup2':13.1,'verify':12.1,'sink':10.2}
    DSL={'n_main':3.2,'n_sup1':2.4,'n_sup2':3.2,'verify':1.7,'sink':2.4}
    ACC=['verify','sink']; TAR=['n_sup2','verify','sink']; FUL=['n_main','n_sup1','n_sup2','verify','sink']
    rem=D-fault_clk
    feas={}
    for R,ns in [('accept',ACC),('targeted',TAR),('full',FUL)]:
        for m in ('Flash','DS'):
            p=sum((DSL if m=='DS' else FL)[n] for n in ns)
            feas[(R,m)]=p<=rem
    QH={'accept':0.35,'targeted':0.65,'full':0.65}; TK={'accept':2000,'targeted':3000,'full':5000}
    def uh(R,m):
        l=not feas[(R,m)]
        return QH[R]*(0 if l else 1)-0.5*TK[R]/60000-(2.0 if l else 0)
    st={'STATIC':('targeted','Flash'),'SD-FC':('targeted','Flash'),
        'R-only':('targeted' if feas[('targeted','Flash')] else 'accept','Flash'),
        'pi-only':('targeted','DS' if not feas[('targeted','Flash')] and feas[('targeted','DS')] else 'Flash'),
        'SEQ':(('targeted' if feas[('targeted','Flash')] else 'accept'),
               'Flash' if feas[(('targeted' if feas[('targeted','Flash')] else 'accept'),'Flash')] else 'DS'),
        'JOINT':max(((R,m) for R in QH for m in ('Flash','DS')),key=lambda rm:uh(rm[0],rm[1])),
        'SINGLE-DS':('full','DS')}
    print(f'\nfeasibility (rem={rem:.1f}s): '+', '.join(f'{R}+{m}={v}' for (R,m),v in sorted(feas.items())))
    print('choices:')
    for s,(R,m) in st.items(): print(f'  {s:10s} {R}+{m} (Uh={uh(R,m):+.3f})')

    # === execute (same-action shared within this repeat) ===
    execs={}
    NODES={'accept':ACC,'targeted':TAR,'full':FUL}
    for strat in ('STATIC','SD-FC','R-only','pi-only','SEQ','JOINT','SINGLE-DS'):
        R,m=st[strat]; key=(R,m)
        if key in execs:
            print(f'  {strat:10s} -> SHARED ({execs[key]["shared_by"]})'); continue
        nodes=NODES[R]; outputs={'n_main':main_out,'n_sup1':sup1_out}
        if R=='full': outputs={}
        tok=0; stopped=None
        arm_start=time.monotonic()  # PER-ARM CLOCK (isolated, not cumulative)
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
        clk=fault_clk+(time.monotonic()-arm_start)  # fault_clk + this arm only
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
    json.dump({'unit':'huanrui F-sup2 D=25s SERIAL K=1 peak-run(user-override)',
        'fault_clk':round(fault_clk,1),'feasibility':{str(k):v for k,v in feas.items()},
        'strategies':{k:list(v) for k,v in st.items()},
        'executions':{str(list(k)):v for k,v in execs.items()},'rows':rows,
        'attempts':attempts,'cash':round(spend,4),'pricing':'peak(user-override)'},
        open(HERE/'HUANRUI_UNIT_RESULT.json','w'),ensure_ascii=False,indent=1)
    print(f'\nUNIT DONE: {attempts}/{CAP_ATTEMPTS} attempts, ¥{spend:.4f}/{CAP_CNY}')

if __name__=='__main__': main()
