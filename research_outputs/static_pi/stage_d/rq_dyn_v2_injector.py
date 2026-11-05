#!/usr/bin/env python3
"""RQ-DYN_V2 injection adapter (execution-interface hook, ~40 lines).
Wraps cap_transport: applies frozen per-(task,scenario,rep,node,attempt) injections.
Mock mode = zero real calls; real mode requires same env gates as V1."""
import json, hashlib
from pathlib import Path

HERE = Path(__file__).parent

def truncate(text, n=20):
    return text[:n]

def inject(response_text, failure_type, conflict_fid=None, conflict_wrong_value=None):
    if failure_type == 'truncate':
        return truncate(response_text)
    elif failure_type == 'conflict':
        # S2: append duplicate fid with wrong value (target_fid/wrong_value from plan)
        try:
            d = json.loads(response_text)
            d['facts'].append({'fid': conflict_fid, 'value': conflict_wrong_value,
                               'doc': 'doc1', 'quote': 'injected'})
            return json.dumps(d, ensure_ascii=False)
        except: return truncate(response_text)
    return response_text

class Injector:
    def __init__(self, ledger_path):
        self.ledger_path = Path(ledger_path)
        # plan is initialized in __init__

    def register(self, task, scenario, rep, node, attempt, failure_type, model_filter=None):
        self.plan[(task, scenario, rep, node, attempt)] = (failure_type, model_filter)

    def __init__(self, ledger_path):
        self.ledger_path = Path(ledger_path)
        self.plan = {}
        self.conflict_fid = None
        self.conflict_wrong_value = None

    def set_conflict(self, fid, wrong_value):
        self.conflict_fid = fid
        self.conflict_wrong_value = wrong_value

    def check(self, task, scenario, rep, node, attempt, raw_response, model=None):
        key = (task, scenario, rep, node, attempt)
        entry = self.plan.get(key)
        if not entry:
            return raw_response, None
        ft, model_filter = entry
        if model_filter and model != model_filter:
            return raw_response, None  # model-specific: skip if different model
        injected = inject(raw_response, ft, self.conflict_fid, self.conflict_wrong_value)
        rec = dict(task=task, scenario=scenario, rep=rep, node=node,
                   attempt=attempt, failure_type=ft,
                   raw_sha=hashlib.sha256(raw_response.encode()).hexdigest()[:12],
                   injected_sha=hashlib.sha256(injected.encode()).hexdigest()[:12])
        with open(self.ledger_path, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        return injected, rec
