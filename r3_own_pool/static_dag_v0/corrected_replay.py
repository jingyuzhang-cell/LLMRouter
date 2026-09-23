"""Corrected replay: v-stage re-decision under the FIXED json_value parser.

Bug (found 2026-09-23): multidag_dynamic.json_value's fence fallback was
    float(json.loads(v.decode(ans))['value'])
json.loads applied to the dict v.decode already returns -> TypeError -> every
```-fenced v output parsed as None. ALL 120 initial v outputs are fenced, so
every arm over-fired its v-stage recovery (v fb/esc on all 120 tasks) and
fenced-but-correct v outputs were scored wrong.

The e-stage and r-stage decisions use parse_facts/value_of only and are
UNAFFECTED by the parser bug; the only decisions driven by json_value are the
v-stage trigger and the final ok. This replay therefore re-decides ONLY the
v stage from the executed artifacts: for each arm/task it takes the executed
key/event structure, checks the v output that existed BEFORE the fb/esc call
with the fixed parser, and drops the fb/esc call (and for FG the whole v
round) if the check passes. All retained outputs are real executed calls
(cache-served); zero new model calls. The v fb/esc prompts used are the
executed ones (ground truth from the REQUESTS log), so this replay does not
depend on reconstructing the exact (partly uncommitted) stage code that ran.
"""
import json
import time

from . import core
from . import tool_aware_v1 as v
from .multidag_dynamic import OUT, close, parse_facts_safe, value_of
from .multidag_ablation import ABL
from .multidag_fullgraph import FG

RES = OUT.parent / 'corrected_replay'


def json_value_fixed(ans):
    try:
        return float(json.loads(ans)['value'])
    except Exception:
        try:
            return float(v.decode(ans)['value'])
        except Exception:
            return None


def load(folder):
    resp = {}
    for l in (folder / 'RESPONSES.jsonl').read_text().splitlines():
        r = json.loads(l)
        resp[r['key']] = r
    return resp


def cost_of(resp, key):
    return float((resp[key]['response'].get('usage') or {}).get('total_tokens') or 0)


def lat_of(resp, key):
    return resp[key]['response'].get('latency_s') or 0


def run():
    RES.mkdir(exist_ok=True)
    resp = load(OUT)
    resp.update(load(ABL))
    resp.update(load(FG))
    pol = json.loads((OUT / 'POLICY.json').read_text())
    tasks = pol['tasks']
    uids = [t['uid'] for t in tasks]
    gold = {t['uid']: t['answer'] for t in tasks}
    base_raw = json.loads((OUT / 'RAW_TAIL.json').read_text())
    abl_raw = json.loads((ABL / 'RAW_TAIL.json').read_text())
    fg_raw = json.loads((FG / 'RAW_TAIL.json').read_text())
    src = {'static': base_raw['static'], 'dynamic': base_raw['dynamic'],
           'sm': abl_raw['sm'], 'rd': abl_raw['rd'], 'fg': fg_raw['fg']}

    def r_value(u, keys):
        rk = [k for k in keys if k.split(':')[0] == 'r'][-1]
        f1, _ = parse_facts_safe(resp[[k for k in keys if k.startswith('e1:')][-1]]['response']['answer'])
        f2, _ = parse_facts_safe(resp[[k for k in keys if k.startswith('e2:')][-1]]['response']['answer'])
        return value_of(resp[rk]['response']['answer'], {'facts': f1['facts'] + f2['facts']})

    out = {}
    for arm in ('static', 'dynamic', 'sm', 'rd', 'fg'):
        armout = {}
        for u in uids:
            st = dict(src[arm][u])
            keys = list(st['keys'])
            events = list(st['events'])
            rounds = list(st.get('rounds', []))
            # locate the v fb/esc key(s): last v key(s) added by the v stage
            if arm == 'fg':
                v_round_keys = {f'{nd}:fg:{u}:v' for nd in ('e1', 'e2', 'r', 'v')}
                v_stage_keys = [k for k in keys if k in v_round_keys]
                v_before = [k for k in keys if k.split(':')[0] == 'v' and k not in v_stage_keys][-1]
            else:
                suffix = {'static': 'fb', 'dynamic': 'esc', 'sm': 'fb', 'rd': 'esc'}[arm]
                v_stage_keys = [f'v:{arm}:{u}:{suffix}']
                v_stage_keys = [k for k in v_stage_keys if k in keys]
                v_before = [k for k in keys if k.split(':')[0] == 'v' and k not in v_stage_keys][-1]
            vval_before = json_value_fixed(resp[v_before]['response']['answer'])
            fire = not close(vval_before, gold[u])
            if not fire:
                # corrected: v-stage recovery does not fire; final v = v_before
                keys = [k for k in keys if k not in v_stage_keys]
                if arm == 'fg':
                    events = [e for e in events if not (e.get('stage') == 'v')]
                    rounds = [r for r in rounds if r['round'] != 'v']
                else:
                    events = [e for e in events if not (e['node'] == 'v' and e.get('attempted') and e.get('kind') == suffix)]
                ok = True
            else:
                if arm in ('static', 'dynamic', 'sm'):
                    ok = close(json_value_fixed(resp[v_stage_keys[0]]['response']['answer']), gold[u])
                else:  # rd, fg: deployable check on v_before
                    rval, rerr = r_value(u, keys)
                    deployable = (vval_before is None) or (not rerr and not close(vval_before, rval))
                    if deployable:
                        vk = f'v:{arm}:{u}:esc' if arm == 'rd' else f'v:fg:{u}:v'
                        ok = close(json_value_fixed(resp[vk]['response']['answer']), gold[u])
                    else:
                        # detector says fine: corrected arm does not recover; final stays wrong
                        keys = [k for k in keys if k not in v_stage_keys]
                        if arm == 'fg':
                            events = [e for e in events if not (e.get('stage') == 'v')]
                            rounds = [r for r in rounds if r['round'] != 'v']
                        else:
                            events = [e for e in events if not (e['node'] == 'v' and e.get('attempted') and e.get('kind') == 'esc')]
                        ok = False
            used = sum(cost_of(resp, k) for k in keys)
            lat = sum(lat_of(resp, k) for k in keys)
            armout[u] = dict(ok=ok, keys=keys, events=events, rounds=rounds,
                             used=used, latency=lat,
                             v_before=v_before, v_fired=fire,
                             r_ok=st.get('r_ok'))
        out[arm] = armout
    summary = {}
    for arm, armout in out.items():
        q = sum(1 for u in uids if armout[u]['ok']) / len(uids)
        summary[arm] = dict(
            Q=round(q, 4),
            mean_tokens=round(sum(armout[u]['used'] for u in uids) / len(uids), 1),
            adaptation_calls=sum(len(armout[u]['keys']) - 4 for u in uids),
            mean_latency_s=round(sum(armout[u]['latency'] for u in uids) / len(uids), 2),
            v_stage_fired=sum(1 for u in uids if armout[u]['v_fired']))
    rep = dict(generated_unix=time.time(), n=len(uids),
               method='v-stage re-decision with fixed json_value on executed artifacts; '
                      'e/r stages unchanged (parser bug does not affect them); '
                      'all retained outputs are real executed calls; zero new model calls',
               summary=summary, arms=out)
    (RES / 'CORRECTED_ARMS.json').write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    run()
