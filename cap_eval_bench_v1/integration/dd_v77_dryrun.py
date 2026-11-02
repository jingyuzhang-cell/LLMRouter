"""DD-V7.7 zero-call end-to-end dry-run of dd_v77_runner_v3.

Six test groups (operator's DD-V7.7 instructions, items 3-5):
  T1  real-fixture prompt assembly — replay the paid n1/n2 outputs from
      dd_v76_n5_paired_v2 through the FIXED build_prompt and assert real
      zeda facts reach every consumer prompt (incl. both same-role parents).
  T2  deterministic full-path run — fake adapter, all 23 requests, fault at
      n5, both arms; assert per-edge propagation AND non-parent isolation
      (e.g. n3 must not see n2 — the F2 regression test).
  T3  schedule fidelity — v3 schedule() must reproduce the frozen
      dd_v74_request_manifest.json (node order, model assignment) exactly.
  T4  scoring isolation — score_q is a pure function of (text, evidence);
      swapping texts across arm labels must swap the scores with the texts.
  T5  cache validity — V77 purposes disjoint from V76; v3 n1/n2 prompts
      byte-identical to v2 (so reusing old purposes WOULD have dedup-replayed
      the truncated outputs — must not happen); 23 distinct (purpose, sha).
  T6  budget recount — per-request in-token estimate from the measured v2
      chars/token ratio + per-role out caps, with realistically padded
      synthetic outputs -> recommended envelope and per-model quotas.

ZERO API calls: the only external data are the frozen DAGSpec, the zeda
evidence store, and the paid v2 ledger (already settled).
"""
import json, re, sys, hashlib
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))

import dd_v77_runner_v3 as R

V2 = B / 'dd_v76_n5_paired_v2'
report = {'tests': {}, 'pass': True}


def check(name, ok, detail=''):
    report['tests'][name] = dict(ok=bool(ok), detail=str(detail)[:400])
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))
    if not ok:
        report['pass'] = False


# ---------- shared fixtures ----------
responses = [json.loads(l) for l in open(V2 / 'LEDGER_responses.jsonl') if l.strip()]
n1_real = next(r['text'] for r in responses if r.get('purpose') == 'V76-shared:n1')
n2_real = next(r['text'] for r in responses if r.get('purpose') == 'V76-shared:n2')
# discriminative per-node markers: verified unique to one fixture each
MK_N1, MK_N2 = '2017-20', '342,296,307.13'
assert MK_N1 in n1_real and MK_N1 not in n2_real, 'n1 marker not unique'
assert MK_N2 in n2_real and MK_N2 not in n1_real, 'n2 marker not unique'
MK = {'n1': MK_N1, 'n2': MK_N2, 'n5': '占位'}   # n5 effective output = GARBAGE
# doc-discriminative markers for the F4 evidence-binding test, verified
# present in exactly one 6000-char doc slice (the文号 sits past the cap)
DOC1_MARK, DOC2_MARK = '186,735,305.01元', '康达律师事务所'

print("=== T1: real-fixture prompt assembly (fixed build_prompt) ===")
# F4: each extraction node bound to exactly its declared evidence doc
p_n1 = R.build_prompt('n1', {})
check("T1 F4 n1 prompt = doc 2023_29 ONLY",
      DOC1_MARK in p_n1 and DOC2_MARK not in p_n1, f"{len(p_n1)} chars")
p_n2 = R.build_prompt('n2', {})
check("T1 F4 n2 prompt = doc 2024_kangda ONLY",
      DOC2_MARK in p_n2 and DOC1_MARK not in p_n2, f"{len(p_n2)} chars")
fx = {'n1': n1_real, 'n2': n2_real}
for nid in ('n3', 'n4', 'n5', 'n6'):
    p = R.build_prompt(nid, fx)
    parents = R.DEPS[nid]
    check(f"T1 {nid} prompt substantive", len(p) > 1500, f"{len(p)} chars")
    for pid in ('n1', 'n2'):
        want = pid in parents
        got = MK[pid] in p
        check(f"T1 {nid} {'sees' if want else 'isolated from'} {pid}", got == want)
check("T1 n8 gets its parent n4 (not a role key)",
      '12,345.67万元' in R.build_prompt('n8', {'n4': 'SYN amt 12,345.67万元'}))

print("\n=== T2: deterministic full-path run (23 requests, zero API) ===")
seen = []


class FakeMeter:
    """Deterministic node adapter: records every request; n1/n2 return the
    PAID v2 fixtures, other nodes return role-field JSON padded to a
    realistic ~1600 chars (v2 measured ~2.4 chars per output token)."""

    def call(self, alias, system, user, max_tokens, purpose):
        nid = purpose.split(':')[1]
        if nid in ('n1', 'n2'):
            text = {'n1': n1_real, 'n2': n2_real}[nid]
        else:
            role = R.ROLES[nid]
            head = f'{{"{R.OUT_FIELD[role]}":"FAKE[{nid}/{role}/{alias}]M{nid}X'
            text = head + '验' * max(0, 1600 - len(head) - 1) + '"}'
            if nid != 'n5':                 # n5's effective output is GARBAGE
                MK[nid] = f'M{nid}X'
        seen.append(dict(purpose=purpose, node=nid, model=alias,
                         prompt=user, prompt_chars=len(user),
                         max_tokens=max_tokens, text=text,
                         sha=hashlib.sha256((system + '\x00' + user)
                                            .encode()).hexdigest()))
        return dict(tokens_in=len(user) * 63 // 100), text


def run_request(meter, nid, model, purpose, ud):
    pr = R.build_prompt(nid, ud, R.ev)
    rec, t = meter.call(model, '', pr, R.OUT_CAP.get(R.ROLES[nid], R.OUT_DEFAULT),
                        purpose)
    return t


fm = FakeMeter()
upstream = {}
for nid in ('n1', 'n2', 'n3', 'n4'):
    upstream[nid] = run_request(fm, nid, 'glm53', f'V77-shared:{nid}', upstream)
for rep in (1, 2):
    run_request(fm, 'n5', 'glm53flash', f'V77-fault:n5:rep{rep}', upstream)
    upstream['n5'] = R.GARBAGE                      # b2 fault replaces output
upstream['n8'] = run_request(fm, 'n8', 'glm53flash', 'V77-shared:n8', upstream)
arm_texts = {}
for action, m67 in (('A_alt', 'glm53flash'), ('B_ib', 'glm53')):
    for rep in (1, 2):
        ud = dict(upstream)
        for nid in ('n6', 'n7', 'n9', 'n10'):
            t = run_request(fm, nid, m67 if nid in ('n6', 'n7') else 'glm53flash',
                            f'V77-{action}:{nid}:rep{rep}', ud)
            ud[nid] = t
        arm_texts[f'{action}_rep{rep}'] = ud['n10']

check("T2 request count == 23", len(seen) == 23, f"{len(seen)}")
mismatch = []
for r in seen:
    if not R.DEPS[r['node']]:
        continue        # parentless nodes (n1/n2) read evidence, not parents;
                        # their binding is the T1 F4 doc-isolation test
    for pid, marker in MK.items():
        present = marker in r['prompt']
        expected = pid in R.DEPS[r['node']]
        if present != expected:
            mismatch.append(f"{r['node']} prompt {'missing' if expected else 'leaks'} {pid}")
check("T2 exact parent set in every prompt (all 13 edges + isolation)",
      not mismatch, '; '.join(mismatch[:4]) or 'all edges exact')
check("T2 fault propagated into every n9 prompt",
      all('占位' in r['prompt'] for r in seen if r['node'] == 'n9'))
check("T2 no near-empty prompts (v2 regression was 66 chars)",
      all(r['prompt_chars'] > 500 for r in seen),
      f"min={min(r['prompt_chars'] for r in seen)}")
check("T2 extraction out cap 1536, all others 768",
      all(r['max_tokens'] == (1536 if r['node'] in ('n1', 'n2') else 768)
          for r in seen))

print("\n=== T3: schedule fidelity vs frozen v74 manifest ===")
man = json.load(open(B / 'dd_v74_request_manifest.json'))['manifest']
v3 = R.schedule()
check("T3 same 23 requests (node, model) as frozen manifest",
      sorted((x['node'], x['model'].replace('glm53flash', 'flash')) for x in v3)
      == sorted((x['node'], x['model']) for x in man))
# the manifest is a request INVENTORY grouped by node; execution order is
# (action -> rep -> n6..n10), same as v2. Verify that order is topologically
# valid: every request's DAGSpec parents are already in `upstream` when it runs
order_ok, why = True, ''
for r in seen:
    for p in R.DEPS[r['node']]:
        pass  # parent availability verified structurally below
seq = [r['node'] for r in seen]
avail = set()
for nid in seq:
    if any(p not in avail and p != nid for p in R.DEPS[nid]):
        order_ok, why = False, f"{nid} ran before a parent"
        break
    avail.add(nid)
check("T3 execution order topologically valid (all parents ready)", order_ok, why)
arm_models = {(r['purpose'].split(':')[0].split('-', 1)[1], r['node']): r['model']
              for r in seen if r['purpose'].startswith(('V77-A_alt', 'V77-B_ib'))}
check("T3 A_alt n6/n7=flash, B_ib n6/n7=glm53, n9/n10 flash in both",
      all(arm_models[('A_alt', n)] == 'glm53flash' for n in ('n6', 'n7', 'n9', 'n10'))
      and all(arm_models[('B_ib', n)] == ('glm53' if n in ('n6', 'n7') else 'glm53flash')
              for n in ('n6', 'n7', 'n9', 'n10')))

print("\n=== T4: scoring isolation ===")
tA, tB = arm_texts['A_alt_rep1'], arm_texts['B_ib_rep1']
qA, qB = R.score_q(tA, R.ev)[0], R.score_q(tB, R.ev)[0]
swapped = {k: R.score_q(t, R.ev)[0]
           for k, t in {'A_alt_rep1': tB, 'B_ib_rep1': tA}.items()}
check("T4 scores follow the text, not the arm label",
      swapped['A_alt_rep1'] == qB and swapped['B_ib_rep1'] == qA)
check("T4 score_q signature takes no arm/action argument",
      'action' not in R.score_q.__code__.co_varnames[:R.score_q.__code__.co_argcount])

print("\n=== T5: cache validity ===")
v2_purposes = {r.get('purpose') for r in responses}
check("T5 V77 purposes disjoint from V76 ledger",
      not ({r['purpose'] for r in seen} & v2_purposes))
v2_sha = {}
for l in open(V2 / 'LEDGER.jsonl'):            # call ledger carries prompt_sha256
    if l.strip():
        rec = json.loads(l)
        v2_sha[rec.get('purpose')] = rec.get('prompt_sha256')
# v2's n1/n2 prompts were byte-identical (both-docs F4 violation, same sha);
# v3 must break that identity via single-doc binding -> different shas from
# v2 AND from each other, so no dedup-replay is possible even if a purpose
# were accidentally reused
sha_n1 = hashlib.sha256(('\x00' + R.build_prompt('n1', {})).encode()).hexdigest()
sha_n2 = hashlib.sha256(('\x00' + R.build_prompt('n2', {})).encode()).hexdigest()
check("T5 v2 n1/n2 prompt-identity anomaly documented",
      v2_sha['V76-shared:n1'] == v2_sha['V76-shared:n2'],
      f"v2 both = {v2_sha['V76-shared:n1'][:12]}")
check("T5 v3 n1/n2 prompts differ from v2 and from each other (F4)",
      sha_n1 != v2_sha['V76-shared:n1'] and sha_n2 != v2_sha['V76-shared:n2']
      and sha_n1 != sha_n2)
check("T5 within-run 23 distinct (purpose, prompt_sha)",
      len({(r['purpose'], r['sha']) for r in seen}) == 23)

print("\n=== T6: budget recount for third execution ===")
RATIO = 7653 / 12157          # measured on v2: 12157 prompt chars -> 7653 in-tokens
in_est = {r['purpose']: r['prompt_chars'] * RATIO for r in seen}
tot = sum(in_est.values()) + sum(r['max_tokens'] for r in seen)
per_model = {}
for r in seen:
    d = per_model.setdefault(r['model'], [0, 0.0])
    d[0] += 1
    d[1] += in_est[r['purpose']] + r['max_tokens']
report['budget'] = dict(
    requests=len(seen),
    chars_per_token_ratio=round(RATIO, 4),
    conservative_token_sum=round(tot),
    recommended_envelope=round(tot * 1.3 / 10000) * 10000,
    per_model={k: dict(calls=v[0], token_quota=round(v[1] * 1.3 / 1000) * 1000)
               for k, v in per_model.items()})
print(json.dumps(report['budget'], ensure_ascii=False, indent=1))
check("T6 estimate fits a 130K envelope", tot * 1.3 < 130000,
      f"{round(tot)} conservative + 30% margin = {round(tot * 1.3)}")

print("\n=== T7: stage-gate verification (operator final instruction, item 6) ===")
# PASS path: synthetic gate-passing extraction built from the actual slices
sl1 = R.ev['zeda_csrc_penalty_2023_29']
sl2 = R.ev['zeda_csrc_penalty_2024_kangda']
d1_dates = sorted(set(re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', sl1)))[:3]
d1_amts = sorted(set(re.findall(r'[\d,.]+(?:万元|亿元|元)', sl1)))[:4]
pass_n1 = json.dumps({'doc_ex': [{'doc_id': 'zeda_csrc_penalty_2023_29',
                                  '主体': '泽达易盛 欺诈发行 处罚 罚款',
                                  'dates': d1_dates, 'amounts': d1_amts}]},
                     ensure_ascii=False)
pass_n2 = json.dumps({'doc_ex': [{'doc_id': 'zeda_csrc_penalty_2024_kangda',
                                  '主体': '泽达易盛 康达律师事务所 未勤勉尽责 警告 罚款 没收'}]},
                     ensure_ascii=False)
rec_ok = dict(stop_reason='stop')
g1 = R.extraction_gate('n1', rec_ok, pass_n1)
g2 = R.extraction_gate('n2', rec_ok, pass_n2)
check("T7 PASS path: contract-conformant n1 passes stage-1 gate", g1['ok'], str(g1))
check("T7 PASS path: contract-conformant n2 passes stage-1 gate", g2['ok'], str(g2))
# FAIL path A: the REAL v2 truncated outputs (stop=max_tokens, broken JSON)
rec_trunc = dict(stop_reason='max_tokens')
gf1 = R.extraction_gate('n1', rec_trunc, n1_real)
gf2 = R.extraction_gate('n2', rec_trunc, n2_real)
check("T7 FAIL path: v2 truncated n1 is rejected", not gf1['ok'],
      str({k: v for k, v in gf1['checks'].items() if not v}))
check("T7 FAIL path: v2 truncated n2 is rejected", not gf2['ok'],
      str({k: v for k, v in gf2['checks'].items() if not v}))
# FAIL path B: clean stop but wrong-source output (F4 regression)
gf3 = R.extraction_gate('n1', rec_ok, pass_n1.replace('zeda_csrc_penalty_2023_29',
                                                      'OTHER_DOC'))
check("T7 FAIL path: wrong-source n1 is rejected (doc-id binding)", not gf3['ok'])
# downstream node gate
gd = R.node_gate('n3', rec_ok, '{"timeline": ["2019年6月 ' + '事' * 300 + '"]}')
check("T7 downstream gate: conformant n3 passes", gd['ok'])
check("T7 downstream gate: n5 exempt (injected fault)",
      R.node_gate('n5', rec_ok, R.GARBAGE)['ok'])
check("T7 downstream gate: empty-field n9 rejected",
      not R.node_gate('n9', rec_ok, '{"verified_facts": ""}')['ok'])

outp = B / 'dd_v77_dryrun'
outp.mkdir(exist_ok=True)
(outp / 'DD_V77_DRYRUN_RESULTS.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=1, default=str))
print(f"\nOVERALL: {'ALL PASS' if report['pass'] else 'FAILURES PRESENT'}")
sys.exit(0 if report['pass'] else 1)
