"""independent_feedback_v1 — Full feedback verification on 6 independent tasks."""
import argparse, json, sys, time, re
from pathlib import Path
from collections import defaultdict

B = Path('/root/cap_eval_bench_v1')
for p in (Path('/root/capital_opinion_pilot'), B, B/'scoring', B/'evidence',
          B/'integration', Path('/root/r3_own_pool')):
    sys.path.insert(0, str(p))
# ...but we need it for auth_gate and feedback_joint_controller
# Import them explicitly instead
import importlib.util as _iu
_spec = _iu.spec_from_file_location('fjc',
    '/root/r3_own_pool/deadline_reward_v1/feedback_joint_controller.py')
fjc = _iu.module_from_spec(_spec)
sys.modules['fjc'] = fjc
_spec.loader.exec_module(fjc)
CapabilityProfile = fjc.CapabilityProfile
JointWeights = fjc.JointWeights
Constraints = fjc.Constraints
optimize_pi = fjc.optimize_pi
decide = fjc.decide

from pilot_common import Meter, BudgetExceeded

RUNNER = 'independent-feedback-v1'
TASKS = {
    'E04-zhuoran': ['E04-zhuoran_20260910','E04-zhuoran_20261009','E04-zhuoran_20261013'],
    'E07-xiwang': ['E07-xiwang_20260328','E07-xiwang_20260429','E07-xiwang_20260822'],
    'E05-nachuan': ['E05-nachuan_20260904','E05-nachuan_20261009'],
    'E06-huanrui': ['E06-huanrui_20260423','E06-huanrui_20260715','E06-huanrui_20260919'],
    'E08-zhongtie': ['E08-zhongtie_20260129','E08-zhongtie_20260327','E08-zhongtie_20260918'],
    'E10-family': ['E10-xiangyuan_20261010','E10b-jiaojian_20261010'],
}
QUESTIONS = {
    'E04-zhuoran': '调查*ST卓然从立案调查到退市风险的完整演变：立案原因与进展、各次退市风险提示的触发条件与时间线、公司目前面临的退市类型判断',
    'E07-xiwang': '调查ST西王的风险警示叠加过程：立案事项、各项风险警示的时间线与叠加关系、公司及实控人面临的具体风险',
    'E05-nachuan': '调查*ST纳川的立案调查背景与退市风险演变：立案涉及事项、各次风险提示的时间线与触发条件、公司的应对措施',
    'E06-huanrui': '调查欢瑞世纪在立案调查背景下的经营状况：立案事项、半年度业绩预告要点、投资者沟通中披露的风险因素',
    'E08-zhongtie': '调查中铁装配在立案调查期间的经营状况：立案事项、年度业绩预告的要点与风险提示、投资者沟通中披露的信息',
    'E10-family': '调查祥源文旅与交建股份实控人同日收到立案告知的关联关系：两家公司的股权关系、实控人身份、立案事项的异同',
}
STRATEGIES = ['Static','SimpleDyn','R_only','pi_only','Joint_R_pi','Joint_Z_R_pi']
GARBAGE = '[{"fact":"占位","evidence_doc_id":"?"}]'
NT = {'f1':'index','f2':'extracts','f3':'timeline','f4':'entity_facts','f5':'factcheck','f6':'report'}
SYS = '你是一个严谨的资本市场调查助手。只输出JSON。'

FROZEN = CapabilityProfile({
    ('index','glm53'): dict(prior_q=0.85, prior_c=643, prior_l=4.1),
    ('index','flash'): dict(prior_q=0.62, prior_c=1063, prior_l=5.2),
    ('extracts','glm53'): dict(prior_q=0.85, prior_c=2783, prior_l=6.2),
    ('extracts','flash'): dict(prior_q=0.62, prior_c=1063, prior_l=6.7),
    ('timeline','glm53'): dict(prior_q=0.75, prior_c=882, prior_l=4.1),
    ('timeline','flash'): dict(prior_q=0.60, prior_c=1063, prior_l=3.7),
    ('entity_facts','glm53'): dict(prior_q=0.80, prior_c=882, prior_l=6.0),
    ('entity_facts','flash'): dict(prior_q=0.58, prior_c=1063, prior_l=6.8),
    ('factcheck','glm53'): dict(prior_q=0.83, prior_c=1362, prior_l=4.3),
    ('factcheck','flash'): dict(prior_q=0.80, prior_c=1063, prior_l=5.2),
    ('report','glm53'): dict(prior_q=0.85, prior_c=1051, prior_l=4.8),
    ('report','flash'): dict(prior_q=0.60, prior_c=1063, prior_l=6.7)})
FEEDBACK = CapabilityProfile({
    ('index','glm53'): dict(prior_q=0.85, prior_c=643, prior_l=4.1),
    ('index','flash'): dict(prior_q=0.65, prior_c=1595, prior_l=6.2),
    ('extracts','glm53'): dict(prior_q=0.85, prior_c=2783, prior_l=6.2),
    ('extracts','flash'): dict(prior_q=0.65, prior_c=1595, prior_l=8.0),
    ('timeline','glm53'): dict(prior_q=0.75, prior_c=882, prior_l=4.1),
    ('timeline','flash'): dict(prior_q=0.58, prior_c=1595, prior_l=4.4),
    ('entity_facts','glm53'): dict(prior_q=0.80, prior_c=882, prior_l=6.0),
    ('entity_facts','flash'): dict(prior_q=0.55, prior_c=1595, prior_l=8.2),
    ('factcheck','glm53'): dict(prior_q=0.83, prior_c=1362, prior_l=4.3),
    ('factcheck','flash'): dict(prior_q=0.72, prior_c=1595, prior_l=6.2),
    ('report','glm53'): dict(prior_q=0.85, prior_c=1051, prior_l=4.8),
    ('report','flash'): dict(prior_q=0.50, prior_c=1595, prior_l=8.0)})
W = JointWeights(w_Q=1.0, w_C=0.5, w_L=0.5)
C = Constraints(budget_tokens=8000, deadline_s=140.0, budget_cash=0.0)

def load_docs(tid):
    docs = {}
    for did in TASKS[tid]:
        f = B/'evidence'/'texts'/f'{did}.txt'
        if f.exists(): docs[did] = f.read_text()[:3500]
    return docs

def build_prompt(uid, kind, upstream, docs, tid):
    q = QUESTIONS[tid]
    if kind == 'index':
        return f'{SYS}\n构建证据索引。文档：{json.dumps(list(docs.keys()),ensure_ascii=False)}\n输出JSON，字段 evidence_index。'
    if kind == 'extracts':
        ds = '\n\n'.join(f'## {k}\n{v}' for k,v in docs.items())
        return f'{SYS}\n从文档抽取关键事实(日期/金额/主体/违规)：\n{ds}\n输出JSON，字段 doc_extracts。'
    if kind == 'timeline':
        return f'{SYS}\n整理时间线：\n{str(upstream.get("doc_extracts",""))[:3000]}\n输出JSON，字段 timeline。'
    if kind == 'entity_facts':
        return f'{SYS}\n识别涉事主体：\n{str(upstream.get("doc_extracts",""))[:3000]}\n输出JSON，字段 entity_facts。'
    if kind == 'factcheck':
        return f'{SYS}\n交叉核验：\n时间线:{str(upstream.get("timeline",""))[:2000]}\n主体:{str(upstream.get("entity_facts",""))[:2000]}\n输出JSON，字段 verified_facts。'
    return f'{SYS}\n问题:{q}\n核验事实:{str(upstream.get("verified_facts",""))[:3000]}\n输出JSON。'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize', action='store_true')
    ap.add_argument('--cap-calls', type=int, default=750)
    ap.add_argument('--cap-tokens', type=int, default=600000)
    ap.add_argument('--max-reps', type=int, default=3)
    args = ap.parse_args()
    if not args.authorize:
        print(json.dumps({'mode':'PLAN-ONLY'})); return 0

    import importlib.util as _iu2
    _spec2 = _iu2.spec_from_file_location('ag',
        '/root/r3_own_pool/deadline_reward_v1/auth_gate.py')
    _ag = _iu2.module_from_spec(_spec2)
    sys.modules['ag'] = _ag
    _spec2.loader.exec_module(_ag)
    _ag.require('independent_feedback_v1')

    out = B/'independent_feedback_v1'
    out.mkdir(exist_ok=True)
    meter = Meter(ledger_path=out/'LEDGER.jsonl',
                  max_calls=args.cap_calls, max_guaranteed_actual=args.cap_tokens)
    results = []
    spent = {'glm53':0, 'glm53flash':0}

    for tid in TASKS:
        docs = load_docs(tid)
        if not docs: continue
        for pname, prof in [('frozen',FROZEN), ('feedback',FEEDBACK)]:
            for anomaly in ('transport', 'evidence_fail'):
                for rep in range(1, args.max_reps+1):
                    # Shared prefix
                    s_out, s_data = {}, {}
                    for uid in ['f1','f2','f3']:
                        kind = NT[uid]
                        da = dict(docs)
                        if anomaly == 'evidence_fail' and uid == 'f2' and len(da)>1:
                            da.pop(sorted(da.keys())[0])
                        prompt = build_prompt(uid, kind, s_data, da, tid)
                        model = 'glm53flash' if kind in ('index','extracts') else 'glm53'
                        try:
                            rec, text = meter.call(model, '', prompt, 768,
                                purpose=f'IF-{pname}-{anomaly[:4]}-{tid}-r{rep}:{uid}')
                        except BudgetExceeded:
                            print(f'BUDGET STOP'); goto_save(results, out, spent); return
                        if uid == 'f3' and anomaly == 'transport':
                            text = GARBAGE
                        s_out[uid] = text; s_data[kind] = text
                        u = rec.get('usage',{})
                        spent[model] = spent.get(model,0) + u.get('input_tokens',0) + u.get('output_tokens',0)

                    rem = [('f3','timeline'),('f4','entity_facts'),('f5','factcheck'),('f6','report')]
                    for strat in STRATEGIES:
                        outputs = dict(s_out); odata = dict(s_data)
                        if anomaly == 'transport': odata['timeline'] = GARBAGE
                        failed = {'f3'}

                        if strat == 'Static' or strat == 'SimpleDyn':
                            Rset = {'f3'}
                            pi = {n: 'glm53flash' if NT[n] in ('index','extracts') else 'glm53' for n,_ in rem}
                        elif strat == 'R_only':
                            Rset = {'f3','f5','f6'}
                            pi = {n: 'glm53flash' for n,_ in rem}
                        else:
                            pi, _ = optimize_pi(prof, W, C,
                                [(n, NT[n].replace('_full','')) for n,_ in rem],
                                dict(tokens=2000, latency=30.0, cash=0.0))
                            if strat == 'pi_only':
                                Rset = {'f3'}
                            else:
                                Rset = {'f3'}  # simplified for now

                        # Execute
                        for uid, ntype in rem:
                            if uid not in Rset and uid in outputs and uid != 'f3':
                                continue
                            da_exec = docs if (anomaly=='evidence_fail' and strat=='Joint_Z_R_pi') else da
                            prompt = build_prompt(uid, ntype, odata, da_exec, tid)
                            m = pi.get(uid, 'glm53flash')
                            if m == 'flash': m = 'glm53flash'
                            try:
                                rec, text = meter.call(m, '', prompt, 768,
                                    purpose=f'IF-{pname}-{anomaly[:4]}-{strat}-{tid}-r{rep}:{uid}')
                            except BudgetExceeded:
                                print(f'BUDGET STOP'); goto_save(results, out, spent); return
                            u2 = rec.get('usage',{})
                            spent[m] = spent.get(m,0) + u2.get('input_tokens',0) + u2.get('output_tokens',0)
                            outputs[uid] = text; odata[ntype] = text

                        # Score
                        text6 = outputs.get('f6','')
                        clean = re.sub(r'[\s,，]', '', text6)
                        hits = sum(1 for k,v in docs.items()
                                   if any(w in clean for w in re.findall(r'[\u4e00-\u9fa5]{3,}', v[:300])[:8]))
                        q = hits / max(1, len(docs))
                        results.append(dict(task=tid, profile=pname, anomaly=anomaly,
                            rep=rep, strategy=strat, Q=round(q,4),
                            pi={k:v for k,v in pi.items()}))
                        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    goto_save(results, out, spent)

def goto_save(results, out, spent):
    (out/'RESULTS.json').write_text(json.dumps(
        dict(runner=RUNNER, results=results, spent=spent,
             n_runs=len(results)), ensure_ascii=False, indent=1))
    print(f'FINAL: {len(results)} runs saved')

if __name__ == '__main__':
    sys.exit(main())
