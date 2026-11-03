import sys
sys.path.insert(0, '/root/capital_opinion_pilot/v5_final_acceptance_20261022_v1/isolated')
from runtime_loader import load_runtime_input
ok=fail=0
def check(n,c,d=''):
    global ok,fail; ok+=bool(c); fail+=(not c); print(('PASS' if c else 'FAIL'),n,d)
import tempfile, pathlib
d=tempfile.mkdtemp()
pathlib.Path(d,'task.md').write_text('t')
pathlib.Path(d,'gold').mkdir(); pathlib.Path(d,'gold','facts.json').write_text('{}')
check('task.md allowed', load_runtime_input(d,'task.md')=='t')
try:
    load_runtime_input(d,'gold/facts.json'); check('gold blocked',False)
except PermissionError: check('gold blocked',True)
try:
    load_runtime_input(d,'evidence/text/D1.txt'); check('arbitrary path blocked',False)
except PermissionError: check('arbitrary path blocked',True)
print(f'GOLD ISOLATION: {ok} passed, {fail} failed'); sys.exit(1 if fail else 0)
