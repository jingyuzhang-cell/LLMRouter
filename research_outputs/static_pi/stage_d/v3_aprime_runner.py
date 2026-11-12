#!/usr/bin/env python3
"""V3_STAGE_A_PRIME (reduced): reuse stage-A extracts/stores/verifies; re-run ONLY
8 narrative reports + 2 slim re-verifies for YJGS (its verify outputs hit the
mt=8000 wall mid-JSON). Frozen details per operator ruling:
  - PER-FACT completeness assertion: every fact's serialized record must appear
    in the request text; log sha256, n_facts, chars per call.
  - Three-metric scoring: Q_transport (code-carried store), Q_narrative (model
    narrative alone), Q_terminal (delivered answer = store + narrative; code-
    carried facts are transport, NOT model capability).
"""
import os, sys, json, time, re, argparse, hashlib
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call
from v3_experiment_runner import TASKS, q_terminal
import qcl_v3_runner as UB

NARRATIVE = ("基于以下已核验事实撰写终端调查报告。事实库由系统逐条携带（fid/value/doc/quote），"
             "你不得复述全部事实，只输出：narrative（综合叙述，引用事实时用其 fid，如 [D1::f3]），"
             "以及 key_facts 数组（对回答调查问题最关键的 fid 列表）。不得新增事实，不得改写金额/日期/主体。\n\n"
             "事实库：\n{combined}\n\n输出 JSON：{{\"narrative\":\"...\",\"key_facts\":[\"fid\",...]}}")
SLIM_VERIFY = ("逐条核验以下事实与已知文档的一致性。只输出 fid 和 status 两项，"
               "【不要复述 value/doc/quote】。\n\n事实：\n{slim}\n\n"
               '输出 JSON：{{"facts":[{{"fid":"...","status":"verified|unverified|conflict"}}]}}')
MT = 8000


def norm(s):
    return re.sub(r'[\s,，、；;：:]+', '', str(s))


def slot_hits(facts_or_text, task):
    blob = (norm(facts_or_text) if isinstance(facts_or_text, str) else
            norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                          for x in facts_or_text if isinstance(x, dict))))
    n = 0
    for c in TASKS[task]['gold']:
        gs, gv = norm(c['span']), norm(c['value'])
        if (gs and gs in blob) or (len(gv) >= 6 and gv in blob):
            n += 1
    return n / len(TASKS[task]['gold'])


def load_stage_a():
    outs = [json.loads(l) for l in open(HERE / 'v3_exp_runs/outputs.jsonl')]
    units = {}
    for task in TASKS:
        for strat, tag, vstrat in (('Shared', 'base', 'Static'), ('DA-JS-v3.1', 'Zx', 'DA-JS-v3.1')):
            unit = f'{task}|A|r1'
            facts = []
            for o in outs:
                if o.get('unit') == unit and o.get('strat') == strat \
                        and o.get('node', '').startswith('ext_') and not o.get('injected'):
                    _, f2, _ = parse_facts(o['raw_output'])
                    if tag == 'base':
                        di = o['node'].replace('ext_', '')
                        pre = f"{di}::"
                    else:
                        di, seg = o['node'].replace('ext_', '').rsplit('_s', 1)
                        pre = f"{di}::s{seg}::"
                    facts += [{'fid': pre + str(x.get('fid', '')), 'value': x.get('value', ''),
                               'doc': x.get('doc', ''), 'quote': x.get('quote', '')}
                              for x in f2 if isinstance(x, dict)]
            store = UB.det_merge(facts)
            vs = {}
            for o in outs:
                if o.get('unit') == unit and o.get('strat') == vstrat and o.get('node') == 'verify':
                    _, vout, _ = parse_facts(o['raw_output'])
                    vf = {str(x.get('fid', '')): x.get('status', 'unverified')
                          for x in vout if isinstance(x, dict)}
                    if len(vf) > len(vs):
                        vs = vf
            cover = len(vs.keys() & {f['fid'] for f in store})
            units[(task, tag)] = dict(store=store, vs=vs, verify_cover=cover,
                                      verify_reusable=bool(vs) and cover >= 0.8 * len(store))
    return units


def _gold_touch(task, fact):
    n = lambda x: re.sub(r'[\s,,、；;：:]+', '', str(x))
    blob = n(str(fact.get('value', '')) + str(fact.get('quote', '')))
    for c in TASKS[task]['gold']:
        gs = n(c['span'])
        if gs and gs in blob:
            return True
    return False


class AP:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'
        self.integrity = self.out / 'input_lengths.jsonl'

    def call(self, unit, node, model, user):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(len(user) + 100, MT)
        if self.real:
            for attempt, delay in enumerate((0, 20, 45), 1):
                if delay:
                    time.sleep(delay)
                try:
                    r = _call(model, SYS_COMMON, user, MT)
                    break
                except Exception as e:
                    print(f'  [retry {attempt}] {type(e).__name__}', flush=True)
                    if attempt == 3:
                        raise
            text, tin, tout, lat = r['text'], r['in'], r['out'], r['lat']
        else:
            text = '{"narrative":"n","key_facts":["a::f1"]}'
            tin, tout, lat = len(user), 64, 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, node=node, model=model, tin=tin, tout=tout,
                   yuan=est, lat=lat, user_chars=len(user),
                   user_sha256=hashlib.sha256(user.encode()).hexdigest()[:16])
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def _gold_touching(self, task, fact):
        return _gold_touch(task, fact)

    def assemble_terminal(self, key, narrative, key_facts, store, vs):
        """The DELIVERED answer: model narrative + code-attached verbatim facts
        for the model-cited fids (model organizes/selects; code carries cited
        evidence unchanged). Saved to disk; Q_terminal scored FROM THIS FILE,
        never from the background store. Full-factbase view recorded separately
        as diagnostic. Slim verify outputs are STATUS ANNOTATIONS only."""
        by_fid = {f['fid']: f for f in store}
        cited = []
        for fid in key_facts:
            f = by_fid.get(str(fid))
            if f:
                cited.append({**f, 'verify_status': vs.get(str(fid), 'unverified'),
                              'status_source': 'slim-annotation (not source verification)'})
        artifact = dict(kind='terminal_answer', unit=key,
                        narrative=narrative, cited_facts=cited,
                        uncited_store_n=len(store) - len(cited))
        d = self.out / 'terminal_answers'
        d.mkdir(exist_ok=True)
        p = d / f'{key.replace("|", "__")}.json'
        p.write_text(json.dumps(artifact, ensure_ascii=False, indent=1))
        delivered_text = narrative + json.dumps(cited, ensure_ascii=False)
        full_text = narrative + json.dumps(
            [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in store],
            ensure_ascii=False)
        return delivered_text, full_text

    def assert_full(self, unit, combined, user):
        """PER-FACT completeness: every fact's serialized record inside the request."""
        missing = [f['fid'] for f in combined
                   if json.dumps(f, ensure_ascii=False)[:120] not in user]
        assert not missing, f'INPUT TRUNCATED {unit}: {len(missing)} facts missing, e.g. {missing[:3]}'
        with open(self.integrity, 'a') as f:
            f.write(json.dumps(dict(ts=time.time(), unit=unit, n_facts=len(combined),
                                    assembled_chars=len(json.dumps(combined, ensure_ascii=False)),
                                    user_chars=len(user),
                                    sha256=hashlib.sha256(user.encode()).hexdigest()[:16],
                                    complete=True)) + '\n')

    def run(self):
        units = load_stage_a()
        for (task, tag), u in sorted(units.items()):
            key = f'{task}|{tag}'
            # 1) verify: reuse or slim re-run
            # 1a) supplemental verification for reused units with GOLD-CRITICAL
            #     missing fids (operator rule; E04|Zx doc9::s1::f11 touches E04-02)
            missing = [f for f in u['store'] if f['fid'] not in u['vs']]
            crit = [f for f in missing if self._gold_touching(task, f)]
            if u['verify_reusable'] and crit:
                eid = f'VERSUP|{key}'
                if not self.store.completed(eid):
                    self.store.begin(eid)
                    slim_entries = [{'fid': f['fid'], 'value': f.get('value', '')}
                                    for f in missing]
                    slim = json.dumps(slim_entries, ensure_ascii=False)
                    user = SLIM_VERIFY.format(slim=slim)
                    self.assert_full(key, slim_entries, user)
                    t = self.call(key, 'verify_supplement', 'qwen', user)
                    _, vf, _ = parse_facts(t)
                    u['vs'].update({str(x.get('fid', '')): x.get('status', 'unverified')
                                    for x in vf if isinstance(x, dict)})
                    self.store.commit(dict(exec_id=eid, unit=key,
                                           supplemented=len(vf), critical=[f['fid'] for f in crit],
                                           budget_left=self.gb.left()))
                    print(f'  {key} verify_supplement +{len(vf)} (critical: {[f["fid"] for f in crit]})', flush=True)
            elif u['verify_reusable'] and missing:
                noncrit = [f['fid'] for f in missing if not self._gold_touching(task, f)]
                if noncrit:
                    print(f'  {key} note: {len(noncrit)} non-critical unverified fids recorded '
                          f'(no gold slot touched): {noncrit[:3]}', flush=True)
            if not u['verify_reusable']:
                eid = f'VER|{key}'
                if not self.store.completed(eid):
                    self.store.begin(eid)
                    slim_entries = [{'fid': f['fid'], 'value': f.get('value', '')}
                                    for f in u['store']]
                    slim = json.dumps(slim_entries, ensure_ascii=False)
                    user = SLIM_VERIFY.format(slim=slim)
                    self.assert_full(key, slim_entries, user)
                    t = self.call(key, 'verify_slim', 'qwen', user)
                    _, vf, _ = parse_facts(t)
                    u['vs'] = {str(x.get('fid', '')): x.get('status', 'unverified')
                               for x in vf if isinstance(x, dict)}
                    self.store.commit(dict(exec_id=eid, unit=key, n_status=len(u['vs']),
                                           budget_left=self.gb.left()))
                    print(f'  {key} verify_slim statuses={len(u["vs"])}', flush=True)
            # 2) narrative report (re-run, corrected contract)
            eid = f'REP|{key}'
            if self.store.completed(eid):
                continue
            self.store.begin(eid)
            combined = [{**f, 'verify_status': u['vs'].get(str(f['fid']), 'unverified')}
                        for f in u['store']]
            user = NARRATIVE.format(combined=json.dumps(combined, ensure_ascii=False))
            self.assert_full(key, combined, user)
            t = self.call(key, 'report_narrative', 'qwen', user)
            # 3) three-metric scoring (zero-call)
            try:
                o = json.loads(t[t.find('{'):t.rfind('}') + 1])
                narrative = str(o.get('narrative', ''))
                key_facts = o.get('key_facts', [])
            except Exception:
                narrative, key_facts = t, []
            delivered_text, full_text = self.assemble_terminal(
                key, narrative, key_facts, u['store'], u['vs'])
            q_t = slot_hits(u['store'], task)
            q_n = slot_hits(narrative, task)
            q_fin = slot_hits(delivered_text, task)       # FROM THE SAVED DELIVERED ANSWER
            q_full = slot_hits(full_text, task)           # diagnostic: narrative+entire factbase
            self.store.commit(dict(exec_id=eid, unit=key, Q_transport=round(q_t, 3),
                                   Q_narrative=round(q_n, 3), Q_terminal=round(q_fin, 3),
                                   Q_terminal_fullfact_diag=round(q_full, 3),
                                   n_key_facts=len(key_facts), store_n=len(u['store']),
                                   budget_left=self.gb.left()))
            print(f'  {key} Qt={q_t:.3f} Qn={q_n:.3f} Qfin={q_fin:.3f} '
                  f'left={self.gb.left()["calls_left"]}', flush=True)
        print(f'A-PRIME DONE budget={self.gb.left()}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'v3_aprime_config.json'))
    ap.add_argument('--out', default=str(HERE / 'v3_aprime_runs'))
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    if a.check:
        units = load_stage_a()
        for (task, tag), u in sorted(units.items()):
            print(f'{task}|{tag}: store={len(u["store"])} verify_cover={u["verify_cover"]} '
                  f'reusable={u["verify_reusable"]}')
        return
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                os.environ[k] = [l.split('=', 1)[1].strip()
                                 for l in open('/root/.env') if l.startswith(k + '=')][0]
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'], flush=True)
    else:
        print('MOCK MODE')
    AP(cfg, a.out, a.real).run()


if __name__ == '__main__':
    main()
