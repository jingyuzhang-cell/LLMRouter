import json,re,os,sys
base=json.load(open('rq1_tasks/rq1_tasks_materials.json'))
ov=json.load(open('rq1_tasks/rq1_v1_5_overlay.json'))
docs_dir=base['docs_dir']
def norm(s): return re.sub(r'\s+','',s)
ok=0; fail=0; skipped=0
for tid,t in ov['derived_gold'].items():
    files={d['doc_id']:d['file'] for d in base['tasks'][tid]['docs']}
    for nid,v in t.items():
        for d in v:
            if d.get('excluded'):
                skipped+=1; continue
            fp=os.path.join(docs_dir,files.get(d.get('evidence_doc'),d.get('evidence_doc','')))
            if not os.path.exists(fp): fp=os.path.join(docs_dir,d.get('evidence_doc',''))
            if not os.path.exists(fp):
                print('MISSING DOC',tid,nid,d['fact_id'],d.get('evidence_doc')); fail+=1; continue
            text=norm(open(fp,encoding='utf-8',errors='ignore').read())
            span=norm(d.get('evidence_span',''))
            if span and span in text: ok+=1
            else:
                print('SPAN NOT FOUND',tid,nid,d['fact_id'],'span=',span[:60]); fail+=1
print(f'PASS={ok} FAIL={fail} EXCLUDED={skipped}')
sys.exit(1 if fail else 0)
