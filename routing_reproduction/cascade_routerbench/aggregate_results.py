import json,pathlib,csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=pathlib.Path(__file__).resolve().parent
rows=[];settings=[];details={}
fig,axes=plt.subplots(3,3,figsize=(15,11),squeeze=False)
for i,dataset in enumerate(('gsm8k','mmlu','mbpp')):
 for j,n in enumerate((3,5,11)):
  name=f'{dataset}_{n}';p=ROOT/'runs'/name/'REPRO_RESULTS.json';ax=axes[i,j]
  ax.set_title(f'{dataset.upper()} · {n} models')
  if not p.exists():ax.text(.5,.5,'Pending',ha='center',va='center',transform=ax.transAxes);continue
  d=json.loads(p.read_text());details[name]=d
  if d['status']=='EXECUTION_ERROR':ax.text(.5,.5,'Execution error',ha='center',transform=ax.transAxes);continue
  a={r['policy']:r['auc'] for r in d['results']}
  settings.append(dict(dataset=dataset,model_count=n,status=d['status'],routing_auc=a['Routing'],cascade_auc=a['Cascade'],cascade_routing_auc=a['Cascade Routing'],delta_vs_routing=a['Cascade Routing']-a['Routing'],delta_vs_cascade=a['Cascade Routing']-a['Cascade'],train_count=d['metadata']['train_count'],test_count=d['metadata']['test_count']))
  for r in d['results']:rows.append(dict(dataset=dataset,model_count=n,seed=0,split_seed=42,**r))
  for label in ('Routing','Cascade','Cascade Routing'):
   rr=[r for r in d['results'] if r['policy']==label];ax.plot([r['normalized_cost'] for r in rr],[r['quality'] for r in rr],marker='.',label=label)
  static=next(r for r in d['results'] if r['policy']=='Best Single / Static');oracle=next(r for r in d['results'] if r['policy']=='Oracle')
  ax.scatter([static['normalized_cost']],[static['quality']],marker='s',color='black',label='Best Single / Static')
  ax.axhline(oracle['quality'],color='gray',linestyle='--',label='Oracle quality')
  ax.set_xlabel('Normalized mean cost');ax.set_ylabel('Quality')
for ax in axes.flat:
 if ax.lines:ax.legend(fontsize=7);break
fig.tight_layout()
for ext in ('png','pdf'):fig.savefig(ROOT/f'fig_cost_quality_curve.{ext}',dpi=160)
complete=len(settings)==9
wins=sum(x['status']=='PASS' for x in settings)
status=('PASS' if wins>=5 else 'FAIL') if complete else 'IN_PROGRESS'
result=dict(status=status,completed_settings=len(settings),planned_settings=9,joint_wins=wins,settings=settings,results=rows,details=details,scope='Requested dataset subsets, zero-shot low-noise, single seed. Not full RouterBench paper-table replication.')
(ROOT/'REPRO_RESULTS.json').write_text(json.dumps(result,indent=2))
if rows:
 with (ROOT/'REPRO_RESULTS.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
lines=[f'# RouterBench subset reproduction: {status}',f'\nCompleted settings: {len(settings)}/9. Cascade Routing exceeds both baselines in {wins} settings. Overall gate requires at least 5/9 joint wins.\n','| Dataset | Models | Train/Test | Routing AUC | Cascade AUC | Cascade Routing AUC | Joint gate |','|---|---:|---:|---:|---:|---:|---|']
for s in settings:lines.append(f"| {s['dataset']} | {s['model_count']} | {s['train_count']}/{s['test_count']} | {s['routing_auc']:.6f} | {s['cascade_auc']:.6f} | {s['cascade_routing_auc']:.6f} | {s['status']} |")
lines += ['\n## Interpretation and limits','The GSM8K three-model smoke passed before the extension was launched. Algorithms, optimization strategies, noise, and split settings were not retuned. Each dataset is filtered before the original 5%/95% split (seed 42). NumPy and upstream Hyperopt seeds are 0. Models and options follow the official scripts/main.sh and scripts/routerbench.py.','Quality/cost estimators use noisy ground truth as in upstream RouterBench simulations, including held-out labels for constructing the simulated estimators. The budget grid also uses held-out single-model aggregates. These results do not establish deployable predictor performance.','The official Hugging Face zero-shot file was SHA-256 verified and converted to CSV without reordering or imputation. Byte identity with the CSV in the authors separate archive has not been established. These subset results must not be equated with the full-benchmark scores quoted in the brief.','AUC uses the unmodified upstream integration. Total cost is replayed benchmark cost summed across all executed model calls, not money spent in this run. Normalized cost divides mean realized cost by the highest held-out single-model mean cost in the pool. Static is selected by training quality and reported as a point; Oracle is a quality upper bound. Their undefined AUC/cost fields remain blank.','One seed only: numerical superiority is not a claim of statistical significance. Small MBPP training set (21 examples) is retained without adjustment. No model API calls were made; the runtime blocks socket connections.','Environment deviations: Python 3.12 venv rather than suggested Python 3.11 Conda; same-release PyTorch CPU build; unused CUDA/triton, xgboost, and tokencost omitted. See REPRO_ENVIRONMENT.json and requirements-resolved.txt.','\n## Artifacts','Per-setting results, exact row indices, raw upstream per-sample outputs, and logs are under runs/. Smoke artifacts are preserved under runs/gsm8k_3/. REPRO_RESULTS.csv provides per-curve-point quality, total/normalized cost, AUC, test sample count and seeds.','\n## Sources','- https://github.com/eth-sri/cascade-routing','- https://github.com/withmartian/routerbench','- https://huggingface.co/datasets/withmartian/routerbench/tree/784021482c3f320c6619ed4b3bb3b41a21424fcb']
(ROOT/'REPRO_SUMMARY.md').write_text('\n'.join(lines)+'\n')
print(status,len(settings),wins)
