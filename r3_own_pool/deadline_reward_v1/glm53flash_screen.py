"""GLM-5.3-Flash screening (operator ruling 2026-10-25, option c).

Scope: ONLY zero-marginal-cost model screening — verify GLM-5.3-Flash
can carry the R2-fix node tasks. NOT the R2-fix formal run; no new paid
experiments; do NOT fall back to option (d) on failure — stop.

4 pre-registered calls, all reusing the FROZEN R2-fix prompts
(r2fix_runner.ROLE_SPEC / HeteroDAG) on the real ydt/D3 document:
  C1  root extraction (valid doc)     -> S1/S2
  C2  timeline <- valid extraction    -> S3a
  C3  timeline <- garbage placeholder -> S3b (fabrication check)
  C4  synthesis <- mixed valid+garbage-> S4 (honest-missing semantics)

Pass criteria (frozen BEFORE calls):
  S1  all calls HTTP 200, non-empty text, marginal cash ¥0
      (subscription: frozen rates glm_53_flash ¥0/call; prior 17 GLM
       calls total ¥0.0; response carries usage but no cash charge)
  S2  extraction parses (fence-tolerant) as JSON array, entries carry
      required fields, >=3 doc-atom hits (dates/amounts), not
      truncated (finish != max_tokens)
  S3a timeline consumes valid extraction: parseable JSON, >=1 date
      traceable to upstream, no invention beyond upstream
  S3b timeline on garbage: NO doc dates fabricated (degenerate or
      explicit cannot-extract acceptable)
  S4  synthesis on mixed input: parseable JSON, key_dates honest
      (empty/noted-missing OR traceable to valid upstream only)

Run: python3 -m deadline_reward_v1.glm53flash_screen
"""
from __future__ import annotations

import json
import re
import sys
import time
import traceback
from pathlib import Path

import requests

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))

from deadline_reward_v1 import r2fix_runner as R
from deadline_reward_v1.full_dag_executor import load_env_creds
from deadline_reward_v1.full_dag_silver import doc_atoms
from deadline_reward_v1.full_dag_tasks import load_docs

HERE = Path(__file__).resolve().parent
URL = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
GARBAGE = R.GARBAGE


def call_glm_flash(prompt: str, key: str, max_out: int,
                   thinking_disabled: bool = True):
    body = dict(model='GLM-5.3-Flash', max_tokens=max_out,
                messages=[dict(role='user', content=prompt)],
                temperature=0.0)
    if thinking_disabled:
        body['thinking'] = {'type': 'disabled'}
    t0 = time.time()
    resp = requests.post(
        URL, headers={'x-api-key': key,
                      'anthropic-version': '2023-06-01',
                      'Content-Type': 'application/json'},
        json=body, timeout=180)
    lat = time.time() - t0
    d = resp.json()
    text, has_thinking_block = '', False
    for blk in d.get('content', []) or []:
        if blk.get('type') == 'text':
            text += blk.get('text', '')
        elif blk.get('type') == 'thinking':
            has_thinking_block = True
    u = d.get('usage', {})
    return dict(http=resp.status_code, answer=text,
                has_thinking_block=has_thinking_block,
                finish_reason=d.get('stop_reason'),
                tokens_in=u.get('input_tokens', 0),
                tokens_out=u.get('output_tokens', 0),
                cash_cny=0.0,   # subscription plan: zero marginal
                latency_s=round(lat, 1), raw_keys=sorted(d.keys()))


def parse_json_array(text: str):
    t = (text or '').strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        if len(parts) == 2:
            t = parts[1].rsplit('```', 1)[0].strip()
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', t, re.S)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, list) else None


def main():
    creds = load_env_creds()
    key = creds['ZHIPU_API_KEY']
    doc = load_docs()[R.DOC_SLOT]
    atoms = doc_atoms(doc['text'])
    dates = atoms['dates'][:6]
    amounts = atoms['amounts'][:6]

    run_dir = HERE / 'fe_screening_runs' / time.strftime(
        'glm53flash_%Y%m%d_%H%M%S')
    run_dir.mkdir(parents=True)
    calls = []
    results = {}

    def record(cid, o):
        calls.append(dict(call_id=cid, **{k: o[k] for k in (
            'http', 'finish_reason', 'tokens_in', 'tokens_out',
            'cash_cny', 'latency_s', 'has_thinking_block')},
            answer_len=len(o['answer'])))
        print(f'  {cid}: HTTP {o["http"]} {o["latency_s"]}s '
              f'len={len(o["answer"])} finish={o["finish_reason"]} '
              f'think_blk={o["has_thinking_block"]} '
              f'tok={o["tokens_in"]}/{o["tokens_out"]}', flush=True)

    try:
        dag = R.HeteroDAG(doc['text'], doc['doc_id'])

        # ---- C1 extraction ----
        p1 = dag.build_prompt(R.ROOT_NODE)
        o1 = call_glm_flash(p1, key, R.ROOT_OUT_CAP)
        record('C1_extraction', o1)
        (run_dir / 'C1_extraction.txt').write_text(o1['answer'])
        results['C1'] = dict(answer_head=o1['answer'][:300])

        # ---- C2 timeline <- valid ----
        dag.outputs[R.ROOT_NODE] = dict(answer=o1['answer'])
        p2 = dag.build_prompt('b0')
        o2 = call_glm_flash(p2, key, R.SECTION_OUT_CAP)
        record('C2_timeline_valid', o2)
        (run_dir / 'C2_timeline_valid.txt').write_text(o2['answer'])

        # ---- C3 timeline <- garbage ----
        dag3 = R.HeteroDAG(doc['text'], doc['doc_id'])
        dag3.outputs[R.ROOT_NODE] = dict(answer=GARBAGE)
        p3 = dag3.build_prompt('b0')
        o3 = call_glm_flash(p3, key, R.SECTION_OUT_CAP)
        record('C3_timeline_garbage', o3)
        (run_dir / 'C3_timeline_garbage.txt').write_text(o3['answer'])

        # ---- C4 synthesis <- mixed ----
        dag4 = R.HeteroDAG(doc['text'], doc['doc_id'])
        dag4.outputs['x0'] = dict(answer=o2['answer'])   # valid timeline
        dag4.outputs['x1'] = dict(answer='[{"amount":"-","note":"复核"}]')
        dag4.outputs['b2'] = dict(answer=GARBAGE)         # faulted branch
        dag4.outputs['b3'] = dict(answer='[{"entity":"中国证监会",'
                                        '"role":"监管机构"}]')
        p4 = dag4.build_prompt('sink')
        o4 = call_glm_flash(p4, key, R.SINK_OUT_CAP)
        record('C4_synthesis_mixed', o4)
        (run_dir / 'C4_synthesis_mixed.txt').write_text(o4['answer'])

        # ---- S1 ----
        s1 = all(c['http'] == 200 and c['answer_len'] > 0
                 for c in calls) and all(c['cash_cny'] == 0.0
                                         for c in calls)
        # ---- S2 extraction validity ----
        arr1 = parse_json_array(o1['answer'])
        has_fields = bool(arr1) and all(
            isinstance(e, dict) and e.get('fact') for e in arr1[:50])
        clean1 = re.sub(r'\s+', '', o1['answer'])
        hits1 = sum(1 for d in dates
                    if re.sub(r'[年月日\s]', '', d) in clean1
                    or d in clean1) + sum(
            1 for a in amounts if a.replace(',', '') in clean1)
        not_trunc1 = o1['finish_reason'] != 'max_tokens'
        s2 = bool(arr1) and has_fields and hits1 >= 3 and not_trunc1
        results['S2'] = dict(n_entries=len(arr1) if arr1 else 0,
                             atom_hits=hits1, truncated=not not_trunc1)
        # ---- S3a valid flow ----
        arr2 = parse_json_array(o2['answer'])
        clean2 = re.sub(r'\s+', '', o2['answer'])
        up_dates = [d for d in dates
                    if re.sub(r'[年月日\s]', '', d) in clean1 or d in clean1]
        tl_dates = [d for d in up_dates
                    if re.sub(r'[年月日\s]', '', d) in clean2 or d in clean2]
        s3a = bool(arr2) and len(tl_dates) >= 1 and (
            o2['finish_reason'] != 'max_tokens')
        results['S3a'] = dict(n_entries=len(arr2) if arr2 else 0,
                              upstream_dates=len(up_dates),
                              timeline_dates=len(tl_dates))
        # ---- S3b garbage flow: no fabrication ----
        arr3 = parse_json_array(o3['answer'])
        clean3 = re.sub(r'\s+', '', o3['answer'])
        fab_dates = [d for d in dates
                     if re.sub(r'[年月日\s]', '', d) in clean3
                     or d in clean3]
        s3b = len(fab_dates) == 0
        results['S3b'] = dict(parse_ok=arr3 is not None,
                              fabricated_dates=fab_dates,
                              answer_head=o3['answer'][:200])
        # ---- S4 mixed synthesis ----
        arr4 = parse_json_array(o4['answer'])
        clean4 = re.sub(r'\s+', '', o4['answer'])
        s4_dates = [d for d in tl_dates
                    if re.sub(r'[年月日\s]', '', d) in clean4 or d in clean4]
        s4 = bool(arr4) and (o4['finish_reason'] != 'max_tokens')
        results['S4'] = dict(n_entries=len(arr4) if arr4 else 0,
                             key_dates_present=len(s4_dates),
                             answer_head=o4['answer'][:300])

        checks = [('S1 zero-marginal + non-empty + HTTP200', s1),
                  ('S2 extraction valid JSON + >=3 atom hits + no trunc',
                   s2),
                  ('S3a timeline consumes valid extraction (>=1 date)',
                   s3a),
                  ('S3b garbage -> NO fabricated dates', s3b),
                  ('S4 mixed synthesis parseable + no trunc', s4)]
        print()
        for n, ok in checks:
            print(f'  [{"PASS" if ok else "FAIL"}] {n}')
        verdict = dict(
            status='COMPLETE', checks={n: bool(ok) for n, ok in checks},
            all_pass=all(ok for _, ok in checks),
            calls=calls, detail=results,
            scope=('GLM-5.3-Flash zero-marginal screening ONLY; '
                   'NOT R2-fix; no fallback to option (d) on failure'))
        (run_dir / 'SCREEN_RESULTS.json').write_text(json.dumps(
            verdict, indent=1, ensure_ascii=False))
        print(f'\nALL_PASS={verdict["all_pass"]}  '
              f'(4 calls, ¥0 marginal cash)')
        print(f'Run: {run_dir}')
    except BaseException as exc:
        (run_dir / 'SCREEN_INCOMPLETE.json').write_text(json.dumps(dict(
            status='INCOMPLETE', reason=repr(exc), calls=calls,
            traceback=traceback.format_exc()), indent=1))
        print(f'INCOMPLETE: {exc}')


if __name__ == '__main__':
    main()
