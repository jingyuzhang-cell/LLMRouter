#!/usr/bin/env python3
"""Resumable KQAPro reasoning/program/self-consistency pilot."""
from __future__ import annotations
import argparse,hashlib,json,random,re,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from threading import Lock
import requests
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from generate_kqa_multi_model_routing import MODELS,load_env
from kqa_routing_utils import MODEL_SPECS,question_type
VAL=ROOT/'data/kqapro/KQAPro_Baselines/dataset/val.json';OUT=ROOT/'data/kqapro/reasoning_pilot_v1'
MODELS_OK=('deepseek','qwen','zhipu','gemini');VARIANTS=('reasoning_final','program_reasoning_final','program_vote3');LOCK=Lock()
def label(text):
 if not isinstance(text,str):return None
 found=re.findall(r'(?im)^\s*FINAL\s*:\s*([A-J])\s*[.)]?\s*$',text)
 if found:return found[-1].upper()
 t=text.strip().upper();return t if re.fullmatch(r'[A-J]',t) else None
def indices(size,seed):
 ids=list(range(11797));ids.sort(key=lambda i:hashlib.sha256(f'{seed}:kqapro-val-{i:05d}'.encode()).hexdigest());train=ids[:int(len(ids)*.70)];train.sort(key=lambda i:hashlib.sha256(f'pilot:{seed}:kqapro-val-{i:05d}'.encode()).hexdigest());return sorted(train[:size])
def prompt(item,aware):
 opts='\n'.join(f'{chr(65+i)}. {x}' for i,x in enumerate(item['choices']));ops=' → '.join(x.get('function','?') for x in item.get('program',[]));hint=f'\nRequired operations: {ops}\n' if aware else ''
 return f"Analyze this multiple-choice knowledge question step by step.{hint}\nQuestion: {item['question']}\n\n{opts}\n\nEnd with a separate line exactly in the form FINAL: <A-J>."
def refusal(resp):
 if resp.status_code!=400:return None
 low=resp.text.casefold();marks=('data_inspection_failed','contentfilter','content_filter','"code":"1301"','inappropriate content','不安全或敏感内容')
 if not any(x in low for x in marks):return None
 try:e=resp.json().get('error',{});return e.get('code') or e.get('type') or 'content_filter'
 except Exception:return 'content_filter'
def complete(env,model,messages,temp,tokens):
 cfg=MODELS[model];key=cfg.get('api_key_env',model.upper()+'_API_KEY');headers={'Content-Type':'application/json','Authorization':f'Bearer {env[key]}'};payload={'model':cfg['name'],'messages':messages,'temperature':temp,'max_tokens':tokens}
 if model=='qwen':payload['enable_thinking']=True
 if model=='gemini':payload['reasoning_effort']='medium'
 latency=0.0
 for attempt,wait in enumerate((3,10,30,60)):
  try:
   start=time.time();resp=requests.post(cfg['api_url'],headers=headers,json=payload,timeout=180);latency+=time.time()-start;code=refusal(resp)
   if code:return {'status':'provider_refusal','text':None,'input_tokens':0,'output_tokens':0,'latency':latency,'error_code':code}
   if resp.status_code==200:
    d=resp.json();txt=str(d.get('choices',[{}])[0].get('message',{}).get('content') or '').strip();u=d.get('usage',{})
    return {'status':'ok','text':txt,'input_tokens':int(u.get('prompt_tokens',u.get('input_tokens',0)) or 0),'output_tokens':int(u.get('completion_tokens',u.get('output_tokens',0)) or 0),'latency':latency}
   if resp.status_code not in (429,503):return {'status':'request_failed','text':None,'input_tokens':0,'output_tokens':0,'latency':latency,'error_code':str(resp.status_code)}
  except requests.RequestException as exc:
   if attempt==3:return {'status':'request_failed','text':None,'input_tokens':0,'output_tokens':0,'latency':latency,'error_code':type(exc).__name__}
  if attempt<3:time.sleep(wait+random.random()*2)
 return {'status':'request_failed','text':None,'input_tokens':0,'output_tokens':0,'latency':latency}
def mapper(env,model,item,analysis):
 opts='\n'.join(f'{chr(65+i)}. {x}' for i,x in enumerate(item['choices']));msgs=[{'role':'system','content':'Map the proposed answer to one option. Return exactly one uppercase letter A-J.'},{'role':'user','content':f"Question: {item['question']}\n{opts}\n\nProposed analysis:\n{analysis}\n\nLetter:"}];r=complete(env,model,msgs,0.0,8);r['label']=label(r.get('text'));return r
def draw(env,model,item,aware,temp):
 msgs=[{'role':'system','content':'Reason carefully. Your last line must be FINAL: followed by one uppercase option letter.'},{'role':'user','content':prompt(item,aware)}];first=complete(env,model,msgs,temp,512);lab=label(first.get('text'));mapped=None
 if first['status']=='ok' and lab is None:mapped=mapper(env,model,item,first['text']);lab=mapped.get('label')
 return {'first':first,'mapper':mapped,'label':lab}
def run_one(env,model,variant,item,idx):
 draws=[draw(env,model,item,variant!='reasoning_final',0.4 if variant=='program_vote3' else 0.0) for _ in range(3 if variant=='program_vote3' else 1)];labs=[x['label'] for x in draws if x.get('label')];counts={x:labs.count(x) for x in set(labs)};pred=max(counts,key=counts.get) if counts and max(counts.values())>=2 else (labs[0] if len(draws)==1 and labs else None);calls=[]
 for d in draws:calls.extend([d['first']]+([d['mapper']] if d.get('mapper') else []))
 status='ok' if pred else ('provider_refusal' if calls and all(x['status']=='provider_refusal' for x in calls) else 'invalid_response');inp=sum(x.get('input_tokens',0) for x in calls);out=sum(x.get('output_tokens',0) for x in calls);lat=sum(x.get('latency',0) for x in calls);gold=chr(65+item['choices'].index(item['answer']));spec=MODEL_SPECS[model]
 return {'task_id':f'kqapro-val-{idx:05d}','source_index':idx,'query':item['question'],'ground_truth':item['answer'],'choices':{'text':item['choices'],'labels':list('ABCDEFGHIJ')},'question_type':question_type(item),'program_operations':[x.get('function') for x in item.get('program',[])],'model':model,'variant':variant,'response':draws[0]['first'].get('text'),'predicted_label':pred,'correct':float(pred==gold),'performance':float(pred==gold),'status':status,'votes':[x.get('label') for x in draws],'draws':draws,'response_time':lat,'input_tokens':inp,'output_tokens':out,'estimated_cost':(inp*spec['input_price']+out*spec['output_price'])/1_000_000,'cost_currency':spec['currency']}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--models',nargs='+',default=list(MODELS_OK),choices=MODELS_OK);ap.add_argument('--variants',nargs='+',default=list(VARIANTS),choices=VARIANTS);ap.add_argument('--size',type=int,default=1000);ap.add_argument('--seed',type=int,default=20260722);ap.add_argument('--concurrency',type=int,default=4);ap.add_argument('--output-dir',type=Path,default=OUT);ap.add_argument('--prepare-only',action='store_true');a=ap.parse_args();data=json.loads(VAL.read_text());selected=indices(a.size,a.seed);a.output_dir.mkdir(parents=True,exist_ok=True);manifest={'schema':'kqapro-reasoning-pilot-v1','seed':a.seed,'size':a.size,'selection_scope':'deterministic subset of 70% train-side task IDs','models':a.models,'variants':a.variants,'planned_primary_calls_per_model':a.size*5,'two_stage_mapper':'only when FINAL label is not parseable','task_ids':[f'kqapro-val-{i:05d}' for i in selected]};mp=a.output_dir/'manifest.json'
 if mp.exists():
  old=json.loads(mp.read_text());
  if old['task_ids']!=manifest['task_ids']:raise SystemExit('manifest task IDs mismatch')
 else:mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in manifest.items() if k!='task_ids'},ensure_ascii=False,indent=2),flush=True)
 if a.prepare_only:return
 env=load_env(a.models);jobs=[];handles={}
 for m in a.models:
  for v in a.variants:
   path=a.output_dir/f'{m}__{v}.jsonl';done=set()
   if path.exists():
    for line in path.open():
     try:done.add(json.loads(line)['task_id'])
     except Exception:pass
   handles[(m,v)]=path.open('a')
   jobs += [(m,v,i) for i in selected if f'kqapro-val-{i:05d}' not in done]
 print(f'pending model-variant tasks: {len(jobs)}',flush=True)
 try:
  with ThreadPoolExecutor(max_workers=a.concurrency) as ex:
   future={ex.submit(run_one,env,m,v,data[i],i):(m,v,i) for m,v,i in jobs}
   for n,f in enumerate(as_completed(future),1):
    m,v,i=future[f]
    try:row=f.result()
    except Exception as exc:print(f'ERROR {m} {v} {i}: {exc}',flush=True);continue
    with LOCK:handles[(m,v)].write(json.dumps(row,ensure_ascii=False)+'\n');handles[(m,v)].flush()
    if n%25==0:print(f'completed this run: {n}/{len(jobs)}',flush=True)
 finally:
  for h in handles.values():h.close()
if __name__=='__main__':main()
