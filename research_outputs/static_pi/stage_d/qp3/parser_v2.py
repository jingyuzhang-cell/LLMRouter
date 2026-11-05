"""Fixed parser: recovers plain-string leaf values from nested dict outputs."""
import re

# Keys that are evidence metadata, never fact values
_EVIDENCE_KEYS = {'doc', 'page', 'quote', 'source', 'doc_id',
                  'page_sha256', 'raw_sha256', 'start', 'end'}
# Keys that are structural labels, never fact values
_STRUCTURAL_KEYS = {'type', 'aspect', 'page_size'}

# String values that are clearly not facts
_NON_FACT_STRINGS = {'json_object', 'json', 'object', 'array', 'string',
                     'number', 'boolean', 'null', 'unknown', 'UNKNOWN', 'N/A',
                     'none', ''}


def _is_fact_string(v):
    """A plain string that qualifies as a fact value."""
    return (isinstance(v, str) and v.strip()
            and v not in _NON_FACT_STRINGS and len(v.strip()) >= 2)


def _extract_from_evidence_dict(d, bucket, predicate):
    """Extract entry from a dict that has doc/page/quote metadata."""
    val = d.get('value')
    if val is None:
        # Look for a plain-string value under a non-metadata key
        for k, v in d.items():
            if k not in _EVIDENCE_KEYS and k not in _STRUCTURAL_KEYS \
                    and k not in ('field', 'fact_id', 'value', 'raw') \
                    and _is_fact_string(v):
                val = v
                break
    return dict(bucket=bucket, predicate=predicate,
                field=d.get('field') or d.get('fact_id') or predicate,
                value=val, raw=str(val) if val is not None else None,
                doc=d.get('doc'), page=d.get('page'),
                quote=d.get('quote', ''))


def normalize_stage_v2_string_values(obj):
    """Flatten stage output, recovering plain-string values in nested dicts."""
    out = []

    def walk(d, bucket, predicate):
        if not isinstance(d, dict):
            if isinstance(d, list):
                for item in d:
                    walk(item, bucket, predicate)
            elif _is_fact_string(d) and predicate:
                out.append(dict(bucket=bucket, predicate=predicate,
                               field=predicate, value=d, raw=d,
                               doc=None, page=None, quote=''))
            return

        has_evidence = any(k in d for k in _EVIDENCE_KEYS)

        if has_evidence:
            # Evidence entry: extract with explicit or string value
            out.append(_extract_from_evidence_dict(d, bucket, predicate))
            return

        # Non-evidence dict: iterate keys
        for k, v in d.items():
            if k in _EVIDENCE_KEYS or k in _STRUCTURAL_KEYS:
                continue
            if k in ('facts', 'answers'):
                # List of entries
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, dict):
                            walk(item, bucket or k, predicate)
                elif isinstance(v, dict):
                    walk(v, bucket or k, predicate)
            elif isinstance(v, str):
                # Plain string value under a non-metadata key → fact value
                if _is_fact_string(v):
                    out.append(dict(bucket=bucket, predicate=predicate or k,
                                   field=k, value=v, raw=v,
                                   doc=d.get('doc'), page=d.get('page'),
                                   quote=d.get('quote', '')))
            elif isinstance(v, dict):
                # Nested dict: check if it's an evidence entry or another level
                if any(m in v for m in _EVIDENCE_KEYS):
                    out.append(_extract_from_evidence_dict(
                        v, bucket or k, k))
                else:
                    walk(v, bucket or k, k)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        if any(m in item for m in _EVIDENCE_KEYS):
                            out.append(_extract_from_evidence_dict(
                                item, bucket or k, k))
                        else:
                            walk(item, bucket or k, k)
                    elif _is_fact_string(item):
                        out.append(dict(bucket=bucket or k, predicate=k,
                                       field=k, value=item, raw=item,
                                       doc=None, page=None, quote=''))

    walk(obj, None, None)
    return out
