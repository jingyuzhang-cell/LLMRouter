"""Complete five-repeat labels for the full frozen 400-query knowledge panel."""
import json
from pathlib import Path

from .data import read_rows, sha
from . import collect_repeat_compatibility_115 as collector

ROOT = Path(__file__).resolve().parents[1]
PANEL_DIR = ROOT / "router_v2/mmlu_utility_panel_400"
OUT = ROOT / "data/repeat_compatibility_400"
LOCAL_REUSE = ROOT / "data/repeat_compatibility_115"


def seed_local_reuse():
    if OUT.exists():
        return
    status=json.loads((LOCAL_REUSE/'STATUS.json').read_text())
    if status.get('phase')!='REPEAT_LABELS_COMPLETE': raise ValueError('Local 115-query repeats incomplete')
    panel_ids={r['query_id'] for r in read_rows(PANEL_DIR/'PANEL.jsonl')}
    OUT.mkdir(parents=True)
    for slot in ('medium','coder'):
        source=LOCAL_REUSE/f'{slot}.jsonl'; source_hash=sha(source)
        if source_hash!=status['raw_sha256'][slot]: raise ValueError(f'Local reuse hash changed: {slot}')
        rows=read_rows(source)
        if len(rows)!=575 or any(r['query_id'] not in panel_ids for r in rows): raise ValueError(f'Bad local reuse: {slot}')
        with (OUT/f'{slot}.jsonl').open('x') as stream:
            for row in rows:
                stream.write(json.dumps({**row,'reuse_provenance':{'path':str(source),'sha256':source_hash}},ensure_ascii=False)+'\n')
    (OUT/'LOCAL_REUSE_AUDIT.json').write_text(json.dumps({'source_status_sha256':sha(LOCAL_REUSE/'STATUS.json'),
      'records':{'medium':575,'coder':575},'queries':115},indent=2)+'\n')


def main():
    seed_local_reuse()
    collector.PANEL_DIR=PANEL_DIR
    collector.OUT=OUT
    collector.main()

if __name__=='__main__':
    main()
