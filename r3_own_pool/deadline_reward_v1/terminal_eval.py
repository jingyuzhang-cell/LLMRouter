"""Terminal-only evaluation: scores the DAG's SINK node output,
not the concatenation of all intermediate outputs.

Dual-metric:
  terminal_q: reference facts in SINK output only (MAIN metric)
  pipeline_q: reference facts in ANY node (diagnostic only)
"""
import re
from typing import Dict


def get_sink_output(outputs: Dict, edges: Dict) -> str:
    """Get the terminal (sink) node's answer text."""
    # find node with no outgoing edges
    sinks = [n for n in outputs
             if not any(n in vs for vs in edges.values())]
    if not sinks:
        return ''
    # if multiple sinks, concatenate (unusual but safe)
    return ' '.join(str(outputs[s].get('answer', ''))
                    for s in sinks)


def eval_terminal(outputs: Dict, edges: Dict,
                  valid_keys: list) -> dict:
    """Evaluate terminal quality using ONLY the sink node's output."""
    sink_text = get_sink_output(outputs, edges)
    clean_sink = re.sub(r'\s+', '', sink_text)

    # also compute pipeline-level for diagnostics
    all_text = ' '.join(str(v.get('answer', ''))
                        for v in outputs.values())
    clean_all = re.sub(r'\s+', '', all_text)

    def check_keys(clean_text):
        hits = 0
        for key in valid_keys:
            for part in key.split('|'):
                found = False
                if part.startswith('d:') and len(part) >= 10:
                    d = part[2:]
                    if len(d) == 8:
                        yyyy, mm, dd = d[:4], d[4:6], d[6:]
                        for v in [f'{yyyy}年{int(mm)}月{int(dd)}日',
                                  f'{yyyy}-{mm}-{dd}', d]:
                            if v in clean_text:
                                found = True
                                break
                elif part.startswith('a:'):
                    if (part[2:] in clean_text or
                            part[2:].replace(',', '') in clean_text):
                        found = True
                elif part.startswith('p:'):
                    if part[2:] in clean_text:
                        found = True
                if found:
                    hits += 1
                    break
        return hits

    t_hits = check_keys(clean_sink)
    p_hits = check_keys(clean_all)
    n = len(valid_keys) if valid_keys else 1

    return dict(
        terminal_q=round(t_hits / n, 4) if valid_keys else 0.0,
        terminal_hits=t_hits,
        pipeline_q=round(p_hits / n, 4) if valid_keys else 0.0,
        pipeline_hits=p_hits,
        n_ref=len(valid_keys),
        sink_text_head=sink_text[:100],
        # diagnostic: which facts are in pipeline but not terminal
        lost_in_synthesis=[
            k for k in valid_keys
            if check_keys_key(clean_all, k)
            and not check_keys_key(clean_sink, k)])
    return result


def check_keys_key(clean_text, key):
    for part in key.split('|'):
        if part.startswith('d:') and len(part) >= 10:
            d = part[2:]
            if len(d) == 8:
                yyyy, mm, dd = d[:4], d[4:6], d[6:]
                for v in [f'{yyyy}年{int(mm)}月{int(dd)}日',
                          f'{yyyy}-{mm}-{dd}', d]:
                    if v in clean_text:
                        return True
        elif part.startswith('a:'):
            if (part[2:] in clean_text or
                    part[2:].replace(',', '') in clean_text):
                return True
        elif part.startswith('p:'):
            if part[2:] in clean_text:
                return True
    return False
