"""Prompt-bound cache snapshots. Execution keys are not cache identities.

Only delivered, non-injected responses paired with requests in the same source
folder enter the cache. Snapshots cannot be poisoned by later fault overrides.
"""
import copy
import hashlib
import json
from pathlib import Path


def prompt_id(model, prompt):
    return model, hashlib.sha256(prompt.encode()).hexdigest()


def load_prompt_cache(folders):
    cache = {}
    for folder in folders:
        folder = Path(folder)
        if any('BUGGY' in part for part in folder.parts):
            continue
        rp, qp = folder / 'RESPONSES.jsonl', folder / 'REQUESTS.jsonl'
        if not rp.exists() or not qp.exists():
            continue
        responses = {r['key']: r for line in rp.read_text().splitlines() if line
                     for r in [json.loads(line)]}
        for line in qp.read_text().splitlines():
            if not line:
                continue
            q = json.loads(line)
            r = responses.get(q['key'])
            if r is None or r.get('model') != q['model']:
                continue
            response = r['response']
            if response.get('status') != 'delivered' or response.get('injected_fault'):
                continue
            cache.setdefault(prompt_id(q['model'], q['prompt']), copy.deepcopy(r))
    return cache


def cached_record(cache, key, model, prompt):
    src = cache.get(prompt_id(model, prompt))
    if src is None:
        return None
    return dict(key=key, model=model, response=copy.deepcopy(src['response']),
                alias_of=src['key'])
