"""Build source-only catalogs for the three new public task inputs. No Gold read."""
import json,hashlib
from pathlib import Path
from evidence_registry import build_registry,resolve
ROOT=Path(__file__).resolve().parent
INPUT=Path('/root/research_outputs/CAPITAL_PUBLIC_DATA_20261031/MODEL_INPUTS')
OUT=ROOT/'PUBLIC_REGISTRIES'
def main():
 OUT.mkdir(exist_ok=False)
 rows=[]
 for rec in json.loads((INPUT/'INDEX.json').read_text()):
  p=INPUT/rec['file'];raw=p.read_bytes()
  if hashlib.sha256(raw).hexdigest()!=rec['sha256']:raise ValueError('TASK_INPUT_CHANGED')
  task=json.loads(raw);sources={}
  for d in task['documents']:
   pages={}
   for pg in d['pages']:
    # HTML has no physical page number. Explicitly distinguish its logical text unit.
    num=pg['page'] if pg['page'] is not None else 1
    pages[str(num)]={'text':pg['text'],'page_sha256':pg['text_sha256'],
                     'page_kind':'PDF_PAGE' if pg['page'] is not None else 'HTML_LOGICAL_TEXT_UNIT'}
   sources[d['doc_id']]={'raw_sha256':d['raw_sha256'],'pages':pages}
  registry=build_registry(sources)
  for eid in registry:resolve(eid,registry,sources)
  model_view=[{'evidence_id':eid,'doc_id':v['doc_id'],'page':v['page'],
               'page_kind':sources[v['doc_id']]['pages'][str(v['page'])]['page_kind'],
               'text':v['quote']} for eid,v in registry.items()]
  result={'task_id':task['task_id'],'input_sha256':rec['sha256'],
          'information_cutoff':task['information_cutoff'],'sources':sources,
          'registry':registry,'model_evidence':model_view,
          'semantic_support':'UNADJUDICATED','new_calls':0}
  path=OUT/(task['task_id']+'.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
  rows.append({'task':task['task_id'],'file':path.name,'segments':len(registry),
               'all_spans_resolve':True,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 (OUT/'INDEX.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows))
if __name__=='__main__':main()
