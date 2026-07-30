#!/usr/bin/env python3
import argparse,json,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from threading import Lock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import generate_kqa_multi_model_routing as g
ROOT=Path(__file__).resolve().parents[1]
PILOT=ROOT/'data/kqapro/rescue_pilot_v1'
write_lock=Lock()
def load_queries(): return [json.loads(x) for x in (PILOT/'queries_sealed.jsonl').open() if x.strip()]
def valid_done(path):
 out=set()
 if path.exists():
  for line in path.open():
   try:
    r=json.loads(line)
    if r.get('predicted_label') in r.get('choices',{}).get('labels',[]):out.add(r['task_id'])
   except Exception:pass
 return out
def row(model,q,result,label,elapsed=None):
 choices=q['choices']; gold=chr(65+choices.index(q['answer']))
 return {'task_id':q['sample_id'],'source_index':q['source_index'],'task_name':'kqapro-rescue-pilot','query':q['question'],'ground_truth':q['answer'],'program':q['program'],'target_operations':q['target_operations'],'choices':{'text':choices,'labels':[chr(65+i) for i in range(len(choices))]},'model_name':g.MODELS[model].get('data_name',model),'model_key':model,'response':result['response'],'predicted_label':label,'correct':float(label==gold),'performance':float(label==gold),'cost_proxy':g.compute_cost_proxy(model,result.get('input_tokens',0),result.get('output_tokens',0)),'response_time':result.get('response_time',elapsed or 0),'input_tokens':result.get('input_tokens',0),'output_tokens':result.get('output_tokens',0)}
def external(model,concurrency):
 qs=load_queries(); path=PILOT/'partial'/f'{model}.jsonl'; done=valid_done(path); env=g.load_env([model]); pending=[q for q in qs if q['sample_id'] not in done]; print('model',model,'done',len(done),'pending',len(pending),flush=True)
 def one(q):
  r=g.call_api(env,model,q['question'],q['choices']); lab=g.extract_choice_label(r.get('response',''),q['choices']) if r['success'] else None
  return q,r,lab
 with path.open('a') as f,ThreadPoolExecutor(max_workers=concurrency) as ex:
  futs=[ex.submit(one,q) for q in pending]
  for n,fu in enumerate(as_completed(futs),1):
   q,r,lab=fu.result()
   if lab:
    with write_lock:f.write(json.dumps(row(model,q,r,lab),ensure_ascii=False)+'\n');f.flush()
   if n%50==0:print('completed_futures',n,'written_total',len(valid_done(path)),flush=True)
 print('finished',model,'valid',len(valid_done(path)),flush=True)
def local_batch(batch_size):
 import torch
 from transformers import AutoTokenizer,AutoModelForCausalLM
 model_key='qwen-3b-local';qs=load_queries();path=PILOT/'partial'/f'{model_key}.jsonl';done=valid_done(path);pending=[q for q in qs if q['sample_id'] not in done];mp='/root/.cache/huggingface/hub/models--Qwen--Qwen2.5-3B-Instruct/snapshots/aa8e72537993ba99e69dfaafa59ed015b17504d1';tok=AutoTokenizer.from_pretrained(mp,local_files_only=True,use_fast=False);tok.padding_side='left';tok.pad_token=tok.eos_token;model=AutoModelForCausalLM.from_pretrained(mp,dtype=torch.float16,device_map='auto',local_files_only=True).eval();print('local done',len(done),'pending',len(pending),flush=True)
 with path.open('a') as f,torch.inference_mode():
  for start in range(0,len(pending),batch_size):
   chunk=pending[start:start+batch_size];prompts=[]
   for q in chunk:
    msgs=[{'role':'system','content':'Return exactly one uppercase option letter from A through J. Your complete response must match ^[A-J]$. Never explain.'},{'role':'user','content':g.build_prompt(q['question'],q['choices'])}];prompts.append(tok.apply_chat_template(msgs,tokenize=False,add_generation_prompt=True))
   inputs=tok(prompts,padding=True,truncation=True,max_length=4096,return_tensors='pt').to('cuda');t=time.time();out=model.generate(**inputs,max_new_tokens=4,do_sample=False,pad_token_id=tok.eos_token_id);elapsed=(time.time()-t)/len(chunk); generated=out[:,inputs.input_ids.shape[1]:]
   for i,q in enumerate(chunk):
    text=tok.decode(generated[i],skip_special_tokens=True).strip();lab=g.extract_choice_label(text,q['choices'])
    if lab:
     res={'response':text,'input_tokens':int(inputs.attention_mask[i].sum()),'output_tokens':int((generated[i]!=tok.pad_token_id).sum()),'response_time':elapsed};f.write(json.dumps(row(model_key,q,res,lab),ensure_ascii=False)+'\n')
   f.flush();print('batch',min(start+len(chunk),len(pending)),'/',len(pending),'valid_total',len(valid_done(path)),flush=True)
 print('finished local valid',len(valid_done(path)),flush=True)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--model',required=True,choices=['qwen-3b-local','deepseek','qwen','gemini','zhipu']);ap.add_argument('--concurrency',type=int,default=4);ap.add_argument('--batch-size',type=int,default=32);a=ap.parse_args();local_batch(a.batch_size) if a.model=='qwen-3b-local' else external(a.model,a.concurrency)
if __name__=='__main__':main()
