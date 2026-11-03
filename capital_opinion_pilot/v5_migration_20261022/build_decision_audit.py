"""Reproducible synthetic acceptance audit, not a real-model performance run."""
from pathlib import Path
import sys,json,copy
sys.path.insert(0,'/root/capital_opinion_pilot')
from test_v5_migration import state,TerminalFixture
from task_quality import TaskQuality,measured_cells
from v5_executor import V5RecoveryExecutor
import joint_scheduler_v5 as v5
import rule_scheduler_rl as rl
OUT=Path('/root/capital_opinion_pilot/v5_migration_20261022')

def base():
 s=state();s.pop('quality_evaluator');s['feedback']['suspicious']={};return s
cases=[]
s=base();cases.append(('healthy_independent_cache',s))
s=base();s['feedback']['suspicious']={'b':(1,3)};cases.append(('evidenced_cache_suspicion_quality_unknown',s))
s=base();s['lineage_valid']={'b':False};cases.append(('independent_cache_fingerprint_invalid',s))
s=base();s['availability']={'fast':False};cases.append(('fast_model_unavailable',s))
s=base();s['token_budget_remaining']=20;cases.append(('token_budget20',s))
s=base();s['deadline_remaining_s']=2;cases.append(('deadline2',s))
s=base();s['token_budget_remaining']=1;cases.append(('insufficient_budget_refuse',s))
s=base();s['terminal_q_min']=.8;cases.append(('unknown_terminal_quality_refuse',s))
s=base();s['missing_outputs']=[];s['feedback']={'verify_targets':['b'],'verify_conflicts':{'b':{'evidence_ref':'TEST_CONFLICT:E1'}}};s['verification_required']=['b'];cases.append(('supported_annotation_only',s))
s=state();cases.append(('synthetic_terminal_calibration_only',s))

def brief(c):
 return None if c is None else {k:c.get(k) for k in ['Z','R','pi','q_task','q_identified','quality_scope','terminal_q','tokens','path_s','cash_cost','selection_rule']}
results=[]
for name,s in cases:
 entry={'case':name,'evidence_scope':'SYNTHETIC_ACCEPTANCE_ONLY','same_inputs':True,
        'quality_source':'SYNTHETIC_TEST_REFERENCE' if s.get('quality_evaluator') else 'UNIDENTIFIED',
        'runtime_state':{k:v for k,v in s.items() if k not in ['quality_evaluator','cost_lat']},
        'capability_cells':[{'node':n,'model':m,'tokens':v[0],'latency_s':v[1],'source':'SYNTHETIC_TEST_CELL'} for (n,m),v in s['cost_lat'].items()]}
 for strategy,chooser in [('V5',v5.choose),('RL',rl.choose)]:
  a,cs=chooser(s);again,_=chooser(copy.deepcopy(s))
  calls=[]
  def call(n,m,inputs):
   if n.startswith('verify_'):value={'grounded':True}
   elif n=='a':value=2
   elif n=='b':value=3
   elif n=='join':value=sum(inputs.values())
   else:value=2*inputs['join']
   tokens,wall=s['cost_lat'][(n,m)][:2] if m is not None else (0,0)
   calls.append({'node':n,'model':m,'tokens':tokens,'wall_s':wall})
   return {'output':value,'contract_ok':True,'tokens':tokens,'wall_s':wall,'cash_cost':{}}
  executed=V5RecoveryExecutor(s,{'b':3},call,strategy).run()
  entry[strategy]={'decision':brief(a),'deterministic_decision':brief(a)==brief(again),
                   'candidates':cs,'execution':executed,
                   'terminal_fixture_correct':executed['outputs'].get('out')==10 if 'out' in executed['outputs'] else None,
                   'physical_calls':len(calls),'meter':calls}
 entry['same_action']=all((entry['V5']['decision'] or {}).get(k)==(entry['RL']['decision'] or {}).get(k) for k in ['Z','R','pi'])
 results.append(entry)
# Reproduce the historical arithmetic without treating it as independent terminal Q.
tq=TaskQuality(*measured_cells())
q,identified,prov=tq.estimate('kdx',{'keep':{'t1':'glm53'},'reexec':{'t2':'deepseek'},'facts_per_call':{('t2','deepseek'):15}})
(OUT/'QUALITY_FORMULA_CHECK.json').write_text(json.dumps({'metric':tq.quality_scope,'identified':identified,'t1':15*.29,'t2':.964*15*.70,'total':q,'provenance':prov,'terminal_accuracy':None},ensure_ascii=False,indent=2))
(OUT/'V5_VS_RL_DECISIONS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2,default=lambda v:sorted(v) if isinstance(v,set) else str(v)))
print('cases',len(results),'different decisions',sum(not r['same_action'] for r in results),'deterministic',all(r[k]['deterministic_decision'] for r in results for k in ['V5','RL']))
