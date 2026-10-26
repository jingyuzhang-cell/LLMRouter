"""Clean t4 redundancy A/B — the ONLY structure-variance experiment for the
doc->t4 duplicate-injection hypothesis (operator continue-directive on the
STEP2_STRUCTURE_AUDIT proposal, 2026-10-26).

Arms (ONLY the t4 user prompt differs; everything else byte-identical):
  DEDUP — E4 node_prompt as-is (t4 consumes merged facts only)
  DUP   — DEDUP text + the t1-line raw-evidence slice appended
           (event['lines']['t1'][:2000]), reconstructing the pre-E4
           duplicate raw-evidence channel per E1's finding.

Controls:
  - Model: glm53flash on ALL nodes (subscription track, marginal cash ¥0),
    thinking disabled, OUT_CAPS from e4 (extract 3072 / mid 1536 / report 2048)
  - SERIAL executor t1..t6 (no threads — parallelism excluded by design)
  - Same event packs as five-strategy v2 (st_packs()), same scorer
    (st_scoring_v2, program-anchored) for both arms
  - n=5 per arm, alternating DEDUP/DUP; fcntl single-instance lock
  - Guard: 66 calls / 1800s wall / subscription cash 0 recorded;
    per-run fail-stop on transport/contract failure (run INCOMPLETE,
    next run); >=3 INCOMPLETE runs -> batch stop
  - Pre-registered criteria in T4AB_FREEZE.json (gate: T4AB_GO=1
    + --freeze-sha256 + clean committed freeze)

Criteria (descriptive, n=5):
  quality_noninferior : mean T1(DEDUP) >= mean T1(DUP)
  cost_improved       : mean tokens(DEDUP) < mean tokens(DUP)
  latency_improved    : mean serial wall(DEDUP) < mean wall(DUP)
  structure_benefit_supported iff quality_noninferior AND
  (cost_improved OR latency_improved). Negative verdicts preserved.
"""
import argparse, fcntl, hashlib, json, os, sys, time, traceback
import urllib.request
from pathlib import Path

P = Path(__file__).resolve().parent
sys.path.insert(0, str(P))
from e4_controlled_experiment import (load_env, _glm_key, GLM_ENDPOINT,
                                      GLM_MODELS, node_prompt, parse_node,
                                      OUT_CAPS, NODE_KIND, EVID_CHARS)
import st_pairing_v2 as sp2
import st_scoring_v2 as s2
from merge_facts import merge_facts

ALIAS = 'glm53flash'
MODEL = GLM_MODELS[ALIAS]
# v2 caps (symmetric, both arms): mechanism-diagnosed after run 1 —
# t4 outputs exceed the e4 mid cap 1536 (substantive JSON truncated on
# BOTH arms), one t2 thinking-burn at 3072 with zero text (documented
# GLM variance). Raised per prior r2fix-line evidence; criteria and
# all other controls unchanged.
OUT_CAPS_V2 = {'extract': 4096, 'mid': 3072, 'report': 3072}
NODES = ['t1', 't2', 't3', 't4', 't5', 't6']
CAP_CALLS, CAP_WALL_S = 66, 1800.0
MAX_INCOMPLETE = 2
DUP_SLICE = 2000

FREEZE_PATH = P / 'T4AB_FREEZE.json'


def glm_call(system, user, max_tokens):
    body = {'model': MODEL, 'max_tokens': max_tokens,
            'thinking': {'type': 'disabled'},
            'system': system, 'messages': [{'role': 'user', 'content': user}]}
    req = urllib.request.Request(GLM_ENDPOINT,
                                 data=json.dumps(body).encode(), method='POST')
    key = _glm_key()
    req.add_header('content-type', 'application/json')
    req.add_header('x-api-key', key)
    req.add_header('authorization', 'Bearer ' + key)
    req.add_header('anthropic-version', '2023-06-01')
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode())
    return {'text': ''.join(b.get('text', '') for b in d.get('content', [])
                            if b.get('type') == 'text'),
            'in': d['usage']['input_tokens'],
            'out': d['usage']['output_tokens'],
            'stop': d.get('stop_reason'),
            'lat': round(time.monotonic() - t0, 2)}


def t4_user(arm, event, merged_json):
    system, user = node_prompt(event, 't4', merged_json, {})
    if arm == 'DUP':
        user = (user + '\n补充证据原文（监管线）：\n'
                + event['lines']['t1'][:DUP_SLICE])
    return system, user


def build_freeze(event):
    dedup_sys, dedup_user = t4_user('DEDUP', event, 'MERGED_JSON')
    dup_sys, dup_user = t4_user('DUP', event, 'MERGED_JSON')
    return {
        'id': 'T4_CLEAN_AB_20261026_V2',
        'revision_reason': 'v1 batch fail-stopped: t4 truncation at mid cap 1536 on BOTH arms + one t2 thinking-burn; caps raised symmetrically to 4096/3072/3072 per pre-documented r2fix-line evidence; criteria/controls unchanged',
        'arms': {
            'DEDUP': dict(t4_user_sha256=hashlib.sha256(
                (dedup_sys + '\x00' + dedup_user).encode()).hexdigest(),
                spec='E4 node_prompt(t4): merged facts only'),
            'DUP': dict(t4_user_sha256=hashlib.sha256(
                (dup_sys + '\x00' + dup_user).encode()).hexdigest(),
                spec='DEDUP + event.lines.t1[:2000] raw-evidence channel '
                     '(reconstruction of the pre-E4 duplicate injection '
                     'documented by E1)'),
        },
        'difference_claim': 'arm prompts identical except the appended '
                            'raw-evidence slice in DUP t4',
        'model': dict(alias=ALIAS, model_id=MODEL, thinking='disabled',
                      out_caps=OUT_CAPS_V2, temperature='endpoint default'),
        'executor': 'serial t1..t6, no threads',
        'event': dict(task=sp2.TASK_ST, dup_slice_chars=DUP_SLICE,
                      evid_chars=EVID_CHARS,
                      note='jsst/舜天 dev sample (event used in prior dev '
                           'experiments; not an unseen confirmation set)'),
        'scoring': 'st_scoring_v2.score_report_st on t6 raw + t5 value; '
                   'chain_filter_st vs pack_text; program-anchored, '
                   'identical for both arms',
        'n_per_arm': 5, 'order': 'alternating DEDUP,DUP x5',
        'caps': dict(calls=CAP_CALLS, wall_s=CAP_WALL_S,
                     cash='subscription marginal ¥0 (recorded, not billed '
                          'per-token on this track)'),
        'fail_policy': 'per-run fail-stop (run INCOMPLETE, no retry); '
                       f'>={MAX_INCOMPLETE + 1} INCOMPLETE runs -> batch stop',
        'criteria': {
            'quality_noninferior': 'mean T1(DEDUP) >= mean T1(DUP)',
            'cost_improved': 'mean tokens(DEDUP) < mean tokens(DUP)',
            'latency_improved': 'mean serial wall(DEDUP) < mean wall(DUP)',
            'structure_benefit_supported':
                'quality_noninferior AND (cost_improved OR latency_improved)'},
        'billing_note': 'GLM subscription track: ¥0 marginal cash per call '
                        '(frozen rates glm_53_flash subscription); tokens '
                        'and wall recorded as the cost/latency axes'}


def run_once(arm, rid, event, meter_state, ledger, resp):
    outputs = {}
    node_log = []
    merged_json = ''
    t0 = time.monotonic()
    for node in NODES:
        if node in ('t3', 't4', 't5', 't6'):
            merged_json = json.dumps(outputs.get('m', {}), ensure_ascii=False)
        if node == 't4':
            system, user = t4_user(arm, event, merged_json)
        else:
            system, user = node_prompt(event, node, merged_json, outputs)
        if meter_state['calls'] >= CAP_CALLS:
            raise RuntimeError('calls cap')
        if time.monotonic() - meter_state['t0'] > CAP_WALL_S:
            raise RuntimeError('wall cap')
        raw = glm_call(system, user, OUT_CAPS_V2[NODE_KIND[node]])
        meter_state['calls'] += 1
        meter_state['tokens'] += raw['in'] + raw['out']
        ok, value = parse_node(node, raw['text'])
        node_log.append(dict(node=node, model=ALIAS, strict_ok=ok,
                             in_tok=raw['in'], out_tok=raw['out'],
                             lat=raw['lat'], stop=raw['stop'],
                             prompt_chars=len(system) + len(user)))
        ledger.write(json.dumps(dict(rid=rid, arm=arm, node=node,
                                     in_tok=raw['in'], out_tok=raw['out'],
                                     lat=raw['lat'], stop=raw['stop'],
                                     prompt_chars=len(system) + len(user)),
                                ensure_ascii=False) + '\n')
        ledger.flush()
        resp.write(json.dumps(dict(rid=rid, arm=arm, node=node,
                                   text=raw['text']),
                              ensure_ascii=False) + '\n')
        resp.flush()
        if not ok:
            return dict(rid=rid, arm=arm, status='INCOMPLETE',
                        failed_node=node, node_log=node_log)
        outputs[node] = value
        if node == 't2':
            outputs['m'] = merge_facts(outputs['t1'], outputs['t2'])
    wall = time.monotonic() - t0
    text = str(outputs.get('t6') or '') + '\n' + json.dumps(
        outputs.get('t5'), ensure_ascii=False)
    sc = s2.score_report_st(text)
    chain = s2.chain_filter_st(sc['covered'],
                               event['lines']['t1'] + '\n' + event['lines']['t2'])
    return dict(rid=rid, arm=arm, status='COMPLETE',
                t1_full=sc['score'], t1_per_fact=sc['per_fact'],
                chain=chain, chain_reach=f'{len(chain)}/3',
                tokens=sum(l['in_tok'] + l['out_tok'] for l in node_log),
                serial_model_s=round(sum(l['lat'] for l in node_log), 2),
                wall_s=round(wall, 2), node_log=node_log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write-freeze', action='store_true')
    ap.add_argument('--freeze-sha256')
    ap.add_argument('--out')
    args = ap.parse_args()
    load_env()
    packs = sp2.st_packs()
    event = {'task': sp2.TASK_ST,
             'lines': {k: packs[k]['text'] for k in ('t1', 't2')}}
    if args.write_freeze:
        FREEZE_PATH.write_text(json.dumps(build_freeze(event),
                                          ensure_ascii=False, indent=1))
        print('freeze written:', FREEZE_PATH)
        print('sha256:', hashlib.sha256(FREEZE_PATH.read_bytes()).hexdigest())
        return 0
    if os.environ.get('T4AB_GO') != '1':
        raise SystemExit('requires T4AB_GO=1')
    if not args.freeze_sha256 or not args.out:
        raise SystemExit('need --freeze-sha256 and --out')
    sha = hashlib.sha256(FREEZE_PATH.read_bytes()).hexdigest()
    if sha != args.freeze_sha256:
        raise SystemExit('FREEZE_MISMATCH')
    lock_fh = open(P / 't4ab.lock', 'w')
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING: another t4ab instance holds the lock.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    ledger = open(out / 'LEDGER.jsonl', 'w')
    resp = open(out / 'RESPONSES.jsonl', 'w')
    meter_state = dict(calls=0, tokens=0, t0=time.monotonic())
    results = []
    try:
        for i in range(1, 6):
            for arm in ('DEDUP', 'DUP'):
                rid = f'{arm}_r{i}'
                print(f'[{rid}] running...', flush=True)
                r = run_once(arm, rid, event, meter_state, ledger, resp)
                results.append(r)
                if r['status'] == 'COMPLETE':
                    print(f'[{rid}] T1={r["t1_full"]} chain={r["chain_reach"]} '
                          f'tok={r["tokens"]} wall={r["wall_s"]}s', flush=True)
                else:
                    print(f'[{rid}] INCOMPLETE at {r["failed_node"]}',
                          flush=True)
                if sum(1 for x in results if x['status'] == 'INCOMPLETE') \
                        > MAX_INCOMPLETE:
                    raise RuntimeError('too many INCOMPLETE runs')
        # aggregate
        import statistics as st
        agg = {}
        for arm in ('DEDUP', 'DUP'):
            rs = [r for r in results
                  if r['arm'] == arm and r['status'] == 'COMPLETE']
            agg[arm] = dict(
                n=len(rs),
                t1_mean=st.mean([r['t1_full'] for r in rs]) if rs else None,
                tok_mean=st.mean([r['tokens'] for r in rs]) if rs else None,
                wall_mean=st.mean([r['serial_model_s'] for r in rs])
                if rs else None)
        d = dict(results=results, aggregate=agg,
                 meter=dict(calls=meter_state['calls'],
                            tokens=meter_state['tokens'],
                            cash_cny=0.0,
                            wall_s=round(time.monotonic()
                                         - meter_state['t0'], 1)),
                 freeze_sha256=sha)
        if agg['DEDUP']['n'] and agg['DUP']['n']:
            q_ni = agg['DEDUP']['t1_mean'] >= agg['DUP']['t1_mean']
            c_im = agg['DEDUP']['tok_mean'] < agg['DUP']['tok_mean']
            l_im = (agg['DEDUP']['wall_mean']
                    < agg['DUP']['wall_mean'])
            d['verdicts'] = dict(quality_noninferior=q_ni,
                                 cost_improved=c_im, latency_improved=l_im,
                                 structure_benefit_supported=q_ni and
                                 (c_im or l_im))
        (out / 'T4AB_RESULTS.json').write_text(json.dumps(
            d, ensure_ascii=False, indent=1, default=str))
        print(json.dumps(d.get('aggregate'), ensure_ascii=False))
        print('verdicts:', d.get('verdicts'))
        print(f"calls={meter_state['calls']} tokens={meter_state['tokens']} "
              f"cash=¥0 (subscription)")
    except BaseException as exc:
        (out / 'T4AB_INCOMPLETE.json').write_text(json.dumps(
            dict(reason=repr(exc), results=results,
                 traceback=traceback.format_exc()),
            ensure_ascii=False, indent=1, default=str))
        print(f'INCOMPLETE BATCH: {exc}')
    finally:
        ledger.close()
        resp.close()
        fcntl.flock(lock_fh, fcntl.LOCK_UN)
        lock_fh.close()


if __name__ == '__main__':
    main()
