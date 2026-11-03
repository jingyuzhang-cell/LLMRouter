"""Optional generic evidence convergence; unverified claims, never conclusions."""
import copy,json,hashlib

def merge(inputs,source_nodes):
 if not isinstance(inputs,list) or not isinstance(source_nodes,list) or len(inputs)!=len(source_nodes) or not inputs:raise ValueError('MERGE_CARDINALITY')
 if len(set(source_nodes))!=len(source_nodes):raise ValueError('MERGE_DUPLICATE_SOURCE')
 result=[];values={}
 for line,src in zip(inputs,source_nodes):
  if not isinstance(line,list):raise ValueError('MERGE_COLLECTION_REQUIRED')
  for item in line:
   if not isinstance(item,dict):raise ValueError('MERGE_RECORD_REQUIRED')
   row=copy.deepcopy(item)
   origin={'source_node':src,'doc_id':item.get('doc_id') or item.get('evidence_doc'),'public_date':item.get('public_date'),'original_record':copy.deepcopy(item)}
   row['origins']=copy.deepcopy(item.get('origins',[]))+[origin];row['trust_status']='UNVERIFIED_MATERIAL'
   row['metadata_missing']=[k for k in ('doc_id','public_date') if not origin[k]]
   # Keep every distinct record and exact evidence/time; no textual normalization.
   key=item.get('fact_key');encoded=json.dumps(item.get('value'),sort_keys=True,ensure_ascii=False)
   if key:
    others=values.setdefault(str(key),[])
    for idx,prior in others:
     if prior!=encoded:
      row['potential_conflict']=True;result[idx]['potential_conflict']=True
    others.append((len(result),encoded))
   result.append(row)
 return result

def execute(node,upstream,context):
 if node.output_contract not in ('facts_merge.v2',):raise ValueError('NOT_MERGE_CONTRACT')
 lines=[];sources=[]
 for b in node.inputs:
  if b.source=='node' and b.port=='facts':lines.append(upstream[b.node_id][b.field]);sources.append(b.node_id)
 merged=merge(lines,sources)
 fingerprint=hashlib.sha256(json.dumps({'contract':node.output_contract,'inputs':lines,'source_nodes':sources},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 return {'doc_extracts':merged}, {'cache_namespace':node.output_contract,'cache_identity':fingerprint,'model_calls':0,'status':'UNVERIFIED_MATERIAL'}
