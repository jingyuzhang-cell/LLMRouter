import json,sys
base=json.load(open('rq1_tasks/rq1_tasks_materials.json'))
ov=json.load(open('rq1_tasks/rq1_v1_5_overlay.json'))
errs=[]; types={}
taskfacts={tid:{f for n in t['nodes'] for f in n.get('fact_ids',[])} for tid,t in base['tasks'].items()}
allderived={d['fact_id'] for t in ov['derived_gold'].values() for v in t.values() for d in v}
for tid,t in base['tasks'].items():
    for n in t['nodes']:
        nid=n['node_id']; typ=ov['node_type_map'][tid][nid]
        types[typ]=types.get(typ,0)+1
        up=set((n.get('reference_upstream') or {}).get('fact_ids',[]))
        for d in ov['derived_gold'].get(tid,{}).get(nid,[]):
            if d['fact_id'] in up: errs.append(f'{tid}/{nid}: derived gold {d["fact_id"]} in upstream input')
            for f in d['from_facts']:
                if f not in taskfacts[tid] and f not in allderived:
                    errs.append(f'{tid}/{nid}: from_fact {f} not a task fact or derived')
        feat=ov['features'][tid][nid]
        if feat['node_type']!=typ: errs.append(f'{tid}/{nid}: feature type mismatch')
print('node type counts:',types)
print('total nodes:',sum(types.values()),'derived facts:',sum(len(v) for t in ov['derived_gold'].values() for v in t.values()))
for e in errs: print('ERROR',e)
print('PASS' if not errs and sum(types.values())==25 else 'FAIL','errors=',len(errs))
sys.exit(0 if not errs and sum(types.values())==25 else 1)
