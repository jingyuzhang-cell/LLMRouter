"""Fixed diagnostic interventions; outer OOF curves are descriptive, never selection."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
import torch
import torch.nn.functional as F
from .data import sha
from .core import paired_ci, rank_loss
from .experiment import Router
from .diagnose_rank_signal import load_inputs

CHECKPOINTS = (1, 5, 10, 20, 40, 60)


class NormalizedModelRouter(Router):
    def predict_batch(self, q):
        outs = []
        for m in range(4):
            mm = torch.full((len(q),), m, dtype=torch.long)
            representation = F.normalize(self.m_emb(mm), dim=1)
            outs.append(self.net(torch.cat([q, representation], 1)).squeeze(-1))
        return torch.stack(outs, 1)


def make_model(kind, dim, seed):
    if kind == 'normalized_model':
        return NormalizedModelRouter(q_dim=dim, seed=seed, alpha=0.)
    return Router(q_dim=dim, seed=seed, alpha=0., use_m_emb=kind != 'four_head')


def diagnostic_fit(kind, xt, yt, xv, yv, seed, epochs=60):
    model = make_model(kind, xt.shape[1], seed)
    initial = dict(query_norm_mean=float(np.linalg.norm(xt, axis=1).mean()),
                   parameters=sum(p.numel() for p in model.parameters()))
    if model.use_m_emb:
        initial['raw_model_embedding_norm_mean'] = float(model.m_emb.weight.detach().norm(dim=1).mean())
        initial['effective_model_embedding_norm_mean'] = 1. if kind == 'normalized_model' else initial['raw_model_embedding_norm_mean']
    rng = np.random.default_rng(seed)
    history = []
    for epoch in range(1, epochs+1):
        model.train()
        order = rng.permutation(len(xt))
        for start in range(0, len(xt), 64):
            idx = order[start:start+64]
            pred = model.predict_batch(torch.tensor(xt[idx], dtype=torch.float32))
            target = torch.tensor(yt[idx], dtype=torch.float32)
            loss = ((pred-target)**2).mean() + model.alpha*rank_loss(pred,target,model.margin)
            model.opt.zero_grad()
            loss.backward()
            model.opt.step()
        if epoch in CHECKPOINTS or epoch == epochs:
            pt, pv = model.predict_all(xt), model.predict_all(xv)
            history.append(dict(epoch=epoch, train_mse=float(((pt-yt)**2).mean()),
                held_mse=float(((pv-yv)**2).mean()),
                train_routed_quality=float(yt[np.arange(len(yt)),pt.argmax(1)].mean()),
                held_routed_quality=float(yv[np.arange(len(yv)),pv.argmax(1)].mean()),
                held_route_fraction=(np.bincount(pv.argmax(1),minlength=4)/len(yv)).tolist()))
    return pv, history, initial


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    torch.set_num_threads(4)
    source=Path(args.source).resolve();out=Path(args.output).resolve()
    frozen,x,datasets=load_inputs(source);y=frozen['quality'];folds=frozen['folds']
    out.mkdir(parents=True,exist_ok=False)
    sources=[Path(__file__),Path(__file__).with_name('experiment.py'),Path(__file__).with_name('core.py'),Path(__file__).parents[1]/'train_router.py']
    protocol=dict(role='exploratory_train_only_mechanism',seeds=[42,43,44],epochs=60,
        variants=['original','normalized_model','four_head'],source=str(source),
        source_oof_sha256=sha(source/'OOF.npz'),implementation={str(p):sha(p) for p in sources},
        checkpoints=CHECKPOINTS,selection='No selection by outer fold curves; all final comparisons use epoch 60',
        hypotheses=['Train vs held error divergence indicates overfitting in this configuration',
          'Unit-normalized model embedding tests relative-scale intervention with same parameter count',
          'Query-only four-head network tests model structure but also changes parameter count'],
        limits=['Development diagnosis, not independent test','No cost or latency inference','Checkpoint curves descriptive only'])
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2))
    predictions={};traces=[]
    for seed in protocol['seeds']:
        for kind in protocol['variants']:
            key=f'{kind}_seed{seed}';predictions[key]=np.zeros_like(y)
            for fold in (0,1,2):
                started=time.monotonic();tr=folds!=fold;va=folds==fold
                pred,history,initial=diagnostic_fit(kind,x[tr],y[tr],x[va],y[va],seed)
                predictions[key][va]=pred
                traces.append(dict(kind=kind,seed=seed,fold=fold,initial=initial,history=history))
                print(f'{key} fold={fold} complete {time.monotonic()-started:.1f}s',flush=True)
            np.savez_compressed(out/f'{key}.npz',predicted_quality=predictions[key])
    for path,digest in protocol['implementation'].items():
        if sha(path)!=digest:raise ValueError('Implementation changed during experiment')
    (out/'TRACES.json').write_text(json.dumps(traces,indent=2))
    reports={}
    index=np.arange(len(y));base=y[index,frozen['DatasetBest']]
    for key,pred in predictions.items():
        values=y[index,pred.argmax(1)];diff=values-base
        reports[key]=dict(quality=float(values.mean()),vs_dataset_best=float(diff.mean()),ci95=paired_ci(diff),
            routing=(np.bincount(pred.argmax(1),minlength=4)/len(y)).tolist(),
            by_dataset={ds:float(values[datasets==ds].mean()) for ds in sorted(set(datasets))})
    result=dict(role=protocol['role'],methods=reports,files={p.name:sha(p) for p in out.glob('*.npz')},
                validation_labels_loaded=False,test_labels_loaded=False)
    (out/'RESULTS.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(reports,indent=2),flush=True)


if __name__=='__main__':main()
