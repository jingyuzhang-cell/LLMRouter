#!/usr/bin/env python3
"""V3-EXPERIMENT: Static / Proposed / DA-JS-v3.1 paired comparison on UB-1.

Authorized: <=300 calls / 1.2M tokens / ¥5. Stages: A (healthy x loose, 2 reps,
includes v3 proactive Zx) -> gate -> B1 (faulted x loose: shared-injection
transient/persistent; Proposed fixed R->pi vs v3.1 ladder w/ online posterior)
-> B2 (healthy x tight D=300: ZERO-CALL decision audit - Zx must be withheld).

Panel (gold port-gated): E03(18,human) E04(11,pending-flagged) SJZG(14,operator
REVISE) YJGS(10,pass1). E05-E08 excluded (no slot gold on disk).
Healthy Static == Proposed (no action defined) -> shared execution, declared.
"""
import os, sys, json, time, re, argparse, glob
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call, truncate
from tfjs_runner import FIDELITY_REPORT_USER, fid_backfill
from da_js_v3 import State, Node, BetaPosterior, decide, update_after_action
import qcl_v3_runner as UB  # det_merge, verify/report helpers pattern

T = '/root/capital_opinion_pilot'
TASKS = {
  'E03': dict(docs={f'D{i}': f'{T}/VAL_GOLD_ANNOTATION_PACKAGE/evidence/D{i}_E03-yuandao_2026-08-29.txt' for i in (2, 3)} |
                        {'D1': f'{T}/VAL_GOLD_ANNOTATION_PACKAGE/evidence/D1_E03-yuandao_2026-05-08.txt'},
              gold=[dict(span=c['span'], value=c['value']) for c in json.load(open(HERE / 'E03_GOLD_CANDIDATES.json'))],
              note='18 slots human-PASS'),
  'E04': dict(docs={f'doc{i}': f'/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_2026{i:02d}{d}.txt'
                    for i, d in ((9, '10'), (10, '09'), (10, '13'))},
              gold=[dict(span=c['quote'], value=c.get('value', '')) for c in json.load(
                  open(f'{T}/VAL_GOLD_ANNOTATION_PACKAGE/e04_candidates_atomic_facts.json'))['candidates']],
              note='11 slots dual-person pending'),
  'SJZG': dict(docs={'suspend': f'{T}/v3_evidence/C_shijuezhongguo/text/sjzg_suspend_2019.txt',
                     'abnormal': f'{T}/v3_evidence/C_shijuezhongguo/text/sjzg_abnormal_2019.txt',
                     'resume': f'{T}/v3_evidence/C_shijuezhongguo/text/sjzg_resume_2019.txt'},
               gold=[dict(span=c['evidence_span'], value=c['value']) for c in
                     json.load(open(HERE / 'RQDYN_GOLD_CANDIDATES_C.json'))],
               note='14 slots operator REVISE-applied'),
  'YJGS': dict(docs={Path(f).stem: f for f in sorted(glob.glob(
                  f'{T}/v3_evidence/B_yujingangshi/text/*.txt'))},
               gold=[dict(span=c['evidence_span'], value=c['value']) for c in
                     json.load(open(HERE / 'RQDYN_GOLD_CANDIDATES_B.json'))],
               note='10 slots pass1'),
}
MT = 8000


def norm(s):
    return re.sub(r'[\s,，、；;：:]+', '', str(s))


def extract_prompt(di, dt):
    return f"从该文档中提取各类事实（日期/金额/主体/违法/处罚/风险），每条含fid、value、doc、quote。\n\n文档 [{di}]:\n{dt}\n\n按系统格式输出 JSON。"


def q_terminal(rf, task):
    blob = norm(' '.join(str(x.get('value', '')) + str(x.get('quote', ''))
                         for x in rf if isinstance(x, dict)))
    n = 0
    for c in TASKS[task]['gold']:
        gs, gv = norm(c['span']), norm(c['value'])
        if (gs and gs in blob) or (len(gv) >= 6 and gv in blob):
            n += 1
    return n / len(TASKS[task]['gold'])


class VX:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.H = {}   # online posterior store (node,agent) -> BetaPosterior
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'
        self.decisions = self.out / 'decisions.jsonl'

    def call(self, unit, strat, node, model, user, inject=False):
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
            if inject:
                text = truncate(text)
        else:
            text = '{"facts":[{"fid":"d::f1","value":"v","doc":"x","quote":"q"}]}'
            if inject:
                text = truncate(text)
            tin, tout, lat = len(user), 64, 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, strat=strat, node=node, model=model,
                   tin=tin, tout=tout, yuan=est, lat=lat, injected=inject,
                   user_chars=len(user),
                   contract=getattr(self, 'last_contract', ''))
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    NARRATIVE_REPORT_USER = (
        "基于以下已核验事实撰写终端调查报告。事实库由系统逐条携带（fid/value/doc/quote），"
        "你不得复述全部事实，只输出：narrative（综合叙述，引用事实时用其 fid，如 [D1::f3]），"
        "以及 key_facts 数组（你认为对回答调查问题最关键的 fid 列表，全量或子集由你判断）。"
        "不得新增事实，不得改写金额/日期/主体。\n\n事实库：\n{combined}\n\n"
        '输出 JSON：{{"narrative":"...","key_facts":["fid",...]}}')

    def build_report_input(self, unit, store, combined):
        """NO hidden truncation. Contract by physical output feasibility:
        echo (<= ~75 facts fits mt=8000) else narrative (fid citations; the
        terminal fact set is carried by code, model organizes only)."""
        cj = json.dumps(combined, ensure_ascii=False)
        echo_out_tok = int(len(combined) * 95)
        contract = 'echo' if echo_out_tok <= 7500 else 'narrative'
        user = (FIDELITY_REPORT_USER.format(combined=cj) if contract == 'echo'
                else self.NARRATIVE_REPORT_USER.format(combined=cj))
        # completeness assertion: the LAST fact's serialized text must be present
        tail = json.dumps(combined[-1], ensure_ascii=False) if combined else '{}'
        assert tail[:80] in user, f'INPUT TRUNCATED for {unit}: tail fact missing'
        with open(self.out / 'input_lengths.jsonl', 'a') as f:
            f.write(json.dumps(dict(ts=time.time(), unit=unit, contract=contract,
                                    n_facts=len(combined), assembled_chars=len(cj),
                                    user_chars=len(user), complete=True)) + '\n')
        self.last_contract = contract
        return user

    def do_extracts(self, unit, strat, docs):
        facts = []
        for di, path in sorted(docs.items()):
            dt = open(path, encoding='utf-8').read()
            t = self.call(unit, strat, f'ext_{di}', 'deepseek', extract_prompt(di, dt))
            _, f2, _ = parse_facts(t)
            facts += [{'fid': f"{di}::{x.get('fid', '')}", 'value': x.get('value', ''),
                       'doc': x.get('doc', di), 'quote': x.get('quote', '')}
                      for x in f2 if isinstance(x, dict)]
        return facts

    def do_zx_extracts(self, unit, strat, docs):
        facts = []
        for di, path in sorted(docs.items()):
            dt = open(path, encoding='utf-8').read()
            mid = len(dt) // 2
            for si, seg in enumerate((dt[:mid], dt[mid:]), 1):
                t = self.call(unit, strat, f'ext_{di}_s{si}', 'deepseek',
                              extract_prompt(f'{di}_s{si}', seg))
                _, f2, _ = parse_facts(t)
                facts += [{'fid': f"{di}::s{si}::{x.get('fid', '')}", 'value': x.get('value', ''),
                           'doc': x.get('doc', di), 'quote': x.get('quote', '')}
                          for x in f2 if isinstance(x, dict)]
        return facts

    def do_verify(self, unit, strat, store):
        slim = json.dumps([{'fid': f['fid'], 'value': f.get('value', ''), 'doc': f.get('doc', '')}
                           for f in store], ensure_ascii=False, separators=(',', ':'))
        user = ("逐条核验以下事实是否与文档一致。按 fid 输出状态，不得改写事实。\n\n"
                f"事实：\n{slim}\n\n按系统格式输出 JSON。")
        t = self.call(unit, strat, 'verify', 'qwen', user)
        _, vf, _ = parse_facts(t)
        return {str(v.get('fid', '')): v.get('status', 'unverified')
                for v in vf if isinstance(v, dict)}

    def do_report(self, unit, strat, store, vs, model='qwen', inject=False):
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in store]
        user = self.build_report_input(unit, store, combined)
        t = self.call(unit, strat, 'report', model, user, inject=inject)
        _, rf, _ = parse_facts(t)
        rf = fid_backfill([x for x in rf if isinstance(x, dict)], combined)
        with open(self.outputs, 'a') as f:
            f.write(json.dumps(dict(ts=time.time(), unit=unit, strat=strat,
                                    node='report_final', model=model, tin=0, tout=0,
                                    yuan=0, lat=0, injected=inject,
                                    raw_output=json.dumps(rf, ensure_ascii=False)),
                               ensure_ascii=False) + '\n')
        return rf

    def log_decision(self, unit, strat, d):
        with open(self.decisions, 'a') as f:
            f.write(json.dumps(dict(ts=time.time(), unit=unit, strat=strat, **d),
                               ensure_ascii=False) + '\n')

    def commit(self, eid, **kw):
        if self.store.completed(eid):
            return True
        self.store.begin(eid)
        self.store.commit(dict(exec_id=eid, **kw, budget_left=self.gb.left()))
        return False

    # ---------------- Stage A ----------------
    def stage_a(self):
        for task, cfg in TASKS.items():
            docs, gold_n = cfg['docs'], len(cfg['gold'])
            for rep in (1, 2):
                unit = f'{task}|A|r{rep}'
                if self.store.completed(f'AX|{unit}|base'):
                    pass
                else:
                    self.store.begin(f'AX|{unit}|base')
                    t0 = time.time()
                    facts = self.do_extracts(unit, 'Shared', docs)
                    store = UB.det_merge(facts)
                    vs = self.do_verify(unit, 'Static', store)
                    rf = self.do_report(unit, 'Static', store, vs)
                    self.store.commit(dict(exec_id=f'AX|{unit}|base', unit=unit,
                                           n_store=len(store), n_report=len(rf),
                                           span_s=round(time.time() - t0, 1),
                                           budget_left=self.gb.left()))
                    print(f'  {unit} base(store={len(store)}) left={self.gb.left()["calls_left"]}', flush=True)
                # v3.1 proactive decision + Zx execution
                if self.store.completed(f'AX|{unit}|v3'):
                    continue
                self.store.begin(f'AX|{unit}|v3')
                t0 = time.time()
                st = State(task=task, G={'report': Node('report', 'report', 'qwen')},
                           H=self.H, faulted=None,
                           B=dict(calls=self.gb.left()['calls_left'],
                                  tokens=self.gb.left()['tokens_left'] or 10 ** 9,
                                  yuan=self.gb.left()['yuan_left']),
                           D=2400.0, task_profile=dict(zx_comparable=True))
                d = decide(st)
                self.log_decision(unit, 'DA-JS-v3.1', d)
                if d['selected'] == 'Zx':
                    segfacts = self.do_zx_extracts(unit, 'DA-JS-v3.1', docs)
                    store2 = UB.det_merge(segfacts)
                    vs2 = self.do_verify(unit, 'DA-JS-v3.1', store2)
                    rf2 = self.do_report(unit, 'DA-JS-v3.1', store2, vs2)
                    self.store.commit(dict(exec_id=f'AX|{unit}|v3', unit=unit,
                                           action='Zx', n_store=len(store2),
                                           n_report=len(rf2),
                                           span_s=round(time.time() - t0, 1),
                                           budget_left=self.gb.left()))
                else:
                    self.store.commit(dict(exec_id=f'AX|{unit}|v3', unit=unit,
                                           action=d['selected'],
                                           budget_left=self.gb.left()))
                print(f'  {unit} v3({d["selected"]}) left={self.gb.left()["calls_left"]}', flush=True)

    # ---------------- Stage B1 ----------------
    def stage_b1(self):
        outs = [json.loads(l) for l in open(self.outputs)]
        for task, cfg in TASKS.items():
            base_rep = next((o for o in reversed(outs) if o.get('unit') == f'{task}|A|r1'
                             and o.get('node') == 'report' and o.get('strat') == 'Static'
                             and not o.get('injected')), None)
            base_rf = []
            for o in outs:
                if o.get('unit') == f'{task}|A|r1' and o.get('node') == 'report_final' \
                        and o.get('strat') == 'Static':
                    base_rf = json.loads(o['raw_output'])
            for ftype in ('transient', 'persistent'):
                unit = f'{task}|B1|{ftype}'
                # shared faulted state = truncated stored base report (zero calls)
                for strat, is_v3 in (('Proposed', False), ('DA-JS-v3.1', True)):
                    eid = f'B1|{unit}|{strat}'
                    if self.store.completed(eid):
                        continue
                    self.store.begin(eid)
                    t0 = time.time()
                    acts = []
                    if is_v3:
                        st = State(task=task, G={'report': Node('report', 'report', 'qwen')},
                                   H=self.H, faulted=('report', 'unknown'),
                                   B=dict(calls=self.gb.left()['calls_left'],
                                          tokens=self.gb.left()['tokens_left'] or 10 ** 9,
                                          yuan=self.gb.left()['yuan_left']),
                                   D=2400.0, task_profile=dict(zx_comparable=True))
                        d1 = decide(st)
                        self.log_decision(unit, strat, d1)
                        acts.append(f"decide1:{d1['selected']}")
                        sel = d1['selected']
                    else:
                        sel = 'R'  # Proposed fixed ladder
                        acts.append('ladder:R')
                    rf = []
                    if sel in ('R', 'pi'):
                        if sel == 'R':
                            t = self.call(unit, strat, 'report', 'qwen',
                                          FIDELITY_REPORT_USER.format(combined='[...]') if False else
                                          self._report_user_for(task, outs),
                                          inject=(ftype == 'persistent') if not is_v3 else False)
                            # v3 R probe: transient unknown -> real retry; persistent hides itself
                            if is_v3:
                                # fault class is hidden; emulate by injecting iff persistent
                                t = truncate(t) if ftype == 'persistent' else t
                            _, rf, _ = parse_facts(t)
                            ok = bool(rf)
                            acts.append(f'R:{ok}')
                            if is_v3:
                                st = update_after_action(st, 'R', dict(restored=ok))
                                if not ok:
                                    d2 = decide(st)
                                    self.log_decision(unit, strat, d2)
                                    acts.append(f"decide2:{d2['selected']}")
                                    if d2['selected'] == 'pi':
                                        rf = self._pi_report(unit, strat, task, outs)
                                        acts.append('pi:ok')
                        else:
                            rf = self._pi_report(unit, strat, task, outs)
                            acts.append('pi:ok')
                    self.store.commit(dict(exec_id=eid, unit=unit, strat=strat, actions=acts,
                                           n_report=len(rf), faulted_ftype=ftype,
                                           span_s=round(time.time() - t0, 1),
                                           budget_left=self.gb.left()))
                    print(f'  {unit} {strat} {acts} left={self.gb.left()["calls_left"]}', flush=True)
            # Static accepts degraded: zero calls, recorded
            for ftype in ('transient', 'persistent'):
                self.commit(f'B1|{task}|B1|{ftype}|Static', unit=f'{task}|B1|{ftype}',
                            strat='Static', actions=['accept-degraded'], n_report=0)

    def _report_user_for(self, task, outs):
        store_rf = []
        for o in outs:
            if o.get('unit') == f'{task}|A|r1' and o.get('strat') == 'Static' \
                    and o.get('node') == 'verify':
                # reconstruct combined from stored store facts (recompute from extracts)
                pass
        facts = self._base_facts(task, outs)
        vs = self._base_vs(task, outs)
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in facts]
        return self.build_report_input(task, facts, combined)

    def _base_facts(self, task, outs):
        cache_p = self.out / f'AX__{task}|A|r1__base.json'
        if cache_p.exists():
            d = json.loads(cache_p.read_text())
            if 'facts_cache' in d:
                return d['facts_cache']
        # recompute from stored extract outputs (namespaced)
        facts = []
        for o in outs:
            if o.get('unit') == f'{task}|A|r1' and o.get('strat') == 'Shared' \
                    and o.get('node', '').startswith('ext_') and not o.get('injected'):
                _, f2, _ = parse_facts(o['raw_output'])
                di = o['node'][4:]
                facts += [{'fid': f"{di}::{x.get('fid', '')}", 'value': x.get('value', ''),
                           'doc': x.get('doc', di), 'quote': x.get('quote', '')}
                          for x in f2 if isinstance(x, dict)]
        return UB.det_merge(facts)

    def _base_vs(self, task, outs):
        for o in outs:
            if o.get('unit') == f'{task}|A|r1' and o.get('strat') == 'Static' \
                    and o.get('node') == 'verify':
                _, vf, _ = parse_facts(o['raw_output'])
                return {str(v.get('fid', '')): v.get('status', 'unverified')
                        for v in vf if isinstance(v, dict)}
        return {}

    def _pi_report(self, unit, strat, task, outs):
        user = self._report_user_for(task, outs)
        t = self.call(unit, strat, 'report', 'deepseek', user)
        _, rf, _ = parse_facts(t)
        return [x for x in rf if isinstance(x, dict)]

    # ---------------- Stage B2 (zero-call decision audit) ----------------
    def stage_b2(self):
        for task in TASKS:
            unit = f'{task}|B2'
            st = State(task=task, G={'report': Node('report', 'report', 'qwen')},
                       H=self.H, faulted=None,
                       B=dict(calls=self.gb.left()['calls_left'],
                              tokens=self.gb.left()['tokens_left'] or 10 ** 9,
                              yuan=self.gb.left()['yuan_left']),
                       D=300.0, task_profile=dict(zx_comparable=True))
            d = decide(st)
            self.log_decision(unit, 'DA-JS-v3.1', d)
            zx_vetoed = any(c['action'] == 'Zx' and 'deadline' in str(c.get('veto', ''))
                            for c in d['candidates'])
            self.commit(f'B2|{unit}|audit', unit=unit, selected=d['selected'],
                        zx_vetoed_by_deadline=zx_vetoed, zero_calls=True)
            print(f'  {unit} v3 decision={d["selected"]} zx_vetoed={zx_vetoed} (0 calls)', flush=True)

    def run(self, stage):
        if stage in ('A', 'ALL'):
            self.stage_a()
        if stage in ('B1', 'ALL'):
            self.stage_b1()
        if stage in ('B2', 'ALL'):
            self.stage_b2()
        print(f'V3-EXP stage {stage} DONE budget={self.gb.left()}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'v3_exp_config.json'))
    ap.add_argument('--out', default=str(HERE / 'v3_exp_runs'))
    ap.add_argument('--stage', default='A', choices=('A', 'B1', 'B2', 'ALL'))
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                os.environ[k] = [l.split('=', 1)[1].strip()
                                 for l in open('/root/.env') if l.startswith(k + '=')][0]
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'], 'stage', a.stage, flush=True)
    else:
        print('MOCK MODE stage', a.stage)
    VX(cfg, a.out, a.real).run(a.stage)


if __name__ == '__main__':
    main()
