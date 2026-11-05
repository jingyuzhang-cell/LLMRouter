#!/usr/bin/env python3
"""RQ_DYN_V1 runner: HomDS+D1D2 (arm A) vs Joint(Z,R,pi) (arm B), 20 execs.
Policy per RQ_DYN_V1_PREREGISTRATION.md v1.0 sec.3/3.0 (frozen):
  Z3 pre-check (all extracts dead -> degrade, no recovery downstream);
  R = same-model reroll once; pi = qwen reroll once after R fail (delivery-class);
  Z2 = merge triple-fail -> per-branch merges + deterministic join;
  Z1 = deterministic fid/date/number conflict check on merge output -> insert
       verification call targeting conflicting fid group.
Real mode: env STAGE_D_REAL_CALLS_AUTHORIZED=1 + DEEPSEEK_API_KEY + QWEN_API_KEY.
"""
import os, sys, json, time, argparse, hashlib, re
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, node_prompt, parse_facts, signals, score_node
# RQ_DYN_V1 task materials: C (视觉中国) + B (豫金刚石), single-DAG definitions
TASKS = ['C_sjzg', 'B_yjt']
CB_MATS = {
 'C_sjzg': {'question': '调查视觉中国黑洞照片舆情事件：多方回应链、市场反应与整改过程',
   'docs': [{'doc_id': 'suspend', 'file': None}, {'doc_id': 'abnormal', 'file': None}, {'doc_id': 'resume', 'file': None}],
   'nodes': [
     {'node_id': 'ext_suspend', 'kind': 'extract', 'doc_refs': ['suspend'], 'task': '提取暂停服务公告中的举报、约谈、整改事实', 'fact_ids': ['C-01','C-02','C-07','C-13'], 'reference_upstream': None},
     {'node_id': 'ext_abnormal', 'kind': 'extract', 'doc_refs': ['abnormal'], 'task': '提取异常波动公告中的异动事实与公司核实声明', 'fact_ids': ['C-03','C-09','C-11','C-14'], 'reference_upstream': None},
     {'node_id': 'ext_resume', 'kind': 'extract', 'doc_refs': ['resume'], 'task': '提取恢复服务公告中的处罚与恢复事实', 'fact_ids': ['C-04','C-05','C-06','C-10','C-12'], 'reference_upstream': None},
     {'node_id': 'merge', 'kind': 'reason', 'doc_refs': [], 'task': '合并三方信息重建事件时间线（举报/约谈→暂停→异动→处罚→恢复）', 'fact_ids': ['C-08'], 'reference_upstream': {'from_nodes': ['ext_suspend','ext_abnormal','ext_resume'], 'fact_ids': ['C-01','C-02','C-03','C-04','C-05','C-07','C-10','C-14']}},
     {'node_id': 'report', 'kind': 'report', 'doc_refs': [], 'task': '生成终端调查报告', 'fact_ids': ['C-08','C-13'], 'reference_upstream': {'from_nodes': ['merge'], 'fact_ids': ['C-08']}}]},
 'B_yjt': {'question': '调查豫金刚石多主体资金占用与违规担保：多监管方、跨年审核与资金占用延续',
   'docs': [{'doc_id': 'notice', 'file': None}, {'doc_id': 'occ2020', 'file': None}, {'doc_id': 'occ2021', 'file': None}, {'doc_id': 'henan', 'file': None}, {'doc_id': 'szse', 'file': None}],
   'nodes': [
     {'node_id': 'ext_notice', 'kind': 'extract', 'doc_refs': ['notice'], 'task': '提取处罚告知书核心事实（文号/日期/禁入/虚增）', 'fact_ids': ['B-01','B-02','B-03','B-04','B-05','B-06'], 'reference_upstream': None},
     {'node_id': 'ext_occ', 'kind': 'extract', 'doc_refs': ['occ2020','occ2021'], 'task': '提取两年专项审核意见与资金占用表事实', 'fact_ids': ['B-07','B-08','B-09'], 'reference_upstream': None},
     {'node_id': 'ext_replies', 'kind': 'extract', 'doc_refs': ['henan','szse'], 'task': '提取两份关注函回复中的监管主体与相关人员信息', 'fact_ids': ['B-10'], 'reference_upstream': None},
     {'node_id': 'merge', 'kind': 'reason', 'doc_refs': [], 'task': '合并三线：多监管方关联、跨年审核一致性、资金占用延续', 'fact_ids': ['B-08','B-09'], 'reference_upstream': {'from_nodes': ['ext_notice','ext_occ','ext_replies'], 'fact_ids': ['B-01','B-03','B-07','B-08','B-09','B-10']}},
     {'node_id': 'report', 'kind': 'report', 'doc_refs': [], 'task': '生成终端调查报告', 'fact_ids': ['B-09','B-10'], 'reference_upstream': {'from_nodes': ['merge'], 'fact_ids': ['B-09']}}]},
}
CB_TEXT = {'C_sjzg': {d['doc_id']: (Path('/root/capital_opinion_pilot/v3_evidence/C_shijuezhongguo/text')/f).read_text('utf-8')
            for d, f in zip(CB_MATS['C_sjzg']['docs'], ['sjzg_suspend_2019.txt','sjzg_abnormal_2019.txt','sjzg_resume_2019.txt'])},
           'B_yjt': {d['doc_id']: (Path('/root/capital_opinion_pilot/v3_evidence/B_yujingangshi/text')/f).read_text('utf-8')
            for d, f in zip(CB_MATS['B_yjt']['docs'], ['yjt_notice_2021.txt','yjt_occupy_2020.txt','yjt_occupy_2021.txt','yjt_henan_reply.txt','yjt_reply_2021.txt'])}}
def cb_node_prompt(task, node, upstream):
    t = CB_MATS[task]
    docs = '\n\n'.join(f"[{dr}]\n" + CB_TEXT[task][dr] for dr in node.get('doc_refs', []))
    up = ''
    ru = node.get('reference_upstream')
    if ru:
        parts = [f"上游节点 {n} 的事实：\n" + json.dumps(upstream[n], ensure_ascii=False) for n in ru['from_nodes'] if n in upstream]
        up = '\n\n'.join(parts)
    return (f"调查问题：{t['question']}\n\n节点任务（{node['kind']}）：{node['task']}\n"
            + (f"文档：\n{docs}" if docs else '') + (f"\n\n{up}" if up else '') + "\n\n按系统格式输出 JSON。")
import json as _json
from pathlib import Path as _P
from rq2_p2r_v3_runner import D2_CONTRACT, DELIVERY_KINDS, D1_PER_FACT, D1_CAP, MAXTOK_BASE, n_upstream_facts
MATS = CB_MATS  # compatibility alias
from rq2_cap_v1_runner import cap_transport
from rq_dyn_v2_injector import Injector

V3_PLAN = {
 'S1': {('C_sjzg',r):'pi_persistent' for r in (1,2,3)} | {('B_yjt',r):'pi_persistent' for r in (1,2,3)},
 'S2': {('C_sjzg',r):'z1_conflict' for r in (1,2,3)} | {('B_yjt',r):'z1_conflict' for r in (1,2,3)},
 'S3': {('C_sjzg',r):'z2_triple' for r in (1,2,3)} | {('B_yjt',r):'z2_triple' for r in (1,2,3)},
}
CONFLICT_TARGETS = {
 'C_sjzg': ('C-01','2019年4月10日'),  # correct=4-11, wrong=4-10
 'B_yjt': ('B-02','2021年8月14日'),   # correct=8-13, wrong=8-14
}
from stage_d_executor import GlobalBudget, RunStore

YUAN = {'deepseek': 0.0129, 'qwen': 0.02}
REPS = 5

def dates_nums(text):
    d = set(re.findall(r'(?:19|20)\d{2}[-年/]\d{1,2}[-月/]\d{1,2}日?', text))
    n = set(re.findall(r'\d[\d,，]*\.?\d*', text))
    return d, n

def z1_conflicts(facts):
    """Deterministic: same fid group with differing date/number sets."""
    groups = {}
    for f in facts:
        if isinstance(f, dict):
            groups.setdefault(str(f.get('fid', '')), []).append(f)
    out = []
    for fid, fs in groups.items():
        if len(fs) < 2:
            continue
        sig = {( frozenset(dates_nums(str(f.get('value', '')) + str(f.get('quote', '')))[0]),
                 frozenset(x.replace(',', '').replace('，', '') for x in dates_nums(str(f.get('value', '')) + str(f.get('quote', '')))[1])) for f in fs}
        if len(sig) > 1:
            out.append((fid, fs))
    return out

class Runner:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.ledger = self.out / 'ledger.jsonl'
        self.injector = None  # set in main() for real mode

    def call(self, cell, task, rep, node, role, model, system, user, mt, scenario=None, attempt=0):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), mt)
        if self.real:
            r = cap_transport(model, system, user, mt)
            text = r['text']
            # V2 injection
            if scenario and self.injector:
                text, irec = self.injector.check(task, scenario, rep, node, attempt, text, model=model)
                if irec:
                    role = f'{role}+inj:{irec["failure_type"]}'
            tin, tout, stop, lat, mr = r['in'], r['out'], r['stop'], r['lat'], r.get('model')
        else:
            text = json.dumps({"facts": [{"fid": node, "value": "mock", "doc": "doc1", "quote": "mock quote"}], "unknown": []}, ensure_ascii=False)
            tin, tout, stop, lat, mr = len(user), 64, 'end_turn', 0.01, None
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), cell=cell, task=task, rep=rep, node=node, role=role,
                   model=model, model_resp=mr, max_tokens=mt, tin=tin, tout=tout,
                   yuan=est, stop=stop, lat=lat, scenario=scenario,
                   prompt_sha=hashlib.sha256((system + '||' + user).encode()).hexdigest()[:16])
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), mt)
        if self.real:
            r = cap_transport(model, system, user, mt)
            text, tin, tout, stop, lat, mr = r['text'], r['in'], r['out'], r['stop'], r['lat'], r.get('model')
        else:
            text = json.dumps({"facts": [{"fid": node, "value": "mock", "doc": "doc1", "quote": "mock quote"}], "unknown": []}, ensure_ascii=False)
            tin, tout, stop, lat, mr = len(user), 64, 'end_turn', 0.01, None
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), cell=cell, task=task, rep=rep, node=node, role=role,
                   model=model, model_resp=mr, max_tokens=mt, tin=tin, tout=tout,
                   yuan=est, stop=stop, lat=lat,
                   prompt_sha=hashlib.sha256((system + '||' + user).encode()).hexdigest()[:16])
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return text

    def run_exec(self, cell, task, rep, scenario=None):
        scn = scenario or 'S1'
        exec_id = f"{cell}|{scn}|{task}|r{rep}"
        if self.store.completed(exec_id):
            return None
        self.store.begin(exec_id)
        dyn = cell == 'DYN'
        upstream, recs, actions = {}, [], []
        extract_nodes = [n for n in MATS[task]['nodes'] if n['kind'] not in DELIVERY_KINDS]
        extract_dead = set()
        for node in MATS[task]['nodes']:
            kind, nid = node['kind'], node['node_id']
            delivery = kind in DELIVERY_KINDS
            model = 'deepseek'
            sysp = SYS_COMMON + (D2_CONTRACT if delivery else '')
            ru = node.get('reference_upstream') or {}
            nup = n_upstream_facts(upstream, ru.get('from_nodes', [])) if delivery else 0
            mt = min(D1_CAP, MAXTOK_BASE + D1_PER_FACT * nup) if delivery else MAXTOK_BASE
            z3 = dyn and delivery and len(extract_dead) == len(extract_nodes) and extract_nodes
            # Z1 input-layer injection: add conflicting fact to upstream for merge
            if scenario and 'S2' in str(scenario) and kind == 'reason' and self.real:
                evo = 'C' if task == 'C_sjzg' else 'B'
                if evo == 'C':
                    conflict_fact = {'fid': 'C-01', 'value': '2019年4月10日', 'doc': 'suspend', 'quote': 'injected conflict'}
                else:
                    conflict_fact = {'fid': 'B-02', 'value': '2021年8月14日', 'doc': 'notice', 'quote': 'injected conflict'}
                # Append to first upstream node's facts so it enters merge input
                for un in (ru.get('from_nodes', []) if ru else []):
                    if upstream.get(un):
                        upstream[un] = upstream[un] + [conflict_fact]
                        break
            userp = cb_node_prompt(task, node, upstream)
            text = self.call(cell, task, rep, nid, 'base', model, sysp, userp, mt, scenario=scenario, attempt=1)
            ok, facts, unk = parse_facts(text)
            base = dict(ok=ok, facts=facts, unknown=unk, model=model, mt=mt, nup=nup)
            sig = signals(node, ok, facts)
            chosen = dict(model=model, facts=facts, unknown=unk, rerolled=False)
            rerolled = None
            if not delivery and not ok:
                extract_dead.add(nid)
            # fault ladder (dyn only; HomDS = R only, same as frozen baseline)
            if (sig['exec'] or sig['prod'] or sig['cite']) and not z3:
                text2 = self.call(cell, task, rep, nid, 'reroll', model, sysp, userp, mt, scenario=scenario, attempt=2)
                ok2, f2, u2 = parse_facts(text2)
                rerolled = dict(ok=ok2, facts=f2, unknown=u2, model=model)
                if score_node(f2) > score_node(facts):
                    chosen = dict(model=model, facts=f2, unknown=u2, rerolled=True)
                    actions.append(dict(action='R', node=nid, outcome='recovered'))
                else:
                    actions.append(dict(action='R', node=nid, outcome='failed'))
                    if dyn and kind == 'merge' and not ok2:
                        text3 = self.call(cell, task, rep, nid, 'reroll2', 'qwen', sysp, userp, mt, scenario=scenario, attempt=3)
                        ok3, f3, u3 = parse_facts(text3)
                        if score_node(f3) > score_node(facts):
                            chosen = dict(model='qwen', facts=f3, unknown=u3, rerolled=True)
                            actions.append(dict(action='pi', node=nid, model='qwen', outcome='recovered'))
                        else:
                            actions.append(dict(action='pi', node=nid, model='qwen', outcome='failed'))
                            if not ok3 and kind == 'merge':
                                # Z2: split per upstream branch + real join
                                branches, bfacts = [], []
                                for un in ru.get('from_nodes', []):
                                    if not upstream.get(un):
                                        continue
                                    up2 = {un: upstream[un]}
                                    up2p = cb_node_prompt(task, node, up2)
                                    bt = self.call(cell, task, rep, nid, f'split:{un}', 'deepseek', sysp, up2p, mt, scenario=scenario, attempt=5)
                                    bok, bf, bu = parse_facts(bt)
                                    branches.append(dict(node=un, ok=bok, n=len(bf)))
                                    if bok:
                                        bfacts += [x for x in bf if isinstance(x, dict)]
                                if bfacts:
                                    chosen = dict(model='deepseek', facts=bfacts, unknown=[], rerolled=True, joined=True)
                                actions.append(dict(action='Z2', node=nid, branches=branches,
                                                    outcome='split+join' if bfacts else 'split-empty',
                                                    n_facts=len(bfacts)))
                            if not ok3:
                                # Z2: split per upstream branch + deterministic join
                                branches, bfacts = [], []
                                for un in ru.get('from_nodes', []):
                                    if not upstream.get(un):
                                        continue
                                    up2 = {un: upstream[un]}
                                    up2p = cb_node_prompt(task, node, up2)
                                    bt = self.call(cell, task, rep, nid, f'split:{un}', 'deepseek', sysp, up2p, mt, scenario=scenario, attempt=5)
                                    bok, bf, bu = parse_facts(bt)
                                    branches.append(dict(node=un, ok=bok, n=len(bf)))
                                    if bok:
                                        bfacts += [x for x in bf if isinstance(x, dict)]
                                chosen = dict(model='deepseek', facts=bfacts, unknown=[], rerolled=True, joined=True)
                                actions.append(dict(action='Z2', node=nid, branches=branches,
                                                    outcome='split+join', n_facts=len(bfacts)))
                    elif dyn and delivery and not ok2:
                        text3 = self.call(cell, task, rep, nid, 'reroll2', 'qwen', sysp, userp, mt, scenario=scenario, attempt=3)
                        ok3, f3, u3 = parse_facts(text3)
                        if score_node(f3) > score_node(facts):
                            chosen = dict(model='qwen', facts=f3, unknown=u3, rerolled=True)
                            actions.append(dict(action='pi', node=nid, model='qwen', outcome='recovered'))
                        else:
                            actions.append(dict(action='pi', node=nid, model='qwen', outcome='failed'))
                            if not ok3 and kind == 'merge':
                                # Z2: split per upstream branch + real join
                                branches, bfacts = [], []
                                for un in ru.get('from_nodes', []):
                                    if not upstream.get(un):
                                        continue
                                    up2 = {un: upstream[un]}
                                    up2p = cb_node_prompt(task, node, up2)
                                    bt = self.call(cell, task, rep, nid, f'split:{un}', 'deepseek', sysp, up2p, mt, scenario=scenario, attempt=5)
                                    bok, bf, bu = parse_facts(bt)
                                    branches.append(dict(node=un, ok=bok, n=len(bf)))
                                    if bok:
                                        bfacts += [x for x in bf if isinstance(x, dict)]
                                if bfacts:
                                    chosen = dict(model='deepseek', facts=bfacts, unknown=[], rerolled=True, joined=True)
                                actions.append(dict(action='Z2', node=nid, branches=branches,
                                                    outcome='split+join' if bfacts else 'split-empty',
                                                    n_facts=len(bfacts)))
            if z3:
                actions.append(dict(action='Z3', node=nid, outcome='degraded-no-recovery'))
            # Z1: deterministic conflict check on merge output
            if dyn and kind == 'merge' and chosen.get('facts'):
                confl = z1_conflicts(chosen['facts'])
                if confl:
                    fid0, fs0 = confl[0]
                    vp = ("以下事实组 fid 相同但日期/数值不一致，请逐条核对并只保留有原文依据的条目。输出JSON {\"facts\":[...],\"unknown\":[...]}：\n"
                          + json.dumps(fs0, ensure_ascii=False))
                    vt = self.call(cell, task, rep, nid, f'verify:{fid0}', 'deepseek', SYS_COMMON, vp, MAXTOK_BASE, scenario=scenario, attempt=4)
                    vok, vf, vu = parse_facts(vt)
                    if vok and score_node(vf) >= score_node(fs0):
                        chosen = dict(model='deepseek', facts=vf, unknown=vu, rerolled=True)
                    actions.append(dict(action='Z1', node=nid, fid=fid0, n_conflict_groups=len(confl),
                                         outcome='verification-inserted'))
            upstream[nid] = chosen['facts']
            recs.append(dict(node_id=nid, kind=kind, signals=sig, chosen=chosen,
                             base_output=base, reroll_output=rerolled,
                             adopted='reroll' if chosen.get('rerolled') else 'base'))
        record = dict(exec_id=exec_id, cell=cell, task=task, rep=rep, nodes=recs,
                      actions=actions, budget_left=self.gb.left())
        self.store.commit(record)
        return record

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'rq_dyn_v1_config.json'))
    ap.add_argument('--out', default=str(HERE / 'rq_dyn_v1_runs'))
    ap.add_argument('--real', action='store_true')
    a = ap.parse_args()
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                raise SystemExit(f'REFUSED: {k}')
        print('REAL MODE — caps:', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE — zero real calls')
    r = Runner(cfg, a.out, a.real)
    if a.real:
        r.injector = Injector(str(a.out) + '/injection_ledger.jsonl')
        r.injector.conflict_fid = 'C-01'
        r.injector.conflict_wrong_value = '2019年4月10日'
        for task_key, (_, wrong) in CONFLICT_TARGETS.items():
            pass  # set per-task at call time
    else:
        r.injector = None
    done = skipped = 0
    stop = False
    # Scenario execution order: S1 (by V2_PLAN), S2, S3, S4
    import os as _os
    _resume = _os.environ.get('V2_RESUME_FROM','S1')
    _all_scn = ('S1','S2','S3','S4')
    for scenario in _all_scn[_all_scn.index(_resume):]:
        plan = V3_PLAN[scenario]
        for (task, rep_val), sub_type in sorted(plan.items()):
            # Map to full scenario name
            if scenario == 'S1':
                scn = 'S1_pi'
            else:
                scn = scenario  # S2, S3 use plain name
            for cell in ('HomDS', 'DYN'):
                eid = f"{cell}|{scn}|{task}|r{rep_val}"
                if r.store.completed(eid):
                    skipped += 1
                    continue
                if r.gb.left()['calls_left'] < 12:
                    print(f'STOP before {eid}: budget guard')
                    stop = True
                    break
                if a.real and scenario == 'S2':
                    fid, wrong = CONFLICT_TARGETS[task]
                    r.injector.set_conflict(fid, wrong)
                if a.real:
                    # Register injections based on scenario+sub_type
                    if sub_type == 'pi_persistent':
                        r.injector.plan = {}
                        # MODEL-SPECIFIC: only truncate DS calls on merge (attempts 1=base, 2=reroll)
                        # Qwen (attempt 3) NOT registered -> not injected
                        r.injector.register(task, scn, rep_val, 'merge', 1, 'truncate', model_filter='deepseek')
                        r.injector.register(task, scn, rep_val, 'merge', 2, 'truncate', model_filter='deepseek')
                    elif sub_type == 'z1_conflict':
                        r.injector.plan = {}  # Z1 injection is at input layer, not response layer
                        fid, wrong = CONFLICT_TARGETS[task]
                        r.injector.set_conflict(fid, wrong)
                    elif sub_type == 'z2_triple':
                        r.injector.plan = {}
                        # ALL three attempts truncated (node-level, both models)
                        r.injector.register(task, scn, rep_val, 'merge', 1, 'truncate')
                        r.injector.register(task, scn, rep_val, 'merge', 2, 'truncate')
                        r.injector.register(task, scn, rep_val, 'merge', 3, 'truncate')
                r.run_exec(cell, task, rep_val, scenario=scn)
                done += 1
                print(f'  {eid} done, calls_left={r.gb.left()["calls_left"]}')
            if stop:
                break
        if stop:
            break
    print(f'BATCH DONE: executed={done} skipped={skipped} stopped={stop} budget={r.gb.left()}')

if __name__ == '__main__':
    main()
