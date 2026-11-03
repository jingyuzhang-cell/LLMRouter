"""V3 (authorized run, PLANNING-ONLY): autonomous initial-DAG generation for the
Kangde Xin cross-year event + structure audit + comparison with the Shuntian DAG.
NO node execution, no model assignment beyond the planner. Zero calls after the
planner step. If the planner fails within its 2-request envelope, we STOP and
report failure — no template fallback, no invented nodes.

Output: initial_dag_v3_kdx.json, V3_KANGDEXIN_DAG_AUDIT.md
"""
import json

from pilot_common import PILOT_DIR, Meter
import semantic_plan as SP
import assemble_dag as AD

CAPS = dict(max_calls=3, max_guaranteed_actual=6500)
KDX_DOCS = ['kdx_inquiry_2018', 'kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020', 'kdx_inquiry_2019']
TASK = ('请调查康得新（002450）跨年度财务披露违法违规事件：追溯2018-2019年年报问询、证监会立案与'
        '行政处罚/市场禁入的过程，核实跨年度虚假记载（虚增利润、银行存款、关联担保）的监管认定与'
        '公司披露，梳理涉及主体、关键时间节点，生成具有准确证据引用的调查报告。'
        '无法确认的事项必须明确标注。')
CUTOFF = '2021-06-30'


def ctx_table():
    man = json.load(open(PILOT_DIR / 'v3_evidence' / 'A_kangdexin' / 'hits.json'))
    manifests = json.load(open(PILOT_DIR / 'v3_evidence' / 'v3_manifests.json'))
    rows = []
    for d in manifests['A_kangdexin']['documents']:
        rows.append({'doc_id': d['doc_id'], 'title': d['title'], 'public_date': d['public_date'],
                     'sha256': d.get('sha256', '')[:12], 'text_chars': d['text_chars']})
    return json.dumps(rows, ensure_ascii=False)


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_v3kdx.jsonl', **CAPS)
    sys_p = SP.plan_system_prompt()
    usr_p = SP.plan_user_prompt(TASK, ctx_table())
    usr_p = usr_p.replace('信息截止2024-07-10', f'信息截止{CUTOFF}')

    rec, txt = meter.call('glm53', sys_p, usr_p, max_tokens=768,
                          purpose='v3kdx_planner_initial', timeout_s=60)
    plan, issues = None, ['parse']
    try:
        plan = SP.parse_plan(txt)
        issues = SP.validate_plan(plan, KDX_DOCS)
    except Exception as e:
        issues = [f'parse:{e}']
    attempts = [{'phase': 'initial', 'call_id': rec['call_id'], 'issues': issues}]
    if issues:
        rec2, txt2 = meter.call(
            'glm53', sys_p,
            usr_p + f'\n\n你的计划未通过结构检查：{json.dumps(issues, ensure_ascii=False)[:400]}。请修正后重新输出完整计划JSON。',
            max_tokens=768, purpose='v3kdx_planner_repair', timeout_s=60)
        try:
            plan = SP.parse_plan(txt2)
            issues = SP.validate_plan(plan, KDX_DOCS)
        except Exception as e:
            issues = [f'parse:{e}']
        attempts.append({'phase': 'repair', 'call_id': rec2['call_id'], 'issues': issues})

    result = {'event': '康得新(002450)跨年度财务披露争议', 'cutoff': CUTOFF, 'task': TASK,
              'planner': {'model': 'GLM-5.3', 'attempts': attempts,
                          'envelope': 'max 2 requests, 60s each, no template fallback'},
              'budget': meter.summary()}
    if issues:
        result['status'] = 'PLANNER_ENVELOPE_EXHAUSTED_OR_INVALID'
        result['issues'] = issues
        (PILOT_DIR / 'initial_dag_v3_kdx.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print('PLANNER FAILED — no fallback. issues:', issues)
        return

    gv, iss = AD.assemble(plan)
    if gv is None:
        result['status'] = 'ASSEMBLY_INVALID'
        result['issues'] = iss
        (PILOT_DIR / 'initial_dag_v3_kdx.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print('ASSEMBLY INVALID — no fallback. issues:', iss)
        return
    graph, validated = gv
    result.update({'status': 'ASSEMBLED', 'plan': plan,
                   'graph': graph.to_dict(),
                   'validation': {'status': 'PASS', 'graph_hash': validated.graph_hash,
                                  'layers': [list(l) for l in validated.layers]}})
    (PILOT_DIR / 'initial_dag_v3_kdx.json').write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print('KDX DAG assembled:', [list(l) for l in validated.layers])
    for t in plan['plan']:
        print(f"  {t['id']} {t['kind']:14s} deps={t['depends']} | {t['goal'][:36]}")


if __name__ == '__main__':
    main()
