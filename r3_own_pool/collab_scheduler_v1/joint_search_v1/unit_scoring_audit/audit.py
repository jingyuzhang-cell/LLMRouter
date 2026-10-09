"""Read-only audit of three executed tasks and split metadata, zero LLM calls.

Writes isolated audit artifacts only; never rescores/replaces historical rows.
Test-panel inspection is limited to aggregate source-label consistency counts.
"""
import hashlib
import json
from pathlib import Path
from static_dag_v0 import tool_aware_v1 as tool
from static_dag_v0.multidag_dynamic import close,parse_facts_safe,value_of,json_value
from static_dag_v0.decompose_v1 import exec_calc

ROOT=Path('/root/r3_own_pool')
OUT=Path(__file__).resolve().parent
RUN=ROOT/'collab_scheduler_v1/joint_search_v1/fullval_runs/fullval_authorized_1h_01'
SOURCE=ROOT/'data/tatqa/tatqa_dataset_train.json'
PANEL=ROOT/'collab_scheduler_v1/joint_search_v1/review/TASK_PANEL_V1.json'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return [json.loads(x) for x in p.read_text().splitlines()]
def numeric(x):
    try:return float(x)
    except (TypeError,ValueError):return None


def main():
    source=json.loads(SOURCE.read_text())
    raw={q['uid']:(p,q) for p in source for q in p['questions']}
    manifest=json.loads((RUN.parent.parent/'FULLVAL_AUTHORIZED_1H.json').read_text())
    workflow=read(RUN/'WORKFLOW.jsonl');scenarios=read(RUN/'SCENARIOS.jsonl')
    traces=[]
    for task in manifest['tasks'][:3]:
        uid=task['uid'];para,q=raw[uid]
        item=dict(uid=uid,question=q['question'],source_answer=q['answer'],source_scale=q.get('scale'),
                  source_derivation=q.get('derivation'),frozen_gold=task['answer'],
                  source_answer_matches_frozen_gold=close(numeric(q['answer']),task['answer']),
                  table=para['table']['table'],executions=[])
        for record in scenarios:
            if record['uid']!=uid:continue
            scene=record['scenario']
            events=[r for r in workflow if r['cid'].startswith(scene+':') and r['key'].endswith(uid)]
            facts={};stages=[]
            for r in events:
                node=r['key'].split(':')[3];answer=r['response']['answer']
                try:parsed=tool.decode(answer);parse_error=None
                except Exception as exc:parsed=None;parse_error=str(exc)
                stage=dict(key=r['key'],node=node,model=r['model'],answer=answer,
                           decoded=parsed,decode_error=parse_error,
                           injected=bool(r['response'].get('injected_fault')),
                           alias_of=r.get('alias_of'))
                if node.startswith('e'):
                    f,error=parse_facts_safe(answer);facts[node]=f['facts']
                    stage.update(valid_facts=f['facts'],facts_parse_error=bool(error))
                elif node=='r':
                    merged=dict(facts=facts.get('e1',[])+facts.get('e2',[]))
                    value,error=value_of(answer,merged)
                    stage.update(expression_value=value,expression_error=bool(error),
                                 merged_values=[f['value'] for f in merged['facts']])
                    if parsed and 'expression' in parsed:
                        try:exec_calc(parsed['expression'],merged)
                        except Exception as exc:stage['calculation_error']=repr(exc)
                elif node=='v':stage['decoded_value']=json_value(answer)
                stages.append(stage)
            final=stages[-1].get('decoded_value')
            item['executions'].append(dict(scenario=scene,original_Q=record['result']['objectives']['Q'],
                final_value=final,diagnostic_matches_source_annotation=close(final,numeric(q['answer'])) if numeric(q['answer']) is not None else None,
                note='Diagnostic comparison only; original Q preserved.',stages=stages))
        traces.append(item)
    panels=json.loads(PANEL.read_text());aggregate={}
    for name in ('tasks_search','tasks_test'):
        entries=panels[name];counts=dict(n=len(entries),source_numeric=0,source_scale_counts={},
          frozen_gold_mismatch_with_source_numeric=0,percent_factor100_mismatch=0,
          discrepancy_diagnostics=dict(factor100_percent=0,equal_at_two_decimal_places=0,other_discrepancy=0))
        for t in entries:
            _,q=raw[t['uid']];a=numeric(q['answer']);scale=q.get('scale','')
            counts['source_scale_counts'][scale]=counts['source_scale_counts'].get(scale,0)+1
            if a is None:continue
            counts['source_numeric']+=1
            if not close(a,t['answer']):
                counts['frozen_gold_mismatch_with_source_numeric']+=1
                if scale=='percent' and close(t['answer']*100,a):
                    counts['percent_factor100_mismatch']+=1
                    counts['discrepancy_diagnostics']['factor100_percent']+=1
                elif round(t['answer'],2)==round(a,2):
                    counts['discrepancy_diagnostics']['equal_at_two_decimal_places']+=1
                else:counts['discrepancy_diagnostics']['other_discrepancy']+=1
        aggregate[name]=counts
    result=dict(role='Unit/scoring audit, no historical rescoring, no test-performance inspection',
      physical_calls=0,inputs={str(p):digest(p) for p in (SOURCE,PANEL,RUN/'WORKFLOW.jsonl',RUN/'SCENARIOS.jsonl')},
      traces=traces,panel_metadata_only=aggregate,
      findings=[
       'Task1: raw percent answer=517.5, derivation ratio=5.175; hybrid_pool discarded scale and used eval(derivation) as gold. Final outputs match raw annotation but fail frozen gold.',
       'Task1 also has an incorrect initial fact-index expression; verifier independently returns raw annotation. Final correctness does not establish every intermediate node correct.',
       'Task2: question fiscal2018, table2018 highs=100,100,101.51,99.75; raw derivation uses table2019 highs=89,98.35,99.87,97.85. Source question/annotation conflict. Do not silently change task or gold.',
       'Task2 numeric strings fail facts schema; recovery response is truncated JSON. Prompt permits only constants0,1,100 but actual exec_calc accepts rational constants, so /4 is executed successfully: prompt/executor contract mismatch, NOT a runtime arithmetic parse failure. Verification outputs disagree with arithmetic.',
       'Task3: required cash cost840 and acquisition spend2.3; extractor instead selects remaining spend80 and acquisition6, omits2.3; reasoning yields834 but verification765/794 disagrees. Actual extraction and verification errors.',
       'SEARCH8/TEST16 use same eval(derivation) label conversion. Metadata aggregate alone identifies percent label mismatch; no candidate execution outcomes accessed for either panel.'],
      next_step='Version task adapter/evaluation policy using native annotations and scale with independent development fixtures; validate source question/derivation conflicts under a preregistered common rule. Do not mutate frozen panels or historical Q. No real reruns authorized here.')
    (OUT/'UNIT_SCORING_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(panel_metadata_only=aggregate,source_label_matches=[dict(uid=t['uid'],matches=t['source_answer_matches_frozen_gold']) for t in traces],physical_calls=0),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
