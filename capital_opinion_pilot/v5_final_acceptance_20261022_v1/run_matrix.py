"""Execute each frozen synthetic scenario once per strategy; no real model."""
import sys,json,hashlib,copy,time
from pathlib import Path
from collections import Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from freeze_matrix import encode,decode
import joint_scheduler_v5 as v5
import rule_scheduler_rl as rl
from v5_executor import V5RecoveryExecutor
from cache_lineage import fingerprint
OUT=Path(__file__).parent


def digest(value):return hashlib.sha256(json.dumps(encode(value),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def decision(c):return None if c is None else {k:c.get(k) for k in ('Z','R','pi','tools','annotations')}


def run():
    protocol=json.loads((OUT/'MATRIX_FREEZE.json').read_text())
    assert hashlib.sha256((OUT/'SCENARIO_MATRIX.json').read_bytes()).hexdigest()==protocol['matrix_sha256']
    for p,h in protocol['code_sha256'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
    matrix=json.loads((OUT/'SCENARIO_MATRIX.json').read_text());rows=[]
    with (OUT/'MATRIX_EXECUTION.jsonl').open('x') as log:
        for case in matrix['cases']:
            s=decode(case['state']);outputs=case['outputs'];row={'id':case['id'],'dimension':case['dimension'],
                'source_class':case['source_class'],'complete_input':case,'real_model_calls':0,
                'independent_real_quality_assessment':False}
            for strategy,chooser in [('V5',v5.choose),('RL',rl.choose)]:
                observations=[]
                def call(n,m,inputs):
                    if n.startswith('verify_'):
                        value={'grounded':inputs['target_output']==3,'evidence_ref':'SYN:E_B'}
                    elif n=='a':value=2
                    elif n=='b':value=3
                    elif n=='join':value=sum(inputs.values())
                    else:value=2*inputs['join']
                    tokens,seconds=s['cost_lat'][(n,m)][:2] if m else (0,s['deterministic_latency'].get(n,0))
                    cash=s['cash_cost'][(n,m)] if m else {}
                    r={'output':value,'contract_ok':True,'tokens':tokens,'wall_s':seconds,'cash_cost':cash}
                    observations.append({'node':n,'model':m,'inputs':inputs,'inputs_fp':fingerprint(inputs),'result':r,'source':'SYNTHETIC_METER'})
                    return r
                ex=V5RecoveryExecutor(copy.deepcopy(s),copy.deepcopy(outputs),call,strategy)
                prepared=copy.deepcopy(ex.state);prepared_hash=digest(prepared)
                host_start=time.monotonic();executed=ex.run();host_s=time.monotonic()-host_start
                # Second solve is diagnostic only, not a second execution or paid call.
                again,again_audit=chooser(copy.deepcopy(prepared))
                actual_choice=executed['selected']
                assert decision(again)==decision(actual_choice),(case['id'],strategy,'decision/execution mismatch')
                for obs in observations:
                    if obs['model'] is not None:
                        assert obs['model']==actual_choice['pi'][obs['node']]
                legal_terminal='out' in executed['outputs'] and executed['status'] in ('COMPLETE','VERIFIED_ANNOTATION')
                fixture_q=int(executed['outputs']['out']==case['quality_reference']['expected_out']) if legal_terminal else None
                candidates=executed['candidates']
                row[strategy]={'prepared_state':encode(prepared),'prepared_state_sha256':prepared_hash,
                    'policy_source_sha256':hashlib.sha256(Path(chooser.__code__.co_filename).read_bytes()).hexdigest(),
                    'decision':decision(actual_choice),'n_candidates':len(candidates),
                    'n_feasible':sum(c['feasible'] for c in candidates),'n_pareto':sum(c['pareto'] for c in candidates),
                    'rejection_counts':dict(Counter(reason for c in candidates for reason in c['rejection_reasons'])),
                    'prediction':None if actual_choice is None else {k:actual_choice.get(k) for k in ('q_task','q_identified','quality_scope','diagnostic_q_proxy','terminal_q','tokens','cash_cost','path_s')},
                    'execution':executed,'meter_observations':observations,'physical_model_callbacks':sum(o['model'] is not None for o in observations),
                    'deterministic_tool_callbacks':sum(o['model'] is None for o in observations),
                    'deterministic_decision':decision(actual_choice)==decision(again),
                    'host_elapsed_s':host_s,'host_elapsed_source':'MEASURED_LOCAL_CPU_ONLY',
                    'terminal_fixture_q':fixture_q,'legal_terminal_coverage':int(legal_terminal),
                    'quality_measurement_source':'FROZEN_SYNTHETIC_ARITHMETIC_REFERENCE_NOT_REAL_GOLD',
                    'resource_measurement_source':'SYNTHETIC_CALLBACK_TOKENS_CASH_TIME; PLANNING_CPU_MEASURED'}
            assert row['V5']['prepared_state_sha256']==row['RL']['prepared_state_sha256']
            assert row['V5']['n_candidates']==row['RL']['n_candidates']
            v,r=row['V5'],row['RL']
            assert [c['rejection_reasons'] for c in v['execution']['candidates']]==[c['rejection_reasons'] for c in r['execution']['candidates']]
            row['same_action']=v['decision']==r['decision']
            row['fairness']={'same_prepared_state':True,'same_candidates':True,'same_rejection_rules':True,'same_meter':True}
            def delta(key):
                a,b=v['execution'].get(key),r['execution'].get(key)
                return a-b if isinstance(a,(int,float)) and isinstance(b,(int,float)) else None
            row['comparison']={'delta_tokens_v5_minus_rl':delta('actual_tokens'),
                'delta_synthetic_execution_s_v5_minus_rl':delta('actual_execution_s'),
                'delta_local_planning_s_v5_minus_rl':delta('actual_planning_s'),
                'terminal_fixture_q_v5':v['terminal_fixture_q'],'terminal_fixture_q_rl':r['terminal_fixture_q'],
                'real_incremental_benefit_verified':False,
                'interpretation':'Synthetic mechanism/selection comparison only; action differences do not imply superiority.'}
            log.write(json.dumps(encode(row),ensure_ascii=False,sort_keys=True)+'\n');log.flush();rows.append(row)
            print(case['id'], 'V5',v['decision'],v['execution']['status'],'RL',r['decision'],r['execution']['status'],flush=True)
    with (OUT/'V5_VS_RL_DECISIONS.json').open('x') as f:json.dump(encode(rows),f,ensure_ascii=False,indent=2)
    summary={'cases':len(rows),'strategy_runs':2*len(rows),'different_actions':sum(not r['same_action'] for r in rows),
        'deterministic_decisions':sum(r[a]['deterministic_decision'] for r in rows for a in ('V5','RL')),
        'same_state_and_hard_rules':all(all(r['fairness'].values()) for r in rows),
        'source':'SYNTHETIC_ACCEPTANCE_ONLY','real_incremental_benefit_verified':False,'real_model_calls':0}
    with (OUT/'MATRIX_SUMMARY.json').open('x') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':run()
