"""Phase V2.3-A / S2 runner: paired target-field ablation (A=full, B=ablated).

Hard caps (operator-authorized): 252 calls, 2,300,000 tokens, ¥4.00.
Task order is a pre-registered random permutation; within a task the 4 cells
(A/B x rep) are randomized. If a cap is hit, the run stops and reports
INCOMPLETE with the completed cells; pair integrity is never broken.

Modes:
  --mock   : deterministic zero-call rehearsal (validates wiring, grading, caps)
  (default): real GLM-5.3-flash calls
"""
import argparse, json, os, random, sys, time
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v23a')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_d/v2')
sys.path.insert(0, '/root/research_outputs/static_pi/stage_a')
import s2_prompts as P
import s2_grade as G
import real_provider_v22 as R
from stage_d_v2_transport import Transport, Ledger

ROOT = '/root/research_outputs/static_pi/stage_d/v23a'
SEED = 20261102
CAP_CALLS = 252
CAP_TOKENS = 2_300_000
CAP_YUAN = 4.0


def load_candidates():
    d = json.load(open(f'{ROOT}/TASK_CANDIDATES_V23A.json'))
    return [t for t in d['candidates'] if t['s0_s1_verdict'] == 'S2_ELIGIBLE']


def field_brief(contract):
    brief = []
    for f in contract.get('required_facts', []):
        b = f.get('bucket') or f.get('subject') or f['fact_id']
        if b not in brief:
            brief.append(b)
    return brief


def target_docs(contract, target_slots):
    facts = {f['fact_id']: f for f in contract.get('required_facts', [])}
    docs = set()
    for fid in target_slots:
        for ev in (facts.get(fid, {}) or {}).get('source_evidence') or []:
            docs.add(ev.get('doc_id'))
    return sorted(d for d in docs if d)


def target_buckets(contract, target_slots):
    facts = {f['fact_id']: f for f in contract.get('required_facts', [])}
    return sorted({(facts[f].get('bucket') or facts[f].get('subject') or f) for f in target_slots if f in facts})


def run_cell(task, cond, rep, provider_call, contract):
    docs = list(contract['source_pages'].keys())
    brief_all = field_brief(contract)
    tdocs = set(target_docs(contract, task['target_slots']))
    tbuckets = set(target_buckets(contract, task['target_slots']))
    e_outputs, truncated = {}, []
    for doc_id in docs:
        brief = brief_all
        if cond == 'B' and doc_id in tdocs:
            brief = [b for b in brief_all if b not in tbuckets]
        system = P.system('E')
        user = P.e_user(contract['question'], doc_id, P.doc_text(contract, doc_id), brief)
        txt, stop = provider_call('E', f'E:{doc_id}', system, user, P.max_tokens('E'))
        if stop == 'max_tokens':
            truncated.append(doc_id)
        try:
            e_outputs[doc_id] = R.extract_any(txt)
        except Exception:
            e_outputs[doc_id] = {'raw': txt[:2000], 'parse_error': True}
    jtxt, jstop = provider_call('J', 'J', P.system('J'),
                                P.j_user(contract['question'], e_outputs), P.max_tokens('J'))
    try:
        jout = R.extract_any(jtxt)
    except Exception:
        jout = {'raw': jtxt[:2000], 'parse_error': True}
    stxt, sstop = provider_call('SINK', 'SINK', P.system('SINK'),
                                P.sink_user(contract['question'], jout, contract), P.max_tokens('SINK'))
    try:
        sink = R.extract_any(stxt)
    except Exception:
        sink = None
    grades = G.grade(sink, contract, task['target_slots'])
    return dict(task_id=task['task_id'], condition=cond, repeat=rep,
                target_slots=task['target_slots'], grades=grades,
                parse_ok=sink is not None,
                truncated=truncated + ([ 'J' ] if jstop == 'max_tokens' else []) +
                          (['SINK'] if sstop == 'max_tokens' else []),
                completed=sum(1 for g in grades.values() if g.get('correct')),
                total=len(grades))


# ── mock provider (zero calls) ──────────────────────────────────────────────
def mock_call_factory(contract, task, cond):
    facts = {f['fact_id']: f for f in contract.get('required_facts', [])}
    tdocs = set(target_docs(contract, task['target_slots']))
    tbuckets = set(target_buckets(contract, task['target_slots']))

    def call(kind, node, system, user, max_tokens):
        if kind == 'E':
            doc_id = node.split(':', 1)[1]
            fields = []
            for f in contract['required_facts']:
                ev = (f.get('source_evidence') or [{}])[0]
                if ev.get('doc_id') != doc_id:
                    continue
                if cond == 'B' and doc_id in tdocs and (f.get('bucket') or f.get('subject')) in tbuckets:
                    continue   # ablated field is not extracted in condition B
                fields.append(dict(field=f.get('bucket') or f['fact_id'], value=f['value'],
                                   quote=ev.get('quote', ''), page=ev.get('page', 1)))
            return json.dumps({'fields': fields}, ensure_ascii=False), 'stop'
        if kind == 'J':
            return json.dumps({'checks': [], 'notes': ['mock']}), 'stop'
        # SINK: answer only what the E layer exposed
        exposed = set()
        for f in contract['required_facts']:
            ev = (f.get('source_evidence') or [{}])[0]
            key = (ev.get('doc_id'), f.get('bucket') or f.get('subject'))
            if cond == 'B' and key[0] in tdocs and key[1] in tbuckets:
                continue
            exposed.add(key)
        answers = []
        for f in contract['required_facts']:
            ev = (f.get('source_evidence') or [{}])[0]
            key = (ev.get('doc_id'), f.get('bucket') or f.get('subject'))
            if key not in exposed:
                continue
            answers.append(dict(fact_id=f['fact_id'], value=f['value'], doc=ev.get('doc_id'),
                                page=ev.get('page', 1), quote=ev.get('quote', '')))
        return json.dumps({'answers': answers, 'abstentions': [], 'complete': True},
                          ensure_ascii=False), 'stop'
    return call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mock', action='store_true')
    ap.add_argument('--limit', type=int, default=None)
    args = ap.parse_args()

    cands = load_candidates()
    if args.limit:
        cands = cands[:args.limit]
    order = list(range(len(cands)))
    random.Random(SEED).shuffle(order)
    cands = [cands[i] for i in order]

    if args.mock:
        ledger = None
        results = []
        for task in cands:
            contract = json.load(open(task['contract']))
            cells = [(c, r) for c in ('A', 'B') for r in (1, 2)]
            random.Random(SEED).shuffle(cells)
            for cond, rep in cells:
                call = mock_call_factory(contract, task, cond)
                results.append(run_cell(task, cond, rep, call, contract))
        json.dump(dict(batch='PHASE_V23A_S2_MOCK', real_calls=0, results=results),
                  open(f'{ROOT}/S2_MOCK_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
        print(f'mock: {len(results)} cells over {len(cands)} tasks; calls=0')
        return

    ledger = Ledger(f'{ROOT}/S2_LEDGER.jsonl')
    tr = Transport(ledger, cap_calls=CAP_CALLS, cap_tokens=CAP_TOKENS)

    def real_call(kind, node, system, user, max_tokens):
        if ledger.cost > CAP_YUAN:
            raise RuntimeError('cost cap')
        rec = tr.call('glm53flash', system, user, max_tokens,
                      purpose=f's2|{CURRENT["task"]}|{CURRENT["cond"]}|r{CURRENT["rep"]}|{node}')
        return rec['text'], rec['stop_reason']

    CURRENT = {}
    results, status = [], 'COMPLETE'
    for task in cands:
        contract = json.load(open(task['contract']))
        cells = [(c, r) for c in ('A', 'B') for r in (1, 2)]
        random.Random(SEED).shuffle(cells)
        for cond, rep in cells:
            CURRENT.update(task=task['event_key'], cond=cond, rep=rep)
            before = len(ledger.records)
            try:
                results.append(run_cell(task, cond, rep, real_call, contract))
            except Exception as e:
                msg = f'{type(e).__name__}: {e}'[:160]
                results.append(dict(task_id=task['task_id'], condition=cond, repeat=rep,
                                    error=msg))
                low = msg.lower()
                if 'cap' in low:
                    status = 'INCOMPLETE'
                elif '401' in low or 'unauthorized' in low or '403' in low or 'forbidden' in low:
                    status = 'ERROR_AUTH'
                else:
                    status = 'ERROR'
            json.dump(dict(batch='PHASE_V23A_S2_PROGRESS', status=status,
                           used=dict(calls=len(ledger.records), tokens=ledger.tokens,
                                     yuan=round(ledger.cost, 4)),
                           results=results),
                      open(f'{ROOT}/S2_PROGRESS.json.tmp', 'w'), ensure_ascii=False, indent=1)
            os.replace(f'{ROOT}/S2_PROGRESS.json.tmp', f'{ROOT}/S2_PROGRESS.json')
            print(f"  {task['event_key']:12s} {cond} r{rep} "
                  f"calls+{len(ledger.records)-before:2d} total={len(ledger.records):3d} "
                  f"tok={ledger.tokens:8d} ¥{ledger.cost:.3f}", flush=True)
            if status.startswith('ERROR') or status == 'INCOMPLETE':
                break
        if status.startswith('ERROR') or status == 'INCOMPLETE':
            break
    n_err = sum(1 for r in results if r.get('error'))
    if n_err and status == 'COMPLETE':
        status = 'ERROR' if n_err == len(results) else 'INCOMPLETE'
    json.dump(dict(batch='PHASE_V23A_S2', status=status, n_errors=n_err, seed=SEED, caps=dict(
        calls=CAP_CALLS, tokens=CAP_TOKENS, yuan=CAP_YUAN),
        used=dict(calls=len(ledger.records), tokens=ledger.tokens, yuan=round(ledger.cost, 4)),
        order=[t['event_key'] for t in cands], results=results),
        open(f'{ROOT}/S2_RESULTS.json', 'w'), ensure_ascii=False, indent=1)
    print(f'\n{status}: calls={len(ledger.records)}/{CAP_CALLS} tokens={ledger.tokens}/{CAP_TOKENS} '
          f'¥{ledger.cost:.3f}/{CAP_YUAN}')


if __name__ == '__main__':
    main()
