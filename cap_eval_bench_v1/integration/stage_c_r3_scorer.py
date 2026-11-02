"""Stage-C-R3: runtime-independent terminal-report quality scorer.

Reads ONLY the frozen execution archive (LEDGER_responses.jsonl), the task
definitions, silver references and evidence texts. Imports nothing from the
runtime engine. Zero model calls. Writes only NEW files — historical raw
results are never modified.

Five dimensions per terminal report (deterministic):
  C1 completeness     — silver facts covered by the REPORT text itself
                        (not accumulated ports: this is the un-saturated,
                        report-level version of Q)
  C2 correctness      — atomic claims (dates/amounts) in the report verified
                        against evidence: supported / unsupported /
                        contradicted (contradiction = mismatch against a
                        silver fact of the same type)
  C3 traceability     — fraction of claims carrying a doc_id citation
  C4 contradictions   — internal conflicting values for same-type facts
  C5 unknown_boundary — task's declared UNKNOWN items marked UNRESOLVED
                        rather than fabricated
"""
import json, re
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
ARCH = Path('/root/r3_own_pool/deadline_reward_v1/stage_c_r1_v1_EXEC_ARCHIVE')
SC = B / 'stage_c_evidence'

DATE = re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?')
AMT = re.compile(r'[\d,]{2,}(?:\.\d+)?(?:万元|亿元|元)')
DOCID = re.compile(r'[a-z]{2,5}_[a-z_]+_\d{4}')


def norm(s):
    return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）年月日/.-]', '', str(s))


def load_all():
    resp = {}
    for l in open(ARCH / 'LEDGER_responses.jsonl'):
        if l.strip():
            r = json.loads(l)
            resp[r['purpose']] = r
    tasks = {}
    for t in json.load(open(SC / 'tasks.json')):
        texts = {d: (SC / 'text' / f'{d}.txt').read_text()
                 for d in t['doc_ids']}
        silver = json.load(open(SC / f"{t['event']}_silver.json"))['facts']
        tasks[t['task_id']] = dict(task=t, texts=texts, silver=silver)
    return resp, tasks


def body(t):
    t = str(t).strip()
    if t.startswith('```'):
        parts = t.split('\n', 1)
        t = parts[1].rsplit('```', 1)[0].strip() if len(parts) == 2 else t
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}', t, re.S)
        try:
            return json.loads(m.group(0)) if m else None
        except Exception:
            return None


def parse_purpose(p):
    run, node, ver = p.rsplit(':', 2)[0], p.split(':')[-2], p.split(':')[-1]
    return p.split(':')[0], node, ver


def reconstruct_run(resp, run_id):
    """Last-version node outputs for one run, from its purposes only."""
    nodes = {}
    for p, r in resp.items():
        if not p.startswith(run_id + ':'):
            continue
        _, node, ver = parse_purpose(p)
        v = int(ver[1:])
        if node not in nodes or v >= nodes[node][0]:
            nodes[node] = (v, r['text'], r.get('stop_reason'))
    out = {}
    for node, (v, text, stop) in nodes.items():
        obj = body(text)
        val = None
        if isinstance(obj, dict):
            val = next(iter(obj.values())) if obj else None
        out[node] = dict(version=v, text=text, stop_reason=stop, obj=obj,
                         value=val)
    return out


def report_text(run_nodes, rpt_suffix='_rpt'):
    rpt = [n for n in run_nodes if n.endswith(rpt_suffix)]
    if not rpt:
        return None
    n = sorted(rpt)[-1]
    o = run_nodes[n]['obj'] if isinstance(run_nodes[n]['obj'], dict) else {}
    return json.dumps(o, ensure_ascii=False) if o else run_nodes[n]['text']


def score_report(rtext, task_data):
    """Five-dimension report-level scoring (deterministic)."""
    silver = task_data['silver']
    ev_text = ' '.join(task_data['texts'].values())
    ev_norm = norm(ev_text)
    rt = str(rtext)
    rt_norm = norm(rt)

    # C1 completeness — report-level silver coverage
    covered = []
    for f in silver:
        a = f['answer']
        hit = norm(a) in rt_norm
        if not hit and f.get('answer_type') == 'date':
            dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', a)
            if dm:
                alt = (f'{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日')
                hit = norm(alt) in rt_norm
        if hit:
            covered.append(f['fact_id'])
    c1 = round(len(covered) / max(1, len(silver)), 4)

    # atomic claims
    claims_d, claims_a = set(DATE.findall(rt)), set(AMT.findall(rt))
    claims = claims_d | claims_a
    supp = unsupp = 0
    contradicted = []
    for c in claims:
        if norm(c) in ev_norm:
            supp += 1
        else:
            unsupp += 1
            # contradiction: same-type silver fact with different value
            same_type = [f['answer'] for f in silver
                         if (f.get('answer_type') == 'date') == (c in claims_d)]
            if same_type and c not in same_type and claims:
                near = any(norm(c)[:4] == norm(s)[:4] for s in same_type)
                if near:
                    contradicted.append(c)
    c2 = dict(supported=supp, unsupported=unsupp,
              contradicted=sorted(set(contradicted)),
              score=round(supp / max(1, supp + unsupp + len(contradicted)), 4))

    # C3 traceability — doc_id citations vs claims
    cits = set(DOCID.findall(rt))
    c3 = round(len(cits) / max(1, len(claims)), 4) if claims else 0.0

    # C4 contradictions — internal: distinct amounts for the same magnitude
    # keyword context is approximated by distinct-value count per type vs
    # distinct-keyword count; deterministic proxy: conflicting = claims that
    # co-occur with >1 distinct value of identical length-class and share
    # the first 2 digits but differ (near-duplicate fabrication marker)
    internal = []
    amounts = sorted(claims_a)
    for i, a1 in enumerate(amounts):
        for a2 in amounts[i + 1:]:
            if a1 != a2 and a1[:2] == a2[:2] and len(a1) == len(a2):
                internal.append((a1, a2))
    c4 = dict(internal_conflict_pairs=len(internal), pairs=internal[:5])

    # C5 unknown boundary
    ub = task_data['task'].get('unknown_boundary', [])
    marks_ok = marks_fabricated = 0
    for u in ub:
        ukey = re.sub(r'[的具体金额数值精确]+', '', u)[:6]
        seg = next((s for s in re.split(r'[。;；\n]', rt) if ukey in norm(s)
                    or ukey in s), '')
        if not seg:
            continue
        if 'UNRESOLVED' in seg or 'UNKNOWN' in seg.upper() or '未知' in seg:
            marks_ok += 1
        elif DATE.search(seg) or AMT.search(seg):
            marks_fabricated += 1
    c5 = dict(boundaries=len(ub), marked_unknown=marks_ok,
              fabricated=marks_fabricated,
              score=round(marks_ok / max(1, marks_ok + marks_fabricated), 4)
              if (marks_ok or marks_fabricated) else None)

    return dict(report_chars=len(rt), c1_completeness=c1,
                covered=covered, c2_correctness=c2, c3_traceability=c3,
                c4_contradictions=c4, c5_unknown=c5)


def fact_attribution(run_nodes, covered_ids, task_data):
    """Which pipeline stage supplied each covered fact: prefix nodes
    (idx/extracts) vs recovery suffix vs split branches — via text match of
    the silver answer inside node outputs."""
    silver = {f['fact_id']: f['answer'] for f in task_data['silver']}
    attrib = {}
    for fid in covered_ids:
        a = norm(silver[fid])
        loc = []
        for n, nd in run_nodes.items():
            if a in norm(nd['text']):
                loc.append(n)
        stage = ('prefix' if any(re.search(r'(idx|ext)', x) for x in loc)
                 else 'suffix')
        if any('_a' in x or '_b' in x for x in loc):
            stage = 'split-branch'
        attrib[fid] = dict(nodes=loc, stage=stage)
    return attrib
