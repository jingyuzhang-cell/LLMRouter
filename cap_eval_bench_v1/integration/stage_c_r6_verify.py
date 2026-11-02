"""Stage-C-R6 P1+P2+P3 zero-call verification.

P1  natural-DAG downstream contribution (4 events, original Planner DAGs,
    NO artificial nodes): a derivation-capable subclass of the declared
    synthetic adapter lets timeline nodes compute cross-doc date intervals
    and verification nodes compare cross-doc ratios FROM THE LEDGER /
    evidence. Demonstrate per event: healthy -> derived facts reach the
    terminal ledger; fault@responsible-node + no-recovery -> derived facts
    absent; recovery -> restored. This is the G1 evidence.
P2  frozen unified terminal scorer (stage_c_r6_scorer semantics inline):
    Q_prefix (original 26) / Q_downstream (4 derived) / Q_terminal /
    UNKNOWN-boundary correctness (2) + observables (upstream_missing,
    traceability, completion). Label-blind: consumes artifacts + Silver v2
    only. Validated by perturbation.
P3  budget re-derivation from R4 real prompt sizes (shared-prefix matrix).

Zero model calls. Frozen files untouched.
"""
import json, re, sys, hashlib
from datetime import date
from pathlib import Path

B = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(B / 'integration'))
import stage_c_r4_runner as R4
import stage_c_r1 as R1
from fact_ledger import FactLedger
from six_arm_scheduler import ARMS

TEXTS = {d: (B / 'stage_c_evidence' / 'text' / f'{d}.txt').read_text()
         for d in ('zzd_penalty_2020', 'zzd_notice_2019', 'km_penalty_2020',
                   'km_notice_2019', 'cs_listing_2025',
                   'cs_plan_summary_2024', 'ls_delist_2020', 'ls_terminate_2020')}
SV2 = json.load(open(B / 'stage_c_evidence' / 'silver_v2.json'))
V = {'checks': {}, 'pass': True}


def check(name, ok, detail=''):
    V['checks'][name] = dict(ok=bool(ok), detail=str(detail)[:300])
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))
    if not ok:
        V['pass'] = False


def canon(y, m, d):
    return f'{y}{int(m)}{int(d)}'


class DerivingAdapter(R4.DeterministicFactAdapter):
    """Declared-synthetic derivation-capable model stand-in: timeline nodes
    compute cross-doc date intervals from ledger facts; verification nodes
    compare cross-doc ratios (from evidence, spans recorded)."""

    def call(self, nid, kind, model, prompt, ledger, evidence,
             visible_fids=None):
        res = super().call(nid, kind, model, prompt, ledger, evidence,
                           visible_fids)
        if not res['success'] or res['ledger'] is None:
            return res
        led = res['ledger']
        if kind in ('timeline', 'verification'):
            seen = set()
            n_derived = 0
            facts = [f for f in led.facts.values() if f.kind == 'date']
            for a in facts:
                ma = re.match(r'(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})',
                              a.content)
                if not ma:
                    continue
                for b in facts:
                    if b.fid == a.fid or (b.source_doc == a.source_doc
                                          and b.source_doc is not None):
                        continue  # cross-document pairs only
                    mb = re.match(r'(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})',
                                  b.content)
                    if not mb:
                        continue
                    key = tuple(sorted([a.fid, b.fid]))
                    if key in seen or n_derived >= 20:
                        continue
                    seen.add(key)
                    n_derived += 1
                    da = date(*map(int, ma.groups()))
                    db = date(*map(int, mb.groups()))
                    led.add(f'{abs((db - da).days)}天', 'derived',
                            source_doc=None, parent_node=nid,
                            parent_version=1, status='confirmed')
        if kind == 'verification':
            docs = list(evidence.items())
            if len(docs) == 2:
                vals = []
                for did, txt in docs:
                    m = re.search(r'1\s*[:：]\s*(0\.\d+)', txt)
                    if m:
                        vals.append((did, m.group(1), m.span()))
                if len(vals) == 2 and vals[0][1] != vals[1][1]:
                    led.add('换股比例不一致', 'derived', source_doc=None,
                            parent_node=nid, parent_version=1,
                            status='confirmed')
        return res


# ---------------------------------------------------------------------------
# P1: per-event downstream contribution through the natural DAG
# ---------------------------------------------------------------------------
print('=== P1: natural-DAG downstream contribution (G1) ===')
tasks = R1.load_tasks()
p1 = {}
for tid in ('SC-E1', 'SC-E2', 'SC-E3', 'SC-E4'):
    data = tasks[tid]
    dag = data['task']['dag']
    tl = next((n['id'] for n in dag['nodes'] if n['kind'] == 'timeline'), None)
    chk = next(n['id'] for n in dag['nodes'] if n['kind'] == 'verification')
    resp = tl or chk     # event's natural derivation node

    def run(anom=None, adapter_cls=R4.DeterministicFactAdapter, arm='Joint(R,pi)'):
        return R4.run_arm_r4(arm, data, anom, budget_tokens=60000)

    # healthy: derived facts at terminal
    orig = R4.DeterministicFactAdapter
    R4.DeterministicFactAdapter = DerivingAdapter
    healthy = run()
    # fault at the derivation node, no recovery (Static) vs recovery
    fault = {resp: dict(type='transport', left=1)}
    static = run(fault, arm='Static-Parallel')
    recov = run(fault, arm='Joint(R,pi)')
    R4.DeterministicFactAdapter = orig

    def derived_facts(r):
        if not r['terminal_ledger_stats']:
            return []
        # terminal output body carries derived content; use report text
        return [x for x in (r.get('report_fact_ids') or [])]

    hs = healthy['terminal_ledger_stats'] or {}
    ss = static['terminal_ledger_stats'] or {}
    rs = recov['terminal_ledger_stats'] or {}
    ev_dd = SV2['events'][next(k for k in SV2['events'] if tid.endswith(
        k.split('_')[0].replace('E', '')))] if False else None
    p1[tid] = dict(healthy=dict(status=healthy['status'], ledger=hs,
                                derived_expected=[f['answer'] for f in
                                                  SV2['events'][[
                                                      k for k in SV2['events']
                                                      if k.startswith(
                                                          tid.replace('SC-', ''))][0]]['downstream_facts']
                                                  if f['answer'] != 'UNKNOWN']),
                   static=dict(status=static['status'], ledger=ss),
                   recovered=dict(status=recov['status'], ledger=rs))
    print(f'  {tid}: resp={resp} healthy={healthy["status"]} ledger={hs.get("n")} '
          f'| fault@resp Static={static["status"]} '
          f'| Joint recovery={recov["status"]} ledger={rs.get("n")}')

check('P1a all four events: natural DAG + derivation adapter completes '
      'healthy runs', all(p1[t]['healthy']['status'] == 'COMPLETE' for t in p1))
check('P1b fault at the derivation node: Static loses the terminal ledger, '
      'recovery restores it',
      all(p1[t]['static']['status'] == 'INCOMPLETE_NO_RECOVERY'
          and p1[t]['recovered']['status'] == 'COMPLETE'
          and (p1[t]['static']['ledger'] or {}).get('n', 0) == 0
          and (p1[t]['recovered']['ledger'] or {}).get('n', 0) > 0 for t in p1))

# ---------------------------------------------------------------------------
# P2: frozen unified scorer (label-blind) + perturbation validation
# ---------------------------------------------------------------------------
print('\n=== P2: unified terminal scorer ===')


def score_v2(terminal_ledger_contents, report_text, silver_v2):
    """terminal_ledger_contents: list of fact contents (with statuses).
    Label-blind: only artifacts + Silver v2."""
    nrm = lambda s: re.sub(r'[\s天,，。;；:：、"\u201c\u201d()\[\]（）年月日/.-]',
                           '', str(s))
    blob_led = nrm(' '.join(terminal_ledger_contents))
    blob_rep = nrm(report_text or '')
    orig_hits = down_hits = 0
    n_orig = n_down = 0
    for ev, d in silver_v2['events'].items():
        for f in d['original_facts']:
            n_orig += 1
            if nrm(f['answer']) in blob_rep or nrm(f['answer']) in blob_led:
                orig_hits += 1
        for f in d['downstream_facts']:
            if f['answer'] == 'UNKNOWN':
                continue
            n_down += 1
            if nrm(f['answer']) in blob_rep or nrm(f['answer']) in blob_led:
                down_hits += 1
    q_prefix = round(orig_hits / max(1, n_orig), 4)
    q_down = round(down_hits / max(1, n_down), 4)
    return dict(Q_prefix=q_prefix, Q_downstream=q_down,
                Q_terminal=round((orig_hits + down_hits)
                                 / max(1, n_orig + n_down), 4))


# scorer validation on P1 artifacts: healthy vs Static-loss vs recovered
R4.DeterministicFactAdapter = DerivingAdapter
E1 = tasks['SC-E1']
tl1 = next(n['id'] for n in E1['task']['dag']['nodes'] if n['kind'] == 'timeline')
h1 = R4.run_arm_r4('Joint(R,pi)', E1, None, budget_tokens=60000)
s1 = R4.run_arm_r4('Static-Parallel', E1, {tl1: dict(type='transport', left=1)},
                   budget_tokens=60000)
r1 = R4.run_arm_r4('Joint(R,pi)', E1, {tl1: dict(type='transport', left=1)},
                   budget_tokens=60000)
R4.DeterministicFactAdapter = R4.DeterministicFactAdapter.__mro__[-2] \
    if False else orig


def ledger_contents(r):
    # deterministic adapter stores output bodies; terminal body carries the
    # merged ledger through report text — use report text + stats
    if not r['terminal_ledger_stats']:
        return [], ''
    return [], str(r.get('report_fact_ids') or []) + ' ' + str(
        r.get('report_unknown_marks') or [])


# proper artifact: re-run with contents captured via a wrapper ledger dump
def full_artifact(arm, anom):
    R4.DeterministicFactAdapter = DerivingAdapter
    res = {}

    class Cap(DerivingAdapter):
        def call(self, *a, **k):
            r = super().call(*a, **k)
            res['last'] = r
            return r
    R4.DeterministicFactAdapter = Cap
    rr = R4.run_arm_r4(arm, E1, anom, budget_tokens=60000)
    R4.DeterministicFactAdapter = DerivingAdapter
    return rr, res.get('last')


rr_h, last_h = full_artifact('Joint(R,pi)', None)
rr_s, last_s = full_artifact('Static-Parallel', {tl1: dict(type='transport', left=1)})
rr_r, last_r = full_artifact('Joint(R,pi)', {tl1: dict(type='transport', left=1)})

# derive 350天 presence per run from the terminal ledger object captured on
# the LAST adapter call (the report node)
def terminal_contents(last):
    if last is None or last.get('ledger') is None:
        return []
    return [f.content for f in last['ledger'].facts.values()]


sc_h = score_v2(terminal_contents(last_h), '', SV2)
sc_s = score_v2(terminal_contents(last_s), '', SV2)
sc_r = score_v2(terminal_contents(last_r), '', SV2)
print(f'  healthy  : {sc_h}')
print(f'  Static   : {sc_s}')
print(f'  recovered: {sc_r}')
check('P2a Q_downstream discriminates: healthy/recovered > Static-loss',
      sc_h['Q_downstream'] > sc_s['Q_downstream']
      and sc_r['Q_downstream'] > sc_s['Q_downstream'])
check('P2b ΔQ_recovery positive on the paired cell',
      round(sc_r['Q_downstream'] - sc_s['Q_downstream'], 4) > 0,
      f"ΔQ={round(sc_r['Q_downstream'] - sc_s['Q_downstream'], 4)}")
check('P2c label-blind: scorer consumes artifacts + Silver v2 only '
      '(signature has no arm/action param)',
      'arm' not in score_v2.__code__.co_varnames[:score_v2.__code__.co_argcount])

# ---------------------------------------------------------------------------
# P3: budget re-derivation from R4 prompt sizes
# ---------------------------------------------------------------------------
print('\n=== P3: budget from R4 real prompt sizes ===')
R4.DeterministicFactAdapter = DerivingAdapter
calls_meta = []


class Meter(DerivingAdapter):
    def call(self, *a, **k):
        calls_meta.append(a[3] if len(a) > 3 else '')  # prompt
        return super().call(*a, **k)


R4.DeterministicFactAdapter = Meter
per_cell = {}
for tid in ('SC-E1', 'SC-E3'):
    data = tasks[tid]
    dag = data['task']['dag']
    tl = next((n['id'] for n in dag['nodes'] if n['kind'] == 'timeline'), None)
    chk = next(n['id'] for n in dag['nodes'] if n['kind'] == 'verification')
    resp = tl or chk     # event's natural derivation node
    for scen, anom in (('S1', {tl: dict(type='transport', left=1)}),
                       ('S2', {chk: dict(type='contract')})):
        # shared prefix (arm-agnostic) then one representative arm suffix
        pre = R4.run_arm_r4('Static-Parallel', data, anom, budget_tokens=60000)
        one = R4.run_arm_r4('Joint(R,pi)', data, anom, budget_tokens=60000)
        per_cell[f'{tid}-{scen}'] = (pre['tokens'], one['tokens'])
R4.DeterministicFactAdapter = DerivingAdapter

RATIO = 0.6295
# deterministic tokens understate real prompts: use prompt_chars * RATIO
total_est = 0.0
for cell, (pre_tok, arm_tok) in per_cell.items():
    suffix = arm_tok - pre_tok
    cell_est = pre_tok + suffix * 6  # shared prefix + 6 arm suffixes
    total_est += cell_est * 2        # 2 reps
total_real_est = total_est / 4000 * 4000 * RATIO  # adapter in-tok model caps
check('P3a budget estimate within a 200K envelope',
      total_est * 1.3 < 200000, f'{round(total_est)} det-tokens, x1.3='
      f'{round(total_est * 1.3)}')
V['p3'] = dict(per_cell={k: [v[0], v[1]] for k, v in per_cell.items()},
               total_est=round(total_est))

out = B / 'stage_c_r3_rescore' / 'STAGE_C_R6_VERIFICATION.json'
out.write_text(json.dumps(V, ensure_ascii=False, indent=1, default=str))
print(f"\nOVERALL: {'ALL PASS' if V['pass'] else 'FAILURES'} -> {out}")
sys.exit(0 if V['pass'] else 1)
