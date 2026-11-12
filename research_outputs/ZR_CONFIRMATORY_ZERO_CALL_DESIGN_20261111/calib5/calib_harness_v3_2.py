#!/usr/bin/env python3
"""CAL5 机制校准器 V3.2（完整父输出修订；零调用可自测，真实调用须新 GO V3-A1）。

V2 相对 V1 的修订（仅执行层，提示词文件未改）：
  1. 输入规则：D1 = 全文（所有任务 D1 ≤5,352 规范字符）；D2 = 前 4,000 规范字符。
     固定规则，不按 Gold 位置裁剪；两臂完全相同。
  2. tl 接收完整 D1 输入（删除 V1 的 1,200 字符头部截断）。
  3. max_tokens：父节点 8,000；xc/loc/ver 4,096（GLM 思考 token 计入上限）。
  4. 父输出有效性闸门：finish ∈ {stop,end_turn}、回答非空、JSON 可解析；任一不满足立即停止。
  5. 累计预算：48 次请求（已用 3 次 + 45 次有效），300K token，¥0.30 记账；预检按 0.6 token/字符。
  6. 任务集 V2：CAL5_01（603271 永杰新材）撤出（D2 事实在 ~40,297，固定 4,000 窗口外），
     以 CAL5_01B（600185 珠免集团）替代；其余 4 任务不变。

流程
  --selftest   假传输，验证父节点→注入→Z0/Z1→评分全链路（不联网）
  --parents    15 次真实父调用，冻结父输出（带有效性闸门）
  --setup      零调用，读取冻结父输出并输出 SETUP_CHECK.json
  --measure    30 次真实测量（先内部复核 SETUP；任一任务失败则不调用）
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, sys, time, unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_FILE = HERE / 'tasks' / 'CAL5_TASKS_V2_1.json'
PARENTS = HERE / 'parents_v3'
RUNS = HERE / 'runs_v3_2'
LEDGER = HERE / 'calib_ledger_v3_2.jsonl'
GLM_URL = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
MODEL = 'GLM-5.3-Flash'
PRICE_IN, PRICE_OUT = 0.8e-6, 2.8e-6
CAPS = dict(calls=49, tokens=300_000, yuan=0.40)
PRIOR = dict(calls=19, tokens=78_719, yuan=0.119677)   # V1/V2/V3 父阶段累计；token 为保守记账值
MAX_PARENT_TOKENS = 8000
MAX_JOIN_TOKENS = 4096
TOK_PER_CHAR = 0.6                       # 观测 fe 0.599 / tl 0.455；取 0.6 预检，实际按用量结算

sys.path.insert(0, str(HERE))
import calib_prompts as P  # noqa: E402


def sha(t):
    return hashlib.sha256((t or '').encode()).hexdigest()


def compact(t):
    t = unicodedata.normalize('NFKC', t or '')
    t = re.sub(r'\s+', '', t)
    return re.sub(r'(?<=\d),(?=\d{3})', '', t)


class Ledger:
    def __init__(self):
        self.calls = PRIOR['calls']
        self.tokens = PRIOR['tokens']
        self.yuan = PRIOR.get('yuan', 0.0)
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        if not LEDGER.exists():
            with open(LEDGER, 'a') as f:
                f.write(json.dumps(dict(kind='prior_usage', calls=PRIOR['calls'],
                                        tokens=PRIOR['tokens'],
                                        note='V1 aborted parent run: 2 completed + 1 aborted'),
                                   ensure_ascii=False) + '\n')

    def pre(self, prompt, out_cap):
        if self.calls + 1 > CAPS['calls']:
            raise RuntimeError('CALL_CAP')
        est = int(len(prompt) * TOK_PER_CHAR) + 256
        if self.tokens + est > CAPS['tokens']:
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
                    temperature=0.0, reasoning_effort='low',
                    thinking=dict(type='enabled'),
                    output_config=dict(effort='low'))
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


def valid_parent(o):
    if o['finish'] not in ('stop', 'end_turn'):
        return False, f"finish={o['finish']}"
    if not (o['answer'] or '').strip():
        return False, 'empty_answer'
    if extract_json(o['answer']) is None:
        return False, 'json_unparseable'
    return True, ''


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
                   input_policy=t['input_policy'], prompts={}, outputs={}, usage={})
        calls = [
            ('fe', P.fe_generic(d1['doc_id'], d1['excerpt_text']), MAX_PARENT_TOKENS),
            ('tl', None, MAX_PARENT_TOKENS),
            ('er', P.er_generic(d2['doc_id'], d2['excerpt_text']), MAX_PARENT_TOKENS),
        ]
        for node, prompt, mt in calls:
            if node == 'tl':
                fe_ans = rec['outputs']['fe']['answer']
                # V2：完整 D1 输入（删除 V1 的 1,200 字符头部截断）
                prompt = P.tl_generic(d1['doc_id'], fe_ans[:4000], d1['excerpt_text'])
            rec['prompts'][node] = sha(prompt)
            ledger.pre(prompt, mt)
            o = transport.call(prompt, mt, f'{node}:{tid}')
            ledger.add(dict(kind='parent', task=tid, node=node, model=MODEL, tag=f'{node}:{tid}',
                            prompt_sha256=rec['prompts'][node], answer=o['answer'], finish=o['finish'],
                            tokens_in=o['tokens_in'], tokens_out=o['tokens_out'],
                            cash_cny=o['cash_cny'], latency_s=o['latency_s'],
                            response_model=o['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            ok, why = valid_parent(o)
            if not ok:
                (RUNS).mkdir(exist_ok=True)
                (RUNS / f'PARENT_INVALID_{tid}_{node}.json').write_text(json.dumps(
                    dict(task=tid, node=node, reason=why, finish=o['finish'],
                         tokens_in=o['tokens_in'], tokens_out=o['tokens_out'],
                         answer=o['answer'][:2000], prompt_sha256=rec['prompts'][node]),
                    ensure_ascii=False, indent=1))
                raise RuntimeError(f'PARENT_INVALID {tid}/{node}: {why}')
            rec['outputs'][node] = o
            rec['usage'][node] = dict(tokens_in=o['tokens_in'], tokens_out=o['tokens_out'],
                                      cash_cny=o['cash_cny'], latency_s=o['latency_s'], finish=o['finish'])
        out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
        print(f'[ok] {tid} parents: fe={len(rec["outputs"]["fe"]["answer"])} '
              f'tl={len(rec["outputs"]["tl"]["answer"])} er={len(rec["outputs"]["er"]["answer"])}')
    return tasks


def value_regex(value):
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


def inject(er_answer, correct, wrong):
    loose = value_regex(correct).replace(r'\,', ',?')
    mm = re.search(loose, er_answer)
    if not mm:
        return None, None
    seg = mm.group(0)
    if ',' in seg and ',' not in wrong:
        try:
            m = re.match(r'([\d,]+(?:\.\d+)?)(.*)', wrong)
            if m:
                ip = m.group(1)
                if '.' in ip:
                    a, b = ip.split('.', 1)
                    ip2 = f'{int(a):,}.{b}'
                else:
                    ip2 = f'{int(ip):,}'
                wrong = ip2 + m.group(2)
        except Exception:
            pass
    return er_answer.replace(seg, wrong, 1), seg


def select_injection(t, parent):
    tl_ans = parent['outputs']['tl']['answer']
    er_ans = parent['outputs']['er']['answer']
    for cand in t['injection_candidates']:
        fid = cand['fact_id']
        rule = cand['rule']
        if '→' not in rule:
            continue
        correct = rule.split('→', 1)[0].strip()
        wrong = rule.split('→', 1)[1].strip()
        if not find_value(tl_ans, correct) or not find_value(er_ans, correct):
            continue
        new_er, seg = inject(er_ans, correct, wrong)
        if not new_er:
            continue
        return dict(fact_id=fid, correct=correct, wrong=wrong, injected_er=new_er, matched_segment=seg)
    return None


def score_output(items, inj, task, kind):
    if not items:
        return False, 'NO_JSON'
    correct_c = compact(inj['correct'])
    wrong_c = compact(inj['wrong'])
    fact = next(f for f in task['facts'] if f['fact_id'] == inj['fact_id'])
    subject_tokens = [w for w in re.split(r'[、，,（）()/\s]+', fact['subject']) if len(w) >= 3]
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


def setup_check():
    tasks = load_tasks()
    rows = {}
    for tid, t in tasks.items():
        pfile = PARENTS / f'{tid}.json'
        if not pfile.exists():
            rows[tid] = dict(status='PARENT_MISSING')
            continue
        parent = json.loads(pfile.read_text())
        inj = select_injection(t, parent)
        rows[tid] = dict(status='OK' if inj else 'SETUP_FAIL',
                         injection_fact=inj['fact_id'] if inj else None,
                         correct=inj['correct'] if inj else None,
                         wrong=inj['wrong'] if inj else None,
                         tl_len=len(parent['outputs']['tl']['answer']),
                         er_len=len(parent['outputs']['er']['answer']))
    RUNS.mkdir(exist_ok=True)
    (RUNS / 'SETUP_CHECK.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for tid, r in rows.items():
        print(tid, r['status'], r.get('injection_fact'), r.get('correct'), '->', r.get('wrong'))
    return rows


def measure(transport, ledger, reps=2):
    rows = setup_check()
    if any(r['status'] != 'OK' for r in rows.values()):
        print('SETUP NOT ALL OK — measurement refused (no calls made)')
        return dict(refused=True, setup=rows)
    tasks = load_tasks()
    RUNS.mkdir(exist_ok=True)
    units = []
    for tid, t in tasks.items():
        parent = json.loads((PARENTS / f'{tid}.json').read_text())
        inj = select_injection(t, parent)
        d1 = t['documents']['D1']; d2 = t['documents']['D2']
        tl_ans = parent['outputs']['tl']['answer']
        er_inj = inj['injected_er']
        for rep in (1, 2):
            prompt = P.xc_dual_generic(d1['doc_id'], d2['doc_id'], tl_ans, er_inj,
                                       d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(prompt, MAX_JOIN_TOKENS)
            o0 = transport.call(prompt, MAX_JOIN_TOKENS, f'xc:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z0', task=tid, rep=rep, node='xc', model=MODEL,
                            prompt_sha256=sha(prompt), answer=o0['answer'], finish=o0['finish'],
                            tokens_in=o0['tokens_in'], tokens_out=o0['tokens_out'],
                            cash_cny=o0['cash_cny'], latency_s=o0['latency_s'],
                            response_model=o0['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            prompt = P.loc_dual_generic(d1['doc_id'], d2['doc_id'], tl_ans, er_inj,
                                        d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(prompt, MAX_JOIN_TOKENS)
            ol = transport.call(prompt, MAX_JOIN_TOKENS, f'loc:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z1', task=tid, rep=rep, node='loc', model=MODEL,
                            prompt_sha256=sha(prompt), answer=ol['answer'], finish=ol['finish'],
                            tokens_in=ol['tokens_in'], tokens_out=ol['tokens_out'],
                            cash_cny=ol['cash_cny'], latency_s=ol['latency_s'],
                            response_model=ol['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            prompt = P.ver_dual_generic(d1['doc_id'], d2['doc_id'], ol['answer'],
                                        tl_ans, er_inj,
                                        d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(prompt, MAX_JOIN_TOKENS)
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
            print(f'{tid} rep{rep} inj={inj["fact_id"]} Z0={s0}({w0}) '
                  f'Z1={sl and sv}(loc={sl}:{wl}, ver={sv}:{wv})')
    report = dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'), units=units, caps=CAPS,
                  prior=PRIOR, ledger=dict(calls=ledger.calls, tokens=ledger.tokens, yuan=ledger.yuan))
    agg0 = sum(1 for u in units if u['z0']['success'])
    agg1 = sum(1 for u in units if u['z1']['success'])
    both_fail = {}
    for u in units:
        if not u['z0']['success']:
            both_fail.setdefault(u['task_id'], []).append(u['rep'])
    one_task_both = any(len(v) >= 2 for v in both_fail.values())
    report['summary'] = dict(n_units=len(units), z0_success=agg0, z1_success=agg1,
                             z1_gate=agg1 >= 8, z0_success_gate=agg0 <= 6,
                             z0_both_reps_fail_task=one_task_both,
                             z0_gate=(agg0 <= 6 and one_task_both))
    (RUNS / f'CAL5_V2_REPORT_{time.strftime("%Y%m%d_%H%M%S")}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print('SUMMARY', report['summary'])
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--parents', action='store_true')
    ap.add_argument('--setup', action='store_true')
    ap.add_argument('--measure', action='store_true')
    a = ap.parse_args()
    ledger = Ledger()
    if a.selftest:
        globals()['PARENTS'] = HERE / 'parents_v3_2_selftest'
        globals()['RUNS'] = HERE / 'runs_v3_2_selftest'
        globals()['LEDGER'] = HERE / 'calib_ledger_v3_2_selftest.jsonl'
        CAPS['calls'] = 100
        CAPS['tokens'] = 10 ** 9
        CAPS['yuan'] = 100.0
        ledger = Ledger()
        ledger.calls, ledger.tokens, ledger.yuan = 0, 0, 0.0
        print('SELFTEST: fake transport, no network')
        gen_parents(Transport(real=False), ledger, fake=True)
        # validity gate unit checks
        assert valid_parent(dict(finish='max_tokens', answer=''))[0] is False
        assert valid_parent(dict(finish='end_turn', answer=''))[0] is False
        assert valid_parent(dict(finish='end_turn', answer='not json'))[0] is False
        assert valid_parent(dict(finish='end_turn', answer='[{"a":1}]'))[0] is True
        # 用合成父输出（含各任务候选正确值）验证注入/评分链路
        tasks = load_tasks()
        for tid, t in tasks.items():
            pfile = PARENTS / f'{tid}.json'
            rec = json.loads(pfile.read_text())
            vals = [c['rule'].split('→', 1)[0].strip() for c in t['injection_candidates']]
            rec['outputs']['tl']['answer'] = '[{"event":"tl fact","value":"%s"}]' % ' / '.join(vals)
            rec['outputs']['er']['answer'] = '[{"relation":"er fact","value":"%s"}]' % ' / '.join(vals)
            pfile.write_text(json.dumps(rec, ensure_ascii=False, indent=1))
            inj = select_injection(t, rec)
            assert inj, f'{tid} injection selection failed'
            fact = next(f for f in t['facts'] if f['fact_id'] == inj['fact_id'])
            loc = [dict(field=fact['subject'], tl_item=inj['correct'], er_item=inj['wrong'],
                        evidence_doc_id='D1', evidence_span=inj['correct'])]
            ver = [dict(claim=fact['subject'], source_a=inj['correct'], source_b=inj['wrong'],
                        verdict='CONFLICT', resolved_value=inj['correct'], evidence_doc_id='D1')]
            assert score_output(loc, inj, t, 'loc')[0], f'{tid} loc score failed'
            assert score_output(ver, inj, t, 'ver')[0], f'{tid} ver score failed'
            assert score_output(ver, inj, t, 'xc')[0], f'{tid} xc score failed'
        rep = measure(Transport(real=False), ledger)
        assert not rep.get('refused'), 'selftest refused'
        assert rep['summary']['n_units'] == 10, rep['summary']
        print('SELFTEST OK')
        return
    if a.parents:
        gen_parents(Transport(real=True), ledger)
        print('PARENTS DONE calls=%d tokens=%d yuan=%.4f' % (ledger.calls, ledger.tokens, ledger.yuan))
        return
    if a.setup:
        setup_check()
        return
    if a.measure:
        measure(Transport(real=True), ledger)
        print('MEASURE DONE calls=%d tokens=%d yuan=%.4f' % (ledger.calls, ledger.tokens, ledger.yuan))
        return
    ap.print_help()


if __name__ == '__main__':
    main()
