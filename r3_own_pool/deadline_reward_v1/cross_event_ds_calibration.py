"""cross_event_ds_calibration.py — 欢瑞世纪+*ST卓然 DS 最小能力补测（授权 2026-10-27）。

AUTHORIZED: <=12 real HTTP attempts, cash <= ¥0.20, off-peak only (peak bound
¥0.379 > cap — admission valid off-peak ONLY), stop-on-anomaly, no retry.

Frozen DAG (node-count erratum E2 corrected): 6 nodes = n_main/n_sup1/n_sup2
(extraction, one per doc) + merge (PROGRAM, zero-call) + verify + sink. Five
model nodes; no ROOT (docs independent). Per-event calibration = 3 extractions
+ verify + sink + 1 repeat of the dominant extraction (huanrui: sup2 [75%
facts]; zhuoran: sup2 [12/28 unique probes]).

Flash-comparability: no same-input Flash archives located for these events ->
cells marked UNKNOWN-vs-Flash (no assumption of DS superiority).
"""
import fcntl
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_executor import load_env_creds

DS_URL = 'https://api.deepseek.com/chat/completions'
PRICE_IN, PRICE_OUT = 1.065e-6, 4.26e-6  # off-peak
OUT_CAP = 3072
CAP_ATTEMPTS, CAP_CNY = 12, 0.20
RATIO = 0.721  # conservative in_tok/char bound (calibration max x1.2)

EXT_TMPL = ('你是一个资本市场事件调查助手。\n## 节点任务类型：extraction（信息入口）\n'
            '## 证据文档 doc_id：{doc_id}\n## 文档内容：\n{doc}\n\n'
            '## 任务要求：从证据文档抽取原子事实（事实陈述、日期、数值、涉事主体），'
            '每条须含 fact, date, entities, evidence_doc_id 字段。\n'
            '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
VER_TMPL = ('你是一个资本市场事件调查助手。\n## 节点任务类型：verify（跨公告一致性核验）\n'
            '## 上游三份抽取输出（唯一信息来源）：\n{merged}\n\n'
            '## 任务要求：核验同一事件在三份公告中的日期、金额、处罚/风险状态是否一致、'
            '互补或冲突。输出每条含 item, doc_a, doc_b, verdict(CONSISTENT|COMPLEMENT|CONFLICT|UNRESOLVED), note。\n'
            '## 输出要求：JSON数组，禁止输出任何非JSON文本。')
SNK_TMPL = ('你是一个资本市场事件调查助手。\n## 节点任务类型：synthesis（最终事件分析）\n'
            '## 上游核验输出（唯一信息来源）：\n{verified}\n\n'
            '## 任务要求：综合三份公告输出事件调查结论，输出JSON数组，每条含 conclusion, '
            'timeline[], amounts[], penalties[], entities[], cross_doc_verdicts[]；'
            '每个条目标注 evidence_doc_id（溯源到具体公告）；未确认事项标注 UNRESOLVED。\n'
            '## 输出要求：JSON数组，禁止输出任何非JSON文本。')

EVENTS = {
    'huanrui': {'slots': ['欢瑞世纪#E06-huanrui:E06-huanrui',
                          '欢瑞世纪#E06-huanrui:E06-huanrui_sup1',
                          '欢瑞世纪#E06-huanrui:E06-huanrui_sup2'], 'repeat': 2},
    'zhuoran': {'slots': ['*ST卓然#E04-zhuoran:E04-zhuoran',
                          '*ST卓然#E04-zhuoran:E04-zhuoran_sup1',
                          '*ST卓然#E04-zhuoran:E04-zhuoran_sup2'], 'repeat': 2},
}
ROLE_KEYS = {'extraction': ['fact', 'date', 'entities', 'evidence_doc_id'],
             'verify': ['item', 'doc_a', 'doc_b', 'verdict', 'note'],
             'synthesis': ['conclusion']}


def peak_now():
    import datetime
    u = datetime.datetime.now(datetime.timezone.utc)
    return u.weekday() < 5 and (1 <= u.hour < 4 or 6 <= u.hour < 10)


def parse_array(text):
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.+?)```', t, re.S)
    if m:
        t = m.group(1).strip()
    i = t.find('[')
    if i > 0:
        t = t[i:]
    return json.loads(t)


def compliance(items, keys):
    if not isinstance(items, list) or not items:
        return 0.0, 0
    ok = sum(1 for x in items if isinstance(x, dict) and all(k in x for k in keys))
    return ok / len(items), len(items)


def ds_call(prompt, creds):
    import urllib.request
    body = {'model': 'deepseek-flash', 'max_tokens': OUT_CAP,
            'messages': [{'role': 'user', 'content': prompt}],
            'thinking': {'type': 'disabled'}}
    req = urllib.request.Request(DS_URL, data=json.dumps(body).encode(), method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', 'Bearer ' + creds['DEEPSEEK_API_KEY'])
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode())
    u = d['usage']
    return {'answer': d['choices'][0]['message'].get('content', ''),
            'in': u.get('prompt_tokens', 0), 'out': u.get('completion_tokens', 0),
            'lat': round(time.monotonic() - t0, 2),
            'stop': d['choices'][0].get('finish_reason', ''),
            'cash': (u.get('prompt_tokens', 0) * PRICE_IN
                     + u.get('completion_tokens', 0) * PRICE_OUT)}


def main():
    lock = open(HERE / 'cross_calib.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('REFUSING: lock held.')
    if peak_now():
        print('G1 FAIL: peak window (admission valid off-peak ONLY) — zero-call stop.')
        return
    docs = load_docs()
    # whole-batch admission: per-call worst = chars*RATIO*in_price + 3072*out_price
    worst = 0.0
    plan = []
    for ev, spec in EVENTS.items():
        texts = [docs[s]['text'] for s in spec['slots']]
        plan.append((ev, 'n_main', EXT_TMPL.format(doc_id='main', doc=texts[0])))
        plan.append((ev, 'n_sup1', EXT_TMPL.format(doc_id='sup1', doc=texts[1])))
        plan.append((ev, 'n_sup2', EXT_TMPL.format(doc_id='sup2', doc=texts[2])))
        # verify/sink prompts depend on outputs; bound by merged-size estimate
        merged_bound = sum(min(len(t) * 1.5, 4000) for t in texts) + 300
        plan.append((ev, 'verify', VER_TMPL.format(merged='X' * int(min(merged_bound, 12000)))))
        plan.append((ev, 'sink', SNK_TMPL.format(verified='X' * int(min(merged_bound, 12000)))))
        plan.append((ev, 'n_sup2_repeat', plan[-3][2]))
    for _, _, p in plan:
        worst += len(p) * RATIO * PRICE_IN + OUT_CAP * PRICE_OUT
    assert len(plan) <= CAP_ATTEMPTS and worst <= CAP_CNY, \
        f'admission FAIL ({len(plan)} calls, ¥{worst:.4f})'
    print(f'admission: {len(plan)} calls, whole-batch worst ¥{worst:.4f} <= ¥{CAP_CNY}')
    creds = load_env_creds()
    ledger = open(HERE / 'CROSS_DS_CALIB_LEDGER.jsonl', 'a')
    results = {}
    attempts = spend = 0
    for ev, node, prompt in plan:
        est = len(prompt) * RATIO * PRICE_IN + OUT_CAP * PRICE_OUT
        assert attempts < CAP_ATTEMPTS and spend + est <= CAP_CNY, 'budget admission'
        try:
            rec = ds_call(prompt, creds)
        except Exception as e:
            attempts += 1
            ledger.write(json.dumps({'attempt': attempts, 'event': ev, 'node': node,
                                     'anomaly': f'{type(e).__name__}: {str(e)[:100]}'},
                                    ensure_ascii=False) + '\n')
            print(f'  {ev}/{node}: ANOMALY {type(e).__name__} — STOP (no retry)')
            return
        attempts += 1
        spend += rec['cash']
        try:
            items = parse_array(rec['answer'])
            keys = ROLE_KEYS['extraction'] if node.startswith('n_') else \
                ROLE_KEYS['verify'] if node == 'verify' else ROLE_KEYS['synthesis']
            comp, n = compliance(items, keys)
            parsed = True
        except Exception:
            items, comp, n, parsed = None, 0.0, 0, False
        row = {'event': ev, 'node': node, 'in': rec['in'], 'out': rec['out'],
               'lat': rec['lat'], 'parsed': parsed, 'n_items': n,
               'field_compliance': round(comp, 3), 'cash': round(rec['cash'], 6),
               'truncated': rec['stop'] in ('length', 'max_tokens'),
               'flash_comparable': 'UNKNOWN (no same-input Flash archive)'}
        results.setdefault(ev, {})[node] = row
        ledger.write(json.dumps({'attempt': attempts, **row}, ensure_ascii=False) + '\n')
        ledger.flush()
        print(f"  {ev:8s}/{node:14s} in={rec['in']:5d} out={rec['out']:4d} lat={rec['lat']:5.1f}s "
              f"parsed={parsed} n={n:3d} comp={comp:.2f} ¥{rec['cash']:.4f} cum=¥{spend:.4f}")
        # chain: verify consumes real extractions, sink consumes real verify
        if node.startswith('n_') and parsed:
            results[ev].setdefault('_texts', {})[node] = rec['answer']
        time.sleep(1.1)
    (HERE / 'CROSS_DS_CALIB_RESULT.json').write_text(
        json.dumps({'results': results, 'attempts': attempts, 'cash': round(spend, 4),
                    'flash_alignment': 'UNKNOWN — no same-input Flash archives for these events; '
                                       'cells marked unknown, no DS-superiority assumption'},
                   ensure_ascii=False, indent=1))
    print(f'\nDONE: {attempts} attempts, ¥{spend:.4f}/{CAP_CNY}')


if __name__ == '__main__':
    main()
