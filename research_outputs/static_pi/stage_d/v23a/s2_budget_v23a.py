"""Phase V2.3-A / A3: S2 protocol parameter computation — precise budget.

Design (preregistered, pending authorization):
  per eligible task: 2 conditions (A full / B target-field ablated) x 2 reps,
  model = glm-5.3-flash (thinking enabled, effort low) for ALL conditions,
  DAG: one E node per document -> J (join) -> SINK,
  separate purpose tags per condition/rep (no cache sharing),
  randomized execution order across (task, condition, rep).

Token model (from the measured V2 ledger: 282 calls, 603,864 tokens):
  E input  ~= doc_chars * 0.75 tokens/char + 400 overhead
  J  input ~= sum(E outputs) with E output ~= 900 chars -> *0.75
  SINK input ~= 2500 chars -> *0.75 ; every call output ~= 600 tokens
  cost = in*0.8e-6 + out*2.8e-6 yuan (GLM flash accounting, as frozen in V2)
"""
import json, os

DOC_SETS = {
 'ZIJING': ['2022-02-12', '2022-06-25', '2022-11-19', '2023-04-22', '2023-07-01'],
 'ZEDA': ['2022-05-12', '2022-07-13', '2022-11-19', '2023-04-22', '2023-07-01'],
 'ZHANGZIDAO': ['2019-01-08', '2019-07-11', '2020-06-25'],
 'KANGMEI': ['2018-12-29', '2019-08-17', '2020-05-15'],
 'KDX': ['kdx_notice_2019', 'kdx_notice_2020', 'kdx_penalty_2020'],
 'YJT': ['yjt_occupy_2020', 'yjt_henan_reply', 'yjt_notice_2021', 'yjt_reply_2021', 'yjt_occupy_2021'],
 'GUOEN': ['ACQUISITION', 'CLOSING'],
 'MVR2': 3, 'E04': 3, 'E06': 3, 'MVR1': 4, 'E08': 3,   # doc counts from frozen contracts
}
CHAR_PATH = {
 'ZIJING': 'docs/ZIJING/ZIJING_{d}.txt', 'ZEDA': 'docs/ZEDA/ZEDA_{d}.txt',
 'ZHANGZIDAO': 'docs/ZHANGZIDAO/ZHANGZIDAO_{d}.txt', 'KANGMEI': 'docs/KANGMEI/KANGMEI_{d}.txt',
 'KDX': '/root/capital_opinion_pilot/v3_evidence/A_kangdexin/text/{d}.txt',
 'YJT': '/root/capital_opinion_pilot/v3_evidence/B_yujingangshi/text/{d}.txt',
 'GUOEN': 'docs/GUOEN/{d}.txt',
}
CONTRACTS = {
 'MVR2': '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR2_yuandao/TASK_CONTRACT_MVR2_v1.json',
 'E04': '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2/TASK_CONTRACT_PHASE2_E04_v1.json',
 'E06': '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/PHASE2/TASK_CONTRACT_PHASE2_E06_v1.json',
 'MVR1': '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/MVR1_shuntian/TASK_CONTRACT_MVR1_v1.json',
 'E08': '/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/E08_zhongtie/TASK_CONTRACT_E08_SILVER_DRAFT.json',
}
ELIGIBLE = ['ZIJING', 'ZEDA', 'ZHANGZIDAO', 'KANGMEI', 'KDX', 'YJT', 'GUOEN',
            'MVR2', 'E04', 'E06', 'MVR1', 'E08']


def doc_chars(ev):
    ds = DOC_SETS[ev]
    if isinstance(ds, int):
        c = json.load(open(CONTRACTS[ev]))
        chars = []
        for did, d in c['source_pages'].items():
            chars.append(sum(len(r.get('text', '')) for r in d['pages'].values()))
        return chars
    return [os.path.getsize(CHAR_PATH[ev].format(d=d)) for d in ds]


def main():
    rows, tot = [], dict(calls=0, in_tok=0, out_tok=0, cost=0.0)
    for ev in ELIGIBLE:
        chars = doc_chars(ev)
        n = len(chars)
        e_in = sum(ch * 0.75 + 400 for ch in chars)
        j_in = n * 900 * 0.75 + 400
        sink_in = 2500 * 0.75 + 400
        per_exec_in = e_in + j_in + sink_in
        per_exec_out = (n + 2) * 600
        calls = 4 * (n + 2)
        in_tok = 4 * per_exec_in
        out_tok = 4 * per_exec_out
        cost = in_tok * 0.8e-6 + out_tok * 2.8e-6
        rows.append(dict(task=ev, docs=n, doc_chars=chars, calls=calls,
                         in_tokens=int(in_tok), out_tokens=int(out_tok),
                         cost_yuan=round(cost, 4)))
        tot['calls'] += calls; tot['in_tok'] += in_tok; tot['out_tok'] += out_tok; tot['cost'] += cost
    for r in rows:
        print(f"{r['task']:12s} docs={r['docs']} calls={r['calls']:3d} in={r['in_tokens']:8d} "
              f"out={r['out_tokens']:6d} ¥{r['cost_yuan']:.4f}  chars={r['doc_chars']}")
    print(f"\nTOTAL calls={tot['calls']} (cap 1150) in={int(tot['in_tok'])} out={int(tot['out_tok'])} "
          f"tokens={int(tot['in_tok'] + tot['out_tok'])} (cap 2,300,000) cost=¥{tot['cost']:.2f} (cap ¥4)")
    json.dump(dict(batch='PHASE_V23A_S2_BUDGET', rows=rows,
                   total=dict(calls=tot['calls'], in_tokens=int(tot['in_tok']),
                              out_tokens=int(tot['out_tok']),
                              tokens=int(tot['in_tok'] + tot['out_tok']),
                              cost_yuan=round(tot['cost'], 4)),
                   caps=dict(calls=1150, tokens=2_300_000, yuan=4.0),
                   token_model='chars*0.75+400 (E), join/sink from measured V2 averages',
                   cost_model='in*0.8e-6 + out*2.8e-6 yuan (GLM flash accounting)'),
              open('/root/research_outputs/static_pi/stage_d/v23a/S2_BUDGET.json', 'w'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
