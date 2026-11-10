#!/usr/bin/env python3
"""Shared P2-C Gold contract builder core (extracted unchanged from build_contracts_batch3.py).

Same schema / verbatim self-check as batches 2-3. Semantics per operator batch-2 ruling:
  - party absent from D2  -> "D2未再载明对应处罚" (not "撤销", never 0)
  - D2 silent on market ban -> final ban UNKNOWN (not "未采取")
  - no explicit receipt date -> UNKNOWN or an explicitly-named disclosure-date slot
  - D1 wording that does not fix a per-person amount -> UNKNOWN, never back-filled from D2
"""
import hashlib, json, re, sys, unicodedata
from pathlib import Path

RAW = Path('/root/research_outputs/static_pi/stage_d/independent_case_search/raw')
OUT = Path('/root/KDX_GOLD_HUMAN_ANNOTATION_PACKAGE/evidence/P2_PILOT')
NOT_RESTATED = 'D2未再载明对应处罚（D2全文未出现且未作说明；不认定为法律意义上的撤销，终罚不计为0）'
BAN_UNKNOWN = 'D2为《行政处罚决定书》公告，未载市场禁入决定；池内无单独市场禁入决定书，终局是否采取无法由D1/D2确认'

def norm(s): return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(s)))


class Task:
    def __init__(self, d1f, d2f):
        self.d1f, self.d2f = d1f, d2f
        self.D = {'D1': (RAW / d1f).read_text('utf-8'), 'D2': (RAW / d2f).read_text('utf-8')}
        self.N = {k: norm(v) for k, v in self.D.items()}
        self.M = {k: json.loads((RAW / f.replace('.txt', '.meta.json')).read_text())
                  for k, f in (('D1', d1f), ('D2', d2f))}
        self.F, self.unknown = [], []

    def ev(self, doc, quote):
        if norm(quote) not in self.N[doc]:
            raise ValueError(f'NOT VERBATIM in {doc} ({self.d1f if doc=="D1" else self.d2f}): {quote[:70]}')
        return [dict(doc_id=doc, page=1, quote=quote, pdf_sha256=self.M[doc]['sha256'])]

    def add(self, fid, subj, pred, val, kind, crit, docs, rule, sa, pa, quotes, unit=None, **kw):
        f = dict(fact_id=fid, status='GOLD_DRAFT', gold_provenance='rule_from_source_text',
                 critical=crit, evidence_required=True, value_kind=kind, subject=subj, predicate=pred,
                 value=val, allowed_citation_docs=docs, source_evidence=quotes,
                 grounding=dict(rule=rule, subject_anchor=sa, predicate_anchor=pa))
        if unit: f['unit'] = unit
        for k in ('derivation', 'dual_stage'):
            if k in kw: f[k] = kw[k]
        self.F.append(f)

    def spans(self, doc, quotes):
        return [e for q in quotes for e in self.ev(doc, q)]

    def patch(self, fid, value=None, evidence=None, deriv=None):
        f = next(x for x in self.F if x['fact_id'] == fid)
        if value is not None: f['value'] = value
        if evidence is not None: f['source_evidence'] = evidence
        if deriv: f.setdefault('derivation', {}).update(deriv)

    def add_unknown(self, fid, subj, pred, kind, docs, rule, quotes, reason):
        self.add(fid, subj, pred, None, kind, False, docs, rule, None, None, quotes)
        self.F[-1]['status'] = 'GOLD_DRAFT_UNKNOWN'
        self.unknown.append(dict(fact_id=fid, reason=reason))

    def write(self, name, task_id, positioning, question, cutoff, d1_title, d2_title,
              corr, known_issues, totals_check, source_nature=None):
        n_scored = sum(1 for f in self.F if f['status'] != 'GOLD_DRAFT_UNKNOWN')
        c = dict(
            task_id=task_id, contract_version='v1-draft', status='DRAFT_PENDING_OPERATOR_REVIEW',
            positioning=positioning, question=question, cutoff=cutoff,
            source_documents={k: dict(title=t, url=self.M[k]['url'], retrieved_at=self.M[k]['retrieved_at'],
                                      pdf_sha256=self.M[k]['sha256'])
                              for k, t in (('D1', d1_title), ('D2', d2_title))},
            source_pages={k: dict(raw_sha256=self.M[k]['sha256'],
                                  pages={'1': dict(text=self.D[k], page_sha256=hashlib.sha256(self.D[k].encode()).hexdigest())})
                          for k in ('D1', 'D2')},
            required_facts=self.F,
            critical_fact_ids=[f['fact_id'] for f in self.F if f.get('critical') and f['status'] != 'GOLD_DRAFT_UNKNOWN'],
            unknown_items=self.unknown,
            entity_correspondence=corr,
            scoring=dict(primary=f'Q_all = TP / N (N={n_scored}' + (', excluding UNKNOWN)' if self.unknown else ')'),
                         safety='error_rate (None when nothing asserted)',
                         auxiliary=['Q_terminal', 'E_literal'], scorer='qs_scorer.py pattern'),
            provenance=dict(nature='两份公告 PDF', model_calls=0, independence='DAG-line independent'),
            known_issues=known_issues,
        )
        if source_nature is not None:
            c['source_nature'] = source_nature
        if getattr(self, 'revision', None):
            c['contract_version'] = 'v1-draft-r1'
            c['revision_log'] = self.revision
        out = OUT / f'TASK_CONTRACT_{name}_v1_DRAFT.json'
        out.write_text(json.dumps(c, ensure_ascii=False, indent=1) + '\n', 'utf-8')
        bad = [(f['fact_id'], e['doc_id']) for f in self.F for e in f['source_evidence']
               if norm(e['quote']) not in self.N[e['doc_id']]]
        print(f'{name}: slots={len(self.F)} critical={len(c["critical_fact_ids"])} unknown={len(self.unknown)} '
              f'N={n_scored} verbatim={"OK" if not bad else bad} totals={"OK" if totals_check else "MISMATCH"} '
              f'sha256={hashlib.sha256(out.read_bytes()).hexdigest()}')
        return not bad and totals_check


