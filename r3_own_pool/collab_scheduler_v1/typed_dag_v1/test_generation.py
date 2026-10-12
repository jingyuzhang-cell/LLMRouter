import json,unittest,copy
from . import test_typed_dag as fixtures
variable_graph=fixtures.variable_graph
from .generation import InitialDAGGenerator
from .protocol import Graph
from functools import partial
InitialDAGGenerator=partial(InitialDAGGenerator,planning_mode="graph_compat")

class GenerationTests(fixtures.ExecutionTests):
    # Reuse fixture helpers, without rerunning inherited execution tests here.
    def test_generation_pipeline(self):
        for size in (3,5):
            def dispatch(m,p):
                try:d=json.loads(p)
                except ValueError:d=json.loads(p.split('\n',1)[1])
                op=d.get('operation')
                if op in ('generate_typed_dag','repair_typed_dag'):
                    g=variable_graph();g.task_id='u'
                    if size==3:
                        g.nodes=[g.nodes[0],g.nodes[2],g.nodes[3]]
                        g.nodes[1].dependencies=['e1'];g.nodes[1].inputs=[b for b in g.nodes[1].inputs if b.node_id!='e2']
                        g.nodes[2].dependencies=['e1','r'];g.nodes[2].inputs=[b for b in g.nodes[2].inputs if b.node_id!='e2']
                        g.final_outputs[0].node_id='compute'
                    # Rename all IDs: generator/executor must not depend on legacy names.
                    mapping={n.node_id:'custom'+str(i) for i,n in enumerate(g.nodes)}
                    for n in g.nodes:
                        n.node_id=mapping[n.node_id];n.dependencies=[mapping[x] for x in n.dependencies]
                        for b in n.inputs:
                            if b.node_id:b.node_id=mapping[b.node_id]
                    g.final_outputs[0].node_id=mapping[g.final_outputs[0].node_id]
                    return g.to_json()
                if op=='review_coverage':return json.dumps(dict(covered=True,requirements={'answer':[d['graph']['final_outputs'][0]['node_id']]},reason='sum covered'))
                if d['contract']=='facts.v1':return '{"facts":[{"value":2,"evidence":"2"}]}'
                if d['contract']=='expression.v1':return '{"expression":"v0"}'
                return '{"value":2}'
            ex=self.executor(dispatch,caps={'request_token_reservation':100,'new_total_tokens':10000})
            a,b=InitialDAGGenerator(ex,'medium').generate_and_execute('u','financial_arithmetic',dict(question='sum 2',ctx_table='2',ctx_text='2'),{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
            self.assertEqual(a.status,'GENERATED');self.assertEqual(len(a.graph.nodes),size);self.assertEqual(b['status'],'COMPLETE');self.assertEqual(a.accounting['new_requests'],2)
    def generator_fixture(self,responses,max_repairs=1):
        seq=iter(responses)
        ex=self.executor(lambda m,p:next(seq));return InitialDAGGenerator(ex,'medium',max_repairs=max_repairs),ex
    def go(self,gen,domain='financial_arithmetic',**kw):return gen.generate('u',domain,dict(question='sum',ctx_table='2',ctx_text='2'),{'answer':'sum'},**kw)
    def good(self):
        g=variable_graph();g.task_id='u';return g.to_json()
    def review(self,covered=True):return json.dumps(dict(covered=covered,requirements={'answer':['audit']},reason='coverage review'))
    def test_illegal_repair(self):
        gen,ex=self.generator_fixture(['{}',self.good(),self.review()]);r=self.go(gen)
        self.assertEqual(r.status,'REPAIRED');self.assertEqual(r.graph.graph_version,2);self.assertTrue(r.graph.provenance['parent_graph']);self.assertEqual(ex.budget.attempts,3)
    def test_semantic_repair(self):
        gen,ex=self.generator_fixture([self.good(),self.review(False),self.good(),self.review()]);self.assertEqual(self.go(gen).status,'REPAIRED')
    def test_bounded_fallback(self):
        gen,ex=self.generator_fixture(['{}','{}']);r=self.go(gen);self.assertEqual(r.status,'FALLBACK');self.assertEqual(ex.budget.attempts,2)
    def test_fallback_execution(self):
        def dispatch(m,p):
            try:d=json.loads(p)
            except ValueError:d=json.loads(p.split('\n',1)[1])
            if d.get('operation'):return '{}'
            if d['contract']=='facts.v1':return '{"facts":[{"value":2,"evidence":"2"}]}'
            if d['contract']=='expression.v1':return '{"expression":"v0+v1"}'
            return '{"value":4}'
        ex=self.executor(dispatch)
        a,b=InitialDAGGenerator(ex,'medium',max_repairs=1).generate_and_execute('u','financial_arithmetic',dict(question='sum',ctx_table='2',ctx_text='2'),{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
        self.assertEqual(a.status,'FALLBACK');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(ex.budget.attempts,6)
    def test_unmatched_domain(self):
        gen,ex=self.generator_fixture(['{}','{}']);r=self.go(gen,'code_generation');self.assertIsNone(r.graph);self.assertEqual(r.status,'NO_MATCHING_FALLBACK')
    def test_gold_rejected_before_call(self):
        gen,ex=self.generator_fixture([])
        with self.assertRaises(ValueError):gen.generate('u','financial_arithmetic',{'question':'q','gold':4},{'answer':'number'})
        self.assertEqual(ex.budget.attempts,0)
    def test_fenced_deterministic_repair(self):
        gen,ex=self.generator_fixture(['```json\n'+self.good()+'\n```',self.review()]);r=self.go(gen);self.assertIn('unwrap_json_fence',r.graph.provenance['deterministic_repairs'])
    def test_restricted_contracts(self):
        gen,ex=self.generator_fixture([self.good(),'{}']);r=self.go(gen,available_types=['extraction']);self.assertEqual(r.status,'FALLBACK_INCOMPATIBLE')
    def test_bad_review_is_not_pass(self):
        gen,ex=self.generator_fixture([self.good(),'{}',self.good(),'{}']);self.assertEqual(self.go(gen).status,'FALLBACK')
    def test_cache_generation_zero_new_cost(self):
        gen,ex=self.generator_fixture([self.good(),self.review()]);a=self.go(gen);b=self.go(gen);self.assertEqual(b.accounting['new_requests'],0);self.assertEqual(b.accounting['new_tokens'],0);self.assertEqual(b.accounting['cache_hits'],2)
    def test_budget_not_hidden_retry(self):
        from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun
        ex=self.executor(lambda m,p:'{}',caps={'new_request_attempts':1})
        with self.assertRaises(StopRun):self.go(InitialDAGGenerator(ex,'medium'))
        self.assertEqual(ex.budget.attempts,1)

# Inherited fixture methods only; retain original tests in their original module.
for name in list(vars(fixtures.ExecutionTests)):
    if name.startswith('test_'):setattr(GenerationTests,name,None)
