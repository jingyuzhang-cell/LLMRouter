"""Zero-call acceptance tests for cap_eval_bench_v1 (B1-B7). No model calls."""
import json
import subprocess
import sys
from pathlib import Path

BENCH = Path('/root/cap_eval_bench_v1')
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / 'scoring'))
sys.path.insert(0, str(BENCH / 'evidence'))
from bench_common import norm                     # noqa: E402
import qe_k_scorer as S                            # noqa: E402
import retrieval_api as R                          # noqa: E402

ok = fail = 0


def check(name, cond, detail=''):
    global ok, fail
    ok += bool(cond)
    fail += (not cond)
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")


# B1 every silver fact re-grounded in the frozen evidence texts
n_total = n_ok = 0
for p in sorted((BENCH / 'scoring' / 'silver').glob('T-*.silver.json')):
    d = json.loads(p.read_text())
    for f in d['silver']:
        n_total += 1
        full = ''.join((BENCH / 'evidence' / 'texts' / f"{f['evidence_doc']}.txt").read_text().split())
        n_ok += int(norm(f['quote']) in norm(full))
check('B1 silver grounding 100%', n_ok == n_total, f'{n_ok}/{n_total}')

# B2 isolation selftest clean
r = subprocess.run(['python3', str(BENCH / 'isolation' / 'gate.py'), 'selftest'],
                   capture_output=True, text=True)
check('B2 isolation selftest clean', r.returncode == 0, r.stdout.strip()[:80])

# B3 scorer on synthetic GOOD and BAD deliverables (T-R1)
task = S.load_task('T-R1')
silver = S.load_silver('T-R1')['silver']
good_text = '。'.join(f"{f['answer']}（{f['evidence_doc']}）" for f in silver) + \
    ' 社交媒体热度与传播情况：UNKNOWN（证据集未含）。 舆情情感倾向：UNKNOWN。'
qg = S.score_quality(task, good_text, silver, S.evidence_dates(task))
check('B3a good coverage=1.0', qg['coverage'] == 1.0, str(qg['coverage']))
check('B3b good unknown_compliance=1.0', qg['unknown_compliance'] == 1.0)
check('B3c good citation_accuracy=1.0', qg['citation_accuracy'] == 1.0, str(qg['citation_accuracy']))
bad_text = '公司于2024-07-08停牌。'  # one date fact, wrong citation absent, fabricated date
qb = S.score_quality(task, bad_text, silver, S.evidence_dates(task))
check('B3d hallucination date penalised', qb['hallucination_penalty'] >= 0.05 and
      '2024-07-08' in qb['hallucination_dates'] or qb['coverage'] > 0, str(qb['hallucination_dates'])[:60])
trace_bad = {'task_id': 'T-R1', 'status': 'INCOMPLETE', 'nodes': [
    {'node_id': 'n1', 'model': 'M', 'attempt': 1, 'usage': {'in': 100, 'out': 50},
     'latency_s': 1.0, 'parse_status': 'OK'},
    {'node_id': 'n1', 'model': 'M', 'attempt': 2, 'usage': {'in': 110, 'out': 55},
     'latency_s': 1.1, 'parse_status': 'OK'}],
    'planning': {'usage': {'in': 200, 'out': 80}, 'latency_s': 2.0},
    'retrieval': {'calls': 1, 'chars_injected': 3000}, 'wall_s': 9999.0}
kb = S.score_reliability(task, trace_bad, {'report': 'x'})
check('B3e incomplete verdict + deadline fail', kb['verdict'] == 'INCOMPLETE'
      and kb['deadline_compliance'] is False, kb['verdict'])
eb = S.score_efficiency(trace_bad)
check('B3f E vector separates first/repair/planning', eb['C_model_first'] == 150
      and eb['C_model_repair'] == 165 and eb['C_planning'] == 280, json.dumps(eb)[:120])

# B4 retrieval determinism + budget + logging
(BENCH / 'evidence' / 'retrieval_log.jsonl').write_text('')
a, ua = R.retrieve('T-R1', 'TEST', ['约谈', '暂停', '异常波动'], 3300)
b, ub = R.retrieve('T-R1', 'TEST', ['约谈', '暂停', '异常波动'], 3300)
check('B4a retrieval deterministic', [c['chunk_id'] for c in a] == [c['chunk_id'] for c in b])
check('B4b budget respected', ua <= 3300)
logged = (BENCH / 'evidence' / 'retrieval_log.jsonl').read_text().strip().splitlines()
check('B4c retrieval logged', len(logged) >= 2 and 'chars_injected' in logged[-1])

# B5 public tasks carry no silver/branch content
pub = (BENCH / 'tasks' / 'tasks_frozen.jsonl').read_text()
check('B5 public tasks clean of branch keys', 'branch' not in pub and 'silver_source' not in pub)

# B6 all 8 tasks reference existing evidence docs & have required keys
docs = {d['doc_id'] for d in json.loads((BENCH / 'evidence' / 'index.json').read_text())}
bad = 0
for l in pub.splitlines():
    t = json.loads(l)
    bad += int(not set(t['evidence_doc_ids']) <= docs)
    bad += int(not (t.get('question') and t.get('information_cutoff') and t.get('deadline_s')))
check('B6 task referential integrity', bad == 0)

# B7 freeze manifest verifies
man = json.loads((BENCH / 'BENCH_FREEZE_MANIFEST.json').read_text())
import hashlib
mismatch = []
for rel, sha in man['files'].items():
    p = BENCH / rel
    if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
        mismatch.append(rel)
check('B7 freeze manifest matches', not mismatch, str(mismatch[:3]))

print(f'\nBENCH TESTS: {ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
