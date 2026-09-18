"""Read-only provenance resolution and physically separated snapshot preparation."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from . import core, tool_aware_v1 as v
from .tatqa_benchmark_build import literals

BASE = core.ROOT / 'static_dag_v0'
OUT = BASE / 'recovery_matrix_v2/pilot_snapshot_fixed'
FORBIDDEN = {'answer', 'gold_answer', 'gold_facts', 'gold_operands', 'program', 'derivation',
             'required', 'required_operands', 'failure_type_gold', 'label', 'gold_value', 'n_ops'}

def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def assert_runtime(obj):
    if isinstance(obj, dict):
        assert not FORBIDDEN.intersection(obj), FORBIDDEN.intersection(obj)
        for value in obj.values(): assert_runtime(value)
    elif isinstance(obj, list):
        for value in obj: assert_runtime(value)

def read_rows(path):
    if not path.exists(): return []
    return [(i, json.loads(line)) for i, line in enumerate(path.read_text().splitlines(), 1) if line.strip()]

class Sources:
    def __init__(self):
        self.tasks = {}
        self.nodes = {}
        self.responses = {}
        for domain, folder in [('multihiertt', 'fresh_static_confirmation'), ('tatqa', 'tatqa_benchmark')]:
            self.tasks.update({(domain, t['uid']): t for t in json.loads((BASE/folder/'TASKS.json').read_text())})
            self.nodes.update({(domain, n['node_id']): n for n in json.loads((BASE/folder/'NODES.json').read_text())})
            path = BASE/folder/'medium_RESPONSES.jsonl'
            for line, r in read_rows(path):
                key = (domain, r['task_uid'], r['node_type'])
                self.responses[key] = (r, path, line, r.get('call_key'))
        # These tasks were executed by large extraction -> medium reasoning.
        for t in json.loads((BASE/'scale_up/TQ_TASKS.json').read_text()):
            self.tasks['tatqa', t['uid']] = t
        path = BASE/'scale_up/RESPONSES.jsonl'
        for line, r in read_rows(path):
            parts = r['key'].split(':')
            if len(parts)==3 and parts[0]=='tq' and parts[2] in ('ext','rsn'):
                kind = {'ext':'extraction','rsn':'reasoning'}[parts[2]]
                self.responses['tatqa',parts[1],kind] = (r,path,line,r['key'])

    def record(self, domain, uid, kind):
        item = self.responses.get((domain, uid, kind))
        if item is None: return None
        r,path,line,key = item
        # Do not expose response wrappers: some include gold_value.
        raw = r.get('response',r)
        if raw.get('status') != 'delivered' or not isinstance(raw.get('answer'),str): return None
        return dict(output=raw['answer'], model=r.get('model'), source_file=str(path.relative_to(core.ROOT)),
                    source_line=line, source_key=key, response_sha256=digest(raw['answer']))

def build_snapshot(node, sources):
    """No reference labels are read by this function; absent responses fail closed."""
    uid,domain=node['task_uid'],node['domain']
    task=sources.tasks.get((domain,uid))
    ext=sources.record(domain,uid,'extraction')
    if ext is None or task is None:
        return dict(valid=False, node_id=node['node_id'], invalid_reason='missing_actual_extraction_output')
    # A present but unparseable extraction is a real failed output, not a missing record.
    try:
        facts=v.parse_facts(ext['output']); parse_error=None
    except (ValueError,KeyError,AssertionError,TypeError) as exc:
        facts={'facts':[]}; parse_error=type(exc).__name__
    failed=ext if ':ex' in node['node_id'] else sources.record(domain,uid,'reasoning')
    if failed is None:
        return dict(valid=False,node_id=node['node_id'],invalid_reason='missing_actual_failed_node_output')
    snap=dict(valid=True,node_id=node['node_id'],task_uid=uid,domain=domain,
              question=task['question'],context=task['context'],facts_source='actual_extraction_output',
              facts_before=facts,actual_extracted_facts=facts,actual_parent_outputs=[ext],
              failed_node_output=failed['output'],failed_output_provenance=failed,
              failure_state={'extraction_parse_error':parse_error},
              dag_state={'path':['extraction','reasoning'],'failed_node_id':node['node_id']})
    assert_runtime(snap)
    return snap

def offline_payload(node,sources):
    uid,dom=node['task_uid'],node['domain']; t=sources.tasks[dom,uid]
    if dom=='multihiertt':
        prog=sources.nodes[dom,uid+':rs']['program']; vals=[]
        for args in re.findall(r'\(([^()]*)\)',prog):
            for x in args.split(','):
                x=x.strip()
                if x.startswith('#') or x.startswith('const_'):continue
                try:vals.append(float(x))
                except ValueError:pass
        required=sorted(set(vals)); n_ops=len(re.findall(r'(?:add|subtract|multiply|divide)\(',prog))
    else:
        prog=t['derivation'];required=sorted({x for x in literals(prog) if x not in (0.,1.,100.)});n_ops=len(re.findall(r'[+\-*/]',prog))
    return dict(node_id=node['node_id'],gold_answer=t['answer'],gold_derivation=prog,
                required_operands=required,failure_type_gold=node['label'],domain=dom,
                pre_recovery_structural_ops=n_ops)

def prepare():
    OUT.mkdir(parents=True,exist_ok=True)
    sources=Sources()
    pool=json.loads((BASE/'recovery_matrix_v2_pool_final.json').read_text())
    pilot=json.loads((BASE/'recovery_matrix_v2_pilot20.json').read_text())
    assert Counter(n['label'] for n in pool)=={'evidence':61,'reasoning':61,'structural':26}
    assert Counter(n['label'] for n in pilot)=={'evidence':8,'reasoning':7,'structural':5}
    # Audit entire pool WITHOUT executing any recovery action.
    snaps={n['node_id']:build_snapshot(n,sources) for n in pool}
    invalid=[dict(node_id=n['node_id'],label=n['label'],domain=n['domain'],reason=snaps[n['node_id']]['invalid_reason']) for n in pool if not snaps[n['node_id']]['valid']]
    selected=[]; replacements=[]; reserved={n['node_id'] for n in pilot}
    for node in pilot:
        if not snaps[node['node_id']]['valid']:
            candidates=[n for n in pool if n['label']==node['label'] and n['domain']==node['domain'] and n['node_id'] not in reserved and snaps[n['node_id']]['valid']]
            candidates.sort(key=lambda n:hashlib.sha256(n['node_id'].encode()).hexdigest())
            if not candidates:raise RuntimeError('No same-label/domain replacement: '+node['node_id'])
            replacement=candidates[0];reserved.add(replacement['node_id'])
            replacements.append(dict(excluded=node['node_id'],replacement=replacement['node_id'],rule='sha256(node_id), ascending, same label/domain'))
            node=replacement
        selected.append(node)
    (OUT/'runtime').mkdir(exist_ok=True);(OUT/'offline').mkdir(exist_ok=True)
    for node in selected:
        name=hashlib.sha256(node['node_id'].encode()).hexdigest()+'.json'
        (OUT/'runtime'/name).write_text(json.dumps(snaps[node['node_id']],ensure_ascii=False,indent=2))
        (OUT/'offline'/name).write_text(json.dumps(offline_payload(node,sources),ensure_ascii=False,indent=2))
    report=dict(pool_counts=dict(Counter(n['label'] for n in pool)),pilot_counts=dict(Counter(n['label'] for n in selected)),
                snapshot_invalid=invalid,replacements=replacements,selected_ids=[n['node_id'] for n in selected],
                full_execution=False,pool_manifest_sha256=hashlib.sha256((BASE/'recovery_matrix_v2_pool_final.json').read_bytes()).hexdigest(),
                pilot_manifest_sha256=hashlib.sha256((BASE/'recovery_matrix_v2_pilot20.json').read_bytes()).hexdigest())
    (OUT/'SNAPSHOT_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report

if __name__=='__main__':
    print(json.dumps(prepare(),ensure_ascii=False,indent=2))
