"""Label validity and label-free prompt grouping for leakage-resistant experiments."""
import re
import unicodedata
from collections import defaultdict
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors


def normalize_prompt(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def require_valid_quality(response):
    quality = response.get('quality', {})
    if (response.get('status') == 'failed'
            or str(response.get('evaluation_status', '')).startswith('generation_failure')
            or quality.get('quality_source') == 'infrastructure_failure_missing'):
        raise ValueError('Generation/infrastructure failure cannot be a model-quality training label')


def prompt_groups(cohort, threshold=.95):
    """Conservative lexical candidates, verified by token Jaccard >= .85.

    Label-free audit grouping only; no answer normalization or semantic claims.
    Numbers are preserved. Up to 8 lexical neighbours are screened per prompt.
    """
    ids = sorted(cohort)
    texts = [normalize_prompt(cohort[q]['query']) for q in ids]
    parent = list(range(len(ids)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(i, j):
        a, b = find(i), find(j)
        parent[max(a,b)] = min(a,b)
    exact = defaultdict(list)
    for i,t in enumerate(texts): exact[t].append(i)
    edges = []
    for indices in exact.values():
        for i in indices[1:]:
            union(indices[0], i)
            edges.append(dict(left=ids[indices[0]], right=ids[i], kind='normalized_exact'))
    if len(ids)>1:
        x = TfidfVectorizer(ngram_range=(1,2), sublinear_tf=True).fit_transform(texts)
        distances, neighbours = NearestNeighbors(n_neighbors=min(8,len(ids)), metric='cosine', n_jobs=2).fit(x).kneighbors(x)
        tokens = [set(re.findall(r'\w+', t)) for t in texts]
        seen = set()
        for i in range(len(ids)):
            for distance,j in zip(distances[i],neighbours[i]):
                j=int(j)
                key=tuple(sorted((i,j)))
                if i==j or key in seen or texts[i]==texts[j] or 1-distance<threshold: continue
                seen.add(key)
                jac=len(tokens[i]&tokens[j])/max(1,len(tokens[i]|tokens[j]))
                if jac>=.85:
                    union(i,j)
                    edges.append(dict(left=ids[i],right=ids[j],kind='lexical_near_duplicate',cosine=float(1-distance),token_jaccard=jac))
    return {q:ids[find(i)] for i,q in enumerate(ids)}, edges


def fold_cost_profiles(costs, folds):
    """Each held fold receives per-slot cost means fitted on other folds only."""
    costs=np.asarray(costs,float);folds=np.asarray(folds)
    result=np.empty_like(costs)
    for fold in np.unique(folds):
        tr=folds!=fold;va=~tr
        for j in range(costs.shape[1]):
            observed=costs[tr,j];observed=observed[np.isfinite(observed)&(observed>=0)]
            if not len(observed): raise ValueError('No training-fold cost observations for slot')
            result[va,j]=observed.mean()
    return result


def known_exposure(root):
    """Read only IDs/prompts and artifact metadata, never score arrays."""
    import json
    from pathlib import Path
    root=Path(root);ids=set();texts=set();evidence=[]
    pilot=root/'data/frozen/pilot_v1.jsonl'
    if pilot.exists():
        for line in pilot.read_text().split('\n'):
            if line.strip():
                row=json.loads(line);ids.add(row['query_id']);texts.add(normalize_prompt(row['query']))
    for marker in (root/'router_v2').glob('*/TEST_OPENED.json'):
        protocol_path=marker.parent/'PROTOCOL.json'
        if not protocol_path.exists(): continue
        protocol=json.loads(protocol_path.read_text())
        if protocol.get('role')=='synthetic_smoke':continue
        predictions=marker.parent/'PREDICTIONS.npz'
        if not predictions.exists():continue
        with np.load(predictions,allow_pickle=False) as saved:
            test_ids=saved['test_ids'].tolist()
        ids.update(test_ids)
        evidence.append(dict(marker=str(marker),role=protocol.get('role'),test_ids=test_ids,
                             results_present=(marker.parent/'RESULTS.json').exists()))
    return ids,texts,evidence
