"""Step-1 semantic re-scoring of 80 real responses (68 full80 + 12 pilot)
against OFFICIAL announcement documents only. Zero API calls.

Principles (operator directive 2026-10-26):
- Reference = official doc text (never model answers; dual-model agreement
  is NOT Gold). Items unverifiable against doc -> UNKNOWN (never wrong).
- Correctness, necessary-fact recall, schema compliance computed
  SEPARATELY; failures classified as format / content-unknown / omission.
- Legend-style outputs (E-id + entities table) resolved before grounding;
  legend-mediated items counted separately (scorer-artifact risk marker).
- TL6/ER6 (KDX) have no official doc in the pool -> semantic UNKNOWN,
  schema still scored; excluded from correctness aggregates.
- Per-item adjudication records preserved.
"""
import json, re, ast, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
from deadline_reward_v1.full_dag_tasks import load_docs
from deadline_reward_v1.full_dag_silver import doc_atoms

PILOT = Path('/root/capital_opinion_pilot')

def norm(s):
    return re.sub(r'[\s,，。；;：:()（）【】\[\]{}"\'\u3000]', '', str(s or ''))

def strip_fence(t):
    t = (t or '').strip()
    if t.startswith('```'):
        p = t.split('\n', 1)
        t = p[1].rsplit('```', 1)[0].strip() if len(p) == 2 else t
    return t

def load_obj(raw):
    t = strip_fence(raw)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}|\[.*\]', t, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            try:
                return ast.literal_eval(m.group(0))
            except Exception:
                return None

def get_items(obj, keys):
    if isinstance(obj, list):
        return obj if obj else None
    if isinstance(obj, dict):
        for k in keys:
            if isinstance(obj.get(k), list) and obj[k]:
                return obj[k]
        ls = [v for v in obj.values() if isinstance(v, list) and v]
        return max(ls, key=len) if ls else None
    return None

def date_forms(d):
    m = re.match(r'(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', str(d or ''))
    if not m:
        return [norm(d)] if d else []
    y, mo, dd = m.group(1), int(m.group(2)), int(m.group(3))
    return [f'{y}{mo:02d}{dd:02d}', f'{y}-{mo:02d}-{dd:02d}',
            f'{y}年{mo}月{dd}日']

def cjk4(s):
    s = str(s or '')
    return [s[i:i+n] for i in range(len(s)) for n in (4, 5, 6)
            if i + n <= len(s) and re.fullmatch(r'[\u4e00-\u9fa5]+', s[i:i+n])]

def grounded(x, ref):
    x = str(x or '').strip()
    if not x:
        return False
    if norm(x) in ref:
        return True
    subs = cjk4(x)
    return bool(subs) and any(norm(c) in ref for c in subs)

# ---------- references ----------
docs = load_docs()
DOC_NORM = {k: norm(d['text']) for k, d in docs.items()}
DOC_ATOMS = {k: doc_atoms(d['text']) for k, d in docs.items()}

frozen = json.loads((PILOT / 'screening_full_80_frozen.json').read_text())
samples = {(nt, s['sample_id']): s['input'] for nt, spec in
           frozen['node_types'].items() for s in spec['samples']}

REF_DOC = {  # from content mapping (verified this round)
    ('fact_extraction', 'S1'): 'ydt#D1_E03-yuandao_2026-05-08',
    ('fact_extraction', 'S2'): 'ydt#D2_E03-yuandao_2026-08-29',
    ('fact_extraction', 'S3'): 'ydt#D3_E03-yuandao_2026-08-29',
    ('timeline', 'TL1'): 'ydt#D1_E03-yuandao_2026-05-08',
    ('timeline', 'TL2'): 'ydt#D2_E03-yuandao_2026-08-29',
    ('timeline', 'TL3'): 'ydt#D3_E03-yuandao_2026-08-29',
    ('timeline', 'TL4'): 'jsst#csrc_penalty_2024_41',
    ('timeline', 'TL5'): 'jsst#csrc_penalty_2024_41',
    ('timeline', 'TL6'): None,   # KDX: no official doc in pool
    ('entity_relations', 'ER1'): 'ydt#D1_E03-yuandao_2026-05-08',
    ('entity_relations', 'ER2'): 'ydt#D2_E03-yuandao_2026-08-29',
    ('entity_relations', 'ER3'): 'ydt#D3_E03-yuandao_2026-08-29',
    ('entity_relations', 'ER4'): 'jsst#csrc_penalty_2024_41',
    ('entity_relations', 'ER5'): 'jsst#csrc_penalty_2024_41',
    ('entity_relations', 'ER6'): None,  # KDX
    ('crosssource_check', 'XC1'): 'ydt#D1_E03-yuandao_2026-05-08',
    ('crosssource_check', 'XC2'): 'ydt#D2_E03-yuandao_2026-08-29',
    ('crosssource_check', 'XC3'): 'ydt#D3_E03-yuandao_2026-08-29',
    ('crosssource_check', 'XC4'): 'jsst#csrc_penalty_2024_41',
    ('crosssource_check', 'XC5'): 'ydt#D1_E03-yuandao_2026-05-08',
}
# XC needs BOTH docs: derive from input fact doc_ids
def xc_docs(inp):
    ids = re.findall(r'D\d+_E\d+-[\w-]+', inp)
    keys = []
    for i in ids:
        for k in docs:
            if k.endswith(i):
                keys.append(k)
                break
    return list(dict.fromkeys(keys))

# ---------- responses ----------
recs = []
led80 = {e['call_id']: e for e in (json.loads(l) for l in
          (PILOT / 'screening_full80_ledger.jsonl').read_text()
          .splitlines() if l.strip())}
for r in (json.loads(l) for l in
          (PILOT / 'screening_full80_responses.jsonl').read_text()
          .splitlines() if l.strip()):
    e = led80[r['call_id']]
    recs.append(dict(nt=e['node_type'], sid=e['sample_id'],
                     model=e['model_alias'], raw=r['raw_response'],
                     json_valid=e['json_valid']))
for e in (json.loads(l) for l in
          (PILOT / 'screening_pilot_v1_ledger.jsonl').read_text()
          .splitlines() if l.strip()):
    rid = e['call_id']
    raw = ''
    p = PILOT / 'screening_pilot_v1_responses.jsonl'
    for l in p.read_text().splitlines():
        d = json.loads(l)
        if d['call_id'] == rid:
            raw = d['raw_response']
            break
    recs.append(dict(nt='fact_extraction', sid=e.get('snippet_id'),
                     model=e['model_alias'], raw=raw,
                     json_valid=e.get('json_valid')))

CONTRACT_KEY = {'fact_extraction': 'facts', 'timeline': 'timeline',
                'entity_relations': 'relations',
                'crosssource_check': 'verdicts'}
ITEM_KEYS = {'fact_extraction': ['facts', 'items'],
             'timeline': ['timeline', 'items', 'events'],
             'entity_relations': ['relations', 'entities', 'items',
                                  'entity_relations', 'links'],
             'crosssource_check': ['verdicts', 'checks', 'comparisons',
                                   'results', 'items']}

def er_resolve(it, legend):
    """Return (subject, object, legend_mediated)."""
    if isinstance(it, dict):
        s, o = it.get('subject'), it.get('object')
        if s is None and it.get('主体1') is not None:
            s, o = it.get('主体1'), it.get('主体2')
        med = False
        if legend and (isinstance(s, str) and re.fullmatch(r'E\d+', s)
                       or isinstance(o, str) and re.fullmatch(r'E\d+', o)):
            s2 = legend.get(s, s)
            o2 = legend.get(o, o)
            med = (s2 != s or o2 != o)
            return s2, o2, med
        return s, o, False
    if isinstance(it, list) and len(it) >= 3:
        return it[0], it[2], False
    if isinstance(it, list) and len(it) == 2:
        return it[0], it[1], False
    return None, None, False

adj_records = []
agg = defaultdict(lambda: defaultdict(lambda: dict(
    n_resp=0, items=0, grounded=0, unknown=0, contradicted=0,
    legend_med=0, no_ref_items=0, fmt_fail=0, strict_schema=0,
    recall_hit=0, recall_n=0)))

for rec in recs:
    nt, sid, m = rec['nt'], rec['sid'], rec['model']
    A = agg[nt][m]
    A['n_resp'] += 1
    obj = load_obj(rec['raw'])
    # strict schema: original contract key present & json valid
    strict = bool(rec.get('json_valid')) and isinstance(obj, dict) and \
        bool(isinstance(obj.get(CONTRACT_KEY[nt]), list)
             and obj[CONTRACT_KEY[nt]])
    A['strict_schema'] += int(strict)
    items = get_items(obj, ITEM_KEYS[nt])
    # ER legend
    legend = None
    if nt == 'entity_relations' and isinstance(obj, dict):
        ents = obj.get('entities') or obj.get('主体') or []
        if isinstance(ents, list) and ents and isinstance(ents[0], dict):
            legend = {str(e.get('id') or e.get('编号')): str(
                e.get('name') or e.get('名称') or '') for e in ents
                if isinstance(e, dict)}
    ref_key = REF_DOC.get((nt, sid))
    inp = samples.get((nt, sid), '')
    has_ref = ref_key is not None and ref_key in DOC_NORM
    if nt == 'crosssource_check':
        xdocs = xc_docs(inp)
        has_ref = len(xdocs) >= 1
        refs = {k: DOC_NORM[k] for k in xdocs if k in DOC_NORM}
    else:
        refs = {ref_key: DOC_NORM[ref_key]} if has_ref else {}
    if not items:
        A['fmt_fail'] += 1
        adj_records.append(dict(nt=nt, sid=sid, model=m,
                                verdict='FORMAT_FAILURE'))
        continue
    refall = norm(''.join(refs.values()))
    for it in items:
        A['items'] += 1
        v = None
        if nt == 'fact_extraction' and isinstance(it, dict):
            q = it.get('quote') or ''
            val = it.get('value') or it.get('fact') or ''
            v = 'GROUNDED' if ((q and norm(q) in refall) or
                               (val and grounded(val, refall))) \
                else ('UNKNOWN' if not has_ref else 'UNKNOWN')
        elif nt == 'timeline' and isinstance(it, dict):
            okd = any(f in refall for f in date_forms(it.get('date')))
            ents = [x for x in (it.get('entities') or [])
                    if len(str(x)) >= 2]
            oke = (not ents) or any(grounded(x, refall) for x in ents)
            v = ('GROUNDED' if (okd and oke) else
                 ('UNKNOWN' if not has_ref else 'UNKNOWN'))
        elif nt == 'entity_relations':
            s, o, med = er_resolve(it, legend)
            if not str(s or '').strip() and not str(o or '').strip():
                v = 'UNKNOWN'
            else:
                g = grounded(s, refall) and (o is None or
                                             grounded(o, refall))
                A['legend_med'] += int(med and g)
                v = 'GROUNDED' if g else 'UNKNOWN'
        elif nt == 'crosssource_check' and isinstance(it, dict):
            v = 'UNKNOWN'
        if v == 'GROUNDED':
            A['grounded'] += 1
        else:
            A['unknown'] += 1
        adj_records.append(dict(nt=nt, sid=sid, model=m,
                                item=json.dumps(it, ensure_ascii=False)[:200],
                                verdict=v, has_doc_ref=has_ref))
    # recall vs doc-necessary atoms
    if has_ref and nt != 'crosssource_check':
        at = DOC_ATOMS[ref_key]
        if nt == 'fact_extraction':
            nec = at['dates'][:6] + at['amounts'][:6] + at['penalties'][:4]
            outn = norm(rec['raw'])
            for x in nec:
                A['recall_n'] += 1
                A['recall_hit'] += int(norm(x) in outn)
        elif nt == 'timeline':
            for d in at['dates'][:8]:
                A['recall_n'] += 1
                A['recall_hit'] += int(any(f in norm(rec['raw'])
                                           for f in date_forms(d)))
        elif nt == 'entity_relations':
            for e_ in at['entities'][:6]:
                A['recall_n'] += 1
                A['recall_hit'] += int(grounded(e_, norm(rec['raw'])) or
                                       norm(e_) in norm(rec['raw']))

# XC special pass: doc-verified mechanical truth where computable
CLAIM = {'consistent': 'consistent', 'inconsistent': 'inconsistent',
         '一致': 'consistent', '不一致': 'inconsistent', '相同': 'consistent',
         '不同': 'inconsistent', 'contradictory': 'inconsistent',
         'consistent?': None}
xc_scored = defaultdict(lambda: [0, 0, 0])  # model -> [correct, wrong, unk]
for rec in recs:
    if rec['nt'] != 'crosssource_check':
        continue
    inp = samples.get(('crosssource_check', rec['sid']), '')
    xdocs = xc_docs(inp)
    if not xdocs:
        continue
    refs = {k: DOC_NORM[k] for k in xdocs if k in DOC_NORM}
    try:
        src = json.loads(strip_fence(inp))
        fa = {norm(f.get('fact_key')): (norm(f.get('value')),
                                        f.get('doc_id'))
              for f in src.get('source_a', {}).get('facts', [])
              if isinstance(f, dict)}
        fb = {norm(f.get('fact_key')): (norm(f.get('value')),
                                        f.get('doc_id'))
              for f in src.get('source_b', {}).get('facts', [])
              if isinstance(f, dict)}
    except Exception:
        continue
    truth = {}
    for k in set(fa) & set(fb):
        va, vb = fa[k][0], fb[k][0]
        da = next((DOC_NORM[key] for key in refs
                   if fa[k][1] and key.endswith(fa[k][1])), '')
        db = next((DOC_NORM[key] for key in refs
                   if fb[k][1] and key.endswith(fb[k][1])), '')
        core_a = re.sub(r'[\u4e00-\u9fa5]+', '', va)
        core_b = re.sub(r'[\u4e00-\u9fa5]+', '', vb)
        ver_a = bool(core_a) and core_a in (da or refs.get(
            list(refs)[0], ''))
        ver_b = bool(core_b) and core_b in (db or refs.get(
            list(refs)[0], ''))
        if ver_a and ver_b:
            truth[k] = 'consistent' if va == vb else 'inconsistent'
    obj = load_obj(rec['raw'])
    items = get_items(obj, ITEM_KEYS['crosssource_check']) or []
    for it in items:
        if not isinstance(it, dict):
            xc_scored[rec['model']][2] += 1
            continue
        k = norm(it.get('fact_key') or
                 (it.get('fact_key_pair') or [None])[0])
        claim = None
        for fld in ('comparison', 'status', 'relation', 'consistency'):
            if it.get(fld) is not None:
                claim = CLAIM.get(str(it[fld]).strip().lower(),
                                  CLAIM.get(str(it[fld]).strip()))
                break
        if k in truth and claim:
            xc_scored[rec['model']][0 if claim == truth[k] else 1] += 1
        else:
            xc_scored[rec['model']][2] += 1

# ---------- report ----------
print('=' * 86)
print('INDEPENDENT SEMANTIC RESCORE (official-doc references only)')
print('=' * 86)
print(f'{"type":>17} {"model":>11} {"items":>5} {"grounded":>9} '
      f'{"unk":>5} {"fmtF":>5} {"strict%":>8} {"recall%":>8} {"legendM":>7}')
for nt in ('fact_extraction', 'timeline', 'entity_relations'):
    for m in ('deepseek', 'glm53', 'glm53flash', 'qwen'):
        A = agg[nt].get(m)
        if not A:
            continue
        sc = A['strict_schema'] / A['n_resp'] * 100
        rc = A['recall_hit'] / A['recall_n'] * 100 if A['recall_n'] else 0
        print(f'{nt:>17} {m:>11} {A["items"]:>5} {A["grounded"]:>9} '
              f'{A["unknown"]:>5} {A["fmt_fail"]:>5} {sc:>7.0f}% '
              f'{rc:>7.0f}% {A["legend_med"]:>7}')
print('\ncrosssource (doc-verified mechanical truth):')
for m in ('deepseek', 'glm53', 'glm53flash', 'qwen'):
    c, w, u = xc_scored.get(m, [0, 0, 0])
    t = c + w
    print(f'  {m:>11}: correct {c}/{t}' if t else
          f'  {m:>11}: no doc-verifiable claims (all {u} UNKNOWN)')

out = dict(
    aggregate={nt: {m: agg[nt][m] for m in agg[nt]} for nt in agg},
    xc=({m: dict(correct=v[0], wrong=v[1], unknown=v[2])
         for m, v in xc_scored.items()}),
    adjudications=adj_records,
    no_reference_samples=['timeline|TL6', 'entity_relations|ER6'],
    principles='official-doc grounding only; UNKNOWN for unverifiable; '
               'dual-model agreement never used as Gold')
(ROOT / 'static_allocation_numeric_pilot_v1'
 / 'INDEPENDENT_SEMANTIC_RESCORE.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=1))
print('\nsaved INDEPENDENT_SEMANTIC_RESCORE.json '
      f'({len(adj_records)} item adjudications)')
