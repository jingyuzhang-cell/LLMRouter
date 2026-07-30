#!/usr/bin/env python3
"""Collect first-token A-J confidence for the 0.5B probe on cost-dev only."""
import json,math,sys
from pathlib import Path
import numpy as np
import torch
from transformers import AutoModelForCausalLM,AutoTokenizer
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
from kqapro_e4_generate import DEFAULT_DATASET,append_jsonl,choice_label,parse_label,prompt_for,read_json,read_jsonl
D=ROOT/"data/kqapro/cost_dev_v1";OUT=ROOT/"run_logs/kqapro/cascade_v2/confidence.jsonl";MODEL="Qwen/Qwen2.5-0.5B-Instruct"
def main():
 OUT.parent.mkdir(parents=True,exist_ok=True);manifest=read_json(D/"partition_manifest.json");val=read_json(DEFAULT_DATASET/"val.json");existing=read_jsonl(D/"routing_cost_dev.jsonl");old={r["source_index"]:r for r in existing if r["model_name"]=="qwen2.5-0.5b-instruct"};done={r["source_index"] for r in read_jsonl(OUT)};pending=[i for i in manifest["indices"] if i not in done];print("pending",len(pending))
 tok=AutoTokenizer.from_pretrained(MODEL,local_files_only=True);tok.padding_side="left";tok.pad_token_id=tok.eos_token_id;ids=[tok.encode(c,add_special_tokens=False)[0] for c in "ABCDEFGHIJ"];model=AutoModelForCausalLM.from_pretrained(MODEL,dtype=torch.bfloat16,device_map="cuda",local_files_only=True).eval();torch.manual_seed(20260723)
 for st in range(0,len(pending),16):
  idx=pending[st:st+16];samples=[val[i] for i in idx];texts=[tok.apply_chat_template([{"role":"user","content":prompt_for(x)}],tokenize=False,add_generation_prompt=True) for x in samples];enc=tok(texts,padding=True,truncation=True,max_length=1024,return_tensors="pt");enc={k:v.cuda() for k,v in enc.items()}
  with torch.inference_mode(): logits=model(**enc).logits[:,-1,:].float()
  letter=logits[:,ids];cond=torch.softmax(letter,1);full=torch.softmax(logits,1);top=cond.topk(2,1);samples3=torch.multinomial(torch.softmax(logits/.2,1),3,replacement=True)
  rows=[]
  for j,(source,sample) in enumerate(zip(idx,samples)):
   prior=old[source];draw=[]
   for z in samples3[j].tolist():draw.append(chr(65+ids.index(z)) if z in ids else None)
   valid=[x for x in draw if x];stable=max([valid.count(x) for x in set(valid)] or [0])/3
   p=cond[j].cpu().numpy();entropy=float(-(p*np.log(p+1e-12)).sum())
   rows.append({"source_index":source,"query":sample["question"],"letter_logits":{chr(65+k):float(letter[j,k]) for k in range(10)},"letter_probabilities":{chr(65+k):float(p[k]) for k in range(10)},"top1_label":chr(65+int(top.indices[j,0])),"top1_probability":float(top.values[j,0]),"margin":float(top.values[j,0]-top.values[j,1]),"entropy":entropy,"letter_probability_mass":float(full[j,ids].sum()),"format_valid":prior["predicted_label"] is not None,"stored_predicted_label":prior["predicted_label"],"top1_matches_stored":prior["predicted_label"]==chr(65+int(top.indices[j,0])),"low_temperature_draws":draw,"stability":stable,"correct":prior["correct"]})
  append_jsonl(OUT,rows)
  if (st//16+1)%10==0:print(min(st+16,len(pending)),len(pending),flush=True)
 print("complete",len(read_jsonl(OUT)))
if __name__=="__main__":main()
