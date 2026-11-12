#!/usr/bin/env python3
"""QCL_TABLE_V3: terminal-Q action-gain measurement on UB-1 (authorized batch).

UB-1: extract(DS x3, cached for E04) -> deterministic store/merge (0 calls) ->
slim verify (qwen, fid-annotation) -> report (qwen, organize contract, quotes
code-attached). Cells (paired on shared extracts/store/verify):
  NONE | R/pi fault cells (report-node, transient+persistent) | E (targeted
  deficient-branch reroll, frozen rule n_facts<10 or provenance<0.8) |
  Zx (per-doc midpoint segment-split extract, 6 calls) | E+Zx joint.
No retries. Hard caps via GlobalBudget. Q_terminal scored post-hoc (zero calls).
"""
import os, sys, json, time, re, argparse
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from rq2_p2r_runner import SYS_COMMON, parse_facts
from stage_d_executor import GlobalBudget, RunStore
from rq_dajf_runner import YUAN, _call, truncate
from merge_vis_runner import stored_extract_sets
from tfjs_runner import FIDELITY_REPORT_USER, fid_backfill

E04_DOCS = {'doc1': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20260910.txt',
            'doc2': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261009.txt',
            'doc3': '/root/cap_eval_bench_v1/evidence/texts/E04-zhuoran_20261013.txt'}
E03_DOCS = {'D1': '/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence/D1_E03-yuandao_2026-05-08.txt',
            'D2': '/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence/D2_E03-yuandao_2026-08-29.txt',
            'D3': '/root/capital_opinion_pilot/VAL_GOLD_ANNOTATION_PACKAGE/evidence/D3_E03-yuandao_2026-08-29.txt'}
ALL_DOCS = {**{d: open(p, encoding='utf-8').read() for d, p in E04_DOCS.items()},
            **{d: open(p, encoding='utf-8').read() for d, p in E03_DOCS.items()}}
NORM_DOCS = {d: re.sub(r'[\s,，、；;：:]+', '', t) for d, t in ALL_DOCS.items()}
MT = 8000
DEF_N, DEF_ES = 10, 0.8   # frozen branch-deficiency thresholds


def norm(s):
    return re.sub(r'[\s,，、；;：:]+', '', str(s))


def extract_prompt(di, dt):
    return f"从该文档中提取各类事实（日期/金额/主体/违法/处罚/风险），每条含fid、value、doc、quote。\n\n文档 [{di}]:\n{dt}\n\n按系统格式输出 JSON。"


def resolve_doc(f):
    """Corrected doc resolution: locate the quote across ALL docs (extract models
    sometimes echo a generic doc id, e.g. E03 outputs labeled 'doc1')."""
    q = norm(f.get('quote', ''))
    if len(q) >= 6:
        for d, t in NORM_DOCS.items():
            if q in t:
                return d
    return None


def provenance(f):
    d, q = str(f.get('doc', '')), norm(f.get('quote', ''))
    if d in NORM_DOCS and len(q) >= 6 and q in NORM_DOCS[d]:
        return True
    return resolve_doc(f) is not None


def branch_metrics(facts):
    """{branch: (n_facts, prov_rate)} + deficiency flags (frozen rule)."""
    by = {}
    for f in facts:
        by.setdefault(str(f['fid']).split('::')[0], []).append(f)
    out = {}
    for b, fs in by.items():
        pr = sum(1 for f in fs if provenance(f)) / max(len(fs), 1)
        out[b] = dict(n=len(fs), prov=round(pr, 3), deficient=bool(len(fs) < DEF_N or pr < DEF_ES))
    return out


def det_merge(facts):
    """UB-1 deterministic merge: dedup (norm(value),doc), sort, keep all else."""
    seen, u = set(), []
    for f in sorted(facts, key=lambda x: (str(x.get('doc', '')), str(x.get('fid', '')))):
        k = (norm(f.get('value', '')), f.get('doc', ''))
        if k in seen:
            continue
        seen.add(k)
        u.append(f)
    return u


class QCL:
    def __init__(self, cfg, out, real):
        self.real = real
        self.out = Path(out)
        st = self.out / 'state'
        st.mkdir(parents=True, exist_ok=True)
        self.gb = GlobalBudget(cfg['calls'], cfg['yuan'], cfg.get('tokens'), st)
        self.store = RunStore(st, self.out)
        self.ledger = self.out / 'ledger.jsonl'
        self.outputs = self.out / 'outputs.jsonl'

    def call(self, unit, cell, node, model, sys_, user, inject=False):
        est = YUAN[model]
        self.gb.reserve_call(est)
        need = self.gb.reserve_tokens(min(len(user), 12000), MT)
        t0 = time.time()
        if self.real:
            r = None
            for attempt, delay in enumerate((0, 20, 45), 1):
                if delay:
                    time.sleep(delay)
                try:
                    r = _call(model, sys_, user, MT)
                    break
                except Exception as e:
                    print(f'    [transport retry {attempt}] {type(e).__name__}: {e}', flush=True)
                    if attempt == 3:
                        raise
            text, tin, tout, lat = r['text'], r['in'], r['out'], r['lat']
            if inject:
                text = truncate(text)
        else:
            text = '{"facts":[{"fid":"b::f1","value":"v","doc":"doc1","quote":"q"}]}'
            if inject:
                text = truncate(text)
            tin, tout, lat = len(user), 64, 0.01
        self.gb.release_reservation(need, tin, tout)
        self.gb.settle(est, 0, 0)
        rec = dict(ts=time.time(), unit=unit, cell=cell, node=node, model=model,
                   tin=tin, tout=tout, yuan=est, lat=lat, injected=inject)
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.outputs, 'a') as f:
            f.write(json.dumps({**rec, 'raw_output': text}, ensure_ascii=False) + '\n')
        return text, lat

    def verify_slim(self, unit, cell, facts):
        slim = json.dumps([{'fid': f['fid'], 'value': f.get('value', ''), 'doc': f.get('doc', '')}
                           for f in facts], ensure_ascii=False, separators=(',', ':'))
        docs_text = '\n\n'.join(f'[{d}]\n{t[:900]}' for d, t in ALL_DOCS.items())
        user = ("逐条核验以下事实是否与文档内容一致。按 fid 输出核验状态，不得改写事实。\n\n"
                f"事实：\n{slim}\n\n文档：\n{docs_text[:3000]}\n\n"
                '输出 JSON：{"facts":[{"fid":"...","status":"verified|unverified|conflict"}]}')
        t, lat = self.call(unit, cell, 'verify', 'qwen', SYS_COMMON, user)
        _, vf, _ = parse_facts(t)
        return {str(v.get('fid', '')): v.get('status', 'unverified')
                for v in vf if isinstance(v, dict)}, lat

    def report(self, unit, cell, facts, vs, model='qwen', inject=False):
        combined = [{**f, 'verify_status': vs.get(str(f['fid']), 'unverified')} for f in facts]
        user = FIDELITY_REPORT_USER.format(
            combined=json.dumps(combined, ensure_ascii=False)[:6000])
        t, lat = self.call(unit, cell, 'report', model, SYS_COMMON, user, inject=inject)
        _, rf, _ = parse_facts(t)
        rf = [x for x in rf if isinstance(x, dict)]
        rf = fid_backfill(rf, combined)
        with open(self.outputs, 'a') as f:
            f.write(json.dumps(dict(ts=time.time(), unit=unit, cell=cell,
                                    node='report_final', model=model, tin=0, tout=0,
                                    yuan=0, lat=0, injected=False,
                                    raw_output=json.dumps(rf, ensure_ascii=False)),
                               ensure_ascii=False) + '\n')
        return rf, lat

    def base_unit(self, unit, facts, cell='NONE'):
        """Shared base: deterministic store -> verify -> report. Returns context."""
        eid = f"BASE|{unit}"
        if self.store.completed(eid):
            return None
        self.store.begin(eid)
        t0 = time.time()
        bm = branch_metrics(facts)
        store = det_merge(facts)
        vs, vlat = self.verify_slim(unit, cell, store)
        rf, rlat = self.report(unit, cell, store, vs)
        self.store.commit(dict(exec_id=eid, unit=unit, branches=bm, n_store=len(store),
                               n_report=len(rf), span_s=round(time.time() - t0, 1),
                               budget_left=self.gb.left()))
        return dict(unit=unit, facts=facts, bm=bm, store=store, vs=vs, base_report=rf)

    # ---- cells ----
    def cell_fault(self, ctx, fault):  # fault in ('transient','persistent')
        unit = ctx['unit']
        for arm in ('R', 'pi'):
            eid = f"FAULT|{unit}|{fault}|{arm}"
            if self.store.completed(eid):
                continue
            self.store.begin(eid)
            t0 = time.time()
            acts = []
            if arm == 'R':
                rf, _ = self.report(unit, f'FAULT-{fault}', ctx['store'], ctx['vs'],
                                    inject=(fault == 'persistent'))
                ok = bool(rf)
                acts.append(f"R:{'ok' if ok else 'fail'}")
            else:
                rf, _ = self.report(unit, f'FAULT-{fault}', ctx['store'], ctx['vs'],
                                    model='deepseek')
                acts.append('pi:ok' if rf else 'pi:fail')
            self.store.commit(dict(exec_id=eid, unit=unit, fault=fault, arm=arm,
                                   actions=acts, n_report=len(rf),
                                   span_s=round(time.time() - t0, 1)))

    def cell_e(self, ctx):
        unit = ctx['unit']
        flagged = [b for b, m in ctx['bm'].items() if m['deficient']]
        eid = f"E|{unit}"
        if self.store.completed(eid) or not flagged:
            return
        self.store.begin(eid)
        t0 = time.time()
        doc_of = {b: 'doc' + b.split('doc')[-1] if 'doc' in b else b for b in ctx['bm']}
        new_facts = [f for f in ctx['facts'] if str(f['fid']).split('::')[0] not in flagged]
        acts = [f'flagged:{flagged}']
        for b in flagged:
            di = doc_of[b]
            dt = ALL_DOCS[di]
            t, _ = self.call(unit, 'E', f'reextract_{b}', 'deepseek', SYS_COMMON,
                             extract_prompt(di, dt))
            _, f2, _ = parse_facts(t)
            f2 = [{'fid': f"{b}::reroll::{x.get('fid', '')}", 'value': x.get('value', ''),
                   'doc': x.get('doc', ''), 'quote': x.get('quote', '')}
                  for x in f2 if isinstance(x, dict)]
            new_facts += f2
            acts.append(f'reroll_{b}:n={len(f2)}')
        store2 = det_merge(new_facts)
        vs2, _ = self.verify_slim(unit, 'E', store2)
        rf, _ = self.report(unit, 'E', store2, vs2)
        bm2 = branch_metrics(new_facts)
        self.store.commit(dict(exec_id=eid, unit=unit, actions=acts, branches_before=ctx['bm'],
                               branches_after=bm2, n_store=len(store2), n_report=len(rf),
                               span_s=round(time.time() - t0, 1)))

    def cell_zx(self, unit, docs, gold_set='E04'):
        eid = f"ZX|{unit}"
        if self.store.completed(eid):
            return
        self.store.begin(eid)
        t0 = time.time()
        facts = []
        for di, dt in docs.items():
            mid = len(dt) // 2
            for si, seg in enumerate((dt[:mid], dt[mid:]), 1):
                t, _ = self.call(unit, 'ZX', f'ext_{di}_s{si}', 'deepseek', SYS_COMMON,
                                 extract_prompt(f'{di}_s{si}', seg))
                _, f2, _ = parse_facts(t)
                facts += [{'fid': f"{di}::s{si}::{x.get('fid', '')}",
                           'value': x.get('value', ''), 'doc': x.get('doc', ''),
                           'quote': x.get('quote', '')} for x in f2 if isinstance(x, dict)]
        store = det_merge(facts)
        vs, _ = self.verify_slim(unit, 'ZX', store)
        rf, _ = self.report(unit, 'ZX', store, vs)
        self.store.commit(dict(exec_id=eid, unit=unit, n_branches=6, n_store=len(store),
                               n_report=len(rf), span_s=round(time.time() - t0, 1)))

    def cell_ezx(self, ctx):
        unit = ctx['unit']
        flagged = [b for b, m in ctx['bm'].items() if m['deficient']]
        if not flagged:
            return
        b = flagged[0]
        eid = f"EZX|{unit}"
        if self.store.completed(eid):
            return
        self.store.begin(eid)
        t0 = time.time()
        di = 'doc' + b.split('doc')[-1] if 'doc' in b else b
        dt = ALL_DOCS[di]
        mid = len(dt) // 2
        new_facts = [f for f in ctx['facts'] if str(f['fid']).split('::')[0] != b]
        for si, seg in enumerate((dt[:mid], dt[mid:]), 1):
            t, _ = self.call(unit, 'EZX', f'ext_{di}_s{si}', 'deepseek', SYS_COMMON,
                             extract_prompt(f'{di}_s{si}', seg))
            _, f2, _ = parse_facts(t)
            new_facts += [{'fid': f"{b}::s{si}::{x.get('fid', '')}",
                           'value': x.get('value', ''), 'doc': x.get('doc', ''),
                           'quote': x.get('quote', '')} for x in f2 if isinstance(x, dict)]
        store2 = det_merge(new_facts)
        vs2, _ = self.verify_slim(unit, 'EZX', store2)
        rf, _ = self.report(unit, 'EZX', store2, vs2)
        self.store.commit(dict(exec_id=eid, unit=unit, branch=b, n_store=len(store2),
                               n_report=len(rf), span_s=round(time.time() - t0, 1)))

    def run(self):
        # E04: cached extracts
        e04 = stored_extract_sets()
        ctxs = []
        for name, facts in e04:
            c = self.base_unit(name, facts)
            ctxs.append(c or self._reload_ctx(name))
        # fault cells on first two E04 units
        for ctx, fault in ((ctxs[0], 'transient'), (ctxs[1], 'persistent')):
            self.cell_fault(ctx, fault)
        # E cells on units with flagged branches (contract: only flagged)
        n_e = 0
        for ctx in ctxs:
            if any(m['deficient'] for m in ctx['bm'].values()) and n_e < 3:
                self.cell_e(ctx)
                n_e += 1
        # Zx on two E04 units
        e04_docs = {d: ALL_DOCS[d] for d in E04_DOCS}
        for name in ('G2_r1', 'V2nat_r1'):
            self.cell_zx(name, e04_docs)
        # E+Zx joint on first flagged unit
        for ctx in ctxs:
            if any(m['deficient'] for m in ctx['bm'].values()):
                self.cell_ezx(ctx)
                break
        # additional fault cells + third Zx (reserve fill, per application priorities)
        by_unit = {c['unit']: c for c in ctxs}
        if 'V2nat_r1' in by_unit:
            self.cell_fault(by_unit['V2nat_r1'], 'transient')
        if 'V2nat_r2' in by_unit:
            self.cell_fault(by_unit['V2nat_r2'], 'persistent')
        e04_docs = {d: ALL_DOCS[d] for d in E04_DOCS}
        if self.gb.left()['calls_left'] >= 10:
            self.cell_zx('G2_r2', e04_docs)
        # E/ZX conditional on corrected flags, across ALL units incl new E03 reps
        for ctx in ctxs:
            if any(m['deficient'] for m in ctx['bm'].values()):
                self.cell_e(ctx)
                self.cell_ezx(ctx)
                break
        # E03: fresh base units (+E on flagged, corrected rule)
        for rep in (1, 2, 3, 4):
            unit = f'E03_r{rep}'
            eid = f"BASE|{unit}"
            if self.store.completed(eid):
                continue
            self.store.begin(eid)
            t0 = time.time()
            facts = []
            for di, dt in E03_DOCS.items():
                txt = open(dt, encoding='utf-8').read()
                t, _ = self.call(unit, 'NONE', f'ext_{di}', 'deepseek', SYS_COMMON,
                                 extract_prompt(di, txt))
                _, f2, _ = parse_facts(t)
                facts += [{'fid': f"{di}::{x.get('fid', '')}", 'value': x.get('value', ''),
                           'doc': x.get('doc', ''), 'quote': x.get('quote', '')}
                          for x in f2 if isinstance(x, dict)]
            bm = branch_metrics(facts)
            store = det_merge(facts)
            vs, _ = self.verify_slim(unit, 'NONE', store)
            rf, _ = self.report(unit, 'NONE', store, vs)
            self.store.commit(dict(exec_id=eid, unit=unit, branches=bm, n_store=len(store),
                                   n_report=len(rf), span_s=round(time.time() - t0, 1)))
            ctxs.append(dict(unit=unit, facts=facts, bm=bm, store=store, vs=vs,
                             base_report=rf))
        print(f'QCL_V3 DONE budget={self.gb.left()}')

    def _reload_ctx(self, unit):
        """Resume path: recompute from cached extracts + stored outputs."""
        d = json.loads((self.out / f"BASE__{unit}.json").read_text())
        facts = next((f for n, f in stored_extract_sets() if n == unit), [])
        store = det_merge(facts)
        outs = [json.loads(l) for l in open(self.outputs)]
        vs = {}
        for o in outs:
            if o.get('unit') == unit and o.get('node') == 'verify':
                _, vf, _ = parse_facts(o['raw_output'])
                vs = {str(v.get('fid', '')): v.get('status', 'unverified')
                      for v in vf if isinstance(v, dict)}
                break
        rf = []
        for o in outs:
            if o.get('unit') == unit and o.get('node') == 'report_final':
                rf = json.loads(o['raw_output'])
        return dict(unit=unit, facts=facts, bm=d['branches'], store=store, vs=vs,
                    base_report=rf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', default=str(HERE / 'qcl_v3_config.json'))
    ap.add_argument('--out', default=str(HERE / 'qcl_v3_runs'))
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
        print('REAL MODE', cfg['calls'], cfg['tokens'], cfg['yuan'])
    else:
        print('MOCK MODE')
    QCL(cfg, a.out, a.real).run()


if __name__ == '__main__':
    main()
