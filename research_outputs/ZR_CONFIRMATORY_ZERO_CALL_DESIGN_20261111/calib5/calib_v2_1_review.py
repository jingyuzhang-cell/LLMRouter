#!/usr/bin/env python3
"""CAL5 V2.1 复核与测量入口（零调用检查 + 30 次测量）。

V2.1 只修正 CAL5_04 的注入格式：原始父输出为 6800万元（无逗号），
旧规则 6,800万元→8,600万元 会引入逗号并改变长度 (+1)；新规则
6800万元→8600万元 保持数值语义、格式与长度一致。
任务集 V2.1 SHA: f9c6fe9a8fb993386502fece1bd52a66b1efa020ee7d303dbc3889fd02f51d49

复用冻结校准器 V3（SHA 446ae7bb）的全部逻辑，仅覆盖任务集路径、
父输出目录、账本与已用预算；不修改测量/注入/评分代码。

  --check    零调用：SETUP、注入完整性（含 CAL5_04 格式）、15 次真实请求体捕获
  --measure  30 次测量（Z0 xc 10 + Z1 loc/ver 20），前置 SETUP 必须 5/5 OK
"""
import argparse, hashlib, json, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import calib_harness_v3 as H

H.TASKS_FILE = HERE / 'tasks' / 'CAL5_TASKS_V2_1.json'
H.PARENTS = HERE / 'parents_v3'
H.RUNS = HERE / 'runs_v3_1'
H.LEDGER = HERE / 'calib_ledger_v3_1.jsonl'
H.CAPS['calls'] = 49          # 累计：19 已用 + 30 测量
H.CAPS['tokens'] = 300_000
H.CAPS['yuan'] = 0.30
PRIOR = dict(calls=19, tokens=78_719, yuan=0.119677)


def ledger_with_prior():
    led = H.Ledger()
    led.calls = PRIOR['calls']
    led.tokens = PRIOR['tokens']
    led.yuan = PRIOR['yuan']
    return led


def body_capture(prompt, max_tokens):
    """拦截 urlopen，返回实际会发送的请求体；不联网。"""
    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps(dict(content=[dict(type='text', text='OK')],
                                   usage=dict(input_tokens=1, output_tokens=1),
                                   stop_reason='end_turn', model=H.MODEL)).encode()

    def fake(req, timeout=None):
        captured['url'] = req.full_url
        captured['body'] = json.loads(req.data.decode())
        return FakeResp()

    real = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        H.Transport(real=True).call(prompt, max_tokens, 'bodycapture')
    finally:
        urllib.request.urlopen = real
    return captured


def check():
    tasks = H.load_tasks()
    out = dict(taskset_sha256=hashlib.sha256(H.TASKS_FILE.read_bytes()).hexdigest(),
               tasks={}, all_ok=True)
    for tid, t in tasks.items():
        p = json.loads((H.PARENTS / f'{tid}.json').read_text())
        inj = H.select_injection(t, p)
        d1, d2 = t['documents']['D1'], t['documents']['D2']
        if not inj:
            out['tasks'][tid] = dict(setup='SETUP_FAIL'); out['all_ok'] = False
            continue
        orig = p['outputs']['er']['answer']; injd = inj['injected_er']
        row = dict(setup='OK', fact=inj['fact_id'], correct=inj['correct'], wrong=inj['wrong'],
                   er_len_before=len(orig), er_len_after=len(injd),
                   er_len_delta=len(injd) - len(orig),
                   correct_before=orig.count(inj['correct']), correct_after=injd.count(inj['correct']),
                   wrong_after=injd.count(inj['wrong']),
                   replace_identity=(orig.replace(inj['matched_segment'], inj['wrong'], 1) == injd),
                   tl_has_correct=bool(H.find_value(p['outputs']['tl']['answer'], inj['correct'])),
                   er_sha_before=H.sha(orig), er_sha_after=H.sha(injd), requests={})
        # 15 次真实父请求体捕获（同一代码路径，max_tokens=8000）
        for node in ('fe', 'tl', 'er'):
            prompt = (HERE / 'review_bundle' / 'CAL5_V3_INDEPENDENT_REVIEW_20261112' /
                      'prompts' / f'{tid}_{node}.txt').read_text()
            assert hashlib.sha256(prompt.encode()).hexdigest() == p['prompts'][node]
            cap = body_capture(prompt, H.MAX_PARENT_TOKENS)
            body = cap['body']
            row['requests'][node] = dict(
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                body_sha256=hashlib.sha256(json.dumps(body, ensure_ascii=False).encode()).hexdigest(),
                endpoint=cap['url'], model=body.get('model'), max_tokens=body.get('max_tokens'),
                thinking=body.get('thinking'), output_config=body.get('output_config'),
                has_thinking=body.get('thinking', {}).get('type') == 'enabled',
                has_output_effort=body.get('output_config', {}).get('effort') == 'low')
            if not (row['requests'][node]['has_thinking'] and row['requests'][node]['has_output_effort']):
                out['all_ok'] = False
        # 注入格式约束：长度不变、单次替换、正确值清零、错误值仅 1 次
        fmt_ok = (row['er_len_delta'] == 0 and row['correct_before'] == 1 and
                  row['correct_after'] == 0 and row['wrong_after'] == 1 and row['replace_identity'])
        row['format_ok'] = fmt_ok
        if not fmt_ok:
            out['all_ok'] = False
        out['tasks'][tid] = row
    H.RUNS.mkdir(exist_ok=True)
    (H.RUNS / 'V2_1_ZERO_CALL_CHECKS.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for tid, r in out['tasks'].items():
        print(tid, r.get('setup'), r.get('fact'), r.get('correct'), '->', r.get('wrong'),
              'delta=', r.get('er_len_delta'), 'format_ok=', r.get('format_ok'))
    print('ALL_OK', out['all_ok'])
    return out


def measure():
    led = ledger_with_prior()
    rep = H.measure(H.Transport(real=True), led)
    print('measure report:', rep)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--measure', action='store_true')
    a = ap.parse_args()
    if a.check:
        check(); sys.exit(0)
    if a.measure:
        measure(); sys.exit(0)
    ap.print_help()
