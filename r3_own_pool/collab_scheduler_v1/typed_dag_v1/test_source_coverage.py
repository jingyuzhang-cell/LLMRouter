import json,unittest
from pathlib import Path
from .source_coverage import manifest,audit_graph_sources,audit_plan_sources,validate_requirements
from .test_goal_ir import ir,build,datum
from .test_semantic_ids import CTX
from .semantic_validation import SemanticErrors
class SourceCoverageTests(unittest.TestCase):
 def required(self,m,source):return [dict(data_id='needed-public-operand',source_id=source,evidence=next(s['text'] for s in m['sources'] if s['source_id']==source))]
 def test_run04_a_structural_but_declared_source_missing(self):
  from .protocol import Graph
  r=Path(__file__).parent/'http_schema_diagnostic_v1/run04';task=json.loads((r/'PUBLIC_INPUT.json').read_text());g=Graph.from_json((r/'execution/A/GRAPH.json').read_text());m=manifest(task['context'])
  a=audit_graph_sources(g,m,self.required(m,'ctx_table'));self.assertEqual(a['source_complete'],'FAIL');self.assertEqual(a['errors'][0]['error_code'],'REQUIRED_SOURCE_MISSING')
 def test_unknown_coverage_never_pass(self):
  g,_=build(ir());self.assertEqual(audit_graph_sources(g,manifest(CTX))['source_complete'],'PENDING_SEMANTIC_REVIEW')
 def test_multi_table_lines_trace(self):
  ctx=dict(CTX,ctx_table='Table A: 2\nTable B: 3\n');m=manifest(ctx);g,_=build(ir());req=self.required(m,'ctx_table:line:0')+[{**self.required(m,'ctx_table:line:1')[0],'data_id':'second'}]
  self.assertEqual(audit_graph_sources(g,m,req)['source_complete'],'DECLARED_SOURCE_PATHS_PRESENT')
 def test_unrelated_field_not_forced(self):
  g,_=build(ir());m=manifest(CTX);a=audit_graph_sources(g,m,self.required(m,'ctx_table'));self.assertEqual(a['source_complete'],'DECLARED_SOURCE_PATHS_PRESENT')
 def test_fabricated_source_evidence_rejected(self):
  m=manifest(CTX)
  with self.assertRaises(SemanticErrors):validate_requirements([dict(data_id='x',source_id='ctx_table',evidence='absent source text')],m)
 def test_duplicate_requirement_rejected(self):
  m=manifest(CTX);r=self.required(m,'ctx_table')
  with self.assertRaises(ValueError):validate_requirements(r+r,m)
 def test_three_five_final_lineage(self):
  for size in (3,5):
   g,_=build(ir(size));a=audit_graph_sources(g,manifest(CTX),self.required(manifest(CTX),'ctx_table'));self.assertIn('ctx_table',a['final_source_lineage']['answer'])
   if size==5:self.assertIn('ctx_text',a['final_source_lineage']['answer'])
 def test_expression_type_and_unit_still_strict(self):
  from .goal_ir import compile_goal_ir
  p=ir();p['steps'][-1]['inputs'][-1]['type']='calculated_value'
  with self.assertRaises(SemanticErrors):compile_goal_ir(p)
  p=ir();p['steps'][-1]['inputs'][-1]['unit']='other'
  with self.assertRaises(SemanticErrors):compile_goal_ir(p)
 def test_preassembly_same_source_check(self):
  from .goal_ir import compile_goal_ir
  from .producer_plan import compile_producer_plan
  raw,_=compile_goal_ir(ir(5));p,_=compile_producer_plan(raw);m=manifest(CTX)
  self.assertEqual(audit_plan_sources(p,m,self.required(m,'ctx_table'))['source_complete'],'DECLARED_SOURCE_PATHS_PRESENT')
 def test_rule_defined_calculation_is_non_llm(self):
  from .protocol import CONTRACTS
  from .test_goal_ir import build
  g,_=build(ir());node=next(n for n in g.nodes if n.node_type=='transformation')
  self.assertEqual(node.output_contract,'calculate.v1');self.assertEqual(set(CONTRACTS[node.output_contract][1]),{'facts','expression'})
  # The generic calculate operation has no intrinsic sum/product rule;
  # an existing typed expression is used by deterministic execution, no extra LLM.

from .test_semantic_ids import LoopTests as Fixture
from .test_producer_plan import producers
from .generation import InitialDAGGenerator
class SourceLoopTests(Fixture):
 def dispatch_source(self,m,p):
  d=json.loads(p) if p.startswith('{') else None
  if d and d.get('operation') in ('plan_goal_ir','repair_goal_ir','plan_typed_dag','repair_semantic_plan'):
   self.assertIn('source_manifest',d['public_task']);return json.dumps(next(self.candidates))
  return self.dispatch(m,p)
 def test_same_checks_both_modes(self):
  for mode,plan in [('semantic',producers(5)),('goal_ir',ir(5))]:
   self.candidates=iter([plan]);ex=self.executor(self.dispatch_source)
   req=[dict(data_id='table-input',source_id='ctx_table',evidence=CTX['ctx_table'])]
   a,b=InitialDAGGenerator(ex,'medium',planning_mode=mode).generate_and_execute('source-loop-'+mode,'financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes},required_source_data=req)
   self.assertEqual(a.status,'GENERATED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],5)
   self.assertEqual(a.graph.provenance['source_coverage']['source_complete'],'DECLARED_SOURCE_PATHS_PRESENT')
 def test_missing_source_rejected_before_review_both_modes(self):
  for mode,p in [('semantic',producers()),('goal_ir',ir())]:
   self.candidates=iter([p]);ex=self.executor(self.dispatch_source)
   req=[dict(data_id='text-input',source_id='ctx_text',evidence=CTX['ctx_text'])]
   a=InitialDAGGenerator(ex,'medium',planning_mode=mode,max_repairs=0,fallbacks={}).generate('missing-source-'+mode,'financial_arithmetic',CTX,{'answer':'sum'},required_source_data=req)
   self.assertIsNone(a.graph);self.assertEqual(ex.budget.attempts,1)
   self.assertIn('REQUIRED_SOURCE_MISSING',json.dumps(a.events))
for name in dir(Fixture):
 if name.startswith('test_') and name not in SourceLoopTests.__dict__:setattr(SourceLoopTests,name,None)
del Fixture
