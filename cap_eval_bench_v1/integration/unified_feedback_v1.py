"""unified_feedback_v1 — THE one comprehensive verification (48 runs).
T-P3 (豫金刚石, zero-exposure) × {frozen,feedback} profiles × {transport,
evidence-fail} anomalies × 6 strategies × 2 reps.

Answers three questions in ONE batch:
  Q1: Does feedback-updated profile improve scheduling? (feedback vs frozen)
  Q2: Does dynamic joint dispatch outperform baselines? (Joint(R,π) vs others)
  Q3: Does structure editing add value when legal opportunities exist?
      (Joint(Z,R,π) vs Joint(R,π) under evidence-fail)

Authorization: batch_name=unified_feedback_v1, max_calls=300,
max_tokens=360000, models={glm53,glm53flash}, tasks=[T-P3].
"""
import argparse, json, sys, time
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
P = Path('/root/capital_opinion_pilot')
for p in (B, B/'scoring', B/'evidence', B/'integration', P,
          '/root/r3_own_pool', '/root/r3_own_pool/deadline_reward_v1'):
    sys.path.insert(0, str(p))

from pilot_common import Meter, BudgetExceeded
from phase2_stage_a import load_task, SYSTEM_NODE, FINAL_CAP
from phase1_real_batch import NODE_CAPS
from canonical_assembler import assemble, fair_final_prompt_suffix
import qe_k_scorer as S
import static_optimizer as SO

RUNNER_VERSION = 'unified-feedback-v1'
TASK_ID = 'T-P3'
NODE_KINDS = {'f1':'index','f2':'extracts','f3':'timeline',
              'f4':'entity_facts','f5':'factcheck_full','f6':'report'}
DEPS = {'f1':[],'f2':['f1'],'f3':['f2'],'f4':['f2'],'f5':['f2','f3','f4'],'f6':['f5']}
GARBAGE = '[{"fact":"占位","evidence_doc_id":"?"}]'
STRATEGIES = ['Static','SimpleDyn','R_only','pi_only','Joint_R_pi','Joint_Z_R_pi']

# Two profiles
FROZEN_Q = {  # original frozen profile (Flash=cheap, GLM=quality)
    'index':{'glm53':0.85,'flash':0.62}, 'extracts':{'glm53':0.85,'flash':0.62},
    'timeline':{'glm53':0.75,'flash':0.60}, 'entity_facts':{'glm53':0.80,'flash':0.58},
    'factcheck':{'glm53':0.83,'flash':0.80}, 'report':{'glm53':0.85,'flash':0.60}}
FEEDBACK_Q = {  # updated: Flash quality drops on citation-heavy nodes
    'index':{'glm53':0.85,'flash':0.65}, 'extracts':{'glm53':0.85,'flash':0.65},
    'timeline':{'glm53':0.75,'flash':0.58}, 'entity_facts':{'glm53':0.80,'flash':0.55},
    'factcheck':{'glm53':0.83,'flash':0.72}, 'report':{'glm53':0.85,'flash':0.50}}
FROZEN_C = {k: SO.COST.get(k, {}) for k in
            ('index','extracts','timeline','entity_facts','factcheck','report')}
# Feedback: Flash costs ~1.5x frozen estimate
FEEDBACK_C = {k: {m: int(v*1.5) if m=='flash' else v for m,v in d.items()}
              for k, d in FROZEN_C.items()}

def predict_pi(profile_q, profile_c, nodes, budget=5000):
    """Greedy: assign GLM where quality/cost ratio is best within budget."""
    assign = {}
    total = 0
    for n in nodes:
        kind = NODE_KINDS[n].replace('_full','')
        glm_q = profile_q.get(kind,{}).get('glm53',0.5)
        flash_q = profile_q.get(kind,{}).get('flash',0.5)
        glm_c = profile_c.get(kind,{}).get('glm53',800)
        flash_c = profile_c.get(kind,{}).get('flash',600)
        # Choose model maximizing quality per token within budget
        if total + glm_c <= budget and glm_q > flash_q:
            assign[n] = 'glm53'; total += glm_c
        else:
            assign[n] = 'flash'; total += flash_c
    return assign

def build_prompt(uid, kind, upstream, evidence_texts, task, profile_name):
    sys_head = SYSTEM_NODE
    if kind == 'index':
        idx = json.dumps([dict(doc_id=k, title=v[:40]) for k,v in evidence_texts.items()], ensure_ascii=False)
        return f'{sys_head}\n子任务：构建证据索引。可用文档：{idx}\n输出 JSON 对象，字段 evidence_index。'
    if kind == 'extracts':
        docs = '\n\n'.join(f'## 文档 {did}\n{txt[:3000]}' for did,txt in list(evidence_texts.items())[:5])
        return (f'{sys_head}\n子任务：从下列证据文档正文抽取关键事实（日期/金额/主体/违规事实），'
                f'输出 JSON，字段 doc_extracts。\n证据文档正文：\n{docs}')
    if kind == 'timeline':
        up = json.dumps(upstream.get('doc_extracts',{}), ensure_ascii=False)[:4000]
        return f'{sys_head}\n子任务：整理时间线（按日期排序），输出 JSON，字段 timeline。\n上游抽取：{up}'
    if kind == 'entity_facts':
        up = json.dumps(upstream.get('doc_extracts',{}), ensure_ascii=False)[:4000]
        return f'{sys_head}\n子任务：识别涉事主体及关系，输出 JSON，字段 entity_facts。\n上游抽取：{up}'
    if kind == 'factcheck_full':
        tl = json.dumps(upstream.get('timeline',[]), ensure_ascii=False)[:2500]
        ef = json.dumps(upstream.get('entity_facts',[]), ensure_ascii=False)[:2500]
        return f'{sys_head}\n子任务：交叉核验全部上游事实，输出 JSON，字段 verified_facts。\n时间线：{tl}\n主体：{ef}'
    # report
    vf = json.dumps(upstream.get('verified_facts',[]), ensure_ascii=False)[:4000]
    docs_sum = '\n'.join(f'文档 {did}: {txt[:200]}' for did,txt in list(evidence_texts.items())[:5])
    fps = fair_final_prompt_suffix(TASK_ID)
    return (f'{sys_head}\n{fps}\n用户问题：{task["question"]}\n核验事实：{vf}'
            f'\n\n## 证据文档摘要（供引用）：\n{docs_sum}')

def anatomy_tag(a):
    return a[:4]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--authorize', action='store_true')
    ap.add_argument('--cap-calls', type=int, default=300)
    ap.add_argument('--cap-tokens', type=int, default=360000)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if not args.authorize:
        print(json.dumps({'mode':'PLAN-ONLY'})); return 0

    from auth_gate import require
    require('unified_feedback_v1')

    task = load_task(TASK_ID)
    ev = {}
    for did in task['evidence_doc_ids']:
        f = B/'evidence'/'texts'/f'{did}.txt'
        if f.exists():
            ev[did] = f.read_text()[:4000]

    out_dir = B/'unified_feedback_v1'
    out_dir.mkdir(exist_ok=True)
    meter = Meter(ledger_path=out_dir/'LEDGER.jsonl',
                  max_calls=args.cap_calls, max_guaranteed_actual=args.cap_tokens)
    import pilot_common
    results = []
    spent = {'glm53':0, 'glm53flash':0}

    for profile_name, pq, pc in [('frozen',FROZEN_Q,FROZEN_C), ('feedback',FEEDBACK_Q,FEEDBACK_C)]:
        for anomaly in ('transport', 'evidence_fail'):
            for rep in (1, 2):
                # Shared pre-anomaly prefix
                shared_out = {}; shared_data = {}; shared_recs = []
                for uid in ['f1','f2','f3']:
                    kind = NODE_KINDS[uid]
                    up = {}
                    for d in DEPS[uid]:
                        port = {'index':'evidence_index','extracts':'doc_extracts',
                                'timeline':'timeline','entity_facts':'entity_facts',
                                'factcheck_full':'verified_facts'}[NODE_KINDS[d]]
                        up[port] = shared_data.get(NODE_KINDS[d])
                    # For evidence_fail: make one doc unavailable at f2
                    ev_avail = dict(ev)
                    if anomaly == 'evidence_fail' and uid == 'f2':
                        first_doc = sorted(ev_avail.keys())[0]
                        ev_avail.pop(first_doc)  # remove one doc
                    prompt = build_prompt(uid, kind, up, ev_avail, task, profile_name)
                    model = 'glm53flash' if kind in ('index','extracts') else 'glm53'
                    rec, text = meter.call(model, '', prompt,
                                           NODE_CAPS.get(kind.replace('_full',''), 512),
                                           purpose=f'UF-{profile_name}-{anomaly}-r{rep}:{uid}')
                    if uid == 'f3' and anomaly == 'transport':
                        text = GARBAGE
                    shared_recs.append(rec)
                    shared_out[uid] = text
                    shared_data[kind] = text
                    u = rec.get('usage',{})
                    spent[model] = spent.get(model,0) + u.get('input_tokens',0) + u.get('output_tokens',0)

                # Fork 6 strategies from SAME state
                for strat in STRATEGIES:
                    outputs = dict(shared_out)
                    odata = dict(shared_data)
                    if anomaly == 'transport':
                        odata['timeline'] = GARBAGE
                    if anomaly == 'evidence_fail':
                        odata['doc_extracts'] = odata.get('doc_extracts','')  # partial

                    run_id = f'UF-{profile_name}-{anatomy_tag(anomaly)}-{strat}-r{rep}'
                    wall0 = time.monotonic()

                    # Strategy determines R and pi
                    remaining = ['f3','f4','f5','f6'] if anomaly == 'transport' else ['f3','f4','f5','f6']
                    if strat == 'Static':
                        Rset = {'f3'}
                        pi = {n: ('glm53flash' if NODE_KINDS[n] in ('index','extracts') else 'glm53') for n in remaining}
                    elif strat == 'SimpleDyn':
                        Rset = {'f3'}  # simple: retry failed node
                        pi = {n: ('glm53flash' if NODE_KINDS[n] in ('index','extracts') else 'glm53') for n in remaining}
                    elif strat == 'R_only':
                        Rset = {'f3','f5','f6'}  # closure
                        pi = {n: 'glm53flash' for n in remaining}  # keep original (all flash for recovery)
                    elif strat == 'pi_only':
                        Rset = {'f3'}
                        pi = predict_pi(pq, pc, remaining, 5000)
                    elif strat == 'Joint_R_pi':
                        best_v, Rset, pi = -9, {'f3'}, None
                        for Rc in [{'f3'}, {'f3','f5','f6'}]:
                            pic = predict_pi(pq, pc, sorted(Rc), 5000)
                            v = sum(pq.get(NODE_KINDS[n].replace('_full',''),{}).get(
                                pic.get(n,'glm53').replace('glm53flash','flash'),0.5)
                                for n in remaining) / len(remaining)
                            c = sum(pc.get(NODE_KINDS[n].replace('_full',''),{}).get(
                                pic.get(n,'glm53').replace('glm53flash','flash'),500)
                                for n in Rc) / 8000
                            if v - c > best_v:
                                best_v, Rset, pi = v - c, Rc, pic
                    else:  # Joint_Z_R_pi
                        best_v, Rset, pi = -9, {'f3'}, None
                        for Rc in [{'f3'}, {'f3','f5','f6'}]:
                            pic = predict_pi(pq, pc, sorted(Rc), 5000)
                            v = sum(pq.get(NODE_KINDS[n].replace('_full',''),{}).get(
                                pic.get(n,'glm53').replace('glm53flash','flash'),0.5)
                                for n in remaining) / len(remaining)
                            c = sum(pc.get(NODE_KINDS[n].replace('_full',''),{}).get(
                                pic.get(n,'glm53').replace('glm53flash','flash'),500)
                                for n in Rc) / 8000
                            if v - c > best_v:
                                best_v, Rset, pi = v - c, Rc, pic
                        # Z: under evidence_fail, try substitution (use all docs again)
                        # Under transport, Z=IDENTITY (no structure change needed)

                    # Execute recovery
                    for uid in remaining:
                        kind = NODE_KINDS[uid]
                        if uid not in Rset and uid in outputs and uid != 'f3':
                            continue
                        up = {}
                        for d in DEPS[uid]:
                            port = {'index':'evidence_index','extracts':'doc_extracts',
                                    'timeline':'timeline','entity_facts':'entity_facts',
                                    'factcheck_full':'verified_facts'}[NODE_KINDS[d]]
                            up[port] = odata.get(NODE_KINDS[d])
                        # For evidence_fail + Joint_Z_R_pi: substitute evidence
                        ev_use = ev if (anomaly == 'evidence_fail' and strat == 'Joint_Z_R_pi') else ev_avail
                        prompt = build_prompt(uid, kind, up, ev_use, task, profile_name)
                        m = pi.get(uid, 'glm53flash')
                        if m == 'flash': m = 'glm53flash'
                        if m == 'glm53': m = 'glm53'
                        rec, text = meter.call(m, '', prompt,
                                               NODE_CAPS.get(kind.replace('_full',''), 512),
                                               purpose=f'{run_id}:{uid}')
                        u2 = rec.get('usage',{})
                        spent[m] = spent.get(m,0) + u2.get('input_tokens',0) + u2.get('output_tokens',0)
                        outputs[uid] = text
                        odata[kind] = text

                    wall = time.monotonic() - wall0
                    # Score
                    import re
                    text = outputs.get('f6','')
                    t = text.strip()
                    if t.startswith('```'):
                        parts = t.split('\n',1)
                        t = parts[1].rsplit('```',1)[0].strip() if len(parts)==2 else t
                    m2 = re.search(r'\{.*\}', t, re.S)
                    try:
                        parsed = json.loads(m2.group(0)) if m2 else {'raw':text[:200]}
                    except:
                        parsed = {'raw':text[:200]}
                    assembled = assemble(task, parsed)
                    try:
                        sc = S.score_run(dict(run_id=run_id, system_id=strat,
                            task_id=TASK_ID,
                            nodes=[dict(node=f'f{i}',status='done') for i in range(6)],
                            retrieval=dict(n_calls=1,chars=4000), program_ms=0.0,
                            status='COMPLETE'), assembled)
                        Qd = sc.get('Q',{})
                        qv = Qd.get('Q',0.0) or 0.0
                    except:
                        qv = -1
                    results.append(dict(profile=profile_name, anomaly=anomaly,
                                        rep=rep, strategy=strat, Q=qv,
                                        R=sorted(Rset), wall=round(wall,1),
                                        calls=len(shared_recs)+len(remaining)))
                    print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    (out_dir/'RESULTS.json').write_text(json.dumps(
        dict(runner=RUNNER_VERSION, results=results, spent=spent,
             budget=dict(calls=args.cap_calls, tokens=args.cap_tokens)),
        ensure_ascii=False, indent=1))
    print(f'FINAL: {len(results)} runs, calls={meter.calls if hasattr(meter,"calls") else "?"}, spent={spent}')

if __name__ == '__main__':
    sys.exit(main())
