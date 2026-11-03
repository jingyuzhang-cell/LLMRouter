"""Isolated, node-at-a-time KDX preparation. No CLI model calls or DAG loop."""
import hashlib,json,re
from pathlib import Path
from assemble_dag import assemble
from pilot_dag_contracts import td
from strict_meter import StrictMeter

ROOT=Path(__file__).resolve().parent
TASK_ID='kdx_002450'
def sha(data):return hashlib.sha256(data).hexdigest()
class Corpus:
 def __init__(self,root=ROOT,expected=None):
  self.root=Path(root);self.task_id=TASK_ID;self.documents={};self.chunks=[]
  manifest=json.loads((self.root/'v3_evidence/v3_manifests.json').read_text())['A_kangdexin']
  for d in manifest['documents']:
   ident=d['doc_id'];base=self.root/'v3_evidence/A_kangdexin'
   raw=(base/'raw'/f'{ident}.pdf').read_bytes();text=(base/'text'/f'{ident}.txt').read_text()
   if not sha(raw).startswith(d['sha256']):raise ValueError('DOCUMENT_HASH_MISMATCH')
   record=dict(d,raw_sha256=sha(raw),text_sha256=sha(text.encode()),actual_chars=len(text))
   if expected and expected.get(ident)!=record['text_sha256']:raise ValueError('TEXT_HASH_MISMATCH')
   self.documents[ident]=record
   # Include the tail; positions are Unicode character offsets in parsed text, not PDF coordinates.
   for start in range(0,len(text),370):
    fragment=text[start:start+450]
    self.chunks.append(dict(task_id=TASK_ID,document_id=ident,doc_id=ident,fragment_id=f'{ident}:{start}:{start+len(fragment)}',start=start,end=start+len(fragment),text=fragment,source_hash=record['text_sha256'],raw_sha256=record['raw_sha256'],fragment_sha256=sha(fragment.encode()),public_date=d['public_date'],url=d['url'],trust_status='UNVERIFIED_SOURCE_FRAGMENT'))
  self.identity=sha(json.dumps(self.documents,sort_keys=True,ensure_ascii=False).encode())
 def locate(self,fragment):
  return next((c for c in self.chunks if c==fragment),None) is not None
 def search(self,terms,required_documents,budget_chars=3300):
  if not terms or not required_documents:raise ValueError('EXPLICIT_REQUIREMENTS_REQUIRED')
  if set(required_documents)-self.documents.keys():raise ValueError('UNKNOWN_DOCUMENT')
  selected=[];used=0
  for doc in required_documents:
   candidates=[c for c in self.chunks if c['document_id']==doc and any(t in c['text'] for t in terms)]
   candidates.sort(key=lambda c:(-sum(c['text'].count(t) for t in terms),c['start']))
   if not candidates:raise ValueError('NECESSARY_EVIDENCE_NOT_LOCATED:'+doc)
   c=candidates[0]
   if used+len(c['text'])>budget_chars:raise ValueError('EVIDENCE_CONTEXT_BOUND')
   selected.append(c);used+=len(c['text'])
  return selected

class KDXNodeAdapter:
 def __init__(self,corpus,plan,meter):
  if type(meter) is not StrictMeter:raise ValueError('STRICT_METER_REQUIRED')
  self.corpus=corpus;self.meter=meter;self.plan=plan
  result,issues=assemble(plan,task_id=TASK_ID)
  if issues or result is None:raise ValueError(str(issues))
  self.graph,self.validation=result
  self.by_id={n.node_id:n for n in self.graph.nodes}
 def prepare(self,node_id,upstream,question,fragments=()):
  if self.corpus.task_id!=TASK_ID or self.graph.task_id!=TASK_ID:raise ValueError('TASK_INDEX_MISMATCH')
  node=self.by_id[node_id];inputs={}
  for b in node.inputs:
   if b.source=='task':inputs[b.port]=question if b.field=='question' else self.corpus.documents
   else:
    if b.node_id not in upstream or b.field not in upstream[b.node_id]:raise ValueError('MISSING_UPSTREAM')
    if b.port in inputs:raise ValueError('MULTI_INPUT_REQUIRES_EXPLICIT_MERGE')
    inputs[b.port]=upstream[b.node_id][b.field]
  if node.output_contract=='doc_retrieval.v1':
   required=next(t['doc_ids'] for t in self.plan['plan'] if t['id']==node_id)
   if set(required)-{c['document_id'] for c in fragments}:raise ValueError('NECESSARY_EVIDENCE_NOT_LOCATED')
   if any(not self.corpus.locate(c) for c in fragments):raise ValueError('FORGED_FRAGMENT')
  return node,inputs,dict(task_id=TASK_ID,corpus_identity=self.corpus.identity,goal=node.subtask,inputs=inputs,evidence_fragments=list(fragments),instructions='Retain fragment_id, source_hash, document_id and date. Treat sources as unverified claims; preserve conflicts. Do not invent facts.')
 def dispatch_node(self,node_id,upstream,question,fragments=(),*,alias,input_upper,bound_evidence,max_output,timeout_s=60):
  node,inputs,payload=self.prepare(node_id,upstream,question,fragments)
  system='Produce JSON with exactly the registered output ports; citations must point to supplied source fragments. Do not adjudicate contradictory sources.'
  record,text=self.meter.call(alias,system,json.dumps(payload,ensure_ascii=False,sort_keys=True),max_tokens=max_output,purpose='KDX:'+node_id,timeout_s=timeout_s,input_upper=input_upper,bound_evidence=bound_evidence)
  output=json.loads(text);expected=td.CONTRACTS[node.output_contract][2]
  if set(output)!=set(expected):raise ValueError('OUTPUT_PORT_CONTRACT')
  for port,typ in expected.items():
   if typ=='text' and not isinstance(output[port],str):raise ValueError('OUTPUT_TYPE_CONTRACT')
   if typ=='json' and not isinstance(output[port],(dict,list)):raise ValueError('OUTPUT_TYPE_CONTRACT')
  if node.output_contract=='doc_retrieval.v1':
   rows=output['doc_extracts'];allowed={c['fragment_id']:c for c in fragments}
   if not isinstance(rows,list) or not rows:raise ValueError('EXTRACT_RECORDS_REQUIRED')
   for row in rows:
    c=allowed.get(row.get('fragment_id'))
    if not c or row.get('source_hash')!=c['source_hash'] or row.get('document_id')!=c['document_id'] or not row.get('quote') or row['quote'] not in c['text']:raise ValueError('EVIDENCE_LINEAGE_REJECTED')
  return output,record
