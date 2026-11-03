"""V2.2 (authorized run): untruncated single-strong-model baseline for the SAME
frozen Shuntian evidence/task/scorer as V2.1. Fixes the 448-cap truncation confound.
One call, max_tokens=768; truncation reported via stop_reason. Dedup-safe purpose.
"""
import json
import time

from pilot_common import PILOT_DIR, Meter
from execute_dag import TASK_QUESTION, evidence_pack
import scoring

CAPS = dict(max_calls=2, max_guaranteed_actual=4500)


def main():
    meter = Meter(ledger_path=PILOT_DIR / 'model_call_ledger_v22.jsonl', **CAPS)
    silver = scoring.load_silver()
    edates = scoring.load_evidence_dates()
    t0 = time.monotonic()
    rec, txt = meter.call(
        'glm53',
        '你是资本市场调查员。基于证据撰写不超过800字的完整调查报告：覆盖调查过程时间线、涉及主体、'
        '监管处罚结论、风险警示安排；每个关键结论标注证据doc_id；无法确认事项单独标注。',
        '调查任务：' + TASK_QUESTION + '\n\n证据原文摘录（逐字，截止2024-07-10，与此前轮次完全相同的冻结证据包）：\n'
        + evidence_pack(),
        max_tokens=768, purpose='v22_baseline_untruncated', timeout_s=90)
    wall = time.monotonic() - t0
    s = scoring.score_output(txt, silver, edates)
    s.update(scoring.score_unresolved_marking(txt))
    out = {
        'arm': 'single_strong_model_untruncated',
        'same_frozen_conditions_as': 'V2.1 baseline (evidence pack / task / silver scorer / cutoff 2024-07-10)',
        'Q': s['fact_coverage'], 'coverage_full/partial': f"{s['coverage_full']}/{s['coverage_partial']}",
        'covered_fact_ids': s['covered_fact_ids'],
        'citation_accuracy': s['citation_accuracy'], 'unverified_dates': s['unverified_dates'],
        'marks_unresolved': s['marks_unresolved'],
        'tokens': {'in': rec['usage']['input_tokens'], 'out': rec['usage']['output_tokens']},
        'truncated': rec['stop_reason'] == 'max_tokens', 'stop_reason': rec['stop_reason'],
        'report_chars': len(txt), 'wall_s': round(wall, 2),
        'price_cny': 'UNKNOWN (coding-plan subscription; tokens are the cost basis)',
        'budget': meter.summary(),
        'report': txt,
    }
    (PILOT_DIR / 'v22_baseline_result.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != 'report'}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
