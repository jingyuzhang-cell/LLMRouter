"""Live progress for the node capability benchmark collection (stateless)."""
import json
import time
from pathlib import Path

OUT = Path(__file__).resolve().parent
SLOTS = ['medium', 'large', 'coder', 'reasoning']
TOTAL = 316


def main():
    print(f"[{time.strftime('%H:%M:%S')}] node benchmark collection")
    done_total = 0
    for s in SLOTS:
        f = OUT / (s + '_RESPONSES.jsonl')
        n = sum(1 for _ in f.open()) if f.exists() else 0
        done_total += n
        st = json.loads((OUT / (s + '_STATUS.json')).read_text()) if (OUT / (s + '_STATUS.json')).exists() else {}
        phase = st.get('phase', 'QUEUED' if n == 0 else 'RUNNING')
        print(f"  {s:9s} {phase:10s} {n:3d}/{TOTAL}")
    st = json.loads((OUT / 'medium_STATUS.json').read_text()) if (OUT / 'medium_STATUS.json').exists() else {}
    print(f"  total {done_total}/1264 calls ({100 * done_total / 1264:.0f}%)")


if __name__ == '__main__':
    main()
