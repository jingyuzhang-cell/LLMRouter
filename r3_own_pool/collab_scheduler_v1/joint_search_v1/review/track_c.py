"""Track C: independent task panel, power assessment, budget fit (zero model calls).

Fills the SEARCH_BUDGET_V1.json `task_panel: UNASSIGNED` gap with a frozen,
hash-deterministic, provably-fresh split:

  1. PROVENANCE: same source and eligibility as all prior panels (TAT-QA train
     split, arithmetic + evaluable derivation + >=2 distinct literals), PLUS a
     STRICTER exposure scan: `used_uids` superset scan over the WHOLE workspace
     (r3_own_pool) instead of the historical static_dag_v0-only root. The
     frozen200 panel (200 tasks) is fully consumed by fault30/smoke analyses and
     cannot serve as independent test material.
  2. SPLIT: sha256("jointsearch_v1:"+uid) ascending over fresh eligible pool →
     SEARCH8 (in-session evaluation panel, identical for all 6 methods x 3
     seeds) + TEST16 (never evaluated during search; one-shot confirmatory
     evaluation of final selections only) + reserve remainder.
  3. POWER: paired-binary assessment from the only existing per-task 2-state
     arm data (frozen200 corrected, 200 tasks x 12 arms): empirical discordance
     D between recovery arms drives MDE(n) = (z_a+z_b)*sqrt(D)/sqrt(n). Search
     panel n=8 cannot resolve small per-config Q differences (selection does
     not need it); confirmatory claims rest on TEST16 + paired tests.
  4. BUDGET: 18 sessions = 6 methods x 3 seeds inside frozen campaign caps;
     per-session 12 configs x 2 states x 8 tasks vs measured 330-request
     scenario scaling <= 400-attempt cap. Confirmation allocation for TEST16 is
     estimated SEPARATELY (not inside the 18 sessions) and needs its own
     approval.

Output: review/TASK_PANEL_V1.json + review/TRACK_C_EVIDENCE.json.
Zero LLM calls; tokenizer used read-only for the prompt-length guard.
"""
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path('/root/r3_own_pool')
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'collab_scheduler_v1/joint_search_v1/review'

from static_dag_v0.tatqa_benchmark_build import literals
from static_dag_v0.multidag_dynamic import ctx_table, ctx_text

DATA = ROOT / 'data/tatqa/tatqa_dataset_train.json'
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
SPLIT_SALT = 'jointsearch_v1'
SEARCH_N, TEST_N = 8, 16


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def used_uids():
    """Superset exposure scan over the whole workspace EXCEPT the raw benchmark
    sources under data/ (the source population is not prior exposure — the
    historical scans never scanned it either). Strictly stronger than the
    historical static_dag_v0-only scan used by frozen200/confirm_dyn."""
    seen = set()
    data_root = ROOT / 'data'
    for p in ROOT.rglob('*'):
        if p.suffix not in ('.json', '.jsonl') or not p.is_file():
            continue
        if data_root in p.parents:
            continue
        try:
            if p.stat().st_size > 60_000_000:
                continue
            txt = p.read_text(errors='ignore')
        except OSError:
            continue
        seen.update(UUID_RE.findall(txt))
    return seen


def eligible_train():
    """Identical eligibility semantics to multidag_dynamic.hybrid_pool (the
    4-node e1(table)+e2(text) DAG lineage): answer_from='table-text' so BOTH
    extractors are load-bearing, arithmetic, evaluable derivation, >=2 distinct
    literals. Exposure filtering done by the caller via the workspace scan."""
    rows = json.loads(DATA.read_text())
    out = []
    for para in rows:
        for q in para['questions']:
            d = (q.get('derivation') or '').strip()
            if q.get('answer_from') != 'table-text':
                continue
            if q.get('answer_type') != 'arithmetic' or not d or not re.search(r'[+\-*/]', d):
                continue
            lits = [x for x in literals(d) if x not in (0.0, 1.0, 100.0)]
            if len(set(lits)) < 2:
                continue
            try:
                gold = eval(d, {'__builtins__': {}}, {})
            except Exception:
                continue
            if not isinstance(gold, (int, float)):
                continue
            out.append(dict(uid=q['uid'], question=q['question'],
                            derivation=d, answer=float(gold),
                            ctx_table=ctx_table(para), ctx_text=ctx_text(para),
                            _blob=q['question'] + json.dumps(para['table']['table'])
                            + ' '.join(x.get('text', str(x)) if isinstance(x, dict)
                                       else str(x) for x in para['paragraphs'])))
    return out


def split_panel(fresh):
    ordered = sorted(fresh, key=lambda t: sha(SPLIT_SALT + ':' + t['uid']))
    return ordered[:SEARCH_N], ordered[SEARCH_N:SEARCH_N + TEST_N], ordered[SEARCH_N + TEST_N:]


def paired_power(arm_a, arm_b):
    """Paired-binary discordance between two arms over shared uids."""
    uids = [u for u in arm_a if u in arm_b]
    n = len(uids)
    n10 = sum(1 for u in uids if arm_a[u]['ok'] and not arm_b[u]['ok'])
    n01 = sum(1 for u in uids if not arm_a[u]['ok'] and arm_b[u]['ok'])
    return dict(n=n, n10=n10, n01=n01, discordance=(n10 + n01) / n,
                marginal_delta=(n10 - n01) / n)


def mde(discordance, n, alpha=0.05, power=0.8):
    z_a, z_b = 1.959964, 0.841621
    return (z_a + z_b) * math.sqrt(discordance / n)


def run():
    checks = {}

    # ---- 1. provenance + fresh pool (guard applied BEFORE split, as in freeze()) ----
    used = used_uids()
    eligible = eligible_train()
    fresh = [t for t in eligible if t['uid'] not in used]

    from transformers import AutoTokenizer
    from static_dag_v0 import run as engine
    tok = AutoTokenizer.from_pretrained(
        engine.MODELS['medium']['path'], local_files_only=True)

    def guard_ok(t):
        # same blob construction as multidag_dynamic.freeze()
        plen = len(tok.apply_chat_template(
            [dict(role='user', content=t['_blob'])],
            tokenize=True, add_generation_prompt=True))
        return plen + 512 <= 8192

    fresh = [t for t in fresh if guard_ok(t)]
    checks['c_fresh_pool_ge_24'] = len(fresh) >= SEARCH_N + TEST_N

    # ---- 2. deterministic split ----
    search, test, reserve = split_panel(fresh)
    s2, t2, _ = split_panel(fresh)
    checks['c_split_deterministic'] = (
        [t['uid'] for t in search] == [t['uid'] for t in s2]
        and [t['uid'] for t in test] == [t['uid'] for t in t2])
    su, tu = {t['uid'] for t in search}, {t['uid'] for t in test}
    checks['c_panels_disjoint'] = not (su & tu)
    checks['c_zero_prior_exposure'] = not (su & used) and not (tu & used)
    checks['c_panel_sizes'] = len(search) == SEARCH_N and len(test) == TEST_N

    # ---- 3. format + tokenizer guard ----
    fields = ('uid', 'question', 'derivation', 'answer', 'ctx_table', 'ctx_text')

    def task_valid(t):
        if any(k not in t for k in fields):
            return False
        lits = [x for x in literals(t['derivation']) if x not in (0.0, 1.0, 100.0)]
        return (isinstance(t['answer'], float) and len(set(lits)) >= 2
                and re.search(r'[+\-*/]', t['derivation']) is not None)

    checks['c_search_format_valid'] = all(task_valid(t) for t in search)
    checks['c_test_format_valid'] = all(task_valid(t) for t in test)
    checks['c_search_tokenizer_guard'] = all(guard_ok(t) for t in search)
    checks['c_test_tokenizer_guard'] = all(guard_ok(t) for t in test)

    # ---- 4. power assessment (frozen200 corrected, per-task paired arms) ----
    fz = json.loads((ROOT / 'static_dag_v0/frozen200/FROZEN200_RESULTS_CORRECTED.json').read_text())
    res = fz['results']
    pairs = {
        'clean:static_vs_dynamic': paired_power(res['clean|static'], res['clean|dynamic']),
        'f30:static_vs_dynamic(seed_avg)': None,
        'clean_vs_f30:single': None,
    }
    f30_disc, f30_delta = [], []
    for seed in ('20260923', '20260924', '20260925'):
        p = paired_power(res[f'f30_s{seed}|static'], res[f'f30_s{seed}|dynamic'])
        f30_disc.append(p['discordance'])
        f30_delta.append(abs(p['marginal_delta']))
    pairs['f30:static_vs_dynamic(seed_avg)'] = dict(
        discordance_mean=sum(f30_disc) / 3, marginal_delta_mean_abs=sum(f30_delta) / 3)
    pairs['clean_vs_f30:single'] = paired_power(
        res['clean|single'], res['f30_s20260923|single'])

    disc_ref = max(
        pairs['clean:static_vs_dynamic']['discordance'],
        pairs['f30:static_vs_dynamic(seed_avg)']['discordance_mean'])
    power = dict(
        reference_pairs=pairs,
        discordance_reference=disc_ref,
        mde_search_n8=mde(disc_ref, SEARCH_N),
        mde_test_n16=mde(disc_ref, TEST_N),
        n_required_for_mde_0p15=math.ceil(((1.959964 + 0.841621) ** 2 * disc_ref) / 0.15 ** 2),
        method='paired binary, normal approx: MDE=(z_a/2+z_b)*sqrt(D/n); D=empirical '
               'discordance from frozen200 per-task arm outcomes (variance prior only; '
               'new X/Z space may differ)',
        interpretation=(f'With D={disc_ref:.3f}: SEARCH8 MDE≈{mde(disc_ref, SEARCH_N):.3f} '
                        '(per-config Q estimates cannot resolve <~0.2 — acceptable: search '
                        'SELECTS, it does not test); TEST16 MDE≈'
                        f'{mde(disc_ref, TEST_N):.3f} on paired marginal delta; n for '
                        f'MDE 0.15 = {math.ceil(((1.959964 + 0.841621) ** 2 * disc_ref) / 0.15 ** 2)}'))
    checks['c_power_numbers_recorded'] = all(
        math.isfinite(v) for v in (power['mde_search_n8'], power['mde_test_n16'],
                                   power['n_required_for_mde_0p15']))

    # ---- 5. budget fit ----
    proto = json.loads((ROOT / 'collab_scheduler_v1/joint_search_v1/SEARCH_BUDGET_V1.json').read_text())
    scen, caps = proto['scenario'], proto['per_session_caps']
    fit = dict(
        sessions=proto['campaign_caps']['sessions'],
        sessions_required=6 * len(proto['search_seeds']),
        scenario_requests=scen['simple_smoke_scaling_requests'],
        cap_requests=caps['new_request_attempts'],
        scenario_tokens=scen['simple_smoke_scaling_tokens'],
        cap_tokens=caps['new_total_tokens'],
        scenario_wall_s=scen['simple_smoke_scaling_wall_s'],
        cap_wall_s=caps['wall_seconds'])
    checks['c_sessions_fit'] = fit['sessions_required'] <= fit['sessions']
    checks['c_scenario_requests_fit'] = fit['scenario_requests'] <= fit['cap_requests']
    checks['c_scenario_tokens_fit'] = fit['scenario_tokens'] <= fit['cap_tokens']
    checks['c_scenario_wall_fit'] = fit['scenario_wall_s'] <= fit['cap_wall_s']

    # ---- 6. confirmation allocation estimate (separate envelope, NOT in 18) ----
    mean_tok = proto['measured']['mean_tokens_per_new_request']
    conf_logical = 6 * 2 * TEST_N * 8   # methods x states x tasks x max logical calls
    confirmation = dict(
        scope='final selection of each method evaluated once on TEST16 x {clean,fault30}',
        max_logical_calls=conf_logical,
        est_tokens_upper=conf_logical * mean_tok,
        est_tokens_upper_M=round(conf_logical * mean_tok / 1e6, 2),
        status='ESTIMATE ONLY — separate approval required before any execution')

    # ---- write frozen manifest ----
    def task_entry(t):
        canon = json.dumps({k: t[k] for k in fields}, sort_keys=True)
        e = {k: t[k] for k in fields}
        e['sha256'] = hashlib.sha256(canon.encode()).hexdigest()
        return e

    manifest = dict(
        version='TASK_PANEL_V1',
        status='FROZEN_FOR_APPROVAL_EXECUTION_NOT_AUTHORIZED',
        source=str(DATA),
        source_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
        eligibility='identical to multidag_dynamic.hybrid_pool (TAT-QA train, '
                    'answer_from=table-text so both extractors are load-bearing, '
                    'arithmetic, evaluable derivation, >=2 distinct literals); '
                    'tokenizer guard prompt+512<=8192 applied BEFORE split',
        exposure_rule='UUID superset scan over whole workspace r3_own_pool EXCLUDING '
                      'raw benchmark sources under data/ (source population is not '
                      'exposure; historically never scanned). Strictly stronger than '
                      'the historical static_dag_v0-only scan; frozen200/smoke/fault30 '
                      'tasks all excluded as exposed',
        split_rule=f'sha256("{SPLIT_SALT}:"+uid) ascending over fresh eligible pool; '
                   f'first {SEARCH_N} = search panel, next {TEST_N} = test panel',
        search_panel=dict(n=SEARCH_N, role='in-session evaluation panel for ALL methods '
                          'and seeds; identical; may be observed during search'),
        test_panel=dict(n=TEST_N, role='NEVER evaluated during search; one-shot '
                       'confirmatory evaluation of final selections only'),
        reserve=dict(n=len(reserve), role='unassigned; any use requires approval'),
        tasks_search=[task_entry(t) for t in search],
        tasks_test=[task_entry(t) for t in test],
        power=power, budget_fit=fit, confirmation_allocation=confirmation)
    (OUT / 'TASK_PANEL_V1.json').write_text(json.dumps(manifest, indent=1))

    all_pass = all(v for v in checks.values() if isinstance(v, bool))
    evidence = dict(checks=checks, all_pass=all_pass,
                    fresh_pool_size=len(fresh), eligible_pool_size=len(eligible),
                    used_uid_count=len(used),
                    search_uids=[t['uid'] for t in search],
                    test_uids=[t['uid'] for t in test],
                    power=power, budget_fit=fit, confirmation_allocation=confirmation,
                    notes=['SEARCH_BUDGET_V1.json left untouched (hash-bound protocol); '
                           'this manifest supersedes its task_panel:UNASSIGNED by reference',
                           'execution still requires approval of the resource envelope'])
    (OUT / 'TRACK_C_EVIDENCE.json').write_text(json.dumps(evidence, indent=1))
    print(json.dumps(checks, indent=1))
    print('power:', json.dumps(power['reference_pairs'], indent=1)[:400])
    print('MDE search8=%.3f test16=%.3f n_for_.15=%d' % (
        power['mde_search_n8'], power['mde_test_n16'], power['n_required_for_mde_0p15']))
    print('ALL PASS' if all_pass else 'FAIL PRESENT')
    return all_pass


if __name__ == '__main__':
    run()
