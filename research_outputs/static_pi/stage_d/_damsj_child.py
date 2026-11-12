"""Child runner for DAMJS stress tests: simulates a DAG with configurable hangs.
Real mode is NOT reachable here (mock transport only) — zero-call by construction."""
import json, os, sys, time, argparse

KINDS = ['E1', 'E2', 'E3', 'E4', 'J1', 'J2', 'SINK', 'FMT']

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--progress', required=True)
    ap.add_argument('--cancel', required=True)
    ap.add_argument('--hang', default='')          # e.g. "E2:600"
    ap.add_argument('--slow', default='')          # e.g. "J1:52"
    ap.add_argument('--fail', default='')          # e.g. "J2"
    a = ap.parse_args()
    hang = dict((n, float(s)) for n, s in (x.split(':') for x in a.hang.split(',') if x))
    slow = dict((n, float(s)) for n, s in (x.split(':') for x in a.slow.split(',') if x))
    fail = set(x for x in a.fail.split(',') if x)

    def w(rec):
        with open(a.progress, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    for node in KINDS:
        if os.path.exists(a.cancel):
            w(dict(ev='node_abort', node=node, reason='cancel_token'))
            return 3
        w(dict(ev='node_start', node=node))
        t0 = time.time()
        if node in hang:
            # simulate a hung socket: loop so SIGTERM can land
            deadline = time.time() + hang[node]
            while time.time() < deadline:
                time.sleep(0.1)
        else:
            time.sleep(slow.get(node, 0.05))
        if node in fail:
            w(dict(ev='node_end', node=node, ok=False, err='simulated'))
            continue
        w(dict(ev='node_end', node=node, ok=True, output=f'out-{node}',
               wall=round(time.time() - t0, 2)))
    return 0

if __name__ == '__main__':
    sys.exit(main())
