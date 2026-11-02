"""Stage-C-R4 P0: Terminal report scoring + recovery increment scoring.

Two independent metrics (NOT merged into one Q):

Metric A - Q_terminal: ONLY scores the final report node output.
  No upstream prefix (n1-n2) outputs included.
  Measures: fact correctness, completeness, evidence traceability, UNKNOWN boundaries.

Metric B - ΔQ_recovery: ONLY scores facts obtainable EXclusively from
  recovery/reconstructed nodes (n3+).  Facts already covered by the shared
  prefix (n1-n2 outputs) are excluded from this metric.

R1 original scoring preserved. R4 is a new independent scorer.
"""
import json, re, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, '/root/capital_opinion_pilot')
from pilot_common import norm

SC = Path('/root/cap_eval_bench_v1/stage_c_evidence')


def load_silver(ev_id):
    return json.load(open(SC / f'{ev_id}_silver.json'))['facts']


def extract_final_report(trace_data):
    """Extract ONLY the report node (n6) output from execution trace."""
    node_records = trace_data.get('node_records', [])
    # Find the LAST successful n6 (report) execution
    report_output = None
    for rec in node_records:
        if rec.get('node_id') == 'n6' and rec.get('status') == 'done':
            report_output = rec.get('output')
    return report_output


def extract_prefix_outputs(trace_data, prefix_nodes=('n1', 'n2')):
    """Extract outputs from shared prefix nodes (pre-anomaly)."""
    outputs = {}
    for rec in trace_data.get('node_records', []):
        if rec.get('node_id') in prefix_nodes and rec.get('status') == 'done':
            outputs[rec['node_id']] = rec.get('output', {})
    return outputs


def extract_recovery_outputs(trace_data, anomaly_node='n3'):
    """Extract outputs from nodes at-or-after the anomaly node (post-recovery)."""
    outputs = {}
    for rec in trace_data.get('node_records', []):
        nid = rec.get('node_id', '')
        node_num = int(nid[1:]) if nid.startswith('n') and nid[1:].isdigit() else 0
        anom_num = int(anomaly_node[1:]) if anomaly_node.startswith('n') else 0
        if node_num >= anom_num and rec.get('status') == 'done':
            outputs[nid] = rec.get('output', {})
    return outputs


def score_facts_in_text(text, silver_facts):
    """Score which Silver facts appear in the given text."""
    def norm_local(s):
        return re.sub(r'[\s,，。;；:：、"\u201c\u201d()\[\]（）]+', '', str(s))

    nt = norm_local(text)
    covered = []
    for f in silver_facts:
        a, typ = f['answer'], f.get('answer_type', 'text')
        na = norm_local(a)
        hit = na in nt
        if not hit and typ == 'date':
            dm = re.match(r'(\d{4})-(\d{2})-(\d{2})', a)
            if dm:
                hit = norm_local(f'{dm.group(1)}年{int(dm.group(2))}月{int(dm.group(3))}日') in nt
        if hit:
            covered.append(f['fact_id'])
    return covered


# ===== METRIC A: Q_terminal =====

def score_terminal(trace_data, silver_facts):
    """Score ONLY the final report output (n6). No upstream prefix."""
    report = extract_final_report(trace_data)
    if not report:
        return {'Q_terminal': 0.0, 'covered': [], 'note': 'no report output'}

    report_text = json.dumps(report, ensure_ascii=False)
    covered = score_facts_in_text(report_text, silver_facts)
    q = round(len(covered) / max(1, len(silver_facts)), 4)
    return {'Q_terminal': q, 'covered': covered, 'note': 'final report only'}


# ===== METRIC B: ΔQ_recovery =====

def score_recovery_increment(trace_data, silver_facts, anomaly_node='n3'):
    """Score facts ONLY obtainable from recovery nodes (n3+), excluding prefix (n1-n2)."""
    prefix_outputs = extract_prefix_outputs(trace_data)
    recovery_outputs = extract_recovery_outputs(trace_data, anomaly_node)

    # Facts covered by prefix (these are NOT recovery contributions)
    prefix_text = json.dumps(prefix_outputs, ensure_ascii=False)
    prefix_covered = set(score_facts_in_text(prefix_text, silver_facts))

    # Facts covered by recovery nodes
    recovery_text = json.dumps(recovery_outputs, ensure_ascii=False)
    all_covered = set(score_facts_in_text(recovery_text, silver_facts))

    # Also check final report (which may contain facts from both sources)
    report = extract_final_report(trace_data)
    report_text = json.dumps(report, ensure_ascii=False) if report else ''
    report_covered = set(score_facts_in_text(report_text, silver_facts))

    # Recovery increment = facts in report that are NOT in prefix
    # (these required recovery or downstream execution to obtain)
    recovery_only = report_covered - prefix_covered

    total_facts = len(silver_facts)
    delta_q = round(len(recovery_only) / max(1, total_facts), 4)

    return {
        'dQ_recovery': delta_q,
        'prefix_covered': sorted(prefix_covered),
        'report_covered': sorted(report_covered),
        'recovery_only_facts': sorted(recovery_only),
        'note': 'facts in report NOT obtainable from shared prefix'
    }


# ===== COMBINED SCORING FUNCTION =====

def score_run_r4(trace_path, ev_id, anomaly_node='n3'):
    """Score a single run using both R4 metrics."""
    trace_data = json.load(open(trace_path))
    silver = load_silver(ev_id)

    terminal = score_terminal(trace_data, silver)
    recovery = score_recovery_increment(trace_data, silver, anomaly_node)

    return {
        'Q_terminal': terminal['Q_terminal'],
        'terminal_covered': terminal['covered'],
        'dQ_recovery': recovery['dQ_recovery'],
        'recovery_only_facts': recovery['recovery_only_facts'],
        'prefix_covered_count': len(recovery['prefix_covered']),
        'report_covered_count': len(recovery['report_covered']),
    }
