#!/usr/bin/env python3
"""MERGE_VIS: minimal paired merge experiment at FULL input visibility.

Grounding (zero-call, 12 natural execs): merge output >= visible@3000 ceiling in
12/12 (set-equal in 8/12) -> the frozen [:3000] merge-input cap, not model
compression, causes the merge-stage loss. Under the frozen cap a fidelity
contract is untestable (merge already ~100% faithful to what it sees).

Design (6 stored extract sets; NO new extract calls):
  both arms: namespaced extract fids (symmetric), FULL merge/verify/report input
             (caps lifted symmetrically), mt=8000 (symmetric; avoids the output
             truncation that sank RQ2_P2R_V2)
  A_full : original merge prompt (byte-identical text)
  B_full : fidelity-contract merge + fid-keyed backfill of value/doc/quote
  downstream both: frozen verify prompt -> frozen B_fidelity report contract
No retries. Parse failures are recorded as failures.
"""
import os, sys, json, time, argparse
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from rq2_p2r_v3_runner import D2_CONTRACT
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, ALLOC, _call, get_docs, merge_prompt, verify_prompt
from tfjs_runner import FIDELITY_REPORT_USER, fid_backfill

MT = 8000
FIDELITY_MERGE_USER = (
    "合并以下多份文档的事实。规则：逐条原样保留每条事实的 fid/value/doc/quote，"
    "不得改写金额、日期、主体与证据原文；不得删除有效事实；完全重复的事实可以去重，"
    "但须在 sources 字段保留全部来源 fid；相互冲突的事实全部保留并在 conflict_with "
    "字段标注，不得取舍；可增加 summary 字段，但不得替代原始事实记录。\n\n"
    "{facts}\n\n按系统格式输出 JSON。")


def stored_extract_sets():
    """6 stored extract sets with branch-namespaced fids (symmetric for both arms)."""
    sets = []
    g2 = [json.loads(l) for l in open(HERE / 'tfjs_runs/outputs.jsonl')]
    for rep in (1, 2, 3):
        recs = sorted([o for o in g2 if o.get('group') == 'G2' and o['arm'] == 'shared'
                       and o.get('unit') == f'r{rep}' and o['node'].startswith('ext_')],
                      key=lambda o: o['node'])
        sets.append((f'G2_r{rep}', recs))
    v2 = [json.loads(l) for l in open(HERE / 'rq_dajf2_runs/outputs.jsonl')]
    for rep in (1, 2, 3):
        recs = sorted([o for o in v2 if o['strategy'] == 'DA-JS-v2'
                       and o['condition'] == 'natural' and o['rep'] == rep
                       and o['node'].startswith('ext_')], key=lambda o: o['node'])
        sets.append((f'V2nat_r{rep}', recs))
    out = []
    for name, recs in sets:
        facts = []
        for o in recs:
            for x in parse_facts(o['raw_output'])[1]:
                if isinstance(x, dict):
                    facts.append({'fid': f"{o['node']}::{x.get('fid', '')}",
                                  'value': x.get('value', ''), 'doc': x.get('doc', ''),
                                  'quote': x.get('quote', '')})
        out.append((name, facts))
    return out


class MV:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'

    def call(self, unit, arm, node, model, sys_, user):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), MT)
        t0 = time.time()
        if self.real:
            r = _call(model, sys_, user, MT)
            text, tin, tout, stop, lat = r['text'], r['in'], r['out'], r['stop'], r['lat']
        else:
            text, tin, tout, stop, lat = '{"facts":[]}', len(user), 8, 'end_turn', 0.0
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, arm=arm, node=node, model=model, tin=tin,
                   tout=tout, yuan=est, stop=stop, lat=lat)
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text

    def save_final(self, unit, arm, node, facts):
        with open(self.outputs, 'a') as f:
            f.write(json.dumps(dict(ts=time.time(), unit=unit, arm=arm, node=node,
                                    model='na', tin=0, tout=0, yuan=0, stop='na', lat=0,
                                    raw_output=json.dumps(facts, ensure_ascii=False)),
                               ensure_ascii=False) + '\n')

    def run_unit(self, name, facts, docs_text, arms=('A_full', 'B_full')):
        for arm in arms:
            eid = f"MV|{name}|{arm}"
            if self.store.completed(eid):
                continue
            self.store.begin(eid)
            t0 = time.time()
            fj = json.dumps(facts, ensure_ascii=False)          # FULL visibility
            user = merge_prompt(fj) if arm == 'A_full' else FIDELITY_MERGE_USER.format(facts=fj)
            mt_text = self.call(name, arm, 'merge', ALLOC['reason'],
                                SYS_COMMON + D2_CONTRACT, user)
            ok, mo, _ = parse_facts(mt_text)
            mo = [x for x in mo if isinstance(x, dict)]
            if arm == 'B_full':
                mo = fid_backfill(mo, facts)
            self.save_final(name, arm, 'merge_final', mo)
            vt = self.call(name, arm, 'verify', ALLOC['verification'], SYS_COMMON + D2_CONTRACT,
                           verify_prompt(json.dumps(mo, ensure_ascii=False), docs_text))
            vs = {str(v.get('fid', '')): v.get('status', 'unverified')
                  for v in parse_facts(vt)[1] if isinstance(v, dict)}
            combined = [{**f, 'verify_status': vs.get(str(f.get('fid', '')), 'unverified')}
                        for f in mo]
            rt = self.call(name, arm, 'report', ALLOC['report'], SYS_COMMON + D2_CONTRACT,
                           FIDELITY_REPORT_USER.format(
                               combined=json.dumps(combined, ensure_ascii=False)))
            rf = fid_backfill([x for x in parse_facts(rt)[1] if isinstance(x, dict)], combined)
            self.save_final(name, arm, 'report_final', rf)
            self.store.commit(dict(exec_id=eid, unit=name, arm=arm, merge_parse_ok=bool(ok),
                                   n_input=len(facts), n_merge=len(mo), n_report=len(rf),
                                   span_s=round(time.time() - t0, 1),
                                   budget_left=self.gb.left()))
            print(f'  {eid} merge={len(mo)} report={len(rf)} left={self.gb.left()["calls_left"]}')

    def run(self, arms):
        docs_text = '\n\n'.join(f'[{d}]\n{t[:800]}' for d, t in get_docs().items())
        for name, facts in stored_extract_sets():
            self.run_unit(name, facts, docs_text, arms)
        print(f'MERGE_VIS DONE arms={arms} budget={self.gb.left()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'merge_vis_config.json'))
    ap.add_argument('--out', default=str(HERE / 'merge_vis_runs'))
    ap.add_argument('--real', action='store_true')
    ap.add_argument('--check', action='store_true', help='zero-call prompt construction check')
    ap.add_argument('--arms', default='A_full,B_full',
                    help='comma-separated arms to run, e.g. A_full (operator option ii)')
    a = ap.parse_args()
    if a.check:
        for name, facts in stored_extract_sets():
            fj = json.dumps(facts, ensure_ascii=False)
            print(f'{name}: n_facts={len(facts)} uniq_fids={len({f["fid"] for f in facts})} '
                  f'A_prompt_chars={len(merge_prompt(fj))} '
                  f'B_prompt_chars={len(FIDELITY_MERGE_USER.format(facts=fj))}')
        return
    cfg = json.load(open(a.config))
    if a.real:
        if os.environ.get('STAGE_D_REAL_CALLS_AUTHORIZED') != '1':
            raise SystemExit('REFUSED')
        for k in ('DEEPSEEK_API_KEY', 'QWEN_API_KEY'):
            if not os.environ.get(k, '').strip():
                os.environ[k] = [l.split('=', 1)[1].strip()
                                 for l in open('/root/.env') if l.startswith(k + '=')][0]
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        raise SystemExit('use --check (zero-call) or --real (authorized)')
    MV(cfg, a.out, a.real).run(tuple(a.arms.split(',')))


if __name__ == '__main__':
    main()
