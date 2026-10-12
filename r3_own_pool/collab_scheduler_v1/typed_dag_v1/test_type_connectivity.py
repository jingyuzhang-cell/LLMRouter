"""Zero-provider-call contract/connectivity regression and saved-response replay."""
import copy,json,unittest
from pathlib import Path
from .producer_plan import compile_producer_plan,verify_producer_bindings,OUTPUT_KINDS,ROLE_KINDS
from .semantic_ids import assemble_semantic
from .semantic_validation import inspect_semantic_plan,SemanticErrors,compare_errors
from .protocol import validate,Limits
from .test_producer_plan import producers
from .test_semantic_ids import CTX,LoopTests as Fixture
from .generation import InitialDAGGenerator

HISTORY=Path(__file__).parent/'stage3_heterogeneous_real_01'
def errors(p):
    try:q,_=compile_producer_plan(p)
    except SemanticErrors as exc:return exc.feedback['errors']
    return inspect_semantic_plan(q)
def graph(p):
    q,e=compile_producer_plan(p);g=assemble_semantic(q,'generic-constraint-unit',CTX,{'answer':'number'})
    verify_producer_bindings(g,e);validate(g);return g

class TypeConnectivityTests(unittest.TestCase):
    def test_expression_not_number(self):
        p=producers(5);p['nodes'][-1]['input_producers']={'value':['math']}
        e=errors(p)[0];self.assertEqual(e['producer_output_type'],['expression']);self.assertEqual(e['expected_input_type'],'number');self.assertEqual(e['offending_port'],'value')
    def test_expression_not_facts(self):
        p=producers();p['nodes'][1]['input_producers']={'facts':['math']}
        e=errors(p)[0];self.assertEqual(e['producer_output_kind'],'calculation_expression');self.assertEqual(e['accepted_input_kinds'],['source_fact'])
    def test_derived_not_source_facts(self):
        p=producers(5);p['nodes'][1]['type']='reasoning';p['nodes'][1].pop('context_field');p['nodes'][1]['input_producers']={'facts':['compute']}
        self.assertTrue(any(e.get('producer_output_kind')=='calculated_result' for e in errors(p)))
    def test_verified_not_source_facts(self):
        p=producers(5);p['nodes'][2]['input_producers']={'facts':['audit']}
        self.assertTrue(any(e.get('producer_output_kind')=='verification_result' for e in errors(p)))
    def test_raw_facts_not_expression(self):
        p=producers();p['nodes'][-1]['input_producers']['expression']=['raw'];self.assertEqual(errors(p)[0]['producer_output_type'],['facts'])
    def test_kinds_keep_wire_protocol(self):
        self.assertEqual(len(set(OUTPUT_KINDS.values())),4);self.assertNotIn('source_fact',ROLE_KINDS['value']);self.assertIn('verification_result',ROLE_KINDS['value'])
    def test_multistage_well_typed(self):
        p=producers(5);g=graph(p);self.assertEqual(len(g.nodes),5);self.assertEqual(next(n for n in g.nodes if n.node_type=='verification').output_contract,'verify_value.v1')
    def test_isolated_extraction(self):
        p=producers();p['nodes'].append(dict(ref='unused',type='extraction',name='extra',subtask='Extract additional operand',context_field='ctx_text',input_producers={}))
        e=next(e for e in errors(p) if e['error_code']=='FINAL_OUTPUT_CONNECTIVITY');self.assertEqual(e['unreachable_required_nodes'],['unused']);self.assertIn(['unused'],e['disconnected_components'])
    def test_necessary_branch_cannot_disappear(self):
        p=producers(5)
        for n in p['nodes']:
            if 'facts' in n['input_producers']:n['input_producers']['facts']=[r for r in n['input_producers']['facts'] if r!='text']
        self.assertIn('text',next(e for e in errors(p) if e['error_code']=='FINAL_OUTPUT_CONNECTIVITY')['unreachable_required_nodes'])
    def test_multiroot_forward_variable(self):
        for size in (3,5):
            p=producers(size);p['nodes'].reverse();g=graph(p);self.assertEqual(len(g.nodes),size);self.assertEqual(len(validate(g).layers[0]),1 if size==3 else 2)
    def test_missing_final_explicit(self):
        p=producers();p['final_outputs'][0]['node_ref']='absent';self.assertIn('FINAL_OUTPUT_REFERENCE',[e['error_code'] for e in errors(p)])
    def test_multiple_final_outputs_union(self):
        p=producers();p['nodes'].append(dict(ref='extra',type='extraction',subtask='Extract diagnostic facts',context_field='ctx_text',input_producers={}))
        p['final_outputs'].append(dict(name='diagnostic',node_ref='extra'));self.assertEqual(errors(p),[]);graph(p)
    def test_saved_solar_four_conflict_fields(self):
        for i in (1,2):
            p=json.loads((HISTORY/f'RESPONSE_{i:02}_PARSED.json').read_text());before=copy.deepcopy(p);es=errors(p)
            self.assertEqual(len(es),3);self.assertEqual([e['consumer_ref'] for e in es],['nodes.2.ref','nodes.3.ref','nodes.4.ref']);self.assertEqual(p,before)
    def test_saved_trip_components(self):
        for i in (3,4):
            p=json.loads((HISTORY/f'RESPONSE_{i:02}_PARSED.json').read_text());es=errors(p);e=es[0]
            self.assertEqual(e['error_code'],'FINAL_OUTPUT_CONNECTIVITY');self.assertEqual(len(e['disconnected_components']),5);self.assertEqual(len(e['unreachable_required_nodes']),4)
    def test_only_final_change_no_progress(self):
        a=json.loads((HISTORY/'RESPONSE_03_PARSED.json').read_text());b=json.loads((HISTORY/'RESPONSE_04_PARSED.json').read_text());self.assertTrue(compare_errors(errors(a),errors(b))['no_progress'])
    def test_type_repeat_no_progress(self):
        a=json.loads((HISTORY/'RESPONSE_01_PARSED.json').read_text());b=json.loads((HISTORY/'RESPONSE_02_PARSED.json').read_text());self.assertTrue(compare_errors(errors(a),errors(b))['no_progress'])
    def test_new_error_not_no_progress(self):
        a=producers(5);a['nodes'][-1]['input_producers']={'value':['math']};b=copy.deepcopy(a);b['nodes'][-1]['input_producers']={'value':['raw']};self.assertFalse(compare_errors(errors(a),errors(b))['no_progress'])

class ConstraintLoopTests(Fixture):
    def test_saved_failures_full_repair_loop_feedback(self):
        for pair in ((1,2),(3,4)):
            self.candidates=iter(json.loads((HISTORY/f'RESPONSE_{i:02}_PARSED.json').read_text()) for i in pair)
            ex=self.executor(self.dispatch);r=InitialDAGGenerator(ex,'medium').generate('history-'+str(pair),'financial_arithmetic',CTX,{'answer':'number'})
            self.assertEqual(r.status,'FALLBACK');self.assertEqual(ex.budget.attempts,2)
            self.assertTrue(any(e.get('phase')=='repair_comparison' and e['status']=='NO_PROGRESS' for e in r.events))
            reasons=[e['feedback'] for e in r.events if e.get('status')=='REJECTED'];self.assertTrue(all(x.get('errors') for x in reasons))
    def test_legal_execution_preserves_lineage_and_meter(self):
        self.candidates=iter([producers(5)]);ex=self.executor(self.dispatch)
        a,b=InitialDAGGenerator(ex,'medium').generate_and_execute('lineage-unit','financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
        self.assertEqual(a.status,'GENERATED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],5)
        self.assertEqual(b['data_errors'],{});self.assertTrue(b['reference_bindings']);self.assertTrue(b['value_lineage']);self.assertEqual(ex.budget.attempts,6)
for name in dir(Fixture):
    if name.startswith('test_') and name not in ConstraintLoopTests.__dict__:setattr(ConstraintLoopTests,name,None)
del Fixture
