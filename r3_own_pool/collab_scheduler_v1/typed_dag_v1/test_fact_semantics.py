import copy,json,unittest
from . import fact_semantics as fs
from .execution import TypedExecutor
from .assembly import assemble
from .test_assembly import plan
from . import test_typed_dag as fixtures

class FactTests(unittest.TestCase):
    def facts(self,text='6 USD and 17 USD',values=(6,17)):
        return fs.ground([dict(value=v,evidence=text) for v in values],'task','extract','ctx_table',text)
    def error(self,code,fn):
        with self.assertRaises(fs.DataError) as caught:fn()
        self.assertEqual(caught.exception.feedback['error_code'],code)
    def test_source_schema_excludes_computed_value(self):
        schema=fs.source_fact_output_schema('6 and 17');variants=schema['properties']['facts']['items']['anyOf']
        self.assertEqual([v['properties']['value']['enum'][0] for v in variants],[6,17]);self.assertEqual([v['properties']['number_start']['enum'][0] for v in variants],[0,6])
    def test_source_schema_no_numbers(self):self.assertEqual(fs.source_fact_output_schema('same unit')['properties']['facts']['maxItems'],0)
    def test_derived_not_raw(self):self.error('DERIVED_AS_SOURCE',lambda:fs.ground([dict(value=11,evidence='6 and 17',kind='derived_value')],'t','e','ctx_table','6 and 17'))
    def test_saved_failure_value_unsupported(self):self.error('SOURCE_VALUE_UNSUPPORTED',lambda:self.facts('Last year cash: 6. This year cash: 17.',(11,)))
    def test_numeric_substring_not_evidence(self):self.error('SOURCE_VALUE_UNSUPPORTED',lambda:self.facts('120',(12,)))
    def test_source_quote_mismatch(self):self.error('SOURCE_MISMATCH',lambda:fs.ground([dict(value=6,evidence='6')],'t','e','ctx_table','17'))
    def test_unknown_id(self):self.error('REFERENCE_NOT_FOUND',lambda:fs.bind('f_'+'0'*24,self.facts()))
    def test_bad_index(self):self.error('REFERENCE_NOT_FOUND',lambda:fs.bind('v2-v0',self.facts()))
    def test_reorder_stable_ids(self):
        facts=self.facts();b=fs.bind('v1-v0',facts)
        self.assertEqual(fs.evaluate(b,list(reversed(facts)))['value'],11)
        self.assertEqual(fs.lower_expression(b,list(reversed(facts))),'v0 - v1')
    def test_unit_mismatch(self):self.error('UNIT_MISMATCH',lambda:fs.bind('v0+v1',self.facts('6 USD and 17 kg')))
    def test_unknown_unit_ratio_not_certified(self):self.assertEqual(fs.evaluate(fs.bind('v1/v0',self.facts('6 and 17')),self.facts('6 and 17'))['unit_check'],'UNDETERMINED')
    def test_multi_node_merge(self):
        a=self.facts();b=copy.deepcopy(a);b[0]['producing_nodes']=['other']
        merged=fs.merge(a+b);self.assertEqual(len(merged),2);self.assertEqual(merged[0]['producing_nodes'],['extract','other'])
    def test_mutated_fact_snapshot(self):
        a=self.facts();b=fs.bind('v1-v0',a);a[0]['value']=7
        self.error('REFERENCE_CHANGED',lambda:fs.evaluate(b,a))
    def test_legal_derived_lineage(self):
        a=self.facts();d=fs.evaluate(fs.bind('v1-v0',a),a)
        self.assertEqual(d['value'],11);self.assertEqual(d['kind'],'derived_value');self.assertEqual(len(d['source_fact_ids']),2)
    def test_repeated_source_requires_offset(self):self.error('AMBIGUOUS_SOURCE',lambda:fs.ground([dict(value=6,evidence='6')],'t','e','ctx_table','6 and 6'))
    def test_repeated_source_explicit_offset(self):
        f=fs.ground([dict(value=6,evidence='6',evidence_start=6)],'t','e','ctx_table','6 and 6');self.assertEqual(f[0]['source']['number_start'],6)
    def test_unit_claim_not_guessed(self):self.error('UNIT_SOURCE_MISMATCH',lambda:fs.ground([dict(value=6,evidence='6',unit='USD')],'t','e','ctx_table','6'))
    def test_constant_only_rejected(self):self.error('REFERENCE_MISSING',lambda:fs.bind('11',self.facts()))

class StrictLoopTests(fixtures.ExecutionTests):
    def runner(self,dispatch):
        ctx=dict(question='Increase?',ctx_table='6 USD and 17 USD',ctx_text='',gold='SECRET')
        graph=assemble(plan(4),'strict-task',ctx,{'answer':'number'})
        return TypedExecutor(graph,{n.node_id:'medium' for n in graph.nodes},self.executor(dispatch),ctx)
    def response(self,model,prompt):
        d=json.loads(prompt.split('\n',1)[1])
        if d['contract']=='facts.v1':return json.dumps(dict(facts=[dict(value=v,evidence=d['inputs']['context']) for v in (6,17)]))
        if d['contract']=='expression.v1':return json.dumps(dict(expression=d['available_fact_variables'][1]+'-'+d['available_fact_variables'][0]))
        return json.dumps(dict(value=d['inputs']['value']))
    def test_full_strict_execution(self):
        r=self.runner(self.response);o=r.run();self.assertEqual(o['status'],'COMPLETE');self.assertEqual(o['final_outputs']['answer'],11)
        self.assertEqual(json.loads(self.prompts[0].split('\n',1)[1])['source_numeric_locations'][0]['number_start'],0);self.assertEqual(o['search_spend']['new_requests'],3);self.assertEqual(o['deployment_tokens'],90);self.assertFalse(any('SECRET' in p for p in self.prompts));self.assertEqual(o['value_lineage']['check']['kind'],'derived_value')
    def test_recovery_updates_fact_map(self):
        def dispatch(m,p):
            if m=='medium' and json.loads(p.split('\n',1)[1])['contract']=='facts.v1':return '{"facts":[{"value":11,"evidence":"6 USD and 17 USD"}]}'
            return self.response(m,p)
        r=self.runner(dispatch);first=r.run();self.assertEqual(first['data_errors']['read']['error_code'],'SOURCE_VALUE_UNSUPPORTED');self.assertNotIn('form',r.reference_bindings)
        out=r.recover_failed('read','large');self.assertEqual(out['status'],'COMPLETE');self.assertEqual(out['search_spend']['new_requests'],4);self.assertEqual(len(r.reference_bindings['form']['references']),2)
    def test_wrong_verification_not_complete(self):
        def dispatch(m,p):
            if json.loads(p.split('\n',1)[1])['contract']=='verify_value.v1':return '{"value":99}'
            return self.response(m,p)
        r=self.runner(dispatch);o=r.run();self.assertEqual(o['status'],'INCOMPLETE');self.assertEqual(o['data_errors']['check']['error_code'],'VERIFICATION_INCONSISTENT')
    def test_missing_facts_block_before_reasoning_request(self):
        r=self.runner(lambda m,p:'{"facts":[]}');o=r.run();self.assertEqual(o['data_errors']['form']['error_code'],'FACT_MISSING');self.assertEqual(o['search_spend']['new_requests'],1)
        with self.assertRaisesRegex(ValueError,'review required'):r.recover_failed('form','large')
for name in vars(fixtures.ExecutionTests):
    if name.startswith('test_'):setattr(StrictLoopTests,name,None)
