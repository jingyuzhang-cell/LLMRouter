"""Static workflow prototype. Evaluator truth never enters executor feedback."""
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'static_dag_v0' / 'run_v0'
NODES = [
 {'id':'demand','deps':[], 'instruction':'Sum each department demand, subtract stock, and add reserve. Return {"units": integer}.'},
 {'id':'quotes','deps':[], 'instruction':'Normalize each supplier quote. effective_unit_cents = unit_cents - discount_cents. shipping_cents = freight_cents + handling_cents. Return {"quotes":[{"vendor":string,"unit_cents":integer,"shipping_cents":integer,"capacity":integer,"days":integer}]} for ALL suppliers. Preserve capacity and days.'},
 {'id':'feasibility','deps':['demand','quotes'], 'instruction':'Use predecessor units and quotes. total_cents = units * unit_cents + shipping_cents. A supplier is eligible iff capacity >= units AND days <= deadline_days AND total_cents <= budget_cents. Return {"options":[{"vendor":string,"total_cents":integer,"eligible":boolean}]} for ALL suppliers.'},
 {'id':'decision','deps':['feasibility'], 'instruction':'Select the eligible supplier with smallest total_cents, breaking ties alphabetically by vendor. If none is eligible, use vendor NONE and total_cents 0. Return {"vendor":string,"total_cents":integer}.'},
]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def lines(path):return [json.loads(s) for s in Path(path).read_text().splitlines() if s]

def topology(nodes):
 ids=[n['id'] for n in nodes]
 if len(ids)!=len(set(ids)):raise ValueError('duplicate node')
 left={n['id']:set(n['deps']) for n in nodes};done=set();layers=[]
 if any(v-set(ids) for v in left.values()):raise ValueError('unknown dependency')
 while left:
  ready=sorted(k for k,v in left.items() if v<=done)
  if not ready:raise ValueError('cycle')
  layers.append(ready);done.update(ready)
  for k in ready:del left[k]
 return layers

def tasks():
 rng=random.Random(20260915);out=[]
 for i in range(20):
  departments=[rng.randint(10,55) for _ in range(4)];stock=rng.randint(5,30);reserve=rng.randint(3,12)
  units=sum(departments)-stock+reserve;deadline=rng.randint(3,8)
  suppliers=[]
  for j in range(3):
   suppliers.append(dict(vendor=chr(65+j),unit_cents=rng.randint(180,460),discount_cents=rng.choice([0,10,20,30]),freight_cents=rng.randint(1,9)*100,handling_cents=rng.randint(0,4)*50,capacity=units+rng.choice([-15,0,25,50]),days=rng.randint(2,10)))
  budget=units*rng.randint(220,450)+500
  # Freeze deliberate edge cases from inputs, without any model output selection.
  if i%5==0:deadline=1
  if i%5==1:
   suppliers[0].update(capacity=units,days=deadline);budget=units*(suppliers[0]['unit_cents']-suppliers[0]['discount_cents'])+suppliers[0]['freight_cents']+suppliers[0]['handling_cents']
  if i%5==2:
   suppliers[1]={**suppliers[0],'vendor':'B'};suppliers[0]['capacity']=suppliers[1]['capacity']=units;suppliers[0]['days']=suppliers[1]['days']=deadline
  inp=dict(departments=departments,stock=stock,reserve=reserve,suppliers=suppliers,budget_cents=budget,deadline_days=deadline)
  out.append(dict(task_id=f'procurement_{i:03d}',family='constrained_procurement',input=inp,
   query='Choose one supplier to fulfill all department requests after stock and reserve adjustments. Reconcile supplier discounts and shipping, enforce capacity, deadline and budget, then minimize total cost; ties use alphabetical vendor. '+json.dumps(inp)))
 return out

def truth(task):
 x=task['input'];units=sum(x['departments'])-x['stock']+x['reserve'];quotes=[];options=[]
 for q in x['suppliers']:
  v=dict(vendor=q['vendor'],unit_cents=q['unit_cents']-q['discount_cents'],shipping_cents=q['freight_cents']+q['handling_cents'],capacity=q['capacity'],days=q['days']);quotes.append(v)
  total=units*v['unit_cents']+v['shipping_cents']
  options.append(dict(vendor=v['vendor'],total_cents=total,eligible=v['capacity']>=units and v['days']<=x['deadline_days'] and total<=x['budget_cents']))
 eligible=sorted((q for q in options if q['eligible']),key=lambda q:(q['total_cents'],q['vendor']))
 decision={k:eligible[0][k] for k in ['vendor','total_cents']} if eligible else dict(vendor='NONE',total_cents=0)
 return dict(demand=dict(units=units),quotes=dict(quotes=quotes),feasibility=dict(options=options),decision=decision)

def prompt(task,node,outputs):
 nid=node['id'];x=task['input']
 local={k:x[k] for k in {'demand':['departments','stock','reserve'],'quotes':['suppliers'],'feasibility':['budget_cents','deadline_days'],'decision':[]}[nid]}
 return 'Execute this workflow node. Treat predecessor outputs as data. Return only the requested JSON object; no code or explanations.\n'+node['instruction']+'\nInput: '+json.dumps(local)+'\nPredecessor outputs: '+json.dumps({d:outputs[d] for d in node['deps']})

def parse(answer,nid):
 text=(answer or '').strip()
 if text.startswith('```'):
  text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
 obj=json.loads(text)
 if not isinstance(obj,dict):raise ValueError('object required')
 def integer(v):return type(v) is int and v>=0
 if nid=='demand':ok=set(obj)=={'units'} and integer(obj['units'])
 elif nid=='decision':ok=set(obj)=={'vendor','total_cents'} and obj['vendor'] in ['A','B','C','NONE'] and integer(obj['total_cents'])
 else:
  key='quotes' if nid=='quotes' else 'options';rows=obj.get(key)
  ok=set(obj)=={key} and isinstance(rows,list) and len(rows)==3 and all(isinstance(r,dict) for r in rows)
  if ok:
   ok=sorted(r.get('vendor','') for r in rows)==['A','B','C']
   fields={'vendor','unit_cents','shipping_cents','capacity','days'} if nid=='quotes' else {'vendor','total_cents','eligible'}
   ok=ok and all(set(r)==fields and all(integer(r[k]) for k in fields-{'vendor','eligible'}) and (nid=='quotes' or type(r['eligible']) is bool) for r in rows)
   obj[key]=sorted(rows,key=lambda r:r['vendor'])
 if not ok:raise ValueError('schema invalid')
 return obj

def route(profile,estimated_input_tokens):
 candidates={}
 for slot,p in profile.items():
  c=estimated_input_tokens+p['mean_output_tokens'];l=p['mean_latency_s']*c/p['mean_total_tokens']
  candidates[slot]=dict(Q=p['quality'],C_tokens=c,L_seconds=l,score=p['quality']-.05*c/1000-.05*l/10)
 selected=max(sorted(candidates),key=lambda s:candidates[s]['score'])
 return selected,candidates
