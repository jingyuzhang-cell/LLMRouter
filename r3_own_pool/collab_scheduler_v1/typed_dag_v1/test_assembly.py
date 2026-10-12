import copy,json,unittest
from pathlib import Path
from .assembly import assemble,ConstraintError
from .protocol import validate,CONTRACTS
from .generation import InitialDAGGenerator
from . import test_typed_dag as fixtures

def plan(size=3):
    nodes=[dict(id='read',type='extraction',subtask='Extract numerical values relevant to question',context_field='ctx_table',dependencies=[]),dict(id='form',type='reasoning',subtask='Express the requested calculation using facts',dependencies=['read']),dict(id='calc',type='transformation',subtask='Compute expression',dependencies=['read','form'])]
    if size==4:nodes.append(dict(id='check',type='verification',subtask='Check computed value',dependencies=['calc']))
    return dict(nodes=nodes,final_outputs=[dict(name='answer',node_id=nodes[-1]['id'])])
CTX=dict(question='sum?',ctx_table='2',ctx_text='2')
class AssemblyTests(unittest.TestCase):
    def make(self,p):return assemble(p,'u',CTX,{'answer':'number'})
    def test_variable_topology(self):
        for size in (3,4):
            g=self.make(plan(size));validate(g);self.assertEqual(len(g.nodes),size);self.assertEqual(g.nodes[2].dependencies,['read','form'])
    def test_exact_contract_binding(self):
        g=self.make(plan(4));self.assertEqual([n.output_contract for n in g.nodes],['facts.v1','expression.v1','calculate.v1','verify_value.v1'])
    def test_missing_reference_not_deleted(self):
        p=plan();p['nodes'][1]['dependencies']=['missing']
        with self.assertRaises(ConstraintError) as e:self.make(p)
        self.assertEqual(e.exception.feedback['error_code'],'DEPENDENCY_REFERENCE');self.assertEqual(p['nodes'][1]['dependencies'],['missing'])
    def test_incompatible_edge_not_deleted(self):
        p=plan(4);p['nodes'][-1]['dependencies']=['calc','form']
        with self.assertRaises(ConstraintError) as e:self.make(p)
        self.assertEqual(e.exception.feedback['error_code'],'CONTRACT_UNBINDABLE')
    def test_ambiguous_contract_not_guessed(self):
        registry=dict(CONTRACTS);registry['alternate.v1']=registry['facts.v1']
        with self.assertRaises(ConstraintError) as e:assemble(plan(),'u',CTX,{'answer':'number'},registry)
        self.assertEqual(e.exception.feedback['error_code'],'CONTRACT_AMBIGUOUS')
    def test_cycle(self):
        p=plan();p['nodes'][0]['dependencies']=['calc']
        with self.assertRaises(ConstraintError) as e:self.make(p)
        self.assertEqual(e.exception.feedback['error_code'],'CYCLE')
    def test_saved_real_invalid_unchanged_replay(self):
        d=json.loads((Path(__file__).parent/'REAL_CANDIDATE_INVALID.json').read_text())
        # Explicit diagnostic projection: never invent missing semantic edges/inputs.
        p=dict(nodes=[dict(id=n['node_id'],type=n['node_type'],subtask=n['subtask'],dependencies=n['dependencies']) for n in d['nodes']],final_outputs=[dict(name=o['name'],node_id=o['node_id']) for o in d['final_outputs']])
        with self.assertRaises(ConstraintError) as e:self.make(p)
        self.assertEqual(e.exception.feedback['error_code'],'CONTRACT_UNBINDABLE')
    def test_multiple_extraction_nodes_retained(self):
        p=plan();p['nodes'].insert(1,dict(id='read_text',type='extraction',subtask='Extract text',context_field='ctx_text',dependencies=[]));p['nodes'][2]['dependencies'].append('read_text');p['nodes'][3]['dependencies'].append('read_text')
        self.assertEqual(len(self.make(p).nodes),4)
    def test_no_contract_ids_from_model(self):
        p=plan();p['nodes'][0]['output_contract']='facts.v99'
        with self.assertRaises(ConstraintError) as e:self.make(p)
        self.assertEqual(e.exception.feedback['error_code'],'PLAN_NODE_FORMAT')

    def test_repair_preserves_nodes(self):
        from .assembly import guard_repair
        p=plan(4);q=plan()
        with self.assertRaises(ConstraintError) as e:guard_repair(p,q)
        self.assertEqual(e.exception.feedback['error_code'],'REPAIR_REMOVED_NODE')
    def test_repair_preserves_valid_edges(self):
        from .assembly import guard_repair
        p=plan();q=copy.deepcopy(p);q['nodes'][2]['dependencies']=['form']
        with self.assertRaises(ConstraintError) as e:guard_repair(p,q)
        self.assertEqual(e.exception.feedback['error_code'],'REPAIR_REMOVED_VALID_EDGE')
    def test_repair_dangling_edge_allowed(self):
        from .assembly import guard_repair
        p=plan();p['nodes'][1]['dependencies']=['missing'];guard_repair(p,plan())

class SemanticLoopTests(fixtures.ExecutionTests):
    def test_contract_type_repair_and_execute(self):
        broken=plan();broken['nodes'][0]['type']='facts.v99'
        answers=iter([json.dumps(broken),json.dumps(plan(4))])
        def dispatch(m,p):
            try:d=json.loads(p)
            except ValueError:d=json.loads(p.split('\n',1)[1])
            if d.get('operation') in ('plan_typed_dag','repair_semantic_plan'):
                if d['operation']=='repair_semantic_plan':self.assertEqual(d['error']['error_code'],'NODE_TYPE')
                return next(answers)
            if d.get('operation')=='review_coverage':return json.dumps(dict(covered=True,requirements={'answer':['check']},reason='computed value'))
            if d['contract']=='facts.v1':return '{"facts":[{"value":2,"evidence":"2"}]}'
            if d['contract']=='expression.v1':return '{"expression":"v0"}'
            return '{"value":2}'
        ex=self.executor(dispatch);a,b=InitialDAGGenerator(ex,'medium',max_repairs=1).generate_and_execute('u','financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
        self.assertEqual(a.status,'REPAIRED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['pipeline_accounting']['new_requests'],6)
    def test_dependency_repair(self):
        bad=plan();bad['nodes'][1]['dependencies']=['absent'];answers=iter([json.dumps(bad),json.dumps(plan()),json.dumps(dict(covered=True,requirements={'answer':['calc']},reason='covers task'))]);ex=self.executor(lambda m,p:next(answers))
        a=InitialDAGGenerator(ex,'medium',max_repairs=1).generate('u','financial_arithmetic',CTX,{'answer':'number'});self.assertEqual(a.status,'REPAIRED')
    def test_semantic_repair_failure_fallback(self):
        ex=self.executor(lambda m,p:'{"nodes":[],"final_outputs":[]}');a=InitialDAGGenerator(ex,'medium',max_repairs=1).generate('u','financial_arithmetic',CTX,{'answer':'number'})
        self.assertEqual(a.status,'FALLBACK');validate(a.graph);self.assertEqual(ex.budget.attempts,2)
    def test_unavailable_index_fails_before_tool(self):
        def dispatch(m,p):
            c=json.loads(p.split('\n',1)[1])
            if c['contract']=='facts.v1':return '{"facts":[{"value":2,"evidence":"2"}]}'
            return '{"expression":"v1-v0"}'
        ex=self.executor(dispatch);g=assemble(plan(),'u',CTX,{'answer':'number'})
        from .execution import TypedExecutor
        out=TypedExecutor(g,{n.node_id:'medium' for n in g.nodes},ex,CTX).run()
        self.assertEqual(out['node_status']['form'],'failed');self.assertEqual(out['node_status']['calc'],'blocked');self.assertIn('unavailable fact index',out['errors']['form'])
for name in vars(fixtures.ExecutionTests):
    if name.startswith('test_'):setattr(SemanticLoopTests,name,None)
