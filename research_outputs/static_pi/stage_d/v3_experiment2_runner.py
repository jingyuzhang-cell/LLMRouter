#!/usr/bin/env python3
"""V3-EXPERIMENT-2: Static / Proposed / DA-JS-v3.2 on UB-1 + two-layer delivery.

Healthy-loose arm: ZERO new calls (scored from A-PRIME stored narratives/stores
under the frozen two-layer contract; v3.2 = Zx delivery on non-saturated tasks
per preregistered profiles, E03 saturated -> base).
B1 fault arm: shared truncated base report (stage-A stored, zero calls) ->
  Proposed fixed R->pi ladder; v3.2 ladder (R probe -> pi escalation, online
  posterior across the batch; task order frozen E03,E04,SJZG,YJGS; transient
  before persistent within task). Recovery = narrative report re-execution
  (R: qwen retry, transient clean/persistent truncated; pi: ds takeover).
B2 tight-deadline audit: zero-call decide() at D=300 (5-doc YJGS -> Zx vetoed;
  3-doc -> feasible), recorded with full audit trail.
"""
import os, sys, json, time, re, argparse, hashlib
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call, truncate
from v3_experiment_runner import TASKS
from ub1_delivery import build_delivery, score_delivery
import qcl_v3_runner as UB
from da_js_v3 import State, Node, BetaPosterior, decide, update_after_action

MT = 8000
PROFILES = {  # preregistered task profiles (saturation from stage-A measured transport)
    'E03': dict(docs_n=3, zx_comparable=True, transport_saturated=True),
    'E04': dict(docs_n=3, zx_comparable=True, transport_saturated=False),
    'SJZG': dict(docs_n=3, zx_comparable=True, transport_saturated=False),
    'YJGS': dict(docs_n=5, zx_comparable=True, transport_saturated=False),
}
NARR = ("基于以下已核验事实撰写终端调查报告。事实库由系统逐条携带，你只输出：narrative（综合叙述，"
        "引用事实用 fid），以及 key_facts 数组（最关键 fid）。不得新增事实或改写金额/日期/主体。\n\n"
        "事实库：\n{combined}\n\n输出 JSON：{{\"narrative\":\"...\",\"key_facts\":[\"fid\",...]}}")


def load_unit(task, tag):
    outs = [json.loads(l) for l in open(HERE / 'v3_exp_runs/outputs.jsonl')]
    unit = f'{task}|A|r1'
    strat = 'Shared' if tag == 'base' else 'DA-JS-v3.1'
    vstrat = 'Static' if tag == 'base' else 'DA-JS-v3.1'
    facts = []
    for o in outs:
        if o.get('unit') == unit and o.get('strat') == strat \
                and o.get('node', '').startswith('ext_') and not o.get('injected'):
            _, f2, _ = parse_facts(o['raw_output'])
            if tag == 'base':
                di = o['node'].replace('ext_', ''); pre = f"{di}::"
            else:
                di, seg = o['node'].replace('ext_', '').rsplit('_s', 1); pre = f"{di}::s{seg}::"
            facts += [{'fid': pre + str(x.get('fid', '')), 'value': x.get('value', ''),
                       'doc': x.get('doc','') or di, 'quote': x.get('quote', '')}
                      for x in f2 if isinstance(x, dict)]
    store = UB.det_merge(facts)
    vs = {}
    for o in outs:
        if o.get('unit') == unit and o.get('strat') == vstrat and o.get('node') == 'verify':
            _, vout, _ = parse_facts(o['raw_output'])
            v = {str(x.get('fid','')): x.get('status','unverified') for x in vout if isinstance(x,dict)}
            if len(v) > len(vs): vs = v
    apr = [json.loads(l) for l in open(HERE / 'v3_aprime_runs/outputs.jsonl')]
    narr, kf = '', []
    for o in apr:
        if o.get('unit') == f'{task}|{tag}' and o.get('node') == 'report_narrative':
            t = o['raw_output']
            try:
                j = json.loads(t[t.find('{'):t.rfind('}')+1]); narr, kf = str(j.get('narrative','')), j.get('key_facts',[])
            except Exception:
                narr, kf = t, []
    return store, vs, narr, kf


class EX2:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'; st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.H = {}
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'
        self.decisions = self.out / 'decisions.jsonl'

    def call(self, unit, strat, node, model, user, inject=False):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(len(user) + 100, MT)
        if self.real:
            for attempt, delay in enumerate((0, 20, 45), 1):
                if delay: time.sleep(delay)
                try:
                    r = _call(model, SYS_COMMON, user, MT); break
                except Exception as e:
                    print(f'  [retry {attempt}] {type(e).__name__}', flush=True)
                    if attempt == 3: raise
            text, tin, tout, lat = r['text'], r['in'], r['out'], r['lat']
            if inject: text = truncate(text)
        else:
            text = '{"narrative":"n","key_facts":[]}'
            if inject: text = truncate(text)
            tin, tout, lat = len(user), 64, 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, strat=strat, node=node, model=model,
                   tin=tin, tout=tout, yuan=est, lat=lat, injected=inject,
                   user_chars=len(user),
                   user_sha256=hashlib.sha256(user.encode()).hexdigest()[:16])
        with open(self.ledger, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f: f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def narr_input(self, store, vs):
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in store]
        user = NARR.format(combined=json.dumps(combined, ensure_ascii=False))
        for f in combined:  # per-fact assertion
            assert json.dumps(f, ensure_ascii=False)[:120] in user, f'TRUNCATED {f["fid"]}'
        return user, combined

    def healthy_arm(self):
        """ZERO calls: two-layer scoring from stored A-PRIME artifacts."""
        rows = {}
        for task in TASKS:
            for tag in ('base', 'Zx'):
                store, vs, narr, kf = load_unit(task, tag)
                art, qb, qa = build_delivery(store, vs, narr, kf)
                rows[f'{task}|{tag}'] = score_delivery(qb, qa, TASKS[task]['gold'])
                self.store.commit(dict(exec_id=f'H|{task}|{tag}', unit=f'{task}|{tag}',
                                       **rows[f'{task}|{tag}'],
                                       budget_left=self.gb.left()))
        return rows

    def fault_arm(self):
        for task in TASKS:
            store, vs, narr, kf = load_unit(task, 'base')
            user, combined = self.narr_input(store, vs)
            for ftype in ('transient', 'persistent'):
                for strat, ladder in (('Proposed', 'fixed'), ('DA-JS-v3.2', 'online')):
                    eid = f'B1|{task}|{ftype}|{strat}'
                    if self.store.completed(eid): continue
                    self.store.begin(eid)
                    t0 = time.time(); acts = []; final_narr, final_kf = '', []
                    if ladder == 'online':
                        st = State(task=task, G={'report': Node('report','report','qwen')},
                                   H=self.H, faulted=('report','unknown'),
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
                    ok = False
                    if sel == 'R':
                        t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'qwen', user,
                                      inject=(ftype == 'persistent'))
                        try:
                            j = json.loads(t[t.find('{'):t.rfind('}') + 1])
                            final_narr = str(j.get('narrative', ''))
                            final_kf = j.get('key_facts', [])
                            ok = bool(final_narr)
                        except Exception:
                            ok = False
                        acts.append(f'R:{"ok" if ok else "fail"}')
                        if ladder == 'online':
                            st = update_after_action(st, 'R', dict(restored=ok))
                            if not ok:
                                d2 = decide(st)
                                with open(self.decisions,'a') as f:
                                    f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|B1|{ftype}',strat=strat,**d2),ensure_ascii=False)+'\n')
                                acts.append(f"decide2:{d2['selected']}")
                                if d2['selected'] == 'pi':
                                    t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'deepseek', user)
                                    j = None
                                    try: j = json.loads(t[t.find('{'):t.rfind('}')+1])
                                    except Exception: pass
                                    if j: final_narr, final_kf = str(j.get('narrative','')), j.get('key_facts',[]); acts.append('pi:ok')
                                    else: acts.append('pi:fail')
                        elif not ok:
                            t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'deepseek', user)
                            try:
                                j = json.loads(t[t.find('{'):t.rfind('}')+1])
                                final_narr, final_kf = str(j.get('narrative','')), j.get('key_facts',[]); acts.append('pi:ok')
                            except Exception: acts.append('pi:fail')
                    elif sel == 'pi':
                        t = self.call(f'{task}|B1|{ftype}', strat, 'report', 'deepseek', user)
                        try:
                            j = json.loads(t[t.find('{'):t.rfind('}')+1])
                            final_narr, final_kf = str(j.get('narrative','')), j.get('key_facts',[]); acts.append('pi:ok')
                        except Exception: acts.append('pi:fail')
                    # two-layer scoring of recovered delivery
                    art, qb, qa = build_delivery(store, vs, final_narr, final_kf)
                    sc = score_delivery(qb, qa, TASKS[task]['gold'])
                    self.store.commit(dict(exec_id=eid, unit=f'{task}|B1|{ftype}', strat=strat,
                                           actions=acts, **sc,
                                           span_s=round(time.time()-t0,1),
                                           budget_left=self.gb.left()))
                    print(f'  {task}|B1|{ftype}|{strat} {acts} Qt={sc["Q_terminal"]}', flush=True)

    def tight_audit(self):
        for task in TASKS:
            st = State(task=task, G={'report': Node('report','report','qwen')},
                       H=self.H, faulted=None,
                       B=dict(calls=self.gb.left()['calls_left'],
                              tokens=self.gb.left()['tokens_left'] or 10**9,
                              yuan=self.gb.left()['yuan_left']),
                       D=300.0, task_profile=dict(PROFILES[task]))
            d = decide(st)
            with open(self.decisions,'a') as f:
                f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|B2',strat='DA-JS-v3.2',**d),ensure_ascii=False)+'\n')
            zx = next((c for c in d['candidates'] if c['action']=='Zx'), None)
            self.store.commit(dict(exec_id=f'B2|{task}|audit', unit=f'{task}|B2',
                                   selected=d['selected'],
                                   zx_veto=zx['veto'] if zx else '', zero_calls=True))
            print(f'  {task}|B2 -> {d["selected"]} (zx_veto={zx["veto"] if zx else "-"}) [0 calls]', flush=True)

    def run(self, stage):
        if stage in ('H','ALL'): self.healthy_arm()
        if stage in ('B1','ALL'): self.fault_arm()
        if stage in ('B2','ALL'): self.tight_audit()
        print(f'EX2 stage {stage} DONE budget={self.gb.left()}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE/'v3_exp2_config.json'))
    ap.add_argument('--out', default=str(HERE/'v3_exp2_runs'))
    ap.add_argument('--stage', default='ALL', choices=('H','B1','B2','ALL'))
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1': raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY','QWEN_API_KEY'):
            if not os.environ.get(k,'').strip():
                os.environ[k]=[l.split('=',1)[1].strip() for l in open('/root/.env') if l.startswith(k+'=')][0]
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'], 'stage', a.stage, flush=True)
    else: print('MOCK MODE stage', a.stage)
    EX2(cfg, a.out, a.real).run(a.stage)

if __name__ == '__main__':
    main()
