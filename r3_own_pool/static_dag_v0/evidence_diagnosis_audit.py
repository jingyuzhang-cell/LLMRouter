"""Zero-call audit of the evidence-diagnosis experiments (Dev-25 subset).

Recomputes, from frozen artifacts only:
  - Dev-25 selection (all-fail under propagated protocol)
  - Arm B (deterministic markdown parser + deployable top-30): operand coverage
    and RESCORED Q of the saved STRUCT_RSN answers
  - DIAG D2/D3/D4 saved answers: schema validity only; their paired inputs were
    never frozen, so their Q is NOT recomputable and stays unreported
  - Arms with no located artifacts (D0, D1, C_Gold): recorded as missing
  - ERV2 S0-S3 (100 failed tasks): first-time scoring of saved reasoning calls
    with the deterministic merge protocol from evidence_reconstruction_v2.run()

No model calls. Output: EVIDENCE_DIAGNOSIS_AUDIT.json
"""
import hashlib
import json
import re
import subprocess
import time

from . import core, tool_aware_v1 as v
from .decompose_v1 import exec_calc
from .recovery_matrix_v2_devset import BASE
from .recovery_matrix_v2_audit import close
from .capability_profiling import OUT as CPROF, POOL
from .capability_analysis import load_corpus
from .confirmation_200 import OUT as CONF1
from .confirmation_500 import OUT as CONF5
from .evidence_reconstruction_v2 import OUT as ERV2
from .structure_aware_dev import parse_structured, rank_by_proximity_deployable, gold_operands

OUT = BASE / 'structure_aware_experiment'
SE = BASE / 'structure_aware_experiment'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit():
    return subprocess.run(['git', '-C', str(core.ROOT), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True).stdout.strip()


def load_jsonl(path):
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                out[r['key']] = r
    return out


def q_of(answer, facts, gold):
    try:
        val = exec_calc(v.decode(answer)['expression'], facts)
        return int(close(val, gold))
    except Exception:
        return 0


def run():
    report = dict(generated_unix=time.time(), commit_hash=commit(),
                  evidence_tier='audit of frozen outputs; zero model calls',
                  scoring='exec_calc(v.decode(answer)["expression"], facts); close tol max(1e-4,1e-4*|gold|)')

    # ---- Dev-25 selection reproduced from frozen propagated results ----
    corpus = load_corpus()
    failed = [r for r in corpus if all(r['per_model'][m]['task_q'] == 0 for m in POOL)]
    dev = failed[:25]
    dev_uids = [r['uid'] for r in dev]
    pol = json.loads((CPROF / 'PROFILE_POLICY.json').read_text())
    task_of = {t['uid']: t for t in pol['tasks']}
    prof = load_jsonl(CPROF / 'RESPONSES.jsonl')

    struct = load_jsonl(SE / 'STRUCT_RSN.jsonl')
    diag = load_jsonl(SE / 'DIAG_RSN.jsonl')
    saved_struct_uids = sorted(k.split(':', 1)[1] for k in struct if k.startswith('STRUCT_RSN:'))
    saved_diag = {}
    for k in diag:
        variant, uid = k.split(':', 1)
        saved_diag.setdefault(variant, []).append(uid)

    # ---- Arm B: parser + deployable top-30, rescored ----
    rows_b = []
    for uid in dev_uids:
        t = task_of[uid]
        q_text, ctx, gold = t['question'], t['context'][:14000], t['answer']
        s_facts = parse_structured(ctx, q_text)
        s_top = rank_by_proximity_deployable(s_facts, q_text, k=30)
        formatted = {'facts': [dict(value=f['value'], evidence=f.get('label', '')[:40]) for f in s_top]}
        ops = gold_operands(uid)
        top_vals = [f['value'] for f in s_top]
        full_vals = [f['value'] for f in s_facts]
        cov_top = (sum(1 for x in ops if any(abs(x - y) < 0.01 for y in top_vals)) / len(ops)) if ops else 1.0
        cov_full = (sum(1 for x in ops if any(abs(x - y) < 0.01 for y in full_vals)) / len(ops)) if ops else 1.0
        rec = struct.get('STRUCT_RSN:' + uid)
        ans = rec['response']['answer'] if rec else None
        rows_b.append(dict(
            uid=uid,
            n_structured=len(s_facts), n_top=len(s_top), n_ops=len(ops),
            operand_coverage_top30=round(cov_top, 4), operand_coverage_full=round(cov_full, 4),
            answer_saved=rec is not None,
            answer_schema_ok=bool(ans) and _schema_ok(ans),
            q_rescored=q_of(ans, formatted, gold) if ans else None))
    q_saved = json.loads((SE / 'STRUCT_REASONING_RESULTS.json').read_text())
    rescored = [r['q_rescored'] for r in rows_b]
    arm_b = dict(
        n=len(rows_b),
        operand_coverage_top30_tasks=sum(1 for r in rows_b if r['operand_coverage_top30'] == 1.0),
        operand_coverage_full_tasks=sum(1 for r in rows_b if r['operand_coverage_full'] == 1.0),
        answers_saved=sum(1 for r in rows_b if r['answer_saved']),
        answer_schema_ok=sum(1 for r in rows_b if r['answer_schema_ok']),
        Q_rescored=sum(x for x in rescored if x is not None) / len(dev_uids),
        saved_zero_vector_matches_rescore=bool(
            len(q_saved) == len(dev_uids) and all(x == 0 for x in q_saved)
            and all(x == 0 for x in rescored)),
        per_task=rows_b)

    # ---- DIAG D2-D4: schema validity only ----
    diag_out = {}
    for variant in sorted(saved_diag):
        uids = sorted(saved_diag[variant])
        entries = [diag.get(f'{variant}:{u}') for u in uids]
        diag_out[variant] = dict(
            n=len(uids),
            uids_match_dev25=sorted(uids) == sorted(dev_uids),
            answer_schema_ok=sum(1 for e in entries if e and _schema_ok(e['response']['answer'])),
            Q='not_recomputable: paired input facts were never frozen; prompts absent',
            note='answers are expressions over v-indices of unknown filtered fact lists')

    # ---- ERV2 S0-S3: first-time zero-call scoring of saved calls ----
    epol = json.loads((ERV2 / 'ERV2_POLICY.json').read_text())
    eresp = load_jsonl(ERV2 / 'RESPONSES.jsonl')

    def pf(key):
        r = eresp.get(key)
        if r is None:
            return {'facts': []}
        try:
            return v.parse_facts(r['response']['answer'])
        except Exception:
            return {'facts': []}

    arms = {s: [] for s in ['S0_baseline', 'S1_re-extract', 'S2_cross_model', 'S3_targeted_reconstruction']}
    cov_rows = []
    for t in epol['tasks']:
        uid, gold = t['uid'], t['answer']
        fA, f1, f2 = pf('A:' + uid), pf('S1_ext:' + uid), pf('S2_ext:' + uid)
        merged = list(fA['facts'])
        existing = {round(f['value'], 6) for f in merged}
        for nf in pf('S3_target:' + uid)['facts']:
            if round(nf['value'], 6) not in existing:
                merged.append(dict(value=nf['value'], evidence='reconstructed'))
                existing.add(round(nf['value'], 6))
        keys = {'S0_baseline': ('S0_rsn:' + uid, fA),
                'S1_re-extract': ('S1_rsn:' + uid, f1),
                'S2_cross_model': ('S2_rsn:' + uid, f2),
                'S3_targeted_reconstruction': ('S3_rsn:' + uid, {'facts': merged})}
        for arm, (k, facts) in keys.items():
            r = eresp.get(k)
            arms[arm].append(q_of(r['response']['answer'], facts, gold) if r else None)
        req = []
        for args in re.findall(r'\(([^()]*)\)', t.get('program', '')):
            for x in args.split(','):
                x = x.strip()
                if x.startswith('#') or x.startswith('const_'):
                    continue
                try:
                    req.append(float(x))
                except ValueError:
                    pass
        req = sorted(set(req))
        have = {round(f['value'], 6) for f in fA['facts']}
        cov_rows.append(sum(1 for x in req if any(abs(x - y) <= 1e-4 * max(1, abs(x)) for y in have)) / len(req) if req else 1.0)
    erv2 = dict(
        n=len(epol['tasks']), selection=epol['selection'],
        extraction_operand_coverage_mean_A=round(sum(cov_rows) / len(cov_rows), 4),
        Q={a: round(sum(x for x in v_ if x is not None) / len(epol['tasks']), 4) for a, v_ in arms.items()},
        note='first-time scoring of previously unscored frozen calls; exploratory, not a frozen pre-registered analysis')

    report.update(dict(
        dev25_selection=dict(n_propagated_allfail=len(failed), selected=dev_uids,
                             struct_uids_match=saved_struct_uids == sorted(dev_uids),
                             diag_variants={k: sorted(u) == sorted(dev_uids) for k, u in saved_diag.items()}),
        arm_B_parser=arm_b,
        diag_variants=diag_out,
        missing_artifacts=dict(
            D0='no frozen outputs located; the "Q=0%" claim has no auditable artifact',
            D1='no frozen outputs located; the "4% (1/25)" claim has no auditable artifact',
            C_gold_facts='never executed on Dev-25 (feasibility notes only); no Q exists'),
        erv2_100_failed=erv2,
        source_files={str(p.relative_to(core.ROOT)): sha(p) for p in [
            CPROF / 'RESPONSES.jsonl', CPROF / 'PROFILE_POLICY.json',
            SE / 'STRUCT_RSN.jsonl', SE / 'DIAG_RSN.jsonl',
            SE / 'STRUCT_REASONING_RESULTS.json', SE / 'dev_structured_results.json',
            ERV2 / 'RESPONSES.jsonl', ERV2 / 'ERV2_POLICY.json']},
        conclusion='coverage recovered does not imply reasoning recovered: parser top-30 covers '
                   'gold operands on %d/%d tasks yet rescoring yields Q=%d/%d; DIAG variant claims '
                   'remain unreported because paired inputs were not frozen.' % (
                       arm_b['operand_coverage_top30_tasks'], arm_b['n'],
                       round(arm_b['Q_rescored'] * arm_b['n']), arm_b['n'])))
    (SE / 'EVIDENCE_DIAGNOSIS_AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ['dev25_selection', 'arm_B_parser',
          'diag_variants', 'missing_artifacts', 'erv2_100_failed']}, ensure_ascii=False, indent=1)[:2600])


def _schema_ok(answer):
    try:
        v.decode(answer)['expression']
        return True
    except Exception:
        return False


if __name__ == '__main__':
    run()
