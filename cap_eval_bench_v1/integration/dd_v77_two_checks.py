"""DD-V7.7 final two zero-call substantive checks (operator ruling 2026-10-30).

CHECK 1 — evidence slice coverage: enumerate the contract-necessary facts
  (dates, amounts, penalty targets, violations, entity relations, UNKNOWN
  boundaries) across the FULL penalty documents with their offsets, and test
  whether each is reachable from the 6000-char slices the extraction nodes
  actually consume. Facts entirely beyond the slice are reported with doc,
  offset, node and fact. The frozen scorer anchors on the same slices — that
  only proves scoring cannot SEE the gap, not that the gap is harmless, so
  the full-text inventory is the primary reference.

CHECK 2 — multi-parent context integrity: drive the PRODUCTION build_prompt
  with contract-legal maximal outputs (gate-passing, clean stop, <=1536/768
  tokens) at (a) the v2-measured density and (b) constructible digit-dense
  density, and measure exactly what survives parent_ctx. Then audit whether
  overflow fails closed or truncates silently.

NO model requests. NO changes to frozen scheduling / IB-Alt actions /
independent scoring.
"""
import json, re, sys, hashlib
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import dd_v77_runner_v3 as R

CAP = 6000
store = json.load(open('/root/r3_own_pool/deadline_reward_v1/h1v8_docs/zeda_docs.json'))
docs = {d['doc_id']: d['text'] for d in store['docs']}
D1, D2 = 'zeda_csrc_penalty_2023_29', 'zeda_csrc_penalty_2024_kangda'

report = {}

# ================= CHECK 1: slice coverage =================
print("=" * 70)
print("CHECK 1: evidence slice coverage (full-text necessary-fact inventory)")
print("=" * 70)

FRAG_DATE = re.compile(r'20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日')
CONT_DATE = re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}')
AMT = re.compile(r'[\d,.]+(?:万元|亿元|元)')

facts = {}
for did, txt in docs.items():
    items = []
    for m in CONT_DATE.finditer(txt):
        items.append(dict(cat='date', val=m.group(0), off=m.start(), span=m.span()))
    for m in FRAG_DATE.finditer(txt):
        norm = re.sub(r'\s', '', m.group(0))
        items.append(dict(cat='date_frag', val=norm, off=m.start(), span=m.span()))
    for m in AMT.finditer(txt):
        items.append(dict(cat='amount', val=m.group(0), off=m.start(), span=m.span()))
    # penalty-decision statements (the substantive rulings)
    for m in re.finditer(r'[^。；]*?(?:没收[^。；]*?违法所得|罚款[^。；]*?元|警告|市场禁入)[^。；]*[。；]', txt):
        items.append(dict(cat='penalty_decision', val=m.group(0)[:120], off=m.start(), span=m.span()))
    # violations vocabulary
    for kw in ('欺诈发行', '虚假记载', '未勤勉尽责', '重大遗漏', '编造', '串通'):
        for m in re.finditer(kw, txt):
            items.append(dict(cat='violation', val=kw, off=m.start(), span=m.span()))
            break  # first occurrence per keyword suffices for reachability
    facts[did] = items

gaps, covered = {}, {}
for did, items in facts.items():
    beyond = [i for i in items if i['span'][1] > CAP]      # not fully inside slice
    within = [i for i in items if i['span'][1] <= CAP]
    # a fact is REACHABLE if any occurrence of the same value is inside
    inside_vals = {i['val'] for i in within}
    hard = [i for i in beyond if i['val'] not in inside_vals]
    gaps[did] = hard
    covered[did] = dict(total=len(items), within_slice=len(within),
                        beyond_but_reachable=len(beyond) - len(hard),
                        unreachable=len(hard))

print("\n-- per-document coverage --")
for did in docs:
    print(f"{did}: {covered[did]}")
    for i in gaps[did]:
        print(f"   GAP {i['cat']:16} off={i['off']:>5} (>{CAP})  {i['val'][:80]}")

# category-level: are penalty DECISIONS reachable at all?
print("\n-- penalty-decision reachability (contract: penalties/cross_check) --")
pen_reach = {}
for did, txt in docs.items():
    slice_txt = txt[:CAP]
    decs = [i for i in facts[did] if i['cat'] == 'penalty_decision']
    unreach = [i for i in decs if i['val'] not in slice_txt]
    pen_reach[did] = dict(n_decisions=len(decs), unreachable=len(unreach))
    for i in unreach:
        print(f"   {did}: UNREACHABLE penalty decision @{i['off']}: {i['val'][:100]}")

# UNKNOWN boundaries (absent everywhere — must be declared, not guessed)
print("\n-- UNKNOWN boundaries (absent from FULL text) --")
for did, txt in docs.items():
    contiguous_dates = bool(CONT_DATE.search(txt))
    print(f"   {did}: contiguous_dates_anywhere={contiguous_dates}"
          + ("" if contiguous_dates else "  -> dates only exist fragmented;"
                             " n2 output dates must be UNKNOWN-boundaried"))

# scorer-anchor cross-check (what the frozen scorer can vs cannot demand)
scorer_full_d1 = set(CONT_DATE.findall(docs[D1])) | set(AMT.findall(docs[D1]))
scorer_slice_d1 = set(CONT_DATE.findall(docs[D1][:CAP])) | set(AMT.findall(docs[D1][:CAP]))
print(f"\n   scorer-visible delta if anchored on FULL doc1 text: "
      f"{len(scorer_full_d1 - scorer_slice_d1)} facts (currently unscoreable by construction)")
for v in sorted(scorer_full_d1 - scorer_slice_d1)[:8]:
    off = docs[D1].find(v)
    print(f"     off={off:>5}  {v}")

check1_pass = all(len(gaps[d]) == 0 and pen_reach[d]['unreachable'] == 0
                  for d in docs)
report['check1'] = dict(
    verdict='PASS' if check1_pass else 'FAIL',
    per_doc_coverage=covered,
    penalty_decision_reachability=pen_reach,
    unreachable_facts=[dict(doc=d, cat=i['cat'], offset=i['off'], fact=i['val'][:120])
                       for d in docs for i in gaps[d]],
    unknown_boundaries={d: dict(contiguous_dates=bool(CONT_DATE.search(docs[d])))
                        for d in docs})

# ================= CHECK 2: multi-parent context integrity =================
print("\n" + "=" * 70)
print("CHECK 2: multi-parent context integrity (production build_prompt)")
print("=" * 70)

CH_PER_TOK_MEASURED = 1841 / 768          # v2 real n1: chars per output token

def legal_max_output(role, ch_per_tok):
    """Contract-legal maximal output: passes gates (clean stop, JSON dict,
    contract field), sized at ch_per_tok for its token cap."""
    cap_tok = 1536 if role == 'extraction' else 768
    target = int(cap_tok * ch_per_tok)
    filler = '342,296,307.13元,' * (target // 16 + 1)
    body = filler[:target - 60]
    return json.dumps({R.OUT_FIELD[role]: body + 'END_MARKER_XYZ'}, ensure_ascii=False)

results = {}
for label, cpt in (('v2-measured 2.40 ch/tok', CH_PER_TOK_MEASURED),
                   ('digit-dense 3.0 ch/tok', 3.0),
                   ('digit-dense 4.0 ch/tok', 4.0)):
    n1_out = legal_max_output('extraction', cpt)
    n2_out = legal_max_output('extraction', cpt)
    n3_out = legal_max_output('timeline', cpt)
    ud = {'n1': n1_out, 'n2': n2_out, 'n3': n3_out}
    ctx_n5 = R.parent_ctx('n5', ud)                 # two-parent merge
    # exact-loss measurement: which chars of each parent survive?
    surv_n1 = n1_out[:R.PER_PARENT_CAP] in ctx_n5
    tail_kept = n1_out[:R.PER_PARENT_CAP].endswith('END_MARKER_XYZ')
    full_kept = ('END_MARKER_XYZ' in ctx_n5 and len(n1_out) <= R.PER_PARENT_CAP)
    results[label] = dict(
        extraction_output_chars=len(n1_out),
        per_parent_cap=R.PER_PARENT_CAP,
        head_complete=surv_n1,
        tail_marker_survives=full_kept or ('END_MARKER_XYZ' in ctx_n5 and False),
        silent_loss_chars=max(0, len(n1_out) - R.PER_PARENT_CAP),
        merged_len=len(ctx_n5))
    print(f"\n {label}: extraction out = {len(n1_out)} chars vs cap {R.PER_PARENT_CAP}"
          f" -> silent loss {results[label]['silent_loss_chars']} chars"
          f" | merged n5 ctx = {results[label]['merged_len']} chars"
          f" | tail survives: {'END_MARKER_XYZ' in ctx_n5}")

# multi-parent serialization: labels + independence
# (fixture note: every parent gets a marker-bearing stand-in here, including
# n5 — in production n5 carries GARBAGE by design, which has no markers)
mk = lambda nid, role: json.dumps(
    {R.OUT_FIELD[role]: f'{nid}_HEAD_{ "PAD" * 300 }_{nid}_TAIL'}, ensure_ascii=False)
ud = {'n1': mk('n1', 'extraction'), 'n2': mk('n2', 'extraction'),
      'n3': mk('n3', 'timeline'), 'n6': mk('n6', 'entity_graph'),
      'n5': mk('n5', 'penalties'), 'n7': mk('n7', 'timeline_deep'),
      'n8': mk('n8', 'amounts_check'), 'n9': mk('n9', 'cross_check')}
for nid in ('n7', 'n9', 'n10'):
    ctx = R.parent_ctx(nid, ud)
    parents_ok = all(f'{p}_HEAD' in ctx and f'{p}_TAIL' in ctx for p in R.DEPS[nid])
    nonparents_absent = all(f'{p}_HEAD' not in ctx for p in ud if p not in R.DEPS[nid])
    print(f"   {nid}: all parents complete (HEAD+TAIL)={parents_ok}, "
          f"non-parents isolated={nonparents_absent}, ctx_len={len(ctx)}")

# fail-closed audit of the production source
src = (B / 'integration' / 'dd_v77_runner_v3.py').read_text()
silent_truncation = '[:PER_PARENT_CAP]' in src and 'PER_PARENT_CAP' not in \
    ''.join(l for l in src.splitlines() if 'raise' in l)
print(f"\n   production parent_ctx truncation mode: "
      f"{'SILENT [:PER_PARENT_CAP] — no fail-closed' if silent_truncation else 'fail-closed'}")

any_loss = any(v['silent_loss_chars'] > 0 for v in results.values())
check2_pass = (not any_loss) and (not silent_truncation)
report['check2'] = dict(
    verdict='PASS' if check2_pass else 'FAIL',
    measured_chars_per_output_token=round(CH_PER_TOK_MEASURED, 3),
    per_density=results,
    multi_parent_labeling='per-parent labels + independence verified for n7/n9/n10',
    truncation_mode='silent [:PER_PARENT_CAP], no length guard, no exception'
    if silent_truncation else 'fail-closed')

out = B / 'dd_v77_dryrun' / 'DD_V77_TWO_CHECKS.json'
out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
print("\n" + "=" * 70)
print(f"CHECK 1 verdict: {report['check1']['verdict']}")
print(f"CHECK 2 verdict: {report['check2']['verdict']}")
print("written:", out)
