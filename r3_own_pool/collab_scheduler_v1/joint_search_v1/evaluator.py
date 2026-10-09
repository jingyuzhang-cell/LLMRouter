"""Fixed four-node X/Z evaluator; no GPU startup or historical truth access.

Caller supplies the already guarded Smoke executor's dispatch/prepare callbacks.
Deployment objectives are cold-workflow trace reconstruction, not physical spend.
"""
import copy
import itertools
import time
import types
from pathlib import Path
from collab_scheduler_v1 import fault30_run as fr
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import (
    make_executor_class, append, StopRun)
from static_dag_v0.multidag_dynamic import value_of, json_value, close

NODES = ('e1', 'e2', 'r', 'v')
METHODS = ('proposed_state_incremental', 'random', 'scalarized_bo',
           'official_qnehvi_same_state', 'proposed_without_state',
           'proposed_without_incremental_cost')


def space():
    return [dict(id='__'.join((*x,z)), X=dict(zip(NODES,x)), Z=z)
            for x in itertools.product(('medium','large'), ('medium','large'),
                                       ('medium','large'), ('coder','large'))
            for z in ('NONE','LOCAL','FULL')]


class MeteredExecutor(make_executor_class()):
    """Inject corruption AFTER obtaining a metered valid response for cost.

    Faults retain the deployment cost of the response being corrupted. This
    deliberately differs from zero-cost synthetic injection in the old Smoke.
    Raw dispatch/trajectory records remain unchanged; only evaluator view changes.
    """
    def begin_cell(self, state, cid):
        super().begin_cell(state, cid)
        self.workflow = []

    def call(self, key, model, prompt, uid=None, node=None):
        fault_key = (uid,node,model)
        fault = self.faults.pop(fault_key, None) if uid is not None else None
        try:
            source = super().call(key,model,prompt,uid=uid,node=node)
        finally:
            if fault is not None:
                self.faults[fault_key] = fault
        rec = copy.deepcopy(source)
        if fault is not None:
            rec['response']['answer'] = fault[0]
            rec['response']['injected_fault'] = True
        self.by_key[key] = rec
        self.workflow.append(rec)
        append(self.directory / 'WORKFLOW.jsonl',dict(state=self.scope,cid=self.cid,**rec))
        return rec


def _evaluate(config, ex, led, tasks, faults, label='base', recovery=False):
    # Private globals avoid monkeypatching shared protocol functions. Keep the
    # tested production execution logic while supplying independent e1/e2 X.
    mapping = dict(config['X'])
    globs = dict(fr.eval_config.__globals__)
    globs['planned_models'] = lambda _: ('DYNAMICDAG', label,
                                         'LOCAL_REROUTE' if recovery else 'NONE', mapping)
    evaluate = types.FunctionType(fr.eval_config.__code__,globs)
    return evaluate(config['id'],ex,led,tasks,faults,{t['uid']:t for t in tasks})


def detected_failure(row, ex, led):
    """Observable outputs only. Never reads task gold or row['ok']."""
    latest = {k.split(':')[3]: ex.by_key[k]['response']['answer'] for k in row['keys']}
    f1,_ = led.parse_facts_safe(latest['e1'])
    f2,_ = led.parse_facts_safe(latest['e2'])
    if not f1['facts'] or not f2['facts']:
        return True
    facts = dict(facts=f1['facts']+f2['facts'])
    value,error = value_of(latest['r'],facts)
    verified = json_value(latest['v'])
    return bool(error or verified is None or not close(value,verified))


class JointEvaluator:
    def __init__(self, executor, ledger, tasks):
        if not tasks or len({t['uid'] for t in tasks}) != len(tasks):
            raise ValueError('Nonempty unique task panel required')
        self.ex,self.led,self.tasks=executor,ledger,copy.deepcopy(tasks)
        self.configs={c['id']:c for c in space()}
        self.completed=set()

    def evaluate(self, config_id, state_id, faults):
        """Reveal ONLY the chosen config/state. Fresh evaluator per method/seed.

        Cache is method-local; deployment C and L count every logical call using
        source usage/service duration even if search executes it via an alias.
        L is SERIAL service-demand reconstruction, never observed E2E latency.
        """
        if config_id not in self.configs:
            raise ValueError('Unknown config')
        key=(config_id,state_id)
        if key in self.completed:
            raise ValueError('Duplicate reveal')
        if any(uid not in {t['uid'] for t in self.tasks} or f[0] not in NODES
               for uid,f in faults.items()):
            raise ValueError('Invalid fault panel')
        config=self.configs[config_id]
        before=(self.ex.budget.attempts,self.ex.budget.actual_tokens)
        started=time.monotonic()
        self.ex.begin_cell(state_id,config_id)
        for uid,(node,answer) in faults.items():
            self.ex.set_fault(uid,node,config['X'][node],answer,{},0)
        rows=_evaluate(config,self.ex,self.led,self.tasks,faults,
                       recovery=config['Z']=='LOCAL')
        if config['Z']=='FULL':
            retry=[t for t in self.tasks if detected_failure(rows[t['uid']],self.ex,self.led)]
            if retry:
                # Exactly one full-graph replay with frozen alternative models.
                # No cached descendant output is substituted without exact prompt
                # identity; all four logical nodes reappear and are charged in C/L.
                retry_config=copy.deepcopy(config)
                retry_config['X']={n:('coder' if m=='large' else 'large')
                                   for n,m in config['X'].items()}
                rerun=_evaluate(retry_config,self.ex,self.led,retry,faults,label='replay')
                for uid,row in rerun.items():
                    rows[uid]=dict(row,keys=rows[uid]['keys']+row['keys'])
        deployment=[]
        for task in self.tasks:
            uid=task['uid'];row=rows[uid]
            records=[self.ex.by_key[k] for k in row['keys']]
            deployment.append(dict(uid=uid,Q=row['ok'],
                C_tokens=sum(r['response']['usage']['total_tokens'] for r in records),
                L_serial_service_reconstructed_s=sum(r['response']['latency_s'] for r in records),
                logical_calls=len(records)))
        self.ex.budget.check()
        physical=fr.physical_accounting(self.ex.events)
        if physical['new_requests'] != self.ex.budget.attempts-before[0] or physical['new_tokens'] != self.ex.budget.actual_tokens-before[1]:
            raise StopRun('Joint evaluator physical ledger mismatch')
        n=len(deployment)
        result=dict(config_id=config_id,state=state_id,
            objectives=dict(Q=sum(r['Q'] for r in deployment)/n,
                C=sum(r['C_tokens'] for r in deployment)/n,
                L=sum(r['L_serial_service_reconstructed_s'] for r in deployment)/n),
            objective_semantics='cold logical workflow tokens; reconstructed SERIAL service demand; no observed deployment wall latency claim',
            search_spend=dict(**physical,observed_wall_s=time.monotonic()-started),
            tasks=deployment)
        append(self.ex.directory/'EVALUATIONS.jsonl',result)
        self.completed.add(key)
        return result


class SearchSession:
    """Online callback interface. No truth table is available to the selector.

    Caller selects from public candidates and accumulated observations, then
    updates its own model. The six algorithm implementations are external.
    """
    def __init__(self,evaluator,method,max_configurations=12):
        if method not in METHODS:
            raise ValueError(method)
        self.evaluator,self.method=evaluator,method
        self.max_configurations=max_configurations
        self.observations=[]
        self.selected=set()

    def step(self,select,states):
        if len(self.selected)>=self.max_configurations:
            raise StopRun('configuration budget')
        candidates=[c for c in space() if c['id'] not in self.selected]
        cid=select(copy.deepcopy(candidates),copy.deepcopy(self.observations))
        if cid not in {c['id'] for c in candidates}:
            raise ValueError('Illegal or repeated selection')
        # states/fault registry never passed to select; observed state features
        # need a separate non-oracle interface before state-aware search admission.
        results=[self.evaluator.evaluate(cid,name,faults) for name,faults in states]
        self.selected.add(cid)
        self.observations.extend(results)
        return copy.deepcopy(results)
