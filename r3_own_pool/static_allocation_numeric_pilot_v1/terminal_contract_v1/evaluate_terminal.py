"""Offline terminal evaluation for raw branch files. Never dispatches calls."""
import copy
import importlib.util
import json
from pathlib import Path
from jsonschema import Draft202012Validator

HERE=Path(__file__).resolve().parent
CONTRACT=json.loads((HERE/'TERMINAL_SCORING_CONTRACT.json').read_text())
SCHEMA=json.loads(Path(CONTRACT['output_schema_path']).read_text())
spec=importlib.util.spec_from_file_location('reused_numeric_terminal_scorer',CONTRACT['original_scorer_path'])
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)

def _strict_object(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError('Duplicate JSON key')
        out[key]=value
    return out

def _reject_constant(value):
    raise ValueError('Nonstandard JSON constant: '+value)

def evaluate(raw_by_branch):
    if set(raw_by_branch)-set(CONTRACT['assigned_slots']):
        return {'content_Q':None,'content_status':'UNRESOLVED_EXTRA_BRANCH',
                'legal_correct_targets':None,'legal_correct_targets_over_six':None,
                'all_branches_numeric_lane_legal':False,'full_opinion_Q':None,'model_calls':0}
    branch_results={};parsed=[];legal_ids=set();all_parseable=True
    unresolved_container=False
    # Catalogue IDs are public task evidence; never derive them from expected values.
    task=json.loads((HERE.parent/'BINDING.json').read_text())['task']
    valid_evidence=set(task['evidence_catalog'])
    for node,assigned in CONTRACT['assigned_slots'].items():
        raw=raw_by_branch.get(node)
        if raw is None:
            branch_results[node]={'status':'MISSING_RESPONSE','schema':None,'numeric_lane_legal':False}
            all_parseable=False;continue
        try:payload=json.loads(raw,object_pairs_hook=_strict_object,parse_constant=_reject_constant) if isinstance(raw,str) else copy.deepcopy(raw)
        except (ValueError,TypeError):
            branch_results[node]={'status':'PARSE_FAILURE','schema':False,'numeric_lane_legal':False}
            all_parseable=False;continue
        native_ok=not list(Draft202012Validator(SCHEMA).iter_errors(payload))
        if isinstance(payload,dict) and set(payload)-{'items'}:
            unresolved_container=True
        rows=payload.get('items') if isinstance(payload,dict) else payload if isinstance(payload,list) else None
        if not isinstance(rows,list):
            all_parseable=False
        else:
            # Preserve all wrong/duplicate/foreign rows for independent content scoring.
            parsed.extend(copy.deepcopy(rows))
        ids=[r.get('item_id') for r in rows if isinstance(r,dict)] if isinstance(rows,list) else []
        slots_ok=len(ids)==len(assigned) and len(set(str(x) for x in ids))==len(ids) and set(str(x) for x in ids)==set(assigned)
        ids_ok=native_ok and all(all(e in valid_evidence for e in r['evidence_ids']) for r in rows)
        legal=bool(native_ok and slots_ok and ids_ok)
        if legal:legal_ids.update(ids)
        branch_results[node]={'status':'OBSERVED','schema':native_ok,'assigned_slots_exact':slots_ok,'evidence_IDs_valid':bool(ids_ok),'numeric_lane_legal':legal}
    content=old.evaluate_final({'items':parsed}) if all_parseable and not unresolved_container else None
    detail=content.get('content_details',{}).get('items',[]) if content else []
    # With any unparseable branch do not invent a content Q; legal branches can
    # still supply independently scoreable targets for delivery coverage.
    if not all_parseable or unresolved_container:
        detail=old.evaluate_final({'items':parsed}).get('content_details',{}).get('items',[])
    correct={r['item_id'] for r in detail if r.get('status')=='MATCH'}
    legal_correct=legal_ids & correct
    return {'branches':branch_results,
            'content_Q':content.get('Q_numeric_conditioned') if content else None,
            'content_evaluation':content,'content_status':'UNRESOLVED_CONTAINER_ASSERTIONS' if unresolved_container else 'PARSED' if all_parseable else 'PARTIALLY_UNOBSERVABLE',
            'legal_correct_targets':len(legal_correct),'required_targets':6,
            'legal_correct_targets_over_six':len(legal_correct)/6,
            'all_branches_numeric_lane_legal':all(x['numeric_lane_legal'] for x in branch_results.values()),
            'full_opinion_Q':None,'full_semantic_contract':None,
            'semantic_citation_accuracy':None,'model_calls':0}
