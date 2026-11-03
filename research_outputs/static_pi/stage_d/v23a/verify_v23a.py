"""Verify the Phase V2.3-A manifest and the frozen assets it depends on."""
import hashlib, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()
def verify(path, label):
    m = json.load(open(path, encoding='utf-8'))
    bad = [k for k, v in m['files'].items()
           if not os.path.exists(os.path.join(os.path.dirname(path), k))
           or sha(os.path.join(os.path.dirname(path), k)) != v['sha256']]
    print(f'{label}: {len(m["files"])} files, {"OK" if not bad else "MISMATCH " + str(bad[:5])}')
    return not bad
ok = verify(os.path.join(HERE, 'MANIFEST_V23A.json'), 'MANIFEST_V23A')
ok &= verify('/root/research_outputs/static_pi/stage_d/FREEZE_V23_SCORING.json', 'FREEZE_V23_SCORING')
ok &= verify('/root/research_outputs/static_pi/stage_d/MANIFEST_PHASE_PI_V2.json', 'MANIFEST_PHASE_PI_V2')
q = '/root/.worktrees/quality-v4/r3_own_pool/deadline_reward_v1/quality_v4/terminal_quality.py'
qok = sha(q) == '136b2e1b09c3fbc991da34a836e6638e36d5c04510975094fa90126ed37b352c'
print('terminal_quality v1.2.3:', 'OK' if qok else 'CHANGED')
sys.exit(0 if (ok and qok) else 1)
