"""Terminal-only evaluation v3 (sink = no outgoing edges).

2026-10-25 fix: the d: branch previously accepted ONLY zero-padded
8-digit compact keys — 年月日-form keys ('d:2021年7月28日') and
unpadded 7-digit keys ('d:2021728', the doc_atoms normalization
output) silently NEVER matched. This affected every prior run
SYMMETRICALLY across arms (keys identical per arm), so recorded
between-arm deltas stay directionally valid, but effective key counts
were reduced. _date_forms now accepts all three historical key forms.
"""
import re


def _date_forms(part):
    """All textual forms a d:-key value may legitimately match."""
    v = part[2:]
    forms = [v]
    m = re.fullmatch(r'(\d{4})年(\d{1,2})月(\d{1,2})日', v)
    if m:
        y, mo, dd = m.group(1), int(m.group(2)), int(m.group(3))
        forms += [f'{y}-{mo:02d}-{dd:02d}', f'{y}{mo:02d}{dd:02d}']
        return forms
    if re.fullmatch(r'\d{8}', v):
        y, mo, dd = v[:4], v[4:6], v[6:]
        forms += [f'{y}-{mo}-{dd}', f'{y}年{int(mo)}月{int(dd)}日']
    elif re.fullmatch(r'\d{7}', v):
        # unpadded YYYY|M|D concatenation (doc_atoms convention):
        # disambiguate 1- vs 2-digit month by calendar validity
        y, rest = v[:4], v[4:]
        for mlen in (1, 2):
            mo, dd = rest[:mlen], rest[mlen:]
            if mo and dd and 1 <= int(mo) <= 12 and 1 <= int(dd) <= 31:
                forms += [f'{y}-{int(mo):02d}-{int(dd):02d}',
                          f'{y}年{int(mo)}月{int(dd)}日',
                          f'{y}{int(mo):02d}{int(dd):02d}']
    return forms


def eval_terminal(outputs, edges, valid_keys):
    sinks = [n for n in outputs if not edges.get(n)]
    sink_text = ' '.join(str(outputs[s].get('answer', ''))
                        for s in sinks) if sinks else ''
    clean_sink = re.sub(r'\s+', '', sink_text)
    all_text = ' '.join(str(v.get('answer', ''))
                       for v in outputs.values())
    clean_all = re.sub(r'\s+', '', all_text)
    def check(text, key):
        for part in key.split('|'):
            if part.startswith('d:'):
                for v in _date_forms(part):
                    if v and v in text:
                        return True
            elif part.startswith('a:'):
                v = part[2:]
                t2 = text.replace(',', '')
                if v in text or v.replace(',', '') in t2:
                    return True
            elif part.startswith('p:'):
                if part[2:] in text: return True
            elif part.startswith('e:'):
                if part[2:] in text: return True
        return False
    t_hits = sum(1 for k in valid_keys if check(clean_sink, k))
    p_hits = sum(1 for k in valid_keys if check(clean_all, k))
    n = max(1, len(valid_keys))
    lost = [k for k in valid_keys
            if check(clean_all, k) and not check(clean_sink, k)]
    return dict(
        terminal_q=round(t_hits / n, 4), terminal_hits=t_hits,
        pipeline_q=round(p_hits / n, 4), pipeline_hits=p_hits,
        n_ref=len(valid_keys), sink_nodes=sinks,
        lost_in_synthesis=lost)
