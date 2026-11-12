#!/usr/bin/env python3
"""V4-II-A (3 tasks E05/E06/E07, frozen Gold, UB-1 two-layer delivery).

Strategies: Static / Proposed (fixed ladder) / DA-JS-v3.2.
Axes per operator ruling:
  healthy x loose (D=2400): v3.2 proactive decision (Zx gate; saturation=False declared)
  EXTRACT transient fault (PRIMARY): shared truncated branch output (zero call) ->
      R re-extract (transient: clean retry) [Proposed & v3.2]; Static accepts degraded
  EXTRACT persistent fault (PRIMARY): R retry truncated too -> pi (other agent) re-extract
  natural insufficiency: E only via corrected dual gates (runtime-flagged)
  REPORT fault: auxiliary (1 cell; known Q-neutral under two-layer)
  B2 tight audit: zero-call decide()
"""
import os, sys, json, time, re, argparse, hashlib
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call, truncate
from ub1_delivery import build_delivery, score_delivery, priority
import qcl_v3_runner as UB
from da_js_v3 import State, Node, BetaPosterior, decide, update_after_action
import v4_runner as V4R

MT = 8000
GOLD = json.load(open(HERE / 'GOLD_E05E06E07_FROZEN.json'))
DOCS = {t: {d: open(p).read() for d, p in
            ((d, sd['path']) for d, sd in GOLD['source_docs'][t].items())} for t in GOLD['tasks']}
PROFILES = {'E05': dict(docs_n=2, zx_comparable=True, transport_saturated=False),
            'E06': dict(docs_n=3, zx_comparable=True, transport_saturated=False),
            'E07': dict(docs_n=3, zx_comparable=True, transport_saturated=False)}

def norm(s): return re.sub(r'[\s,，、；;：:]+', '', str(s))

def slot_hits(facts_or_text, task):
    blob = (norm(facts_or_text) if isinstance(facts_or_text, str) else
            norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                          for x in facts_or_text if isinstance(x, dict))))
    n = 0
    for r in GOLD['tasks'][task]:
        if r['verdict_final'] != 'GOLD':
            continue
        gs = norm(r['span'])
        gv = norm(re.sub(r'[（(].*?[)）]', '', r['desc']))
        if (gs and gs in blob) or (len(gv) >= 6 and gv in blob):
            n += 1
    return round(n / len(GOLD['scoring_slots'][task]), 3)

class VA:
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
            text = V4R.extract_prompt('d', 'x') and '{"facts":[{"fid":"f1","value":"v","doc":"D1","quote":"q"}]}'
            if inject: text = truncate(text)
            tin, tout, lat = len(user), 64, 0.01
        self.gb.release_reservation(need, tin, tout); self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, strat=strat, node=node, model=model,
                   tin=tin, tout=tout, yuan=est, lat=lat, injected=inject, user_chars=len(user))
        with open(self.ledger, 'a') as f: f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f: f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def narr(self, task, strat, store, vs, model='qwen', inject=False, unit=None):
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in store]
        user = V4R.NARR.format(combined=json.dumps(combined, ensure_ascii=False))
        for f in combined:
            assert json.dumps(f, ensure_ascii=False)[:120] in user, f'TRUNCATED {f["fid"]}'
        t = self.call(unit or task, strat, 'report', model, user, inject=inject)
        try:
            j = json.loads(t[t.find('{'):t.rfind('}') + 1])
            n = str(j.get('narrative', ''))
            return (n, j.get('key_facts', [])) if n else ('', [])
        except Exception:
            return '', []

    def score(self, task, store, vs, narr, kf):
        art, qb, qa = build_delivery(store, vs, narr, kf)
        sc = score_delivery(qb, qa, [dict(span=r['span'], value=r['desc'])
                                     for r in GOLD['tasks'][task] if r['verdict_final'] == 'GOLD'])
        return sc

    def run_task(self, task):
        docs = DOCS[task]
        eid = f'BASE|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            facts = []
            for di, dt in sorted(docs.items()):
                t = self.call(task, 'Shared', f'ext_{di}', 'deepseek', V4R.extract_prompt(di, dt))
                _, f2, _ = parse_facts(t)
                facts += [{'fid': f"{di}::{x.get('fid','')}", 'value': x.get('value',''),
                           'doc': x.get('doc', di), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
            store = UB.det_merge(facts)
            vs = self._verify(task, 'Static', store)
            narr, kf = self.narr(task, 'Static', store, vs)
            sc = self.score(task, store, vs, narr, kf)
            qtransport = slot_hits(store, task)
            self.store.commit(dict(exec_id=eid, unit=task, n_store=len(store), Q_transport=qtransport,
                                   **sc, budget_left=self.gb.left()))
            print(f'  {task} base store={len(store)} Qt={sc["Q_terminal"]} transport={qtransport}', flush=True)
        # v3.2 healthy decision
        eid = f'V32|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            st = State(task=task, G={'report': Node('report','report','qwen')}, H=self.H, faulted=None,
                       B=dict(calls=self.gb.left()['calls_left'],
                              tokens=self.gb.left()['tokens_left'] or 10**9,
                              yuan=self.gb.left()['yuan_left']),
                       D=2400.0, task_profile=dict(PROFILES[task]))
            d = decide(st)
            with open(self.decisions,'a') as f:
                f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|healthy',strat='v3.2',**d),ensure_ascii=False)+'\n')
            if d['selected'] == 'Zx':
                facts = []
                for di, dt in sorted(docs.items()):
                    mid = len(dt)//2
                    for si, seg in enumerate((dt[:mid], dt[mid:]), 1):
                        t = self.call(task, 'DA-JS-v3.2', f'ext_{di}_s{si}', 'deepseek',
                                      V4R.extract_prompt(f'{di}_s{si}', seg))
                        _, f2, _ = parse_facts(t)
                        facts += [{'fid': f"{di}::s{si}::{x.get('fid','')}", 'value': x.get('value',''),
                                   'doc': x.get('doc', di), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
                store2 = UB.det_merge(facts)
                vs2 = self._verify(task, 'DA-JS-v3.2', store2)
                narr, kf = self.narr(task, 'DA-JS-v3.2', store2, vs2)
                sc = self.score(task, store2, vs2, narr, kf)
                self.store.commit(dict(exec_id=eid, unit=task, action='Zx', n_store=len(store2),
                                       Q_transport=slot_hits(store2, task), **sc, budget_left=self.gb.left()))
            else:
                self.store.commit(dict(exec_id=eid, unit=task, action=d['selected'], budget_left=self.gb.left()))
            print(f'  {task} v3.2 -> {d["selected"]}', flush=True)
        # EXTRACT fault axes (primary): branch = first doc
        branch_doc = sorted(DOCS[task])[0]; di = branch_doc
        eid = f'XF|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            base_facts = self._cached_ext(task, 'Shared')
            branch_facts = [f for f in base_facts if f['fid'].startswith(di + '::')]
            other = [f for f in base_facts if not f['fid'].startswith(di + '::')]
            # shared faulted state = truncated stored branch output (zero call)
            for ftype in ('transient', 'persistent'):
                for strat in ('Proposed', 'DA-JS-v3.2'):
                    feid = f'XF|{task}|{ftype}|{strat}'
                    if self.store.completed(feid): continue
                    self.store.begin(feid)
                    acts = []
                    if strat == 'DA-JS-v3.2':
                        st = State(task=task, G={di: Node(di, 'extract', 'deepseek')}, H=self.H,
                                   faulted=(di, 'unknown'),
                                   B=dict(calls=self.gb.left()['calls_left'],
                                          tokens=self.gb.left()['tokens_left'] or 10**9,
                                          yuan=self.gb.left()['yuan_left']),
                                   D=2400.0, task_profile=dict(PROFILES[task]))
                        d1 = decide(st)
                        with open(self.decisions,'a') as f:
                            f.write(json.dumps(dict(ts=time.time(),unit=f'{task}|XF|{ftype}',strat=strat,**d1),ensure_ascii=False)+'\n')
                        acts.append(f"decide1:{d1['selected']}"); sel = d1['selected']
                    else:
                        sel = 'R'; acts.append('ladder:R')
                    new_branch = []
                    if sel == 'R':
                        t = self.call(f'{task}|XF|{ftype}', strat, f'ext_{di}', 'deepseek',
                                      V4R.extract_prompt(di, DOCS[task][di]),
                                      inject=(ftype == 'persistent'))
                        _, f2, _ = parse_facts(t)
                        new_branch = [{'fid': f"{di}::{x.get('fid','')}", 'value': x.get('value',''),
                                       'doc': x.get('doc', di), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
                        ok = bool(new_branch)
                        acts.append(f'R:{"ok" if ok else "fail"}')
                        if not ok:
                            if strat == 'DA-JS-v3.2':
                                st = update_after_action(st, 'R', dict(restored=False))
                                d2 = decide(st)
                                acts.append(f"decide2:{d2['selected']}")
                                if d2['selected'] == 'pi':
                                    new_branch = self._pi_extract(task, ftype, strat, di)
                                    acts.append('pi:ok' if new_branch else 'pi:fail')
                            else:
                                new_branch = self._pi_extract(task, ftype, strat, di)
                                acts.append('pi:ok' if new_branch else 'pi:fail')
                    elif sel == 'pi':
                        new_branch = self._pi_extract(task, ftype, strat, di)
                        acts.append('pi:ok' if new_branch else 'pi:fail')
                    store2 = UB.det_merge(other + new_branch)
                    vs2 = self._verify(f'{task}|XF|{ftype}', strat, store2)
                    narr, kf = self.narr(f'{task}|XF|{ftype}', strat, store2, vs2)
                    sc = self.score(task, store2, vs2, narr, kf)
                    self.store.commit(dict(exec_id=feid, unit=f'{task}|XF|{ftype}', strat=strat,
                                           actions=acts, **sc, budget_left=self.gb.left()))
                    print(f'  {task}|XF|{ftype}|{strat} {acts} Qt={sc["Q_terminal"]}', flush=True)
            # Static degraded (branch lost) recorded zero-call
            store_s = UB.det_merge(other)
            vs_s = {}
            sc = self.score(task, store_s, vs_s, '', [])
            self.store.commit(dict(exec_id=f'XF|{task}|Static', unit=f'{task}|XF', strat='Static',
                                   actions=['accept-degraded-branch'], **sc, zero_calls=True))
            self.store.commit(dict(exec_id=eid, unit=task, done=True, budget_left=self.gb.left()))
        # REPORT fault auxiliary (1 cell)
        eid = f'RF|{task}'
        if not self.store.completed(eid):
            self.store.begin(eid)
            base_facts = self._cached_ext(task, 'Shared'); store = UB.det_merge(base_facts)
            vs = self._verify_cached(task)
            narr, kf = self.narr(task, 'Proposed', store, vs, inject=True, unit=f'{task}|RF')
            sc = self.score(task, store, vs, narr, kf)
            self.store.commit(dict(exec_id=eid, unit=f'{task}|RF', strat='Proposed',
                                   actions=['report-fault->R'], **sc, budget_left=self.gb.left()))
            print(f'  {task}|RF (auxiliary) Qt={sc["Q_terminal"]}', flush=True)
        # B2 zero-call audit
        st = State(task=task, G={'report': Node('report','report','qwen')}, H=self.H, faulted=None,
                   B=dict(calls=99, tokens=10**9, yuan=9.0), D=300.0, task_profile=dict(PROFILES[task]))
        d = decide(st)
        zx = next((c for c in d['candidates'] if c['action'] == 'Zx'), None)
        self.store.commit(dict(exec_id=f'B2|{task}|audit', unit=f'{task}|B2', selected=d['selected'],
                               zx_veto=zx['veto'] if zx else '', zero_calls=True))
        print(f'  {task}|B2 -> {d["selected"]} [0 calls]', flush=True)

    def _pi_extract(self, task, ftype, strat, di):
        t = self.call(f'{task}|XF|{ftype}', strat, f'ext_{di}', 'qwen',
                      V4R.extract_prompt(di, DOCS[task][di]))
        _, f2, _ = parse_facts(t)
        return [{'fid': f"{di}::pi::{x.get('fid','')}", 'value': x.get('value',''),
                 'doc': x.get('doc', di), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]

    def _verify(self, unit, strat, store):
        slim = json.dumps([{'fid': f['fid'], 'value': f.get('value','')} for f in store], ensure_ascii=False)
        user = ("逐条核验以下事实与已知文档一致性。只输出 fid 和 status，不要复述 value。\n\n"
                f"事实：\n{slim}\n\n输出 JSON：{{\"facts\":[{{\"fid\":\"...\",\"status\":\"verified|unverified|conflict\"}}]}}")
        t = self.call(unit, strat, 'verify', 'qwen', user)
        _, vf, _ = parse_facts(t)
        return {str(x.get('fid','')): x.get('status','unverified') for x in vf if isinstance(x, dict)}

    def _verify_cached(self, task):
        outs = [json.loads(l) for l in open(self.outputs)]
        for o in reversed(outs):
            if o.get('unit') == task and o.get('strat') == 'Static' and o.get('node') == 'verify':
                _, vf, _ = parse_facts(o['raw_output'])
                return {str(x.get('fid','')): x.get('status','unverified') for x in vf if isinstance(x, dict)}
        return {}

    def _cached_ext(self, task, strat):
        outs = [json.loads(l) for l in open(self.outputs)]
        facts = []
        for o in outs:
            if o.get('unit') == task and o.get('strat') == strat and o.get('node','').startswith('ext_') \
               and '_s' not in o['node'] and not o.get('injected'):
                _, f2, _ = parse_facts(o['raw_output'])
                di = o['node'].replace('ext_', '')
                facts += [{'fid': f"{di}::{x.get('fid','')}", 'value': x.get('value',''),
                           'doc': x.get('doc',''), 'quote': x.get('quote','')} for x in f2 if isinstance(x, dict)]
        return facts

    def run(self):
        for task in GOLD['tasks']:
            self.run_task(task)
        print(f'V4-II-A DONE budget={self.gb.left()}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'v4a_config.json'))
    ap.add_argument('--out', default=str(HERE / 'v4a_runs'))
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
    VA(cfg, a.out, a.real).run()

if __name__ == '__main__':
    main()
