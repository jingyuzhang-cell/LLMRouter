import copy,json,tempfile,unittest
from pathlib import Path
from . import Graph,Node,Binding,Output,Limits,validate,ValidationError,TypedExecutor,fixed_financial_graph
from collab_scheduler_v1.joint_search_v1.evaluator import MeteredExecutor
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import Budget,StopRun
from collab_scheduler_v1.joint_search_v1.scoring_contract_final import score_v21

def variable_graph():
    g=fixed_financial_graph('task-with-any-id')
    g.nodes.insert(3,Node('compute','transformation','Execute expression',
        [Binding('facts','node','facts','e1'),Binding('facts','node','facts','e2'),Binding('expression','node','expression','r')],
        'calculate.v1',['e1','e2','r']))
    g.nodes[-1]=Node('audit','verification','Return checked value',[Binding('question','task','question'),Binding('value','node','value','compute')],
                    'verify_value.v1',['compute'])
    g.final_outputs=[Output('answer','audit','value')]
    return g

class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        g=fixed_financial_graph('a');self.assertEqual(g.content_hash,Graph.from_json(g.to_json()).content_hash)
    def test_fixed_and_variable(self):
        self.assertEqual(len(validate(fixed_financial_graph('a')).layers),3)
        self.assertEqual(len(variable_graph().nodes),5);validate(variable_graph())
    def bad(self,mutate):
        g=fixed_financial_graph('a');mutate(g)
        with self.assertRaises(ValidationError):validate(g)
    def test_duplicate(self):self.bad(lambda g:g.nodes.append(copy.deepcopy(g.nodes[0])))
    def test_dangling(self):self.bad(lambda g:g.nodes[2].dependencies.append('missing'))
    def test_self_cycle(self):self.bad(lambda g:g.nodes[0].dependencies.append('e1'))
    def test_unknown_type(self):self.bad(lambda g:setattr(g.nodes[0],'node_type','python'))
    def test_contract_version(self):self.bad(lambda g:setattr(g.nodes[0],'output_contract','facts.v99'))
    def test_interface(self):self.bad(lambda g:setattr(g.nodes[2].inputs[1],'field','value'))
    def test_gold_binding(self):self.bad(lambda g:setattr(g.nodes[0].inputs[0],'field','answer'))
    def test_missing_output(self):self.bad(lambda g:g.final_outputs.clear())
    def test_limits(self):
        for limit in (Limits(max_nodes=3),Limits(max_depth=2),Limits(max_llm_calls=3)):
            with self.assertRaises(ValidationError):validate(fixed_financial_graph('a'),limits=limit)
    def test_arbitrary_ids(self):
        g=fixed_financial_graph('a');mapping={n.node_id:'arbitrary'+str(i) for i,n in enumerate(g.nodes)}
        for n in g.nodes:
            n.node_id=mapping[n.node_id];n.dependencies=[mapping[p] for p in n.dependencies]
            for b in n.inputs:
                if b.node_id:b.node_id=mapping[b.node_id]
        g.final_outputs[0].node_id=mapping['v'];validate(g)
    def test_full_cycle(self):
        ns=[Node(u,'verification','verify',[Binding('question','task','question'),Binding('value','node','value',p)],'verify_value.v1',[p]) for u,p in [('a','b'),('b','a')]]
        g=Graph('cycle','typed-dag.v1',1,'u',ns,[Output('answer','a','value')])
        with self.assertRaisesRegex(ValidationError,'cycle'):validate(g)

class ExecutionTests(unittest.TestCase):
    def executor(self,dispatch=None,caps=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name)
        base=dict(new_request_attempts=100,new_total_tokens=10000,request_token_reservation=100,
                  max_output_tokens=50,wall_seconds=60,logical_calls_per_task_config_state=30)
        base.update(caps or {});budget=Budget(p,base)
        self.prompts=[]
        def call(model,prompt):
            self.prompts.append(prompt)
            if dispatch:answer=dispatch(model,prompt)
            else:
                c=json.loads(prompt.split('\n',1)[1]);typ=c['contract'];data=c['inputs']
                if typ=='facts.v1':answer=json.dumps({'facts':[{'value':1.5 if data['context']=='table' else 2.5,'evidence':data['context']}]})
                elif typ=='expression.v1':answer=json.dumps({'expression':'+'.join('v'+str(i) for i in range(len(data['facts']))) or '0'})
                else:answer=json.dumps({'value':data.get('value',4.0)})
            return dict(status='delivered',answer=answer,usage=dict(prompt_tokens=20,completion_tokens=10,total_tokens=30))
        return MeteredExecutor(p,budget,call,lambda m:None,dict(medium='medium',large='large',coder='coder'))
    def run_graph(self,g,ex):return TypedExecutor(g,{n.node_id:'medium' for n in g.nodes},ex,dict(question='sum?',ctx_table='table',ctx_text='text',answer='GOLD_MUST_NOT_LEAK'),fact_semantics='legacy')
    def test_fixed_execution_scoring_no_gold(self):
        ex=self.executor();runner=self.run_graph(fixed_financial_graph('uid'),ex);r=runner.run()
        self.assertEqual(r['final_outputs']['answer'],4.0);self.assertEqual(r['search_spend']['new_requests'],4)
        self.assertEqual(r['deployment_tokens'],120);self.assertTrue(runner.score(score_v21,4.0))
        self.assertFalse(any('GOLD_MUST_NOT_LEAK' in p for p in self.prompts))
    def test_five_node_tool_execution(self):
        ex=self.executor();r=self.run_graph(variable_graph(),ex).run()
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(len(r['node_status']),5)
        self.assertEqual(r['final_outputs']['answer'],4.0);self.assertEqual(ex.budget.attempts,4)
    def test_cache_zero_physical_deployment_preserved(self):
        ex=self.executor();g=variable_graph();a=self.run_graph(g,ex).run();b=self.run_graph(g,ex).run()
        self.assertEqual(b['search_spend']['new_requests'],0);self.assertEqual(a['deployment_tokens'],b['deployment_tokens'])
    def test_invalid_graph_zero_dispatch(self):
        ex=self.executor();g=variable_graph();g.nodes[0].output_contract='code.v1'
        with self.assertRaises(ValidationError):self.run_graph(g,ex)
        self.assertEqual(ex.budget.attempts,0)
    def test_failed_blocks_descendants(self):
        ex=self.executor(lambda m,p:'{}');r=self.run_graph(variable_graph(),ex).run()
        self.assertEqual(r['status'],'INCOMPLETE');self.assertEqual(r['node_status']['r'],'blocked');self.assertEqual(ex.budget.attempts,2)
    def test_reroute_without_cost_rollback(self):
        def respond(m,p):
            c=json.loads(p.split('\n',1)[1]);typ=c['contract']
            if typ=='facts.v1':return '{"facts":[{"value":2,"evidence":"input"}]}'
            if typ=='expression.v1':return '{}' if m=='medium' else '{"expression":"v0+v1"}'
            return '{"value":4}'
        ex=self.executor(respond);r=self.run_graph(fixed_financial_graph('u'),ex);r.run()
        self.assertEqual(r.status['v'],'blocked');out=r.recover_failed('r','large')
        self.assertEqual(out['status'],'COMPLETE');self.assertEqual(ex.budget.attempts,5)
        with self.assertRaises(ValidationError):r.recover_failed('r','medium')
    def test_recovery_is_bounded(self):
        ex=self.executor(lambda m,p:'{}');runner=self.run_graph(variable_graph(),ex);runner.run()
        with self.assertRaises(ValidationError):runner.recover_failed('e1','large',max_attempts=1)
        self.assertEqual(ex.budget.attempts,2)
    def test_task_identity_with_separator(self):
        ex=self.executor();runner=self.run_graph(fixed_financial_graph('a:b'),ex)
        self.assertEqual(runner.run()['status'],'COMPLETE')
        self.assertTrue(all(len(k.split(':')[-1])==64 for k in ex.by_key))
    def test_hard_budget(self):
        ex=self.executor(caps={'new_request_attempts':1})
        with self.assertRaises(StopRun):self.run_graph(variable_graph(),ex).run()
        self.assertEqual(ex.budget.attempts,1)
    def test_mutation_after_validation_rejected(self):
        ex=self.executor();runner=self.run_graph(variable_graph(),ex)
        runner.graph.nodes[0].subtask='changed'
        with self.assertRaises(ValidationError):runner.run()
        self.assertEqual(ex.budget.attempts,0)
    def test_arbitrary_ids_execute(self):
        g=variable_graph();mapping={n.node_id:'custom'+str(i) for i,n in enumerate(g.nodes)}
        for n in g.nodes:
            n.node_id=mapping[n.node_id];n.dependencies=[mapping[p] for p in n.dependencies]
            for b in n.inputs:
                if b.node_id:b.node_id=mapping[b.node_id]
        for o in g.final_outputs:o.node_id=mapping[o.node_id]
        out=self.run_graph(g,self.executor()).run()
        self.assertEqual(out['status'],'COMPLETE');self.assertEqual(out['final_outputs']['answer'],4.0)
    def test_three_node_single_root_graph(self):
        g=fixed_financial_graph('three');g.nodes.pop(1)
        for n in g.nodes:
            n.dependencies=[d for d in n.dependencies if d!='e2']
            n.inputs=[b for b in n.inputs if b.node_id!='e2']
        out=self.run_graph(g,self.executor()).run()
        self.assertEqual(len(out['node_status']),3);self.assertEqual(out['status'],'COMPLETE')
    def test_malformed_protocol_rejected(self):
        with self.assertRaises(ValidationError):Graph.from_json('{}')
        g=variable_graph();g.nodes[0].inputs=None
        with self.assertRaises(ValidationError):validate(g)
    def test_unsafe_expression_and_nonfinite(self):
        for text,c in [('{"expression":"__import__(1)"}','expression.v1'),('{"value":NaN}','verify_value.v1'),('{"value":true}','verify_value.v1')]:
            with self.assertRaises(ValueError):TypedExecutor.parse(text,c)

if __name__=='__main__':unittest.main()
