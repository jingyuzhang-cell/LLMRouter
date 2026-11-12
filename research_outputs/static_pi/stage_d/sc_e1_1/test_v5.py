"""Offline checks for detectors V5 (zero calls): old replays unchanged, probe labels classified."""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).parent.parent))
import detectors_v4 as V4, detectors_v5 as V5, sc_e1_1_runner as R, sc_e1_runner as OLD, sc_e1_scorer as SC, sc_e1_1_stage_a2 as A2
V5.verify_pins()
RES = []
def chk(n, c, d=''):
    RES.append((n, bool(c))); print(f'  {n:<74} {"PASS" if c else "FAIL"} {"" if c else d}')
ct = SC.load_contract(); docs, slots_json = R.load_task(ct); slots = json.loads(slots_json)
e = A2.load_reused_e(Path(__file__).parent / 'canary_A', docs)
rows, _ = R.evidence_rows(e, SC.doc_index(ct))
j2s = [r for p in (Path(__file__).parent / 'canary_A2/LEDGER.jsonl', Path(__file__).parent / 'fork_t1/run/LEDGER.jsonl') for r in R.read_ledger(p) if r['phase'] == 'done' and r['node'] == 'J2']
diff = []
for r in j2s:
    a, b = V4.detect_m1(slots, OLD.extract_json(r['text']), rows), V5.detect_m1(slots, OLD.extract_json(r['text']), rows)
    diff += [f for f in a if a[f]['state'] != b[f]['state']]
chk('M1 unchanged on all nine pre-probe J2 outputs', not diff, diff[:5])
probe = [r for r in R.read_ledger(Path(__file__).parent.parent / 'j2_probe/run/LEDGER.jsonl') if r['phase'] == 'done']
labels = {}
for r in probe:
    for v in (OLD.extract_json(r['text']) or {}).get('verified') or []:
        if isinstance(v, dict): labels[str(v.get('status')).strip().lower()] = V5.classify(v.get('status'))
chk('every probe label classified except the ambiguous inferred (kept unknown by design)', all(v in ('affirmed', 'suppressed') for k, v in labels.items() if k != 'inferred'), labels)
chk('正确 and 核验一致 affirmed; 材料未涉及/not_supported/not_in_material suppressed; inferred unknown',
    (labels.get('正确'), labels.get('核验一致'), labels.get('材料未涉及'), labels.get('not_supported'), labels.get('not_in_material'), labels.get('inferred')) == ('affirmed', 'affirmed', 'suppressed', 'suppressed', 'suppressed', 'unknown'), labels)
Path('V5_REGRESSION.json').write_text(json.dumps(dict(passed=sum(1 for _, ok in RES if ok), total=len(RES), labels=labels,
    files={p: hashlib.sha256((Path(__file__).parent / p).read_bytes()).hexdigest() for p in ('detectors_v5.py', 'detectors_v4.py')}), ensure_ascii=False, indent=1))
print(f"{sum(1 for _, ok in RES if ok)}/{len(RES)} passed"); sys.exit(0 if all(ok for _, ok in RES) else 1)
