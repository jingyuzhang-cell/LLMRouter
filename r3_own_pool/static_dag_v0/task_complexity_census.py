"""Task-complexity census: how many MultiHiertt / TAT-QA questions actually
admit a non-trivial computation DAG, vs. being 0-3 step calculations.

Ground truth is parsed from the official annotations, not model output:
  MultiHiertt  qa.program      step list, e.g. "add(5,11), add(#0,6), add(#1,10)"
  TAT-QA       q.derivation    infix expression, e.g. "(680-774)/774"

Per question we rebuild the computation DAG and measure
  n_ops    operator nodes           depth  longest dependency chain (ops)
  width    max ops schedulable in parallel (level width)
  chain    width == 1 (pure sequential; parallel scheduling is a no-op)
  n_leaves distinct numeric/cell operands (extraction leaves)
plus evidence-source spans (tables / paragraphs touched).

Writes task_complexity_census.json next to this file.
"""
import json
import re
import statistics as st
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MHTT_DIR = ROOT.parent.parent / 'phase_c9_0/external/MultiHiertt-data/multihiertt_data'
TATQA = {
    'train': ROOT.parent / 'data/tatqa/tatqa_dataset_train.json',
    'dev': ROOT.parent / 'data/tatqa/tatqa_dataset_dev.json',
}


# ---------------------------------------------------------------- TAT-QA infix
_NUM = r'\d+(?:\.\d+)?'
_TOK = re.compile(rf'({_NUM})|([-+*/<>=])|([()])')


def tokenize_infix(s):
    s = s.replace('[', '(').replace(']', ')').replace(',', '')
    s = re.sub(r'[$%]', '', s)
    toks, i = [], 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
            continue
        m = _TOK.match(s, i)
        if not m:
            return None
        if m.group(1):
            toks.append(('num', float(m.group(1))))
        elif m.group(2):
            toks.append(('op', m.group(2)))
        else:
            toks.append(('par', m.group(3)))
        i = m.end()
    return toks


class InfixParser:
    """Recursive descent over comparison < additive < multiplicative."""

    def __init__(self, toks):
        self.t = toks
        self.i = 0
        self.n_ops = 0
        self.depth = 0        # operator-only depth

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def parse(self):
        node = self.cmp_expr()
        if self.i != len(self.t) or node is None:
            return None
        return node

    def cmp_expr(self):
        node = self.add_expr()
        while self.peek() == ('op', '<') or self.peek() == ('op', '>') or self.peek() == ('op', '='):
            self.i += 1
            self.n_ops += 1
            d = self.depth
            self.depth = d + 1
            rhs = self.add_expr()
            if rhs is None:
                return None
            self.depth = d + 1
            node = ('op', node, rhs)
        return node

    def add_expr(self):
        node = self.mul_expr()
        while self.peek() in (('op', '+'), ('op', '-')):
            self.i += 1
            self.n_ops += 1
            d = self.depth
            rhs = self.mul_expr()
            if rhs is None:
                return None
            self.depth = d + 2
            node = ('op', node, rhs)
        return node

    def mul_expr(self):
        node = self.unary()
        while self.peek() in (('op', '*'), ('op', '/')):
            self.i += 1
            self.n_ops += 1
            d = self.depth
            rhs = self.unary()
            if rhs is None:
                return None
            self.depth = d + 2
            node = ('op', node, rhs)
        return node

    def unary(self):
        if self.peek() == ('op', '-'):
            self.i += 1
            node = self.unary()
            return node  # sign folded into the literal; not an extra op
        if self.peek() == ('par', '('):
            self.i += 1
            node = self.cmp_expr()
            if self.peek() != ('par', ')'):
                return None
            self.i += 1
            return node
        if self.peek()[0] == 'num':
            v = self.peek()[1]
            self.i += 1
            return ('leaf', v)
        return None


def _op_depth(n):
    if n[0] == 'leaf':
        return 0
    return 1 + max(_op_depth(n[1]), _op_depth(n[2]))


def dag_stats_infix(derivation):
    """Return (n_ops, depth, width, n_leaves, chain) or None if unparseable."""
    toks = tokenize_infix(derivation)
    if not toks:
        return None
    p = InfixParser(toks)
    tree = p.parse()
    if tree is None:
        return None
    # level width over operator nodes only
    levels = Counter()

    def walk(n, lv):
        if n[0] == 'leaf':
            return
        levels[lv] += 1
        walk(n[1], lv + 1)
        walk(n[2], lv + 1)

    walk(tree, 0)
    leaves = set()

    def collect(n, neg=False):
        if n[0] == 'leaf':
            leaves.add(round(n[1] * (-1 if neg else 1), 6))
            return
        collect(n[1], neg)
        collect(n[2], neg or False)

    collect(tree)
    n_ops = p.n_ops
    depth = _op_depth(tree) if n_ops else 0
    width = max(levels.values()) if levels else 0
    return n_ops, depth, width, len(leaves), n_ops == 0 or width <= 1


# ------------------------------------------------------- MultiHiertt programs
def split_top(s):
    parts, depth, cur = [], 0, []
    for c in s:
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
        if c == ',' and depth == 0:
            parts.append(''.join(cur).strip())
            cur = []
        else:
            cur.append(c)
    tail = ''.join(cur).strip()
    if tail:
        parts.append(tail)
    return parts


_STEP = re.compile(r'^([a-zA-Z_]+)\((.*)\)$')
_ARG = re.compile(r'^(#(\d+)|const_\w+|(-?\d+(?:\.\d+)?))$')


def dag_stats_program(program):
    """Steps like 'add(5,11), add(#0,6)': (n_ops, depth, width, n_leaves, chain)."""
    steps = [s for s in split_top(program) if s]
    if not steps:
        return None
    parsed = []
    for s in steps:
        m = _STEP.match(s)
        if not m:
            return None
        args = []
        for a in split_top(m.group(2)):
            am = _ARG.match(a.strip())
            if not am:
                return None
            args.append(am.group(1))
        parsed.append(args)
    level = []
    for i, args in enumerate(parsed):
        deps = [int(a[1:]) for a in args if a.startswith('#')]
        if any(d >= i for d in deps):
            return None
        level.append(0 if not deps else 1 + max(level[d] for d in deps))
    lv_cnt = Counter(level)
    n_leaves = sum(1 for args in parsed for a in args
                   if not a.startswith('#') and not a.startswith('const_'))
    n_ops = len(parsed)
    width = max(lv_cnt.values())
    return n_ops, (max(level) + 1), width, n_leaves, width <= 1


# ------------------------------------------------------------------- census
def hist(xs, edges):
    c = Counter()
    for x in xs:
        for name, lo, hi in edges:
            if lo <= x < hi:
                c[name] += 1
                break
    return dict(c)


def pct(n, d):
    return round(100.0 * n / d, 1) if d else 0.0


OPS_EDGES = [('0', 0, 1), ('1-2', 1, 3), ('3', 3, 4), ('4', 4, 5), ('5', 6, 6),
             ('5+', 5, 10 ** 9)]
NODE_EDGES = [('<=3', 0, 4), ('4-5', 4, 6), ('6-7', 6, 8), ('>=8', 8, 10 ** 9)]


def summarize(rows, name):
    comp = [r for r in rows if r['n_ops'] is not None]
    n_all = len(rows)
    out = {'dataset': name, 'n_questions': n_all,
           'answer_type': dict(Counter(r['answer_type'] for r in rows)),
           'parse_ok_arithmetic': len(comp)}
    if not comp:
        return out
    ops = [r['n_ops'] for r in comp]
    total_nodes = [r['n_ops'] + r['n_leaves'] for r in comp]
    branching = [r for r in comp if r['width'] >= 2]
    sched = [r for r in comp if r['n_ops'] >= 4 or (r['n_ops'] == 3 and r['width'] >= 2)]
    strict = [r for r in comp if r['n_ops'] >= 5 or (r['n_ops'] >= 4 and r['width'] >= 2)]
    out.update({
        'ops_hist': hist(ops, OPS_EDGES),
        'depth_hist': hist([r['depth'] for r in comp],
                           [('1', 1, 2), ('2', 2, 3), ('3', 3, 4), ('>=4', 4, 10 ** 9)]),
        'total_nodes_hist': hist(total_nodes, NODE_EDGES),
        'ops_mean': round(st.mean(ops), 2),
        'ops_median': st.median(ops),
        'total_nodes_p90': sorted(total_nodes)[int(0.9 * len(total_nodes))],
        'pct_no_computation_all': pct(sum(1 for r in rows if r['n_ops'] in (None, 0)), n_all),
        'pct_le3ops_all': pct(sum(1 for r in rows if (r['n_ops'] or 0) <= 3), n_all),
        'pct_le3ops_comp': pct(sum(1 for r in comp if r['n_ops'] <= 3), len(comp)),
        'pct_ge4ops_all': pct(sum(1 for r in rows if (r['n_ops'] or 0) >= 4), n_all),
        'pct_branching_comp': pct(len(branching), len(comp)),
        'pct_schedulable_comp': pct(len(sched), len(comp)),          # >=4 ops | 3 ops w/ fork
        'pct_schedulable_all': pct(len(sched), n_all),
        'pct_strict_complex_comp': pct(len(strict), len(comp)),       # >=5 | >=4 & fork
        'pct_strict_complex_all': pct(len(strict), n_all),
        'pct_chain_only_comp': pct(sum(1 for r in comp if r['chain']), len(comp)),
        'multi_source': {},
    })
    if name.startswith('MultiHiertt'):
        out['multi_source'] = {
            'pct_multitable_comp': pct(sum(1 for r in comp if r.get('n_tables', 1) >= 2), len(comp)),
            'pct_text_and_table_comp': pct(sum(1 for r in comp
                                              if r.get('n_text', 0) and r.get('n_cells', 0)), len(comp)),
            'pct_multisource_schedulable': pct(
                sum(1 for r in sched if r.get('n_tables', 1) >= 2 or
                    (r.get('n_text', 0) and r.get('n_cells', 0))), len(sched)) if sched else 0.0,
        }
    else:
        out['multi_source'] = {
            'pct_table_text_comp': pct(sum(1 for r in comp if r.get('cross_modal')), len(comp)),
            'pct_table_text_schedulable': pct(sum(1 for r in sched if r.get('cross_modal')),
                                              len(sched)) if sched else 0.0,
        }
    return out


def census_tatqa():
    rows = []
    for split, path in TATQA.items():
        for para in json.loads(path.read_text()):
            for q in para['questions']:
                r = {'split': split, 'answer_type': q['answer_type'],
                     'n_ops': None, 'depth': 0, 'width': 0, 'n_leaves': 0, 'chain': True,
                     'cross_modal': q.get('answer_from') == 'table-text'}
                if q['answer_type'] == 'arithmetic':
                    stats = dag_stats_infix(q.get('derivation', ''))
                    if stats:
                        r['n_ops'], r['depth'], r['width'], r['n_leaves'], r['chain'] = stats
                    elif q.get('derivation', '').strip():
                        r['n_ops'] = None
                elif q['answer_type'] == 'count':
                    r['n_ops'], r['depth'], r['n_leaves'] = 1, 1, 0
                rows.append(r)
    return rows


def census_multihiertt():
    rows = []
    for split in ('train', 'dev'):
        for item in json.loads((MHTT_DIR / f'{split}.json').read_text()):
            q = item['qa']
            ev = q.get('table_evidence') or []
            r = {'split': split, 'answer_type': q.get('question_type', '?'),
                 'n_ops': None, 'depth': 0, 'width': 0, 'n_leaves': 0, 'chain': True,
                 'n_cells': len(set(ev)),
                 'n_tables': len({e.split('-')[0] for e in ev}) if ev else 0,
                 'n_text': len(q.get('text_evidence') or [])}
            if q.get('question_type') == 'arithmetic' or q.get('program'):
                stats = dag_stats_program(q.get('program', ''))
                if stats:
                    r['n_ops'], r['depth'], r['width'], r['n_leaves'], r['chain'] = stats
                    # extraction leaves come from evidence cells when present
                    if r['n_cells']:
                        r['n_leaves'] = max(r['n_leaves'], r['n_cells'])
            rows.append(r)
    return rows


def main():
    results = {
        'TAT-QA': summarize(census_tatqa(), 'TAT-QA'),
        'MultiHiertt': summarize(census_multihiertt(), 'MultiHiertt'),
    }
    (ROOT / 'task_complexity_census.json').write_text(json.dumps(results, indent=1))
    for name, r in results.items():
        print(f'== {name} ==  n={r["n_questions"]}  answer_type={r["answer_type"]}')
        print(f'   arithmetic parsed: {r.get("parse_ok_arithmetic")}')
        for k in ('ops_hist', 'depth_hist', 'total_nodes_hist', 'ops_mean', 'ops_median',
                  'total_nodes_p90', 'pct_no_computation_all', 'pct_le3ops_all',
                  'pct_le3ops_comp', 'pct_ge4ops_all', 'pct_branching_comp',
                  'pct_chain_only_comp', 'pct_schedulable_comp', 'pct_schedulable_all',
                  'pct_strict_complex_comp', 'pct_strict_complex_all', 'multi_source'):
            print(f'   {k}: {r.get(k)}')
        print()


if __name__ == '__main__':
    main()
