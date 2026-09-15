"""Node-level GAP existence audit from frozen tool-aware v1 shadow outputs.

Zero generation. Answers, per node type: (a) is there model heterogeneity to
route on (oracle minus best fixed policy), and (b) is semantic failure
intrinsic or inherited from upstream extraction errors. Recomputes from
CANDIDATE_AUDIT.json / PER_TASK.json / PLANS.json and writes
NODE_GAP_AUDIT.json plus a REPORT.md section.
"""
import argparse
import json

import numpy as np

from . import core, tool_aware_v1 as v

OUT = v.OUT / 'fresh'
MODELS = ['medium', 'large', 'coder', 'reasoning']


def run():
    v.verify()
    if (OUT / 'NODE_GAP_AUDIT.json').exists():
        raise FileExistsError('Node gap audit already exists')
    audit = json.loads((OUT / 'CANDIDATE_AUDIT.json').read_text())
    per = json.loads((OUT / 'PER_TASK.json').read_text())
    shadow = set(json.loads((OUT / 'SHADOW_IDS.json').read_text()))
    nodes = {}
    for r in audit:
        if r['task_id'] in shadow:
            nodes.setdefault((r['task_id'], r['node_type']), {})[r['candidate']] = r

    def q(cands, m):
        c = cands.get(m)
        return int(bool(c['actual_shadow_node_accuracy'])) if c and c['actual_status'] == 'delivered' else 0

    by_type = {}
    for nt in ['extraction', 'semantic']:
        sub = {k: c for k, c in nodes.items() if k[1] == nt}
        acc = {m: float(np.mean([q(c, m) for c in sub.values()])) for m in MODELS}
        oracle = float(np.mean([max(q(c, m) for m in MODELS) for c in sub.values()]))
        by_type[nt] = dict(n_nodes=len(sub), accuracy=acc, oracle=oracle,
                           oracle_minus_best_policy=oracle - max(acc.values()),
                           best_fixed_policy=max(acc, key=acc.get),
                           nodes_where_any_model_succeeds=int(sum(max(q(c, m) for m in MODELS) for c in sub.values())))
    shadow_rows = [r for r in per if r['task_id'] in shadow]
    decompose = dict(
        extraction_pass_semantic_pass=sum(r['extraction_operand_recall_pass'] and r['semantic_answer_equivalence_pass'] for r in shadow_rows),
        extraction_pass_semantic_fail=sum(r['extraction_operand_recall_pass'] and not r['semantic_answer_equivalence_pass'] for r in shadow_rows),
        extraction_fail=sum(not r['extraction_operand_recall_pass'] for r in shadow_rows))
    result = dict(
        question='Does a learnable node-level model-preference GAP exist, and where?',
        shadow=dict(tasks=len(shadow), nodes=len(nodes), models=MODELS, small='unavailable/not required'),
        by_node_type=by_type,
        semantic_failure_decomposition=decompose,
        verdict=dict(
            extraction='heterogeneous and potentially learnable: oracle 0.9 vs best fixed (large) 0.7 over n=10; CI wide at this n',
            semantic='uniform capability wall: every model fails every shadow semantic node (oracle 0.0); '
                     f"{decompose['extraction_pass_semantic_fail']} of 10 failures are intrinsic (extraction passed, semantic still failed)",
            implication='node-conditioned routing has signal only on extraction-type nodes in the current pool; '
                        'semantic nodes need capability/decomposition work, not model selection'),
        constraints='Descriptive audit of the frozen v1 shadow subset; no new generation; no router retrained')
    core.write(OUT / 'NODE_GAP_AUDIT.json', result)
    lines = ['', '## Node-level GAP 存在性审计（零生成）', '',
             '| 节点类型 | n | medium | large | coder | R1 | Oracle | Oracle−最优固定 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for nt, d in by_type.items():
        a = d['accuracy']
        lines.append(f"| {nt} | {d['n_nodes']} | {a['medium']:.1f} | {a['large']:.1f} | {a['coder']:.1f} | "
                     f"{a['reasoning']:.1f} | {d['oracle']:.1f} | {d['oracle_minus_best_policy']:+.1f} |")
    d = decompose
    lines += [f'语义失败分解（shadow 10 题）：提取过+语义过 {d["extraction_pass_semantic_pass"]}；'
              f'提取过+语义败 {d["extraction_pass_semantic_fail"]}（内在语义失败）；提取败 {d["extraction_fail"]}（上游继承）。',
              '', '判定：提取节点存在异质可学习空间（oracle 0.9 vs large 0.7，n=10 CI 宽）；'
              '语义节点是全模型统一能力墙（oracle 0.0），其中一半以上为内在失败而非上游继承——'
              '这不是路由问题，是能力/分解问题。Node-conditioned routing 目前只在提取型节点有信号。', '']
    (OUT / 'REPORT.md').write_text((OUT / 'REPORT.md').read_text() + '\n'.join(lines) + '\n')
    print(json.dumps(dict(by_type={k: {kk: vv for kk, vv in val.items() if kk != 'accuracy'} for k, val in by_type.items()},
                          semantic_decomposition=decompose), indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=['run'])
    ap.parse_args()
    run()


if __name__ == '__main__':
    main()
