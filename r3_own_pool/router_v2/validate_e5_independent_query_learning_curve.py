"""Independent reconstruction of E5 artifact metrics and paired intervals."""
import json
from pathlib import Path
import numpy as np
from .data import sha

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'router_v2/e5_independent_query_learning_curve'


def main():
    p=json.loads((OUT/'PROTOCOL.json').read_text()); r=json.loads((OUT/'RESULTS.json').read_text())
    for path,h in p['hashes'].items(): assert sha(path)==h, path
    assert sha(OUT/'PROTOCOL.json')==r['protocol_sha256']
    assert sha(OUT/'PER_FOLD.jsonl')==r['per_fold_sha256']
    assert sha(OUT/'POOLED_PREDICTIONS.npz')==r['pooled_predictions_sha256']
    inp=np.load(OUT/'INPUTS.npz',allow_pickle=False); z=np.load(OUT/'POOLED_PREDICTIONS.npz',allow_pickle=False)
    ids=inp['ids'].tolist(); ix={q:i for i,q in enumerate(ids)}; y=inp['quality'].astype(float)
    samples=[json.loads(s) for s in (OUT/'SAMPLES.jsonl').open()]
    records=[json.loads(s) for s in (OUT/'PER_FOLD.jsonl').open()]
    assert len(samples)==120 and len(records)==240 and len(set(inp['groups']))==400
    frozen=json.loads((ROOT/'router_v2/experiment_repeat_compatibility_400_fold_local/FOLDS.json').read_text())
    sizes=['40','80','120','Full']; reps=['Original','Content_secondary']; methods=r['methods']
    for f in frozen:
        for seed in p['subsampling_seeds']:
            prior=set()
            for n in sizes:
                sample=next(s for s in samples if s['fold']==f['fold'] and s['subsampling_seed']==seed and s['n']==n)
                dev=set(sample['development_ids']); test=set(sample['test_ids'])
                assert dev<=set(f['development_ids']) and prior<=dev and not dev&test
                assert sample['test_ids']==f['test_ids']
                assert len(dev)==(len(f['development_ids']) if n=='Full' else int(n))
                assert set(sample['inner_train_ids'])|set(sample['inner_validation_ids'])==dev
                assert not set(sample['inner_train_ids'])&set(sample['inner_validation_ids'])
                prior=dev
    accum=np.zeros_like(z['train_sum']); counts=np.zeros_like(z['train_counts']); cover=np.zeros_like(counts)
    selections=np.zeros_like(z['selections'])
    for row in records:
        ri=reps.index(row['representation']); ni=sizes.index(row['n']); si=p['subsampling_seeds'].index(row['subsampling_seed'])
        file=OUT/'jobs'/f'{row["job"]}.npz'; meta=json.loads((OUT/'jobs'/f'{row["job"]}.json').read_text())
        assert sha(file)==row['source_prediction_sha256']==meta['npz_sha256']
        job=np.load(file,allow_pickle=False); d=job['development_indices']; t=job['test_indices']; b=int(job['bestsingle'])
        assert b==inp['quality'][d].mean(0).argmax()
        assert [v['optimization_seed'] for v in meta['ma_fit']]==[42,43,44]
        assert all(1<=v['best_epoch']<=100 for v in meta['ma_fit'])
        tq=[y[t,b],y[t,job['ridge_test'].argmax(1)],y[t[None,:],job['ma_test'].argmax(2)].mean(0)]
        dq=[y[d,b],y[d,job['ridge_train'].argmax(1)],y[d[None,:],job['ma_train'].argmax(2)].mean(0)]
        c=[np.bincount(np.full(len(t),b),minlength=4),np.bincount(job['ridge_test'].argmax(1),minlength=4),np.bincount(job['ma_test'].argmax(2).ravel(),minlength=4)/3]
        counts[ri,ni,si,d]+=1;cover[ri,ni,si,t]+=1
        for mi,m in enumerate(methods):
            np.testing.assert_allclose(tq[mi],z['test'][ri,ni,si,mi,t])
            accum[ri,ni,si,mi,d]+=dq[mi];selections[ri,ni,si,mi]+=c[mi]
            assert np.isclose(tq[mi].mean(),row['methods'][m]['outer_test_expected_quality'])
            assert np.isclose(dq[mi].mean(),row['methods'][m]['train_expected_quality'])
    np.testing.assert_allclose(accum,z['train_sum']);np.testing.assert_array_equal(counts,z['train_counts'])
    np.testing.assert_allclose(selections,z['selections']);assert np.all(cover==1)
    boot=np.random.default_rng(20260914).integers(0,400,(10000,400))
    def meanboot(q):return q[boot].mean(1)
    def check_summary(a,summary):
        assert np.isclose(a.mean(),summary['mean'])
        assert np.isclose(a.std(ddof=1),summary['std'])
        np.testing.assert_allclose(a,summary['by_subsampling_seed'])
    def check_ci(values,summary):np.testing.assert_allclose(np.quantile(values,[.025,.975]),summary['ci95'],atol=1e-9)
    for ri,rep in enumerate(reps):
        trdist={};tedist={}
        for ni,n in enumerate(sizes):
            level=r['representations'][rep]['levels'][n]
            base=z['test'][ri,ni,:,0];gap=y.max(1)-base.mean(0)
            for mi,m in enumerate(methods):
                mm=level['methods'][m];a=z['test'][ri,ni,:,mi]
                train=accum[ri,ni,:,mi].sum(1)/counts[ri,ni].sum(1)
                te=meanboot(a.mean(0)); num=accum[ri,ni,:,mi].sum(0);den=counts[ri,ni].sum(0)
                tr=num[boot].sum(1)/den[boot].sum(1);trdist[ni,mi]=tr;tedist[ni,mi]=te
                check_summary(a.mean(1),mm['outer_test_expected_quality']);check_ci(te,mm['outer_test_expected_quality'])
                check_summary(train,mm['train_expected_quality']);check_ci(tr,mm['train_expected_quality'])
                check_summary(train-a.mean(1),mm['train_test_gap']);check_ci(tr-te,mm['train_test_gap'])
                gain=(a-base);check_summary(gain.mean(1),mm['comparison_vs_bestsingle']);check_ci(meanboot(gain.mean(0)),mm['comparison_vs_bestsingle'])
                check_summary(gain.mean(1)/(y.max(1).mean()-base.mean(1)),mm['gap_recovery'])
                check_ci(meanboot(gain.mean(0))/meanboot(gap),mm['gap_recovery'])
            diff=z['test'][ri,ni,:,2]-z['test'][ri,ni,:,1]
            check_summary(diff.mean(1),level['delta_ma_minus_queryonly']);check_ci(meanboot(diff.mean(0)),level['delta_ma_minus_queryonly'])
        for ai,bi in [(0,1),(1,2),(2,3),(0,3)]:
            transition=r['representations'][rep]['marginal_gains'][f'{sizes[ai]}_to_{sizes[bi]}']
            for mi,m in enumerate(methods):
                aa=z['test'][ri,bi,:,mi]-z['test'][ri,ai,:,mi]
                check_summary(aa.mean(1),transition[m]['outer_test_change']);check_ci(meanboot(aa.mean(0)),transition[m]['outer_test_change'])
                check_ci(trdist[bi,mi]-trdist[ai,mi],transition[m]['train_change'])
                check_ci(trdist[bi,mi]-trdist[ai,mi]-tedist[bi,mi]+tedist[ai,mi],transition[m]['train_test_gap_change'])
            diff=(z['test'][ri,bi,:,2]-z['test'][ri,bi,:,1])-(z['test'][ri,ai,:,2]-z['test'][ri,ai,:,1])
            check_summary(diff.mean(1),transition['delta_ma_minus_queryonly_change']);check_ci(meanboot(diff.mean(0)),transition['delta_ma_minus_queryonly_change'])
    full=[v for v in records if v['representation']=='Original' and v['n']=='Full']
    assert all(json.loads((OUT/'jobs'/f'{v["job"]}.json').read_text())['full_baseline_reproduced'] for v in full)
    assert r['assessment']['E']['secondary_used'] is False
    result=dict(passed=True,validator_sha256=sha(Path(__file__)),samples=120,per_fold_records=240,
                unique_jobs=len(list((OUT/'jobs').glob('*.json'))),ma_initializations=558,
                sampling_and_folds=True,all_query_predictions_reconstructed=True,selection_distributions=True,
                means_and_subsampling_std=True,paired_bootstrap_intervals=True,oracle_ratio_intervals=True,
                marginal_gains=True,full_baselines_reproduced=True,no_secondary_for_primary_verdict=True)
    (OUT/'INDEPENDENT_VALIDATION.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
