"""Wait for existing collectors, then run P1 once; never sends API requests."""
import json, time, subprocess, sys, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
PANEL=ROOT/'router_v2/mmlu_utility_panel_400'
DATA=ROOT/'data/mmlu_utility_repeats_400'
STATE=PANEL/'P1_PIPELINE_STATUS.json'
def state(phase, **extra):
    value=dict(phase=phase,updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra)
    tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(STATE)
def main():
    deadline=time.monotonic()+24*3600
    while True:
        statuses={}
        for slot in ('large','reasoning'):
            try:statuses[slot]=json.loads((DATA/(slot+'_STATUS.json')).read_text())
            except (FileNotFoundError,json.JSONDecodeError):statuses[slot]={'phase':'WAITING'}
        if any(s['phase']=='CIRCUIT_OPEN' for s in statuses.values()):
            state('BLOCKED_COLLECTION_FAILURE',collectors=statuses);return
        if all(s['phase']=='FINISHED' for s in statuses.values()):break
        if time.monotonic()>deadline:
            state('BLOCKED_COLLECTION_TIMEOUT',collectors=statuses);return
        state('WAITING_FOR_COLLECTION',collectors=statuses);time.sleep(30)
    state('BUILDING_DISTRIBUTIONS')
    subprocess.run([sys.executable,'-m','router_v2.utility_distributions','--panel-dir',str(PANEL),'--data-dir',str(DATA)],cwd=ROOT,check=True)
    status=json.loads((DATA/'DISTRIBUTION_STATUS.json').read_text())
    if not status['complete']:
        state('BLOCKED_INCOMPLETE_PAIRS',n_complete=status['n_complete'],invalid_excluded=status['invalid_excluded']);return
    state('RUNNING_P1')
    output=ROOT/'router_v2/mmlu_learnability_400'
    subprocess.run([sys.executable,'-m','router_v2.mmlu_learnability','--panel-dir',str(PANEL),'--data-dir',str(DATA),'--output',str(output)],cwd=ROOT,check=True)
    result=json.loads((output/'RESULTS.json').read_text())
    state('P1_COMPLETE',signal_gate_pass=result['signal_gate_pass'],report=str(output/'REPORT.md'),ma_training='NOT_STARTED')
if __name__=='__main__':
    try:main()
    except Exception as exc:
        state('BLOCKED_PIPELINE_ERROR',error=str(exc));raise
