"""Post-run localization only; no new generations or parameter changes."""
import json
from .core import OUT,write,lines

def main():
 tasks=json.loads((OUT/'TASKS.json').read_text());rows=lines(OUT/'NODES.jsonl');r={(v['task_id'],v['node_id']):v for v in rows};conditional={'feasibility':{'correct':0,'evaluable':0},'decision':{'correct':0,'evaluable':0}}
 for t in tasks:
  tid=t['task_id'];d=r[tid,'demand'].get('parsed');q=r[tid,'quotes'].get('parsed');f=r[tid,'feasibility'].get('parsed');a=r[tid,'decision'].get('parsed')
  if d is not None and q is not None:
   expected=[]
   for v in q['quotes']:
    total=d['units']*v['unit_cents']+v['shipping_cents']
    expected.append(dict(vendor=v['vendor'],total_cents=total,eligible=v['capacity']>=d['units'] and v['days']<=t['input']['deadline_days'] and total<=t['input']['budget_cents']))
   conditional['feasibility']['evaluable']+=1;conditional['feasibility']['correct']+=f==dict(options=expected)
  if f is not None:
   options=sorted((v for v in f['options'] if v['eligible']),key=lambda v:(v['total_cents'],v['vendor']))
   expected={k:options[0][k] for k in ['vendor','total_cents']} if options else dict(vendor='NONE',total_cents=0)
   conditional['decision']['evaluable']+=1;conditional['decision']['correct']+=a==expected
 write(OUT/'FAILURE_LOCALIZATION.json',dict(conditional_on_actual_predecessors=conditional,role='posthoc_descriptive_not_new_trial',interpretation='Correctness against actual predecessor data isolates local execution errors from inherited upstream errors; not evidence repair will improve final outcomes.'))
 print(json.dumps(conditional))
if __name__=='__main__':main()
