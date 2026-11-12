#!/usr/bin/env python3
"""SC-E1.1 Plan A': J1 switched to DS, E outputs reused from canary, 3 arms × ≤3 calls."""
import json, os, sys, time, hashlib, urllib.request, argparse
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent), '/root/capital_opinion_pilot']
import sc_e1_runner as OLD
import sc_e1_scorer as SC
import transport as DS_TRANSPORT

# Reuse system prompts byte-identically
E_SYS, J1_SYS, J2_SYS, SINK_SYS = OLD.E_SYS, OLD.J1_SYS, OLD.J2_SYS, OLD.SINK_SYS

# Plan A' routing: ALL nodes use DS
ROUTING = {'J1': 'ds', 'J2': 'ds', 'SINK': 'ds'}
MAX_TOKENS = {'J1': 8000, 'J2': 4000, 'SINK': 4000}
DS_MODEL, DS_BASE, DS_KEY_ENV = DS_TRANSPORT.OPENAI_MODELS['deepseek']
PRICE_IN, PRICE_OUT = 0.8e-6, 2.8e-6
MAX_CALLS, MAX_TOKENS_TOTAL, MAX_YUAN = 9, 230_000, 0.30

GOLD_PATH = '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/SC_E1_ZHANGZIDAO/TASK_CONTRACT_SC_E1_v1_1.json'


def ds_call(system, user, max_tokens):
    """Make a DeepSeek API call."""
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key:
        key = [l.split('=', 1)[1].strip() for l in open('/root/.env') if l.startswith('DEEPSEEK_API_KEY=')][0]
    body = {'model': DS_MODEL, 'max_tokens': max_tokens,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': user}],
            'response_format': {'type': 'json_object'},
            'thinking': {'type': 'disabled'}}
    req = urllib.request.Request(
        DS_BASE + '/chat/completions',
        data=json.dumps(body).encode('utf-8'), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + key)
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    lat = round(time.monotonic() - t0, 2)
    c = d['choices'][0]['message'].get('content', '')
    if isinstance(c, list):
        c = ''.join(x.get('text', '') for x in c if isinstance(x, dict))
    u = d['usage']
    return {'text': c, 'in': u.get('prompt_tokens', 0),
            'out': u.get('completion_tokens', 0), 'stop': d['choices'][0].get('finish_reason', ''),
            'lat': lat, 'model': d.get('model', DS_MODEL)}


def j1_prompt(e_texts):
    return f"告知书(D1)抽取：\n{e_texts['E_D1']}\n\n决定书(D2)抽取：\n{e_texts['E_D2']}"


def _glm_call(system, user):
    """Call GLM for pi model-switch recovery."""
    import urllib.request as _ur
    key = os.environ.get('STAGE_D_GLM_KEY', '')
    body = {"model": "GLM-5.3-Flash", "max_tokens": 4000,
            "system": system, "messages": [{"role": "user", "content": user}],
            "reasoning_effort": "low"}
    req = _ur.Request("https://open.bigmodel.cn/api/anthropic/v1/messages",
                      data=json.dumps(body, ensure_ascii=False).encode(), method='POST')
    req.add_header("content-type", "application/json")
    req.add_header("x-api-key", key)
    req.add_header("authorization", "Bearer " + key)
    req.add_header("anthropic-version", "2023-06-01")
    t0 = time.monotonic()
    with _ur.urlopen(req, timeout=180) as resp:
        d = json.loads(resp.read().decode())
    text = "".join(b.get("text", "") for b in d.get("content", [])
                   if isinstance(b, dict) and b.get("type") == "text")
    return {"text": text, "in": d["usage"]["input_tokens"],
            "out": d["usage"]["output_tokens"], "stop": d.get("stop_reason"),
            "lat": round(time.monotonic() - t0, 2), "model": d.get("model", "GLM")}


def _qwen_call(system, user):
    """Call Qwen for pi model-switch recovery (0% truncation in prior capability matrix)."""
    import urllib.request as _ur
    key = os.environ.get('QWEN_API_KEY', '')
    if not key:
        key = [l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith('QWEN_API_KEY=')][0]
    body = {"model": "qwen-plus", "max_tokens": 4000,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    req = _ur.Request("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                      data=json.dumps(body, ensure_ascii=False).encode(), method='POST')
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + key)
    t0 = time.monotonic()
    with _ur.urlopen(req, timeout=180) as resp:
        d = json.loads(resp.read().decode())
    c = d["choices"][0]["message"].get("content", "")
    if isinstance(c, list):
        c = "".join(x.get("text","") for x in c if isinstance(x, dict))
    u = d["usage"]
    return {"text": c, "in": u.get("prompt_tokens",0),
            "out": u.get("completion_tokens",0), "stop": d["choices"][0].get("finish_reason",""),
            "lat": round(time.monotonic()-t0, 2), "model": d.get("model","qwen-plus")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--out', default=str(HERE / 'plan_a_runs'))
    ap.add_argument('--replay-v2', action='store_true',
                    help='Replay V2 FR J2 anomaly: use V2 J1, inject real empty J2')
    ap.add_argument('--replay-persistent', action='store_true',
                    help='Inject empty J2 for initial AND R retry (forces pi escalation)')
    a = ap.parse_args()

    if a.real and os.environ.get('SC_E1_1_CANARY_GO') != '1':
        raise SystemExit('REFUSED: need SC_E1_1_CANARY_GO=1')

    # Load cached E outputs
    cached = json.load(open(HERE / 'cached_E_outputs.json'))
    e_texts = {'E_D1': cached['E_D1'], 'E_D2': cached['E_D2']}
    
    # V2 replay: use V2 FR's real J1 output and inject real empty J2
    v2_results = None
    if a.replay_v2:
        v2_path = HERE / 'plan_a_v2_runs' / 'RESULTS.json'
        v2_results = json.load(open(v2_path))
        v2_fr_j1 = v2_results['arms']['Fixed-Recovery']['j1_text']
        v2_fr_j2_empty = v2_results['arms']['Fixed-Recovery']['j2_text']  # the real empty output
        print(f'[REPLAY-V2] Using V2 FR J1 ({len(v2_fr_j1)} chars) and real J2 empty output')
        print(f'[REPLAY-V2] Real J2 anomaly: "{v2_fr_j2_empty}"')

    # Load Gold
    gold = json.load(open(GOLD_PATH))
    facts = gold.get('facts', [])

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / 'LEDGER.jsonl'
    results_path = out / 'RESULTS.json'

    calls_used = 0
    tokens_used = 0
    yuan_used = 0.0
    all_results = {}

    def do_call(arm, node, system, user):
        nonlocal calls_used, tokens_used, yuan_used
        if calls_used >= MAX_CALLS:
            raise SystemExit(f'STOP: call cap {MAX_CALLS}')
        est_tokens = len(user) * 0.8 + MAX_TOKENS.get(node, MAX_TOKENS.get(node.split('_')[0], 4000))
        if tokens_used + est_tokens > MAX_TOKENS_TOTAL:
            raise SystemExit(f'STOP: token cap')
        est_yuan = est_tokens * PRICE_IN + MAX_TOKENS.get(node, MAX_TOKENS.get(node.split("_")[0], 4000)) * PRICE_OUT
        if yuan_used + est_yuan > MAX_YUAN:
            raise SystemExit(f'STOP: yuan cap')

        if a.real:
            r = ds_call(system, user, MAX_TOKENS.get(node, MAX_TOKENS.get(node.split("_")[0], 4000)))
        else:
            r = {'text': '{"party_matrix": []}', 'in': 100, 'out': 50,
                 'stop': 'stop', 'lat': 0.01, 'model': 'mock'}

        tin, tout = r['in'], r['out']
        yuan = tin * PRICE_IN + tout * PRICE_OUT
        calls_used += 1
        tokens_used += tin + tout
        yuan_used += yuan

        rec = {'arm': arm, 'node': node, 'backend': 'ds', 'model': r['model'],
               'in': tin, 'out': tout, 'stop': r['stop'], 'lat': r['lat'],
               'yuan': round(yuan, 6), 'ts': time.time(),
               'text_len': len(r['text'])}
        with open(ledger_path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return r

    ARMS = ('Static', 'Fixed-Recovery', 'Joint-Dynamic')

    def j2_is_empty(j2_text):
        """Semantic anomaly: model returns valid JSON but zero verified facts."""
        try:
            d=json.loads(j2_text)
            return len(d.get('verified',[]))==0
        except:
            return len(j2_text.strip())<50

    for arm in ARMS:
        print(f'\n--- {arm} ---')
        actions=[]
        # J1: replay uses V2's real J1; normal mode calls fresh
        if v2_results:
            j1_text_cached = v2_fr_j1
            j1 = {'text': j1_text_cached, 'stop': 'stop', 'out': len(j1_text_cached)//2,
                  'in': 0, 'lat': 0.0, 'model': 'replayed'}
            print(f'  J1: [REPLAYED from V2, {len(j1_text_cached)} chars, 0 new calls]')
        else:
            j1_user = j1_prompt(e_texts)
            j1 = do_call(arm, 'J1', J1_SYS, j1_user)
        print(f'  J1: stop={j1["stop"]} out={j1["out"]} tok text_len={len(j1["text"])}')
        if j1['stop'] in ('max_tokens', 'length') or not j1['text'].strip():
            all_results[arm] = {'status': 'J1_FAILED', 'j1_stop': j1['stop'], 'actions': actions}
            continue

        # J2: replay injects the real V2 anomaly first
        j2_user = f"J1推理结果：\n{j1['text']}"
        if v2_results:
            j2 = {'text': v2_fr_j2_empty, 'stop': 'stop', 'out': 10,
                  'in': 0, 'lat': 0.0, 'model': 'replayed_anomaly'}
            print(f'  J2: [REPLAYED anomaly: "{j2["text"]}"]')
            _persistent = getattr(a, 'replay_persistent', False)
        else:
            j2 = do_call(arm, 'J2', J2_SYS, j2_user)
        print(f'  J2: stop={j2["stop"]} out={j2["out"]} tok text_len={len(j2["text"])}')
        
        # Strategy-specific J2 anomaly handling
        j2_anomaly = j2['stop'] in ('max_tokens','length') or j2_is_empty(j2['text'])
        
        if j2_anomaly:
            if arm == 'Static':
                # Static: no recovery, accept the failure
                actions.append('J2_anomaly_detected:NO_RECOVERY')
                print(f'  ⚠️ J2 anomaly (empty/truncated) → Static does NOT recover')
            elif arm == 'Fixed-Recovery':
                # FR: same-model retry once
                actions.append('J2_anomaly_detected:R_retry')
                print(f'  ⚠️ J2 anomaly → R (same-model retry)')
                if v2_results and _persistent:
                    j2 = {'text': v2_fr_j2_empty, 'stop': 'stop', 'out': 10,
                          'in': 0, 'lat': 1.0, 'model': 'replayed_persistent_anomaly'}
                    print(f'  J2_retry: [INJECTED persistent anomaly]')
                else:
                    j2 = do_call(arm, 'J2_retry', J2_SYS, j2_user)
                print(f'  J2_retry: stop={j2["stop"]} out={j2["out"]} text_len={len(j2["text"])}')
                if j2_is_empty(j2['text']):
                    actions.append('R_retry:STILL_EMPTY')
                    print(f'  ⚠️ R retry still empty → FR has no further recovery')
                else:
                    actions.append('R_retry:RECOVERED')
            elif arm == 'Joint-Dynamic':
                # JD: R first, then pi if R fails
                actions.append('J2_anomaly_detected:R_retry')
                print(f'  ⚠️ J2 anomaly → R (same-model retry)')
                if v2_results and _persistent:
                    j2 = {'text': v2_fr_j2_empty, 'stop': 'stop', 'out': 10,
                          'in': 0, 'lat': 1.0, 'model': 'replayed_persistent_anomaly'}
                    print(f'  J2_retry: [INJECTED persistent anomaly]')
                else:
                    j2 = do_call(arm, 'J2_retry', J2_SYS, j2_user)
                print(f'  J2_retry: stop={j2["stop"]} out={j2["out"]} text_len={len(j2["text"])}')
                if j2_is_empty(j2['text']):
                    actions.append('R_retry:FAILED')
                    # pi: switch model to GLM
                    actions.append('pi_model_switch:qwen')
                    print(f'  ⚠️ R failed → pi (switch to Qwen)')
                    j2 = _qwen_call(J2_SYS, j2_user)
                    print(f'  J2_pi: stop={j2["stop"]} out={j2["out"]} text_len={len(j2["text"])}')
                    if j2_is_empty(j2['text']):
                        actions.append('pi:STILL_EMPTY')
                    else:
                        actions.append('pi:RECOVERED')
                else:
                    actions.append('R_retry:RECOVERED')
        
        # SINK
        sink_user = f"J1结果：\n{j1['text']}\n\nJ2核验结果：\n{j2['text']}"
        sink = do_call(arm, 'SINK', SINK_SYS, sink_user)
        print(f'  SINK: stop={sink["stop"]} out={sink["out"]} tok text_len={len(sink["text"])}')

        all_results[arm] = {
            'status': 'COMPLETED',
            'j1_stop': j1['stop'], 'j2_stop': j2['stop'], 'sink_stop': sink['stop'],
            'sink_text': sink['text'][:5000],
            'j1_text': j1['text'],
            'j2_text': j2['text'],
            'actions': actions,
        }

    # Summary
    summary = {
        'plan': 'A-prime (J1=DS, E reused)',
        'calls_used': calls_used,
        'tokens_used': tokens_used,
        'yuan_used': round(yuan_used, 4),
        'caps': {'calls': MAX_CALLS, 'tokens': MAX_TOKENS_TOTAL, 'yuan': MAX_YUAN},
        'arms': all_results,
    }
    json.dump(summary, open(results_path, 'w'), ensure_ascii=False, indent=1)
    print(f'\n===== PLAN A\' SUMMARY =====')
    print(f'Calls: {calls_used}/{MAX_CALLS}')
    print(f'Tokens: {tokens_used}/{MAX_TOKENS_TOTAL}')
    print(f'Yuan: ¥{yuan_used:.4f}/{MAX_YUAN}')
    for arm, res in all_results.items():
        print(f'{arm:16s}: {res["status"]}')


if __name__ == '__main__':
    main()
