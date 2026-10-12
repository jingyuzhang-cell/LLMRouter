import copy,json,unittest
from pathlib import Path
from .goal_ir import compile_goal_ir,goal_ir_schema,guard_goal_repair
from .producer_plan import compile_producer_plan
from .semantic_ids import assemble_semantic
from .semantic_validation import SemanticErrors
from .protocol import validate,Limits
from .heterogeneous_models import allocate
from .test_semantic_ids import CTX,LoopTests as Fixture
from .generation import InitialDAGGenerator

def datum(symbol,typ,unit='unitless'):return dict(symbol=symbol,type=typ,unit=unit)
def step(ref,op,inputs,out,context=None):
    s=dict(ref=ref,operation=op,description='Generic operation '+ref,inputs=inputs,outputs=[out])
    if context:s['context_field']=context
    return copy.deepcopy(s)
def ir(size=3):
    a=datum('table_data','source_facts');e=datum('sum_formula','expression');v=datum('sum_result','calculated_value')
    rows=[step('read','extract',[],a,'ctx_table'),step('plan','form_expression',[a],e),step('eval','calculate',[a,e],v)]
    if size==5:
        b=datum('text_data','source_facts');rows.insert(1,step('read_text','extract',[],b,'ctx_text'))
        rows[2]['inputs'].append(b);rows[3]['inputs'].append(b)
        v=datum('checked_sum','verified_value');rows.append(step('check','verify_value',[datum('sum_result','calculated_value')],v))
    return dict(final_goal=dict(description='Compute requested generic sum',outputs=[dict(name='answer',**v)]),steps=rows)
def build(p):
    raw,e=compile_goal_ir(p);plan,_=compile_producer_plan(raw);g=assemble_semantic(plan,'generic-ir-unit',CTX,{'answer':'sum'});validate(g);return g,e

class IRTests(unittest.TestCase):
    def fail(self,p,code):
        with self.assertRaises(SemanticErrors) as ex:compile_goal_ir(p)
        self.assertEqual(ex.exception.feedback['error_code'],code)
    def test_three_five(self):
        for n in (3,5):g,e=build(ir(n));self.assertEqual(len(g.nodes),n);self.assertEqual(e['invented_edges'],0)
    def test_forward_order_same_graph(self):
        a=ir(5);b=copy.deepcopy(a);b['steps'].reverse();self.assertEqual(build(a)[0].nodes,build(b)[0].nodes)
    def test_multiple_roots_aggregate(self):self.assertEqual(len(validate(build(ir(5))[0]).layers[0]),2)
    def test_missing_symbol(self):
        p=ir();p['steps'][1]['inputs'][0]['symbol']='undefined';self.fail(p,'IR_MISSING_PRODUCER')
    def test_ambiguous_output(self):
        p=ir(5);p['steps'][1]['outputs']=copy.deepcopy(p['steps'][0]['outputs']);self.fail(p,'IR_AMBIGUOUS_PRODUCER')
    def test_duplicate_ref(self):
        p=ir();p['steps'][1]['ref']='read';self.fail(p,'IR_AMBIGUOUS_REF')
    def test_expression_not_number(self):
        p=ir(5);p['steps'][-1]['inputs']=[datum('sum_formula','calculated_value')];self.fail(p,'IR_TYPE_MISMATCH')
    def test_calculated_not_facts(self):
        p=ir();p['steps'][1]['inputs']=[datum('sum_result','source_facts')];self.fail(p,'IR_TYPE_MISMATCH')
    def test_operation_wrong_output(self):
        p=ir();p['steps'][0]['outputs'][0]['type']='calculated_value';self.fail(p,'IR_OPERATION_OUTPUT_TYPE')
    def test_units_no_coercion(self):
        p=ir();p['steps'][1]['inputs'][0]['unit']='dollars';self.fail(p,'IR_UNIT_MISMATCH')
    def test_goal_missing(self):
        p=ir();p['final_goal']['outputs'][0]['symbol']='absent';self.fail(p,'IR_GOAL_UNCOVERED')
    def test_goal_type(self):
        p=ir();p['final_goal']['outputs'][0]['type']='verified_value';self.fail(p,'IR_GOAL_TYPE_UNIT')
    def test_unused_branch(self):
        p=ir();p['steps'].append(step('extra','extract',[],datum('unused','source_facts'),'ctx_text'));self.fail(p,'FINAL_OUTPUT_CONNECTIVITY')
    def test_cycle(self):
        a=datum('a','verified_value');b=datum('b','verified_value')
        p=dict(steps=[step('A','verify_value',[b],a),step('B','verify_value',[a],b)],final_goal=dict(description='Check result',outputs=[dict(name='answer',**a)]));self.fail(p,'CYCLE')
    def test_missing_aggregation(self):
        p=ir();p['steps'][-1]['inputs'].pop();self.fail(p,'IR_OPERATION_INPUTS')
    def test_forbid_redundant_dependencies(self):
        p=ir();p['steps'][0]['dependencies']=[];self.fail(p,'IR_STEP_FORMAT')
    def test_repair_does_not_drop_step(self):
        a=ir(5);b=ir();
        with self.assertRaises(SemanticErrors):guard_goal_repair(a,b)
    def test_raw_output_goal_valid_task(self):
        a=datum('facts','source_facts');p=dict(steps=[step('read','extract',[],a,'ctx_table')],final_goal=dict(description='Extract requested data',outputs=[dict(name='answer',**a)]));self.assertEqual(len(build(p)[0].nodes),1)
    def test_result_unit_conversion_rejected(self):
        p=ir();p['steps'][-1]['outputs'][0]['unit']='dollars';self.fail(p,'IR_IMPLICIT_UNIT_CONVERSION')
    def test_repair_goal_not_rewritten(self):
        a=ir();b=ir();b['final_goal']['outputs'][0]['symbol']='table_data'
        with self.assertRaises(SemanticErrors):guard_goal_repair(a,b)
    def test_schema_no_execution_binding(self):
        s=goal_ir_schema();self.assertNotIn('dependencies',json.dumps(s));self.assertNotIn('node_id',json.dumps(s));self.assertEqual(len(s['properties']['steps']['items']['anyOf']),5)
    def test_hetero_existing_allocator(self):
        g,_=build(ir(5));result=allocate(g,{'medium':'m','large':'l','coder':'c'},'heterogeneous_type_baseline');self.assertTrue(result['heterogeneous'])

class IRLoopTests(Fixture):
    def dispatch_ir(self,m,p):
        payload=json.loads(p) if p.startswith('{') else None
        if payload and payload.get('operation') in ('plan_goal_ir','repair_goal_ir'):return json.dumps(next(self.candidates))
        return self.dispatch(m,p)
    def test_ir_three_five_metered_execution(self):
        for size in (3,5):
            self.candidates=iter([ir(size)]);ex=self.executor(self.dispatch_ir)
            a,b=InitialDAGGenerator(ex,'medium',planning_mode='goal_ir').generate_and_execute('ir-loop-'+str(size),'financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
            self.assertEqual(a.status,'GENERATED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],2 if size==3 else 5)
            self.assertIn('goal_ir_compilation',a.graph.provenance);self.assertEqual(b['data_errors'],{});self.assertTrue(b['value_lineage']);self.assertEqual(ex.budget.attempts,4 if size==3 else 6)
    def test_heterogeneous_stub_execution(self):
        self.candidates=iter([ir(5)]);ex=self.executor(self.dispatch_ir);assigned={}
        def assign(g):
            assigned.update(allocate(g,ex.bindings)['assignment']);return assigned
        a,b=InitialDAGGenerator(ex,'medium',planning_mode='goal_ir').generate_and_execute('ir-hetero-stub','financial_arithmetic',CTX,{'answer':'sum'},assign)
        self.assertEqual(b['status'],'COMPLETE');self.assertEqual(set(assigned.values()),{'medium','large','coder'})
    def test_bounded_ir_repair(self):
        a=ir();a['steps'][1]['inputs'][0]['symbol']='missing';self.candidates=iter([a,ir()]);ex=self.executor(self.dispatch_ir)
        r=InitialDAGGenerator(ex,'medium',planning_mode='goal_ir').generate('ir-repair','financial_arithmetic',CTX,{'answer':'sum'});self.assertEqual(r.status,'REPAIRED');self.assertEqual(ex.budget.attempts,3)
for name in dir(Fixture):
    if name.startswith('test_') and name not in IRLoopTests.__dict__:setattr(IRLoopTests,name,None)
del Fixture
