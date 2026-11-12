"""Render every T1 request for review (zero calls). Inputs: frozen Stage A' ledger (Static arm) and reused E outputs."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SC = HERE.parent
sys.path[:0] = [str(SC), str(SC.parent)]
import sc_e1_scorer as S  # noqa: E402
import sc_e1_1_runner as R  # noqa: E402
import sc_e1_1_stage_a2 as A2  # noqa: E402
import sc_e1_runner as OLD  # noqa: E402
import detectors_v2 as D  # noqa: E402

A2_HEADER = ('复核要求：下列槽位在上一次核验中被标为无法核验，但程序已逐字核对的证据表中存在可能相关的原文句子。'
             '请对照所列原文逐一重新核验：原文能支持的，给出 status 与 final_value；原文确实不能支持的，保留无法核验。'
             '其余槽位按原要求核验。')
A2_ITEM = '- {fact_id}（{subject}{predicate}）候选原文：{rows}'
A2_ROW = '[{row}|{doc}] {quote}'
BASE_LINE = ('确定性派生值（由程序根据决定书抽取结果计算，不由模型计算）：{fact_id} {subject}{predicate} = {value}'
             '（纳入规则：决定书抽取中带罚款金额的不同当事人逐一相加，共 {parties} 名）')
H_HEADER = ('终端校验反馈：下列答案的取值无法从其所引原文中读出，或所引原文不在证据表中。'
            '请改为引用证据表中能直接读出该值的原文；证据表中没有这样的原文时，将该槽位写入 unknown_slots。')
H_ITEM = '- {fact_id}（{subject}{predicate}）：原答案 {value}；原因：{reason}'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def main():
    ct = S.load_contract()
    docs, slots_json = R.load_task(ct)
    slots = json.loads(slots_json)
    e = A2.load_reused_e(SC / 'canary_A', docs)
    rows, _ = R.evidence_rows(e, S.doc_index(ct))
    done = [r for r in R.read_ledger(SC / 'canary_A2/LEDGER.jsonl') if r['phase'] == 'done' and r['arm'] == 'Static']
    j1 = next(r for r in done if r['node'] == 'J1')['text']
    j2 = next(r for r in done if r['node'] == 'J2')['text']
    j2_obj = OLD.extract_json(j2)
    base = D.deterministic_total(OLD.extract_json(e['E_D2']))
    derived = [s for s in slots if D.slot_type(s) == 'derived']
    base_lines = '\n'.join(BASE_LINE.format(fact_id=s['fact_id'], subject=s['subject'], predicate=s['predicate'], value=base['value'],
                                            parties=base['parties']) for s in derived if s['fact_id'] == 'F19')

    m1 = D.detect_m1(slots, j2_obj, rows)
    flagged = [f for f, v in m1.items() if v['state'] == 'EXPLICIT_SUPPRESSION']
    by_row = {r['row']: r for r in rows}
    items = []
    for s in slots:
        if s['fact_id'] in flagged:
            cand = '；'.join(A2_ROW.format(row=r, doc=by_row[r]['doc'], quote=by_row[r]['quote']) for r in m1[s['fact_id']]['candidate_rows'])
            items.append(A2_ITEM.format(fact_id=s['fact_id'], subject=s['subject'], predicate=s['predicate'], rows=cand))
    addendum = A2_HEADER + '\n' + '\n'.join(items)

    j2_plain = R.j2_user(j1, slots_json)
    j2_targeted = j2_plain + '\n\n' + addendum
    keep = [v for v in j2_obj.get('verified') or [] if not (isinstance(v, dict) and v.get('fact_id') in flagged)]
    j2_bypass_text = json.dumps(dict(j2_obj, verified=keep), ensure_ascii=False)

    def sink_user(j2_text):
        return f'核验结果：\n{j2_text}\n\n{R.evidence_block(rows)}\n\n{base_lines}\n\n槽位：{slots_json}'

    requests = {
        'A0_SINK': sink_user(j2),
        'A1_J2_blind': j2_plain,
        'A2_J2_targeted': j2_targeted,
        'A3_SINK_bypass': sink_user(j2_bypass_text),
    }
    out = {}
    for name, user in requests.items():
        (HERE / f'{name}.user.txt').write_text(user, 'utf-8')
        out[name] = dict(chars=len(user), sha256=sha(user), est_input_tokens=int(len(user) * 0.6))
    (HERE / 'A2_addendum.txt').write_text(addendum, 'utf-8')
    (HERE / 'base_total_line.txt').write_text(base_lines, 'utf-8')
    meta = dict(flagged_slots=flagged, candidate_rows={f: m1[f]['candidate_rows'] for f in flagged}, base_total=base,
                requests=out, addendum_chars=len(addendum), templates=dict(A2_HEADER=A2_HEADER, A2_ITEM=A2_ITEM, A2_ROW=A2_ROW,
                BASE_LINE=BASE_LINE, H_HEADER=H_HEADER, H_ITEM=H_ITEM),
                note='A1 and A2 SINK requests are built after their J2 call returns; they follow the A0 template with the new J2 text.')
    (HERE / 'RENDER_META.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), 'utf-8')
    print(json.dumps(dict(flagged=flagged, base=base['value'], requests=out, addendum_chars=len(addendum)), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
