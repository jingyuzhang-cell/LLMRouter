#!/usr/bin/env python3
"""V4_CONFIRMATORY_I: 3 strategies on 2 NEW ported tasks (MVR1, QS).
Full pipeline per task (no cache): extract(DS) -> det store -> slim verify ->
narrative report -> TWO-LAYER delivery scoring. v3.2 decides (docs_n-scaled Zx,
saturation=False declared: no prior for new tasks). B1 faults shared-injection.
B2 zero-call audit. P2B confirmed finished before launch."""
import os, sys, json, time, re, argparse, hashlib
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call, truncate
from ub1_delivery import build_delivery, score_delivery
import qcl_v3_runner as UB
from da_js_v3 import State, Node, decide, update_after_action

MT = 8000
TASKS = {}
for nm, note in (('MVR1', 'machine-verifiable reference (Route B), 4 docs, 16 slots'),
                 ('QS', 'GOLD_APPROVED, 2 docs, 20 slots')):
    p = json.load(open(HERE / f'V4I_{nm}_PORT.json'))
    TASKS[nm] = dict(docs={k: v for k, v in p['docs'].items()},  # normalized text
                     raw_docs=None, gold=p['slots'], note=note)
PROFILES = {'MVR1': dict(docs_n=4, zx_comparable=True, transport_saturated=False),
            'QS': dict(docs_n=2, zx_comparable=True, transport_saturated=False)}
NARR = ("基于以下已核验事实撰写终端调查报告。事实库由系统逐条携带，你只输出：narrative（综合叙述，"
        "引用事实用 fid），以及 key_facts 数组（最关键 fid）。不得新增事实或改写金额/日期/主体。\n\n"
        "事实库：\n{combined}\n\n输出 JSON：{{\"narrative\":\"...\",\"key_facts\":[\"fid\",...]}}")

def norm(s): return re.sub(r'[\s,，、；;：:]+', '', str(s))

def extract_prompt(di, dt):
    return f"从该文档中提取各类事实（日期/金额/主体/违法/处罚/风险），每条含fid、value、doc、quote。\n\n文档 [{di}]:\n{dt}\n\n按系统格式输出 JSON。"

def parse_narr(t):
    try:
        j = json.loads(t[t.find('{'):t.rfind('}') + 1])
        n = str(j.get('narrative', ''))
        return (n, j.get('key_facts', [])) if n else ('', [])
    except Exception:
        return '', []

class V4:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out); st = self.out / 'state'; st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out); self.H = {}
        self.ledger = self.out / 'ledger.jsonl'; self.outputs = self.out / 'outputs.jsonl'
        self.decisions = self.out / 'decisions.jsonl'

    def call(self, unit, strat, node, model, user, inject=False):
        est = YUAN[model]; self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(len(user) + 100, MT)
        if self.real:
            for a, d in enumerate((0, 20, 45), 1):
                if d: time.sleep(d)
                try: r = _call(model, SYS_COMMON, user, MT); break
                except Exception as e:
                    print(f'  [retry {a}] {type(e).__name__}', flush=True)
                    if a == 3: raise
            text, tin, tout, lat = r['text'], r['in'], r['out'], r['lat']
            if inject: text = truncate(text)
        else:
            text = '{"narrative":"n","key_facts":[]}'
            if inject: text = truncate(text)
            tin, tout, lat = len(user), 64, 0.01
        self.gb.release_reservation(need, tin, tout); self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, strat=strat, node=node, model=model,
                   tin=tin, tout=tout, yuan=est, lat=lat, injected=inject, user_chars=len(user))
        with open(self.ledger, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f: f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def extracts(self, task, docs, strat, seg=False):
        facts = []
        for di, dt in sorted(docs.items()):
            if seg:
                mid = len(dt) // 2
                for si, s in enumerate((dt[:mid], dt[mid:]), 1):
                    t = self.call(task, strat, f'ext_{di}_s{si}', 'deepseek', extract_prompt(f'{di}_s{si}', s))
                    _, f2, _ = parse_facts(t)
                    facts += [{'fid': f"{di}::s{si}::{x.get('fid','')}", 'value': x.get('value',''),
                               'doc': x.get('doc', di), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
            else:
                t = self.call(task, strat, f'ext_{di}', 'deepseek', extract_prompt(di, dt))
                _, f2, _ = parse_facts(t)
                facts += [{'fid': f"{di}::{x.get('fid','')}", 'value': x.get('value',''),
                           'doc': x.get('doc', di), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
        return facts

    def verify(self, task, strat, store):
        slim = json.dumps([{'fid': f['fid'], 'value': f.get('value','')} for f in store],
                          ensure_ascii=False)
        user = ("逐条核验以下事实与已知文档一致性。只输出 fid 和 status，不要复述 value。\n\n"
                f"事实：\n{slim}\n\n输出 JSON：{{\"facts\":[{{\"fid\":\"...\",\"status\":\"verified|unverified|conflict\"}}]}}")
        t = self.call(task, strat, 'verify', 'qwen', user)
        _, vf, _ = parse_facts(t)
        return {str(x.get('fid','')): x.get('status','unverified') for x in vf if isinstance(x, dict)}

    def narr_input(self, store, vs):
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in store]
        user = NARR.format(combined=json.dumps(combined, ensure_ascii=False))
        for f in combined:
            assert json.dumps(f, ensure_ascii=False)[:120] in user, f'TRUNCATED {f["fid"]}'
        return user

    def score(self, task, store, vs, narr, kf):
        art, qb, qa = build_delivery(store, vs, narr, kf)
        return score_delivery(qb, qa, TASKS[task]['gold'])

    def run_task(self, task):
        cfg = TASKS[task]; docs = cfg['docs']
        eid = f'BASE|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            facts = self.extracts(task, docs, 'Shared')
            store = UB.det_merge(facts); vs = self.verify(task, 'Static', store)
            user = self.narr_input(store, vs)
            t = self.call(task, 'Static', 'report', 'qwen', user)
            narr, kf = parse_narr(t)
            sc = self.score(task, store, vs, narr, kf)
            self.store.commit(dict(exec_id=eid, unit=task, n_store=len(store), **sc,
                                   budget_left=self.gb.left()))
            print(f'  {task} base store={len(store)} Qt={sc["Q_terminal"]}', flush=True)
        # v3.2 arm
        eid = f'V32|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            st = State(task=task, G={'report': Node('report','report','qwen')}, H=self.H,
                       faulted=None, B=dict(calls=self.gb.left()['calls_left'],
                                            tokens=self.gb.left()['tokens_left'] or 10**9,
                                            yuan=self.gb.left()['yuan_left']),
                       D=2400.0, task_profile=dict(PROFILES[task]))
            d = decide(st)
            with open(self.decisions,'a') as f:
                f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|healthy',strat='v3.2',**d),ensure_ascii=False)+'\n')
            if d['selected'] == 'Zx':
                facts = self.extracts(task, docs, 'DA-JS-v3.2', seg=True)
                store2 = UB.det_merge(facts); vs2 = self.verify(task, 'DA-JS-v3.2', store2)
                user = self.narr_input(store2, vs2)
                t = self.call(task, 'DA-JS-v3.2', 'report', 'qwen', user)
                narr, kf = parse_narr(t)
                sc = self.score(task, store2, vs2, narr, kf)
                self.store.commit(dict(exec_id=eid, unit=task, action='Zx', n_store=len(store2), **sc,
                                       budget_left=self.gb.left()))
            else:
                self.store.commit(dict(exec_id=eid, unit=task, action=d['selected'],
                                       budget_left=self.gb.left()))
            print(f'  {task} v3.2 -> {d["selected"]}', flush=True)
        # B1 faults (shared truncated base narrative = zero call)
        base = json.loads((self.out / f'BASE__{task}.json').read_text())
        for ftype in ('transient', 'persistent'):
            for strat in ('Proposed', 'DA-JS-v3.2'):
                eid = f'B1|{task}|{ftype}|{strat}'
                if self.store.completed(eid): continue
                self.store.begin(eid)
                # rebuild store/vs from outputs
                facts = self.extracts_cached(task, 'Shared'); store = UB.det_merge(facts)
                vs = self.verify_cached(task, 'Static')
                user = self.narr_input(store, vs)
                acts = []
                if strat == 'DA-JS-v3.2':
                    st = State(task=task, G={'report': Node('report','report','qwen')}, H=self.H,
                               faulted=('report','unknown'),
                               B=dict(calls=self.gb.left()['calls_left'],
                                      tokens=self.gb.left()['tokens_left'] or 10**9,
                                      yuan=self.gb.left()['yuan_left']),
                               D=2400.0, task_profile=dict(PROFILES[task]))
                    d1 = decide(st)
                    with open(self.decisions,'a') as f:
                        f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|B1|{ftype}',strat=strat,**d1),ensure_ascii=False)+'\n')
                    acts.append(f"decide1:{d1['selected']}"); sel = d1['selected']
                else:
                    sel = 'R'; acts.append('ladder:R')
                narr, kf, ok = '', [], False
                if sel == 'R':
                    t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'qwen', user,
                                  inject=(ftype == 'persistent'))
                    narr, kf = parse_narr(t); ok = bool(narr)
                    acts.append(f'R:{"ok" if ok else "fail"}')
                    if not ok:
                        if strat == 'DA-JS-v3.2':
                            st = update_after_action(st, 'R', dict(restored=False))
                            d2 = decide(st)
                            with open(self.decisions,'a') as f:
                                f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|B1|{ftype}',strat=strat,**d2),ensure_ascii=False)+'\n')
                            acts.append(f"decide2:{d2['selected']}")
                            if d2['selected'] == 'pi':
                                t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'deepseek', user)
                                narr, kf = parse_narr(t); acts.append('pi:ok' if narr else 'pi:fail')
                        else:
                            # Proposed fixed ladder: R failed -> pi (v4_runner dead-code FIX)
                            t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'deepseek', user)
                            narr, kf = parse_narr(t); acts.append('pi:ok' if narr else 'pi:fail')
                elif sel == 'pi':
                    t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'deepseek', user)
                    narr, kf = parse_narr(t); acts.append('pi:ok' if narr else 'pi:fail')
                sc = self.score(task, store, vs, narr, kf)
                self.store.commit(dict(exec_id=eid, unit=f'{task}|B1|{ftype}', strat=strat,
                                       actions=acts, **sc, budget_left=self.gb.left()))
                print(f'  {task}|B1|{ftype}|{strat} {acts} Qt={sc["Q_terminal"]}', flush=True)
        # B2 zero-call audit
        st = State(task=task, G={'report': Node('report','report','qwen')}, H=self.H, faulted=None,
                   B=dict(calls=99, tokens=10**9, yuan=9.0), D=300.0,
                   task_profile=dict(PROFILES[task]))
        d = decide(st)
        zx = next((c for c in d['candidates'] if c['action'] == 'Zx'), None)
        self.store.commit(dict(exec_id=f'B2|{task}|audit', unit=f'{task}|B2', selected=d['selected'],
                               zx_veto=zx['veto'] if zx else '', zero_calls=True))
        print(f'  {task}|B2 -> {d["selected"]} [0 calls]', flush=True)

    def extracts_cached(self, task, strat):
        outs = [json.loads(l) for l in open(self.outputs)]
        facts = []
        for o in outs:
            if o.get('unit') == task and o.get('strat') == strat and o.get('node','').startswith('ext_'):
                _, f2, _ = parse_facts(o['raw_output'])
                di = o['node'].replace('ext_', '')
                facts += [{'fid': f"{di}::{x.get('fid','')}", 'value': x.get('value',''),
                           'doc': x.get('doc',''), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
        return facts

    def verify_cached(self, task, strat):
        outs = [json.loads(l) for l in open(self.outputs)]
        for o in reversed(outs):
            if o.get('unit') == task and o.get('strat') == strat and o.get('node') == 'verify':
                _, vf, _ = parse_facts(o['raw_output'])
                return {str(x.get('fid','')): x.get('status','unverified') for x in vf if isinstance(x, dict)}
        return {}

    def run(self):
        for task in TASKS:
            self.run_task(task)
        print(f'V4-I DONE budget={self.gb.left()}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'v4_config.json'))
    ap.add_argument('--out', default=str(HERE / 'v4_runs'))
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                os.environ[k] = [l.split('=', 1)[1].strip() for l in open('/root/.env') if l.startswith(k + '=')][0]
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'], flush=True)
    else: print('MOCK MODE')
    V4(cfg, a.out, a.real).run()

if __name__ == '__main__':
    main()
