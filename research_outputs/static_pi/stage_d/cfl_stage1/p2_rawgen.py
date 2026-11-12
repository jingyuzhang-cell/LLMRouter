"""DAG_P2_RAW_GEN: 3 GLM-Flash calls to generate Raw DAGs per M8_P2_PROTOCOL V1.1 Appendix A.
Frozen prompt, temp=0, max_tokens=2000. No retry/fallback. Caps: 3 calls / 6K tokens / Y0."""
import json,os,sys,time,hashlib,urllib.request
sys.path.insert(0,'/root/research_outputs/static_pi/stage_d')
from stage_d_v2_transport import build_request, glm_key, MODEL_CFG
PROMPT="""你是任务规划器。根据以下调查任务和文档清单，将任务分解为执行 DAG。

任务：调查*ST卓然从立案调查到退市风险的完整演变：立案原因与进展、
各次退市风险提示的触发条件与时间线、公司目前面临的退市类型判断。

可用文档：
- doc1: 上海卓然 关于公司立案调查进展暨退市风险提示公告（2026-09-10）
- doc2: 上海卓然 关于公司股票可能被实施重大违法强制退市的第四次风险提示公告（2026-10-09）
- doc3: 上海卓然 关于公司股票可能存在因股价低于1元而终止上市的首次风险提示（2026-10-13）

要求：
1. 节点数不超过 8 个；
2. 每个节点 kind ∈ {extracts, timeline, reasoning, verification, report}；
3. 恰好一个 report 节点作为唯一终端；
4. 每个节点声明其直接读取的文档（doc_refs），非抽取类节点可为空；
5. 依赖边只表达真实数据依赖；
6. 只输出 JSON，格式：
{"nodes": [{"id": "...", "task": "...", "kind": "...", "doc_refs": ["doc1", ...]}],
 "edges": [{"from": "...", "to": "..."}]}"""
OUT='/root/research_outputs/static_pi/stage_d'
LED=f'{OUT}/cfl_stage1/P2_RAWGEN_LEDGER.jsonl'
calls=0;tok=0
for i in (1,2,3):
    body={'model':'GLM-5.3-Flash','max_tokens':2000,'temperature':0,
          'thinking':{'type':'disabled'},
          'messages':[{'role':'user','content':PROMPT}]}
    sha=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    req=urllib.request.Request(MODEL_CFG['glm53flash']['url'],
        data=json.dumps(body).encode(),method='POST')
    req.add_header('content-type','application/json')
    req.add_header('authorization','Bearer '+glm_key())
    t0=time.monotonic()
    with urllib.request.urlopen(req,timeout=120) as r:
        d=json.loads(r.read().decode())
    ch=d['choices'][0];u=d.get('usage',{})
    c=ch.get('message',{}).get('content','')
    text=''.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else(c or'')
    tin,tout=u.get('prompt_tokens',0),u.get('completion_tokens',0)
    calls+=1;tok+=tin+tout
    with open(LED,'a') as f:
        f.write(json.dumps(dict(ts=time.strftime('%Y-%m-%dT%H:%M:%S'),alias='glm53flash',
            purpose=f'p2rawgen|Raw-{i}',prompt_sha256=sha,
            usage=dict(input_tokens=tin,output_tokens=tout),
            accounting_yuan=round(tin*0.8e-6+tout*2.8e-6,8),
            latency_s=round(time.monotonic()-t0,3),text=text),ensure_ascii=False)+'\n')
    # parse + structure hash
    try:
        j=json.loads(text[text.find('{'):text.rfind('}')+1])
        nodes=sorted([(n['id'],n['kind'],tuple(sorted(n.get('doc_refs',[])))) for n in j['nodes']])
        edges=sorted([(e['from'],e['to']) for e in j['edges']])
        sh=hashlib.sha256(json.dumps([nodes,edges]).encode()).hexdigest()[:16]
        json.dump(j,open(f'{OUT}/cfl_stage1/P2_RawDAG_{i}.json','w'),ensure_ascii=False,indent=1)
        print(f"Raw-{i}: {len(j['nodes'])} nodes {len(j['edges'])} edges hash={sh} in={tin} out={tout}")
    except Exception as e:
        print(f"Raw-{i}: PARSE FAIL ({e}) — raw saved")
        open(f'{OUT}/cfl_stage1/P2_RawDAG_{i}_raw.txt','w').write(text)
print(f"DONE: {calls} calls {tok} tokens")
