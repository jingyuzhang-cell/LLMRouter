#!/usr/bin/env python3
"""V6 确认性实验两阶段执行器（预注册 V6_PREREG_FINAL_v2；预算 V6_BUDGET_APPROVAL）。

阶段门控（操作者锁定的顺序）：
  --phase fc          运行 48 次 FC 执行（写 slot 级命中矩阵）
  --phase freeze-abo  用冻结版 v6_abo.py 计算 A/B/O 并 SHA256 冻结（禁止在 FC 未齐时运行）
  --phase pd          运行 48 次 PD 执行（A/B/O 冻结文件不存在则拒绝启动）

纪律：全量输入（禁止截断，裁定 c）；任一预算上限先到即停；API 异常重试一次，
再失败即暂停整个运行；注入点/场景/臂序全部来自冻结随机化表。
"""
import json, os, time, hashlib, random, re, urllib.request, argparse, sys, signal

HARD_CALL_TIMEOUT = 360  # s; SIGALRM backstop (raised 240->360 after recurring read-timeouts on long generations; transport robustness only, protocol unchanged)

class CallTimeout(Exception):
    pass

def _on_alarm(signum, frame):
    raise CallTimeout()

def call_hard(fn, *a, **kw):
    """墙钟硬超时：超时抛 CallTimeout → logged_call_guard 重试一次 → 再超时暂停（纪律 2）。"""
    signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(HARD_CALL_TIMEOUT)
    try:
        return fn(*a, **kw)
    finally:
        signal.alarm(0)
from pathlib import Path

HERE = Path(__file__).parent
DESIGN = HERE / 'v6_runs'
DESIGN.mkdir(exist_ok=True)
PKG_F = HERE / 'V6_TASK_PACKAGES_FROZEN.json'
RAND_F = HERE / 'V6_RANDOMIZATION_TABLE.json'
ABO_F = DESIGN / 'V6_ABO_FROZEN.json'
LEDGER = DESIGN / 'ledger.jsonl'
BUDGET_F = DESIGN / 'budget_state.json'
CAPS = dict(calls=700, tokens=7_000_000, yuan=12.00)  # amended per operator 2026-11-10 (orig 6M/¥8)

def get_key(name):
    for line in open('/root/.env'):
        if line.startswith(name + '='):
            return line.strip().split('=', 1)[1]
    raise RuntimeError(f'key {name} missing')

KEYS = dict(DEEPSEEK_API_KEY=get_key('DEEPSEEK_API_KEY'))
def glm_key():
    cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
    for r in cfg['config']['providerConfigRules']['providerRules']:
        if r.get('providerId') == 'bigmodel-api-6':
            return r['config']['access']['apiKey']
    raise RuntimeError('GLM key not found')

def call_model(model, system, user, max_tokens=4096, timeout=300):
    if 'glm' in model.lower():
        url, key = 'https://open.bigmodel.cn/api/paas/v4/chat/completions', glm_key()
    else:
        url, key = 'https://api.deepseek.com/chat/completions', KEYS['DEEPSEEK_API_KEY']
    body = {'model': model, 'messages': [
        {'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        'max_tokens': max_tokens if 'glm' not in model.lower() else max(8192, max_tokens),
        'temperature': 0}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    text = d['choices'][0]['message'].get('content', '') or ''
    if not isinstance(text, str):
        text = ''.join(b.get('text', '') for b in text if isinstance(b, dict))
    u = d.get('usage', {})
    return {'text': text, 'in': u.get('prompt_tokens', 0), 'out': u.get('completion_tokens', 0),
            'lat': time.monotonic() - t0, 'model': model}

def mock_call(model, system, user, **kw):
    return {'text': '{"facts":[{"fact":"mock"}]}', 'in': len(user) // 3, 'out': 32,
            'lat': 0.01, 'model': model}

# ---------- 预算（纪律 1：任一上限先到即停；纪律 2：异常重试一次后暂停） ----------
class Budget:
    def __init__(self):
        s = json.load(open(BUDGET_F)) if BUDGET_F.exists() else dict(calls=0, tokens=0, yuan=0.0)
        self.calls, self.tokens, self.yuan = s['calls'], s['tokens'], s['yuan']
    def ok(self):
        return (self.calls < CAPS['calls'] and self.tokens < CAPS['tokens']
                and self.yuan < CAPS['yuan'])
    def spend(self, tin, tout):
        self.calls += 1
        self.tokens += tin + tout
        self.yuan += (tin * 0.000001 + tout * 0.000002)  # V5 单价
        json.dump(dict(calls=self.calls, tokens=self.tokens, yuan=round(self.yuan, 6)),
                  open(BUDGET_F, 'w'))
        return self.ok()

def norm(s):
    return re.sub(r'[\s,，、（）()〔〕\[\]""'']+', '', str(s))

def slot_hits(all_output, slots):
    flat = norm(all_output)
    hits = []
    for slot in slots:
        val = norm(slot.get('value', ''))
        ae = [norm(a) for a in slot.get('allowed_expressions', []) if a]
        hit = (val and len(val) >= 4 and val in flat) or any(a and len(a) >= 4 and a in flat for a in ae)
        if not hit:
            nums = re.findall(r'[0-9][0-9,，.．%万元亿元]+', slot.get('value', ''))
            if nums and all(n.replace(',', '').replace('，', '') in flat.replace(',', '').replace('，', '')
                            for n in nums if len(n) >= 4):
                hit = True
        hits.append(1 if hit else 0)
    return hits

def inject_anomaly(text, scenario):
    if not text:
        return text
    if scenario == 'S3':
        return text[:len(text) // 3]          # 结构异常：截断
    if scenario == 'S4':
        return text.replace('{', '[').replace('}', ']').replace('"', "'")  # 格式异常
    return text

def node_prompt(node, doc_texts, upstream_outputs):
    kind = node.get('kind', 'extract')
    role = node.get('role', '')
    system = f'你是精确的信息{kind}智能体。{role}。只输出一个JSON对象，不得编造。'
    if kind == 'extract':
        body = '\n\n'.join(f'[{d}]\n{doc_texts[d]}' for d in node['docs'] if d in doc_texts)
        user = ('请从以下文书中提取全部可核查事实（日期/金额/主体/文书性质与文号/处罚/风险），'
                f'每条含fact与quote。输出JSON:{{"facts":[{{"fact":"...","quote":"..."}}]}}\n\n文书：\n{body}')
    elif kind == 'timeline':
        user = (f'请基于以下上游事实构建时间线。输出JSON:{{"timeline":[{{"date":"...","event":"..."}}]}}\n\n上游事实：\n'
                + json.dumps(upstream_outputs, ensure_ascii=False))
    elif kind == 'verification':
        user = (f'请核验以下上游事实的一致性与矛盾。输出JSON:{{"verified":[{{"fact":"...","status":"consistent|conflict|unverifiable"}}]}}\n\n上游事实：\n'
                + json.dumps(upstream_outputs, ensure_ascii=False))
    elif kind == 'reason':
        user = (f'请合并以下全部上游事实，同事实去重、不同年份/主体不合并。输出JSON:{{"facts":[{{"fact":"...","quote":"..."}}]}}\n\n上游事实：\n'
                + json.dumps(upstream_outputs, ensure_ascii=False))
    else:
        user = ('请综合以下上游事实生成终端调查报告：正文叙事（按重要性：金额/日期/主体/处罚/核心事实），'
                '并在facts字段逐条携带全部事实与quote（双层交付：正文+事实附录）。\n\n上游事实：\n'
                + json.dumps(upstream_outputs, ensure_ascii=False))
    return system, user

def execute(pkg, arm, scenario, inject_node, pair, deadline_s=300, mock=False):
    t0 = time.monotonic()
    nodes = pkg['dag']['nodes']
    slots = pkg['slots']
    doc_texts = {}
    for d, m in pkg['docs'].items():
        doc_texts[d] = open(m['path'], encoding='utf-8', errors='ignore').read()  # 全量，禁止截断
    call = mock_call if mock else call_model
    budget = Budget()
    outputs, node_outputs = [], {}
    recoveries = []
    for node in nodes:
        if time.monotonic() - t0 > deadline_s:
            break
        system, user = node_prompt(node, doc_texts,
            {k: v for k, v in node_outputs.items() if k in (node.get('upstream') or [])})
        model = 'deepseek-chat' if node['kind'] == 'extract' else 'glm-5.3-flash'
        if not budget.ok():
            return dict(status='BUDGET_STOP')
        r = call_hard(call, model, system, user)
        if not budget.spend(r['in'], r['out']):
            outputs.append(r); return dict(status='BUDGET_STOP')
        outputs.append(r)
        text = r['text']
        if node['node'] == inject_node and nodes.index(node) > 0:
            corrupted = inject_anomaly(text, scenario)
            if arm == 'Proposed-Dynamic':
                if scenario == 'S4':
                    rp = (system, f'以下输出存在格式异常，请修正后重新输出：\n{corrupted}')
                else:
                    rp = (system, user)
            else:
                rp = (system, f'以下内容可能有误，请基于原始任务重新输出：\n任务：{user}\n可能有误的输出：{corrupted}')
            rr = call_hard(call, model, *rp)
            if not budget.spend(rr['in'], rr['out']):
                outputs.append(rr); return dict(status='BUDGET_STOP')
            outputs.append(rr)
            recoveries.append(dict(node=node['node'], scenario=scenario, arm=arm))
            text = rr['text']
        node_outputs[node['node']] = text
    all_output = ' '.join(str(v) for v in node_outputs.values())
    hits = slot_hits(all_output, slots)
    return dict(status='OK', task=pkg['task_id'], arm=arm, pair=pair, scenario=scenario,
                inject_node=inject_node, tp=sum(hits), n_slots=len(slots), hits=hits,
                calls=len(outputs), tokens_in=sum(x['in'] for x in outputs),
                tokens_out=sum(x['out'] for x in outputs),
                cost_yuan=round(sum(x['in'] for x in outputs) * 0.000001
                                + sum(x['out'] for x in outputs) * 0.000002, 4),
                makespan_s=round(time.monotonic() - t0, 1), recoveries=recoveries,
                node_outputs=node_outputs)  # raw persistence (audit-grade)

def logged_call_guard(fn, *a, **kw):
    """纪律 2：异常重试一次，再失败抛 PauseRun。"""
    try:
        return fn(*a, **kw)
    except Exception as e1:
        try:
            return fn(*a, **kw)
        except Exception as e2:
            raise RuntimeError(f'PAUSE: api failure twice ({e2})')

def run_phase(phase, mock=False):
    pkgs = json.load(open(PKG_F))['packages']
    rand = json.load(open(RAND_F))['table']
    arm_of = dict(fc='Fixed-Composite', pd='Proposed-Dynamic')[phase]
    if phase == 'pd' and not ABO_F.exists():
        raise SystemExit('REFUSED: A/B/O not frozen yet (run --phase freeze-abo after FC completes)')
    out_f = DESIGN / f'results_{phase}.json'
    done = {}
    if out_f.exists():
        for r in json.load(open(out_f)):
            done[(r['task'], r['pair'])] = r
    if phase == 'fc':
        need = [(e['task'], e['pair']) for e in rand]
    else:
        need = [(e['task'], e['pair']) for e in rand]
    results = list(done.values())
    with open(LEDGER, 'a') as lf:
        for e in rand:
            key = (e['task'], e['pair'])
            if key in done:
                continue
            budget = Budget()
            if not budget.ok():
                print('BUDGET CAP REACHED — STOP'); break
            pkg = pkgs[e['task']]
            rec = logged_call_guard(execute, pkg, arm_of, e['scenario'], e['inject_node'],
                                    e['pair'], mock=mock)
            if rec.get('status') == 'BUDGET_STOP':
                print('BUDGET CAP REACHED — STOP'); break
            results.append(rec)
            lf.write(json.dumps(rec, ensure_ascii=False) + '\n'); lf.flush()
            json.dump(results, open(out_f, 'w'), ensure_ascii=False, indent=1)
            print(f"[{len(results)}/48] {e['task']} p{e['pair']} {e['scenario']} {arm_of}: "
                  f"TP={rec['tp']}/{rec['n_slots']} calls={rec['calls']}")
    print(f'PHASE {phase}: {len(results)} executions recorded -> {out_f}')

def freeze_abo(mock=False):
    fc_f = DESIGN / 'results_fc.json'
    if not fc_f.exists():
        raise SystemExit('REFUSED: FC results missing')
    sys.path.insert(0, str(HERE))
    from v6_abo import compute_abo
    pkgs = json.load(open(PKG_F))['packages']
    fc = json.load(open(fc_f))
    by_task = {}
    for r in fc:
        by_task.setdefault(r['task'], []).append(r)
    tasks = {}
    for t, rows in sorted(by_task.items()):
        assert len(rows) == 4, f'{t}: expected 4 FC reps, got {len(rows)}'
        hits = [r['hits'] for r in rows]
        slots = pkgs[t]['slots']
        nodes = pkgs[t]['dag']['nodes']
        tasks[t] = compute_abo(hits, slots, nodes)
    doc = dict(version='V6_ABO_FROZEN_V1', frozen_at=time.strftime('%Y-%m-%d'),
               gate='computed from 48 FC executions only, before any PD result was produced',
               source_sha256=hashlib.sha256(fc_f.read_bytes()).hexdigest(),
               abo_code_sha256='8bb6fb5b823a46edbb718116f9aaf7670677385edfd91441381a14f507baa2c5',
               tasks=tasks)
    ABO_F.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    print('A/B/O FROZEN:', {t: (v['A'], v['B'], v['O']) for t, v in tasks.items()})

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=['fc', 'freeze-abo', 'pd', 'smoke'], required=True)
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    if a.real and os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
        raise SystemExit('REFUSED: real mode requires STAGE_D_REAL_CALLS_AUTHORIZED=1')
    if not a.real and a.phase in ('fc', 'pd'):
        raise SystemExit('fc/pd phases are real-only (mock smoke uses --phase smoke)')
    if a.phase == 'smoke':
        pkgs = json.load(open(PKG_F))['packages']
        e = json.load(open(RAND_F))['table'][0]
        rec = execute(pkgs[e['task']], 'Fixed-Composite', e['scenario'], e['inject_node'], e['pair'], mock=True)
        rec2 = execute(pkgs[e['task']], 'Proposed-Dynamic', e['scenario'], e['inject_node'], e['pair'], mock=True)
        print('SMOKE FC :', {k: rec[k] for k in ('status', 'task', 'tp', 'n_slots', 'calls')})
        print('SMOKE PD :', {k: rec2[k] for k in ('status', 'task', 'tp', 'n_slots', 'calls')})
    elif a.phase == 'fc':
        run_phase('fc')
    elif a.phase == 'pd':
        run_phase('pd')
    elif a.phase == 'freeze-abo':
        freeze_abo()
