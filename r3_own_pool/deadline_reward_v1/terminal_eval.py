"""Terminal-only evaluation v3 (sink = no outgoing edges)."""
import re

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
            if part.startswith('d:') and len(part) >= 10:
                d = part[2:]
                if len(d) == 8:
                    yyyy, mm, dd = d[:4], d[4:6], d[6:]
                    for v in [f'{yyyy}年{int(mm)}月{int(dd)}日',
                              f'{yyyy}-{mm}-{dd}', d]:
                        if v in text: return True
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
