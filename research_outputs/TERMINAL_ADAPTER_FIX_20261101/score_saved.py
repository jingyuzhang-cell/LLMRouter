"""Offline-only terminal path: saved output -> fixed adapter -> unchanged scorer.
No runner imports: importing the live runner would initialize its ledger.
"""
import argparse,ast,hashlib,json,sys
from pathlib import Path
from online_adapter import adapt_sink
ROOT=Path(__file__).resolve().parent
OLD=Path('/root/research_outputs/mvr_batch1')
BASE=Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence')
EVAL_PATH='/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def scoring_route():
    tree=ast.parse((OLD/'runner.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='eval_run')
    ns={'sys':sys,'EVAL_PATH':EVAL_PATH}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(OLD/'runner.py'),'exec'),ns)
    return ns['eval_run']

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('OUTPUT_EXISTS_NO_OVERWRITE')
    contracts={}
    paths={'MVR1':BASE/'MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json',
           'MVR2':BASE/'MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json'}
    protected=[OLD/'runner.py',OLD/'pairs.jsonl',OLD/'ledger.jsonl',Path(EVAL_PATH)/'terminal_quality.py',*paths.values()]
    before={str(f):digest(f) for f in protected}
    for tid,path in paths.items():
        c=json.loads(path.read_text());c['_source_pages']=c.pop('source_pages');contracts[tid]=c
    evaluate=scoring_route();rows=[]
    for line in (OLD/'pairs.jsonl').read_text().splitlines():
        pair=json.loads(line)
        for arm,record in pair['arms'].items():
            stored=record['terminal']
            terminal=adapt_sink(json.dumps(stored,ensure_ascii=False),contracts,pair['task'])
            assert [c['value'] for c in terminal['claims']]==[c['value'] for c in stored['claims']]
            score=evaluate(contracts,pair['task'],terminal)
            rows.append(dict(task=pair['task'],pair=pair['pair'],arm=arm,
                             original_f1=record['eval']['fact_metrics']['f1'],
                             shadow_f1=score['fact_metrics']['f1'],
                             shadow_gate=score['critical_gate']['status'],
                             shadow_Q_final=score['Q_final'],
                             adapter_diagnostics=terminal['adapter_diagnostics'],
                             values_unchanged=True,blocking_reasons=score['blocking_reasons']))
    after={str(f):digest(f) for f in protected};assert before==after
    result=dict(mode='OFFLINE_SAVED_TERMINAL_INTEGRATION',raw_model_output_replay=False,
                input_scope='Archived terminal objects; no reconstruction of missing model text',
                rows=rows,source_hashes=before,protected_files_unchanged=True,
                network_calls=0,live_transport_present=False,
                historical_scores_replaced=False)
    with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(dict(runs=len(rows),nonzero_f1=sum(r['shadow_f1']>0 for r in rows),
                         gate_fail=sum(r['shadow_gate']=='FAIL' for r in rows),new_calls=0)))
if __name__=='__main__':main()
