"""Deterministic program semantics for facts_merge.v1 (zero LLM calls).

Merge N facts-typed retrieval outputs into one doc_extracts value:
- every item keeps provenance: source_node, doc_id, public_date (when present);
- identical items (same normalized fact text + doc) are deduplicated (keep first,
  record all origins);
- same fact_key with DIFFERENT values are BOTH kept and a conflict marker is
  attached — merged output is typed material for downstream VERIFICATION nodes,
  never a settled conclusion.
"""
import json
import re


def _norm(s):
    return re.sub(r'[\s,，。;；:：、"\'''"（）()\[\]【】]+', '', str(s))


def _key(item):
    for k in ('fact_key', 'key', 'topic', 'subject'):
        if isinstance(item, dict) and item.get(k):
            return _norm(item[k])
    return _norm(json.dumps(item, ensure_ascii=False, sort_keys=True))[:64]


def merge_facts(inputs, source_nodes):
    """inputs: list of facts lists (one per upstream extracts_f node, order = deps).
    source_nodes: corresponding node ids. Returns the merged doc_extracts value."""
    if not isinstance(inputs, list):
        inputs = [inputs]
    merged, index = [], {}
    for line, src in zip(inputs, source_nodes):
        for item in (line if isinstance(line, list) else [line]):
            if not isinstance(item, dict):
                item = {'value': item}
            entry = dict(item)
            provenance = {'source_node': src,
                          'doc_id': item.get('doc_id') or item.get('evidence_doc'),
                          'public_date': item.get('public_date')}
            k = _key(item)
            if k in index:
                first = index[k]
                if _norm(json.dumps(item.get('value', item), ensure_ascii=False)) == \
                        _norm(json.dumps(merged[first].get('value', merged[first]), ensure_ascii=False)):
                    merged[first].setdefault('origins', []).append(provenance)  # duplicate fact, same value
                    continue
                entry['conflict_with'] = first          # same key, different value: keep BOTH
                entry['conflict_marker'] = True
                merged[first]['conflict_marker'] = True
            else:
                index[k] = len(merged)
            entry.setdefault('origins', []).append(provenance)
            merged.append(entry)
    return merged


def merge_stats(merged):
    return {'items': len(merged),
            'conflict_marked': sum(1 for m in merged if m.get('conflict_marker')),
            'multi_origin': sum(1 for m in merged if len(m.get('origins', [])) > 1),
            'docs_touched': sorted({o.get('doc_id') for m in merged for o in m.get('origins', [])
                                    if o.get('doc_id')})}
