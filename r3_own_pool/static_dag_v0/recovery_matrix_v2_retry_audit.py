"""Retry-semantics audit (zero model calls). For each of the 148 failure nodes, compare the
original historical reasoning call against the full-run retry_same call:
  - model / generation params / checkpoint (cross-era code identity)
  - prompt sha256 (byte-level)
  - answer exact match
Splits by data source because original pipelines differ in what fed the reasoning prompt
(gold facts for node-isolated benchmarks; own extraction output for scale_up)."""
import hashlib
import json
from collections import Counter, defaultdict
from . import tool_aware_v1 as v
from .tatqa_benchmark_build import literals
from .recovery_matrix_v2_full_prep import OUT

def sha(s):
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()

def load_jsonl(p):
    return [json.loads(l) for l in open(p).read().splitlines() if l.strip()]

def audit_retry():
    BASE = OUT.parent.parent
    # --- source indexes ---
    fresh_calls = {c['call_key']: c for c in json.loads((BASE / 'fresh_static_confirmation/CALLS.json').read_text())}
    fresh_resp = {}
    for r in load_jsonl(BASE / 'fresh_static_confirmation/medium_RESPONSES.jsonl'):
        fresh_resp[r['call_key']] = r
    tq_calls = {c['call_key']: c for c in json.loads((BASE / 'tatqa_benchmark/CALLS.json').read_text())}
    tq_resp = {}
    for r in load_jsonl(BASE / 'tatqa_benchmark/medium_RESPONSES.jsonl'):
        tq_resp[r['call_key']] = r
    tq_tasks = {t['uid']: t for t in json.loads((BASE / 'scale_up/TQ_TASKS.json').read_text())}
    su_rows = {r['key']: r for r in load_jsonl(BASE / 'scale_up/RESPONSES.jsonl')}
    # --- full-run retry records (success flags live in the audit output, not raw results) ---
    retry = {}
    for r in load_jsonl(OUT / 'FULL_ACTION_RESULTS.jsonl'):
        if r['action'] == 'retry_same':
            retry[r['node_id']] = r
    success = {res['node_id']: res['actions']['retry_same']['success']
               for res in json.loads((OUT / 'FULL_RESULTS.json').read_text())['results']}
    snaps = {s['node_id']: s for s in (json.loads(p.read_text()) for p in (OUT / 'runtime').glob('*.json'))}

    def original_reasoning(dom, uid):
        """Return (source, model, prompt_sha256_or_None, answer, facts_kind)."""
        if dom == 'multihiertt':
            c, r = fresh_calls[uid + ':rs'], fresh_resp[uid + ':rs']
            return 'multihiertt_benchmark_gold_facts', r.get('model'), sha(c['prompt']), r['answer'], 'gold_facts'
        if (uid + ':rs') in tq_resp:
            c, r = tq_calls[uid + ':rs'], tq_resp[uid + ':rs']
            return 'tatqa_benchmark_gold_facts', r.get('model'), sha(c['prompt']), r['answer'], 'gold_facts'
        rsn, ext = su_rows['tq:' + uid + ':rsn'], su_rows['tq:' + uid + ':ext']
        t = tq_tasks[uid]
        try:
            facts = v.parse_facts(ext['answer']); kind = 'own_extraction_facts'
        except Exception:
            facts = dict(facts=[dict(value=x, evidence='gold') for x in sorted({l for l in literals(t['derivation']) if l not in (0., 1., 100.)})])
            kind = 'gold_literal_fallback'
        prompt = v.sprompt(dict(question=t['question']), facts)
        return 'scale_up', rsn.get('model'), sha(prompt), rsn['answer'], kind

    rows = []
    for nid, snap in snaps.items():
        dom, uid = snap['domain'], snap['task_uid']
        ret = retry[nid]
        call = ret['calls'][0]
        src, o_model, o_prompt_sha, o_answer, facts_kind = original_reasoning(dom, uid)
        rows.append(dict(node_id=nid, domain=dom, label=None, source=src, facts_kind=facts_kind,
                         orig_model=o_model, retry_model=call['model'],
                         model_equal=o_model == call['model'],
                         prompt_sha_equal=o_prompt_sha == call.get('prompt_sha256', sha(call['prompt'])),
                         answer_exact_match=o_answer.strip() == call['response']['answer'].strip(),
                         retry_success=success[nid]))
    # attach labels
    lab = {s['node_id']: s['failure_type_gold'] for s in (json.loads(p.read_text()) for p in (OUT / 'offline').glob('*.json'))}
    for r in rows: r['label'] = lab[r['node_id']]

    def summarize(sel):
        n = len(sel)
        return dict(n=n,
                    model_equal=sum(r['model_equal'] for r in sel),
                    prompt_sha_equal=sum(r['prompt_sha_equal'] for r in sel),
                    answer_exact=sum(r['answer_exact_match'] for r in sel),
                    retry_success=sum(r['retry_success'] for r in sel)) if n else dict(n=0)

    by_source = {s: summarize([r for r in rows if r['source'] == s]) for s in sorted({r['source'] for r in rows})}
    matched = [r for r in rows if r['prompt_sha_equal']]
    mismatched = [r for r in rows if not r['prompt_sha_equal']]
    # cross-era generation-parameter identity: both eras call run.call_model; payload hardcoded
    run_src = (BASE / 'run.py').read_text()
    params = dict(temperature=0, top_p=1, max_tokens=512,
                  hardcoded_in_engine='temperature=0,top_p=1,max_tokens=512' in run_src.replace(' ', ''),
                  checkpoint_verified_by_sha256='weight_sha256' in run_src)
    summary = dict(
        n_nodes=len(rows),
        by_source=by_source,
        prompt_matched=dict(total=len(matched),
                            answer_exact=sum(r['answer_exact_match'] for r in matched),
                            retry_success=sum(r['retry_success'] for r in matched)),
        prompt_mismatched=dict(total=len(mismatched),
                               answer_exact=sum(r['answer_exact_match'] for r in mismatched),
                               retry_success=sum(r['retry_success'] for r in mismatched),
                               by_source=Counter(r['source'] for r in mismatched)),
        generation_params=params,
        verdict=None, per_node=rows)
    if summary['prompt_matched']['total'] and matched:
        m = summary['prompt_matched']
        summary['verdict'] = dict(
            true_re_execution_subset=m['total'],
            runtime_nondeterminism_rate=round(1 - m['answer_exact'] / m['total'], 4),
            re_execution_recovery_rate=round(m['retry_success'] / m['total'], 4))
    return summary

if __name__ == '__main__':
    s = audit_retry()
    per = s.pop('per_node')
    (OUT / 'RETRY_AUDIT.json').write_text(json.dumps(dict(**s, per_node=per), ensure_ascii=False, indent=2))
    print(json.dumps(s, ensure_ascii=False, indent=2, default=dict))
