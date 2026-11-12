#!/usr/bin/env python3
"""CAL5 机制校准器（问询函×回复；零调用可自测，真实调用须独立 GO）。

流程
  --selftest   假传输，验证 父输出→注入→Z=0/Z=1→评分 全链路（不联网）
  --parents    5 任务 × (fe+tl+er)=15 次真实调用，冻结父输出
  --measure    10 配对单元 × (Z=0:1 + Z=1:2)=30 次真实调用，评分并出报告

冻结约束
  - 两臂同 D1/D2 原文窗口（任务契约内的 excerpt_text）
  - 两臂同父输出；注入同一字段、同一值、同一父输出（er），一次注入
  - Gold 不入任何输入；父输出/校准输出全部落账
  - 调用/token/费用硬上限：45 次、300K token、¥0.30 记账（GLM 边际 ¥0）
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, time, unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_FILE = HERE / 'tasks' / 'CAL5_TASKS.json'
PARENTS = HERE / 'parents'
RUNS = HERE / 'runs'
LEDGER = HERE / 'calib_ledger.jsonl'
GLM_URL = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
MODEL = 'GLM-5.3-Flash'
PRICE_IN, PRICE_OUT = 0.8e-6, 2.8e-6
CAPS = dict(calls=45, tokens=300_000, yuan=0.30)
MAX_PARENT_TOKENS = 3000
MAX_JOIN_TOKENS = 2048

sys.path.insert(0, str(HERE))
import calib_prompts as P  # noqa: E402


def sha(t):
    return hashlib.sha256((t or '').encode()).hexdigest()


def norm(t):
    """审计用规范化：NFKC + 去空白；保留标点与千分位。"""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', t or ''))


def compact(t):
    """数值匹配用：NFKC + 去空白 + 去千分位逗号。"""
    return re.sub(r'(?<=\d),(?=\d{3})', '', norm(t))


class Ledger:
    def __init__(self):
        self.calls = 0
        self.tokens = 0
        self.yuan = 0.0
        LEDGER.parent.mkdir(parents=True, exist_ok=True)

    def pre(self, est_in, out_cap):
        if self.calls + 1 > CAPS['calls']:
            raise RuntimeError('CALL_CAP')
        # token cap 按实际用量结算；预检只按输入侧保守估计，避免输出预留把上限提前撞满
        if self.tokens + est_in > CAPS['tokens']:
            raise RuntimeError('TOKEN_CAP')

    def add(self, entry):
        self.calls += 1
        self.tokens += entry['tokens_in'] + entry['tokens_out']
        self.yuan += entry['cash_cny']
        if self.yuan > CAPS['yuan'] + 1e-9:
            raise RuntimeError('YUAN_CAP')
        if self.tokens > CAPS['tokens']:
            raise RuntimeError('TOKEN_CAP_AFTER')
        with open(LEDGER, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())


class Transport:
    def __init__(self, real=True):
        self.real = real

    def call(self, prompt, max_tokens, tag):
        if not self.real:
            return fake_call(prompt, max_tokens, tag)
        key = os.environ.get('STAGE_D_GLM_KEY') or os.environ.get('ZHIPU_API_KEY')
        if not key:
            p = Path('/root/.env')
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.startswith('ZHIPU_API_KEY='):
                        key = line.split('=', 1)[1].strip()
        if not key:
            raise RuntimeError('NO_GLM_KEY')
        body = dict(model=MODEL, max_tokens=max_tokens,
                    system='你是一个严谨的资本市场文书核查助手。只输出要求的 JSON。',
                    messages=[dict(role='user', content=prompt)],
                    temperature=0.0, reasoning_effort='low')
        import urllib.request
        req = urllib.request.Request(GLM_URL, data=json.dumps(body, ensure_ascii=False).encode(), method='POST')
        req.add_header('content-type', 'application/json')
        req.add_header('x-api-key', key.strip())
        req.add_header('authorization', 'Bearer ' + key.strip())
        req.add_header('anthropic-version', '2023-06-01')
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.loads(r.read().decode())
        lat = round(time.monotonic() - t0, 3)
        blocks = raw.get('content', [])
        text = ''.join(b.get('text', '') for b in blocks if isinstance(b, dict) and b.get('type') == 'text')
        u = raw.get('usage') or {}
        tin = sum(u.get(k) or 0 for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))
        tout = u.get('output_tokens', 0)
        return dict(answer=text, finish=raw.get('stop_reason'), tokens_in=tin, tokens_out=tout,
                    cash_cny=round((tin * PRICE_IN + tout * PRICE_OUT), 6), latency_s=lat,
                    response_model=raw.get('model'))


def fake_call(prompt, max_tokens, tag):
    """自测用：按 tag 返回固定 JSON；不发网络请求。"""
    if tag.startswith('fe:'):
        return dict(answer='[{"fact":"占位事实1","date":"2026-05-06","entities":["公司"],"evidence_doc_id":"D1"}]',
                    finish='end_turn', tokens_in=100, tokens_out=20, cash_cny=0.0, latency_s=0.0, response_model='FAKE')
    if tag.startswith('tl:'):
        return dict(answer='[{"date":"2026-05-06","event":"收到问询函","value":"-10.52%","evidence":"D1"}]',
                    finish='end_turn', tokens_in=100, tokens_out=20, cash_cny=0.0, latency_s=0.0, response_model='FAKE')
    if tag.startswith('er:'):
        return dict(answer='[{"entity":"标的公司","role":"被评估方","relation":"评估增值率","value":"-10.52%","evidence_doc_id":"D2"}]',
                    finish='end_turn', tokens_in=100, tokens_out=20, cash_cny=0.0, latency_s=0.0, response_model='FAKE')
    if tag.startswith('loc:'):
        return dict(answer='[{"field":"评估增值率","tl_item":"-10.52%","er_item":"-15.20%","evidence_doc_id":"D1","evidence_span":"增值率-10.52%"}]',
                    finish='end_turn', tokens_in=100, tokens_out=20, cash_cny=0.0, latency_s=0.0, response_model='FAKE')
    return dict(answer='[{"claim":"评估增值率","source_a":"-10.52%","source_b":"-15.20%","verdict":"CONFLICT","resolved_value":"-10.52%","evidence_doc_id":"D1"}]',
                finish='end_turn', tokens_in=100, tokens_out=30, cash_cny=0.0, latency_s=0.0, response_model='FAKE')


def load_tasks():
    return json.loads(TASKS_FILE.read_text())


def extract_json(text):
    """容忍前后缀的 JSON 数组抽取。"""
    s = (text or '').strip()
    if s.startswith('```'):
        s = re.sub(r'^```\w*\n|```$', '', s, flags=re.M).strip()
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else None
    except Exception:
        m = re.search(r'\[.*\]', s, re.S)
        if m:
            try:
                v = json.loads(m.group(0))
                return v if isinstance(v, list) else None
            except Exception:
                return None
    return None


def gen_parents(transport, ledger, fake=False):
    tasks = load_tasks()
    PARENTS.mkdir(exist_ok=True)
    for tid, t in tasks.items():
        out_path = PARENTS / f'{tid}.json'
        if out_path.exists() and not fake:
            print(f'[skip] {tid} parents frozen')
            continue
        d1 = t['documents']['D1']; d2 = t['documents']['D2']
        rec = dict(task_id=tid, code=t['code'], doc_ids=[d1['doc_id'], d2['doc_id']],
                   prompts={}, outputs={}, usage={})
        calls = [
            ('fe', P.fe_generic(d1['doc_id'], d1['excerpt_text']), MAX_PARENT_TOKENS),
            ('tl', None, MAX_PARENT_TOKENS),
            ('er', P.er_generic(d2['doc_id'], d2['excerpt_text']), MAX_PARENT_TOKENS),
        ]
        for node, prompt, mt in calls:
            if node == 'tl':
                fe_ans = rec['outputs']['fe']['answer']
                prompt = P.tl_generic(d1['doc_id'], fe_ans[:4000], d1['excerpt_text'][:1200])
            rec['prompts'][node] = sha(prompt)
            ledger.pre(len(prompt) + 256, mt)
            o = transport.call(prompt, mt, f'{node}:{tid}')
            ledger.add(dict(kind='parent', task=tid, node=node, model=MODEL, tag=f'{node}:{tid}',
                            prompt_sha256=rec['prompts'][node], answer=o['answer'], finish=o['finish'],
                            tokens_in=o['tokens_in'], tokens_out=o['tokens_out'],
                            cash_cny=o['cash_cny'], latency_s=o['latency_s'],
                            response_model=o['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            rec['outputs'][node] = o
            rec['usage'][node] = dict(tokens_in=o['tokens_in'], tokens_out=o['tokens_out'],
                                      cash_cny=o['cash_cny'], latency_s=o['latency_s'], finish=o['finish'])
        out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        print(f'[ok] {tid} parents: fe={len(rec["outputs"]["fe"]["answer"])} tl={len(rec["outputs"]["tl"]["answer"])} er={len(rec["outputs"]["er"]["answer"])}')
    return tasks


def value_regex(value):
    """把事实值转成容忍千分位/空白的正则（数字间允许逗号，兼容 11,856.93 与 11856.93）。"""
    v = re.sub(r'(?<=\d),(?=\d{3})', '', compact(value))
    parts = []
    for ch in v:
        if ch.isdigit():
            parts.append(re.escape(ch) + r',?')
        elif ch == '.':
            parts.append(r'\.')
        else:
            parts.append(re.escape(ch))
    return ''.join(parts)


def find_value(text, value):
    return re.search(value_regex(value), compact(text))


def inject(er_answer, matches):
    """在 er 输出中把第一个匹配的正确值替换为错误值；返回 (新文本, 命中片段)。"""
    m = re.search(value_regex(matches['correct']), compact(er_answer))
    if not m:
        return None, None
    # 在原文定位对应片段：按 compact 映射不可行时，用宽松正则直接在原文替换
    loose = value_regex(matches['correct']).replace(r'\,', ',?')
    mm = re.search(loose, er_answer)
    if not mm:
        return None, None
    seg = mm.group(0)
    wrong = matches['wrong']
    # 保持原片段的千分位风格
    if ',' in seg and ',' not in wrong:
        try:
            num_part = re.match(r'([\d,]+(?:\.\d+)?)(.*)', wrong)
            if num_part:
                ip = num_part.group(1)
                if '.' in ip:
                    a, b = ip.split('.', 1)
                    ip2 = f'{int(a):,}.{b}'
                else:
                    ip2 = f'{int(ip):,}'
                wrong = ip2 + num_part.group(2)
        except Exception:
            pass
    return er_answer.replace(seg, wrong, 1), seg


def select_injection(t, parent):
    tl_ans = parent['outputs']['tl']['answer']
    er_ans = parent['outputs']['er']['answer']
    for cand in t['injection_candidates']:
        fid = cand['fact_id']
        fact = next(f for f in t['facts'] if f['fact_id'] == fid)
        rule = cand['rule']
        if '→' not in rule:
            continue
        correct = rule.split('→', 1)[0].strip()
        wrong = rule.split('→', 1)[1].strip()
        if not find_value(tl_ans, correct) or not find_value(er_ans, correct):
            continue
        new_er, seg = inject(er_ans, dict(correct=correct, wrong=wrong))
        if not new_er:
            continue
        return dict(fact_id=fid, correct=correct, wrong=wrong, injected_er=new_er, matched_segment=seg,
                    tl_has=bool(find_value(tl_ans, correct)), er_has=True)
    return None


def score_output(items, inj, task, kind):
    """kind: xc (Z=0) / loc (Z=1 第一步) / ver (Z=1 第二步)。"""
    if not items:
        return False, 'NO_JSON'
    correct_c = compact(inj['correct'])
    wrong_c = compact(inj['wrong'])
    subject_tokens = []
    fact = next(f for f in task['facts'] if f['fact_id'] == inj['fact_id'])
    for w in re.split(r'[、，,（）()/\s]+', fact['subject']):
        if len(w) >= 3:
            subject_tokens.append(w)
    for it in items:
        if not isinstance(it, dict):
            continue
        blob = compact(' '.join(str(v) for v in it.values()))
        has_correct = correct_c in blob
        has_wrong = wrong_c in blob
        has_subject = any(tok in blob for tok in subject_tokens)
        if kind == 'loc':
            if (has_correct or has_wrong or has_subject) and it.get('evidence_span'):
                return True, 'LOCATED'
        else:
            verdict = str(it.get('verdict', '')).upper()
            if verdict in ('CONFLICT', 'UNSUPPORTED') and has_correct:
                return True, 'CONFLICT_RESOLVED'
            if verdict in ('CONFLICT', 'UNSUPPORTED') and has_subject:
                return True, 'CONFLICT_SUBJECT'
    return False, 'NO_ADJUDICATION'


def measure(transport, ledger, fake=False, reps=2):
    tasks = load_tasks()
    RUNS.mkdir(exist_ok=True)
    units = []
    for tid, t in tasks.items():
        pfile = PARENTS / f'{tid}.json'
        if not pfile.exists():
            print(f'[MISSING PARENTS] {tid}')
            continue
        parent = json.loads(pfile.read_text())
        inj = select_injection(t, parent)
        if not inj:
            print(f'[SETUP_FAIL] {tid}: 父输出无可用注入字段')
            units.append(dict(task_id=tid, setup_fail=True))
            continue
        d1 = t['documents']['D1']; d2 = t['documents']['D2']
        tl_ans = parent['outputs']['tl']['answer']
        er_inj = inj['injected_er']
        for rep in (1, 2):
            # Z=0
            prompt = P.xc_dual_generic(d1['doc_id'], d2['doc_id'], tl_ans[:4000], er_inj[:4000],
                                       d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(len(prompt) + 256, MAX_JOIN_TOKENS)
            o0 = transport.call(prompt, MAX_JOIN_TOKENS, f'xc:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z0', task=tid, rep=rep, node='xc', model=MODEL,
                            prompt_sha256=sha(prompt), answer=o0['answer'], finish=o0['finish'],
                            tokens_in=o0['tokens_in'], tokens_out=o0['tokens_out'],
                            cash_cny=o0['cash_cny'], latency_s=o0['latency_s'],
                            response_model=o0['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            # Z=1 loc
            prompt = P.loc_dual_generic(d1['doc_id'], d2['doc_id'], tl_ans[:4000], er_inj[:4000],
                                        d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(len(prompt) + 256, MAX_JOIN_TOKENS)
            ol = transport.call(prompt, MAX_JOIN_TOKENS, f'loc:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z1', task=tid, rep=rep, node='loc', model=MODEL,
                            prompt_sha256=sha(prompt), answer=ol['answer'], finish=ol['finish'],
                            tokens_in=ol['tokens_in'], tokens_out=ol['tokens_out'],
                            cash_cny=ol['cash_cny'], latency_s=ol['latency_s'],
                            response_model=ol['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            # Z=1 ver
            prompt = P.ver_dual_generic(d1['doc_id'], d2['doc_id'], ol['answer'][:4000],
                                        tl_ans[:4000], er_inj[:4000],
                                        d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(len(prompt) + 256, MAX_JOIN_TOKENS)
            ov = transport.call(prompt, MAX_JOIN_TOKENS, f'ver:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z1', task=tid, rep=rep, node='ver', model=MODEL,
                            prompt_sha256=sha(prompt), answer=ov['answer'], finish=ov['finish'],
                            tokens_in=ov['tokens_in'], tokens_out=ov['tokens_out'],
                            cash_cny=ov['cash_cny'], latency_s=ov['latency_s'],
                            response_model=ov['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            i0 = extract_json(o0['answer']); il = extract_json(ol['answer']); iv = extract_json(ov['answer'])
            s0, w0 = score_output(i0, inj, t, 'xc')
            sl, wl = score_output(il, inj, t, 'loc')
            sv, wv = score_output(iv, inj, t, 'ver')
            units.append(dict(task_id=tid, rep=rep, injection=inj['fact_id'],
                              correct=inj['correct'], wrong=inj['wrong'],
                              z0=dict(success=s0, why=w0, finish=o0['finish']),
                              z1=dict(loc=sl, loc_why=wl, ver=sv, ver_why=wv,
                                      success=(sl and sv), finish=[ol['finish'], ov['finish']])))
            print(f'{tid} rep{rep} inj={inj["fact_id"]} Z0={s0}({w0}) Z1={sl and sv}(loc={sl}:{wl}, ver={sv}:{wv})')
    report = dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'), units=units,
                  caps=CAPS, ledger=dict(calls=ledger.calls, tokens=ledger.tokens, yuan=ledger.yuan))
    agg0 = sum(1 for u in units if not u.get('setup_fail') and u['z0']['success'])
    agg1 = sum(1 for u in units if not u.get('setup_fail') and u['z1']['success'])
    n = sum(1 for u in units if not u.get('setup_fail'))
    report['summary'] = dict(n_units=n, z0_success=agg0, z1_success=agg1,
                             z1_gate=agg1 >= 8, z0_gate=agg0 <= 6)
    (RUNS / f'CAL5_REPORT_{time.strftime("%Y%m%d_%H%M%S")}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print('SUMMARY', report['summary'])
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--parents', action='store_true')
    ap.add_argument('--measure', action='store_true')
    a = ap.parse_args()
    ledger = Ledger()
    if a.selftest:
        globals()['PARENTS'] = HERE / 'parents_selftest'
        globals()['RUNS'] = HERE / 'runs_selftest'
        globals()['LEDGER'] = HERE / 'calib_ledger_selftest.jsonl'
        # 临时任务文件：用 CAL5_TASKS.json 的副本；假传输全链路
        print('SELFTEST: fake transport, no network')
        tasks = gen_parents(Transport(real=False), ledger, fake=True)
        # 覆盖父输出以含正确值（假传输 tl 已含 -10.52%）
        rep = measure(Transport(real=False), ledger, fake=True)
        assert rep['summary']['n_units'] > 0, 'selftest produced no units'
        print('SELFTEST OK')
        return
    if a.parents:
        gen_parents(Transport(real=True), ledger)
        print('PARENTS DONE calls=%d tokens=%d yuan=%.4f' % (ledger.calls, ledger.tokens, ledger.yuan))
        return
    if a.measure:
        measure(Transport(real=True), ledger)
        print('MEASURE DONE calls=%d tokens=%d yuan=%.4f' % (ledger.calls, ledger.tokens, ledger.yuan))
        return
    ap.print_help()


if __name__ == '__main__':
    main()
