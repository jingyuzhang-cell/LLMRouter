#!/usr/bin/env python3
"""Generate frozen router predictions without reading confirmation outcomes."""
import json
from pathlib import Path
import torch
from llmrouter.models.mlprouter.router import MLPClassifierNN
from llmrouter.utils import load_model
ROOT=Path(__file__).resolve().parents[1]
def main():
 cp=load_model(str(ROOT/"llmrouter/saved_models/mlprouter/mlprouter_nvidia_current_v1_seed42.pkl"));qs=[json.loads(x) for x in (ROOT/"data/nvidia_confirm_v1/queries_sealed.jsonl").open()];emb=torch.load(ROOT/"data/example_data/routing_data/query_embeddings_longformer.pt",map_location="cpu",weights_only=False);model=MLPClassifierNN(cp["input_dim"],cp["hidden_layer_sizes"],len(cp["model_names"]),cp["activation"]);model.load_state_dict(cp["state_dict"]);model.eval();mean=torch.tensor(cp["embedding_mean"]);std=torch.tensor(cp["embedding_std"]);tasks={x:i for i,x in enumerate(cp["task_names"])};pred={}
 for r in qs:
  v=(emb[int(r["embedding_id"])].float()-mean)/std;t=torch.zeros(len(tasks));
  if r["task_name"] in tasks:t[tasks[r["task_name"]]]=1
  x=torch.cat([v,t]).unsqueeze(0)
  with torch.no_grad():idx=int(torch.argmax(model(x),1))
  pred[r["query"]]=cp["model_names"][idx]
 out=ROOT/"run_logs/nvidia_confirm_v1/router_predictions.json";out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(pred,indent=2));print("predictions",len(pred))
if __name__=="__main__":main()
