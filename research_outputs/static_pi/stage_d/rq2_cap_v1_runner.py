#!/usr/bin/env python3
"""RQ2_CAP_V1 runner: 4 models x 19 frozen nodes x 5 reps node-level capability
measurement (RQ2_CAP_V1_PREREGISTRATION.md). Real mode requires --real AND env
STAGE_D_REAL_CALLS_AUTHORIZED=1 AND STAGE_D_GLM_KEY (+ DEEPSEEK_API_KEY,
QWEN_API_KEY present). Mock mode = zero real calls.

Frozen node inputs are rebuilt from V3 HomImp reference execs (E05 r1, E06 r1,
E07 r2, E08 r1); prompt_sha recorded per node and cross-checkable against the
HomImp ledger. Uniform max_tokens=6000; D2 contract on delivery kinds only.
Results append to rq2_cap_v1_runs/results.jsonl; resume skips existing
(task,node,model,rep) rows. Budget via frozen GlobalBudget.
"""
import os, sys, json, time, argparse, urllib.request, hashlib
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import MATS, TASKS, SYS_COMMON, node_prompt, parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT, DELIVERY_KINDS
from stage_d_executor import GlobalBudget
import rq2_p2r_v2_analyze as SCORE  # frozen V1.5 gold matcher

REF = {('E05'): 1, ('E06'): 1, ('E07'): 2, ('E08'): 1}
MODELS = ['glm53flash', 'glm53', 'deepseek', 'qwen']
YUAN = {'glm53flash': 0.04, 'glm53': 0.10, 'deepseek': 0.0129, 'qwen': 0.02}
MAXTOK = 6000
REPS = 5
GLM_EP = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
QWEN_EP = 'https://dashscope.aliyuncs.com/compatible-mode/v1'


def cap_transport(model, system, user, max_tokens, timeout_s=180):
    """Frozen request bodies; glm53 = flash body with model id GLM-5.3;
    deepseek/qwen = frozen openai_call body shape (qwen reads QWEN_API_KEY)."""
    if model in ('glm53flash', 'glm53'):
        body = {"model": ('GLM-5.3-Flash' if model == 'glm53flash' else 'GLM-5.3'),
                "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}],
                "reasoning_effort": "low"}
        req = urllib.request.Request(
            GLM_EP, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
            method='POST')
        key = os.environ.get('STAGE_D_GLM_KEY', '').strip()
        req.add_header('content-type', 'application/json')
        req.add_header('x-api-key', key)
        req.add_header('authorization', 'Bearer ' + key)
        req.add_header('anthropic-version', '2023-06-01')
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        return {"text": "".join(b.get('text', '') for b in d.get('content', [])
                                if isinstance(b, dict) and b.get('type') == 'text'),
                "in": d["usage"]["input_tokens"],
                "out": d["usage"]["output_tokens"],
                "stop": d.get("stop_reason"), "lat": round(time.monotonic() - t0, 2),
                "model": d.get('model')}
    model_id, base, envk = (('deepseek-flash', 'https://api.deepseek.com',
                             'DEEPSEEK_API_KEY') if model == 'deepseek'
                            else ('qwen-plus', QWEN_EP, 'QWEN_API_KEY'))
    body = {"model": model_id, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    if model == 'deepseek':
        body["thinking"] = {"type": "disabled"}
    req = urllib.request.Request(
        base + '/chat/completions', data=json.dumps(body).encode('utf-8'),
        method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + os.environ.get(envk, ''))
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        d = json.loads(r.read().decode())
    c = d["choices"][0]["message"].get("content", "")
    if isinstance(c, list):
        c = "".join(x.get("text", "") for x in c if isinstance(x, dict))
    u = d["usage"]
    return {"text": c, "in": u.get("prompt_tokens", u.get("input_tokens", 0)),
            "out": u.get("completion_tokens", u.get("output_tokens", 0)),
            "stop": d["choices"][0].get("finish_reason", ''),
            "lat": round(time.monotonic() - t0, 2), "model": d.get('model')}


def reference_upstream(task):
    d = json.load(open(HERE / 'rq2_p2r_v3_runs' /
                       f'HomImp__{task}__r{REF[task]}.json'))
    return {x['node_id']: x['chosen']['facts'] for x in d['nodes']
            if 'chosen' in x}


def gold_for(task, node):
    return [SCORE.FACTS[f] for f in node.get('fact_ids', [])]


def score_output(task, node, text):
    ok, facts, unk = parse_facts(text)
    gs = gold_for(task, node)
    if not ok:
        return dict(parse_ok=False, matched=0, n=len(gs), facts=0,
                    node_q=0.0 if gs else None)
    matched = sum(1 for g in gs if any(SCORE.match(g, f) for f in facts
                                       if isinstance(f, dict)))
    return dict(parse_ok=True, matched=matched, n=len(gs), facts=len(facts),
                node_q=(matched / len(gs)) if gs else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq2_cap_v1_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq2_cap_v1_runs'))
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--probe-only', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED: STAGE_D_REAL_CALLS_AUTHORIZED=1 required')
        if not os.environ.get('STAGE_D_GLM_KEY', '').strip():
            raise SystemExit('REFUSED: STAGE_D_GLM_KEY not set')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                raise SystemExit(f'REFUSED: {k} not set')
        print('REAL MODE — caps:', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE — zero real calls')
    out = Path(a.out)
    (out / 'state').mkdir(parents=True, exist_ok=True)
    gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'),
                      out / 'state')
    ledger = out / 'ledger.jsonl'
    results = out / 'results.jsonl'
    done = set()
    if results.exists():
        for line in open(results):
            r = json.loads(line)
            done.add((r['task'], r['node'], r['model'], r['rep']))

    def call(model, system, user, max_tokens, meta):
        est = YUAN[model]
        gb.reserve_call(est)
        need = gb.reserve_tokens(min(len(user), 12000), max_tokens)
        t0 = time.monotonic()
        if a.real:
            r = cap_transport(model, system, user, max_tokens)
            text, tin, tout = r['text'], r['in'], r['out']
            stop, lat, mresp = r['stop'], r['lat'], r.get('model')
        else:
            text = json.dumps({"facts": [{"fid": "mock", "value": "mock",
                                          "doc": "doc1",
                                          "quote": "mock"}], "unknown": []},
                              ensure_ascii=False)
            tin, tout, stop, lat, mresp = len(user), 64, 'end_turn', 0.01, None
        gb.release_reservation(need, tin, tout)
        gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), model=model, model_resp=mresp,
                   max_tokens=max_tokens, tin=tin, tout=tout, yuan=est,
                   stop=stop, lat=lat,
                   prompt_sha=hashlib.sha256(
                       (system + '||' + user).encode()).hexdigest()[:16],
                   **meta)
        with open(ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text, rec

    # probes for new channels (glm53, qwen)
    active = list(MODELS)
    if a.real and not a.probe_only:
        for m in ('glm53', 'qwen'):
            try:
                _, pr = call(m, '只输出JSON。', '{"facts":[],"unknown":[]}',
                             200, {'task': 'PROBE', 'node': 'probe',
                                   'model_probe': m, 'rep': 0})
                print(f'probe {m}: ok stop={pr["stop"]} model_resp={pr["model_resp"]}')
            except Exception as e:
                active.remove(m)
                print(f'probe {m}: FAILED ({type(e).__name__}) -> excluded')
    if a.probe_only:
        print('probe-only done; active:', active)
        return

    n = 0
    for task in TASKS:
        upstream = reference_upstream(task)
        for node in MATS['tasks'][task]['nodes']:
            delivery = node['kind'] in DELIVERY_KINDS
            sysp = SYS_COMMON + (D2_CONTRACT if delivery else '')
            userp = node_prompt(task, node, upstream)
            for model in active:
                for rep in range(1, REPS + 1):
                    if (task, node['node_id'], model, rep) in done:
                        continue
                    if gb.left()['calls_left'] < 5:
                        print('STOP: boundary guard (calls_left<5)')
                        return
                    text, _ = call(model, sysp, userp, MAXTOK,
                                   dict(task=task, node=node['node_id'],
                                        kind=node['kind'], rep=rep))
                    s = score_output(task, node, text)
                    with open(results, 'a') as f:
                        f.write(json.dumps(
                            dict(task=task, node=node['node_id'],
                                 kind=node['kind'], model=model, rep=rep,
                                 delivery=delivery, **s), ensure_ascii=False)
                            + '\n')
                    n += 1
                    if n % 20 == 0:
                        print(f'  {n} rows done, calls_left='
                              f'{gb.left()["calls_left"]}')
    print(f'BATCH DONE: rows={n} budget={gb.left()}')


if __name__ == '__main__':
    main()
