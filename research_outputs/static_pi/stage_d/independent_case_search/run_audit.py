import json
import search_cases as S

log = json.loads((S.OUT / 'PREFILTER_LOG.json').read_text('utf-8'))
ranked = sorted(log['survivors'], key=lambda r: (-(len(r['adjusted']) > 0), -(r['notice_party_overlap'] >= 0.9),
                                                 -r['decision']['parties'], r['code']))
order = [r['code'] for r in ranked]
(S.OUT / 'AUDIT_ORDER.json').write_text(json.dumps(dict(rule='adjusted>0, notice overlap>=0.9, parties desc', order=order),
                                                   ensure_ascii=False, indent=1), 'utf-8')
print('audit order (first 16):', order[:16], flush=True)
S.audit_codes(order[:16])
