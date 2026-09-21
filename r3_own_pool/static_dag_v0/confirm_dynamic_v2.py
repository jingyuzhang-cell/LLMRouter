"""Large-scale frozen Dynamic-v2 confirmation (pre-registered one-shot).

Purpose: separate a real small effect from sample noise for the +2.1pp Live
Static-vs-Dynamic-v2 result (48 tasks, CI covers 0). NOT an attempt to improve
the number: the Dynamic-v2 policy, thresholds, prompts, budget rule and fallback
tables are byte-identical to live_static_dynamic (FROZEN_COMMIT 8417776
semantics); no re-tuning on any confirmation data before the run.

Task source: TAT-QA train split (data/tatqa/tatqa_dataset_train.json), which no
prior experiment in this workspace has touched (availability audit 2026-09-21:
dev split fresh remainder 47; train split 1,867 eligible, 0 seen in any
workspace artifact). Same eligibility filter as scale_up_collect.build_tq_tasks
plus a tokenizer length guard (prompt + 512 <= 8192).

Selection: sha256("confirm_dyn:"+uid) ascending, first 250. Frozen before any
call. The runner reuses live_static_dynamic.run() unmodified via module OUT
override; the policy file is named LIVE_POLICY.json only because that is the
filename the frozen runner reads.
"""
import hashlib
import json
import re

from . import core
from .recovery_matrix_v2_devset import BASE
from .tatqa_benchmark_build import literals, context

DATA = core.ROOT / 'data/tatqa/tatqa_dataset_train.json'
N_TASKS = 250
MIN_TASKS = 200
SEEN_SCAN_ROOT = core.ROOT / 'static_dag_v0'
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

OUT = BASE / 'dynamic_v2_confirm_250'


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def used_uids():
    """Aggressive superset: every UUID appearing in any workspace json/jsonl."""
    seen = set()
    for p in SEEN_SCAN_ROOT.rglob('*'):
        if p.suffix not in ('.json', '.jsonl') or not p.is_file():
            continue
        try:
            txt = p.read_text(errors='ignore')
        except Exception:
            continue
        if len(txt) > 60_000_000:
            continue
        seen.update(UUID_RE.findall(txt))
    return seen


def eligible_train():
    rows = json.loads(DATA.read_text())
    out = []
    for para in rows:
        for q in para['questions']:
            d = (q.get('derivation') or '').strip()
            if q.get('answer_type') != 'arithmetic' or not d or not re.search(r'[+\-*/]', d):
                continue
            lits = [x for x in literals(d) if x not in (0.0, 1.0, 100.0)]
            if len(set(lits)) < 2:
                continue
            try:
                gold = eval(d, {'__builtins__': {}}, {})
            except Exception:
                continue
            if isinstance(gold, (int, float)):
                out.append(dict(uid=q['uid'], question=q['question'], derivation=d,
                                answer=float(gold), context=context(para)))
    return out


def freeze():
    seen = used_uids()
    pool = [t for t in eligible_train() if t['uid'] not in seen]
    from . import run as engine
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(engine.MODELS['medium']['path'], local_files_only=True)
    sized = []
    for t in pool:
        prompt_len = len(tok.apply_chat_template(
            [dict(role='user', content=t['context'])], tokenize=True, add_generation_prompt=True))
        if prompt_len + 512 <= 8192:
            sized.append(t)
    sized.sort(key=lambda t: sha('confirm_dyn:' + t['uid']))
    assert len(sized) >= MIN_TASKS, len(sized)
    sel = sized[:N_TASKS]
    uids = [t['uid'] for t in sel]
    assert len(set(uids)) == len(uids)
    policy = dict(
        role='dynamic_v2_large_scale_confirmation_one_shot',
        frozen_commit='8417776 (live_static_dynamic policy semantics, unchanged)',
        n_tasks=len(sel), n_target=N_TASKS,
        selection='sha256("confirm_dyn:"+uid) ascending; TAT-QA train split; zero overlap with any workspace artifact (UUID superset scan); tokenizer guard prompt+512<=8192; no headroom/failure screening',
        availability_audit=dict(dev_fresh_remainder=47, train_eligible_fresh=len(sized)),
        dag='extraction(large) -> reasoning(medium); success = expression on consumed facts == gold (close, 1e-4 rel)',
        static_policy='node failure -> one local fallback (extraction large->coder; reasoning medium->coder); downstream plan unchanged; recovered outputs propagate',
        dynamic_policy=('extraction fallback switches large->medium after the first primary extraction failure (memory in task order); '
                        'reasoning failure escalates to large (stronger untried model), budget-gated; real outputs propagate; '
                        'selective: reasoning is the only affected descendant; topology unchanged'),
        budget='per-task = 1.2 x Static arm realized tokens; B_rem recomputed after every call; exhausted budget -> escalation skipped and recorded',
        generation='temperature 0, top_p 1, max_tokens 512 via run.call_model',
        metrics_preregistered='paired delta-Q task-level bootstrap CI (B=10000), McNemar exact, Help/Harm, tokens, latency, budget violations; confirmatory interpretation only',
        tasks=sel)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'LIVE_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    (OUT / 'CONFIRM_POLICY.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    print(json.dumps(dict(frozen=True, n=len(sel), fresh_pool=len(sized)), ensure_ascii=False))


def run():
    if not (OUT / 'LIVE_POLICY.json').exists():
        freeze()
    pol = json.loads((OUT / 'LIVE_POLICY.json').read_text())
    assert pol['n_tasks'] == N_TASKS
    from . import live_static_dynamic as L
    L.OUT = OUT
    L.run()


if __name__ == '__main__':
    run()
