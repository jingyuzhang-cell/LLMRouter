"""Live progress for the label-repair reasoning collection (stateless)."""
import json
import time
from pathlib import Path

RAW = Path(__file__).resolve().parent / 'raw'
TARGET = 1030


def main():
    status = json.loads((RAW / 'reasoning_STATUS.json').read_text())
    stamps = [json.loads(l)['unix_time'] for l in (RAW / 'reasoning.jsonl').open()]
    now = time.time()
    recent = sum(1 for t in stamps if now - t < 1800)
    rate = recent / 30.0
    done, failures = status['completed'], status.get('failures', 0)
    eta = (TARGET - done) / rate if rate > 1e-6 else float('inf')
    print(f"[{time.strftime('%H:%M:%S')}] {status.get('phase')}: {done}/{TARGET} ({100 * done / TARGET:.1f}%)  "
          f"failures={failures}  attempts={status.get('attempts')}")
    print(f"  rate(30min window): {rate:.1f}/min  remaining={TARGET - done}  "
          f"ETA≈{eta:.0f}min" + (' (inf=s stalled)' if eta > 1e6 else ''))
    slow = [t for t in stamps if now - t < 1800]
    if slow:
        print(f"  last completed row: {(now - max(stamps)) / 60:.1f} min ago")


if __name__ == '__main__':
    main()
