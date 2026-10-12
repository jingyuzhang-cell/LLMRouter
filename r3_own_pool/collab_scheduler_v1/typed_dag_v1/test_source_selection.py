import json,unittest
from . import fact_semantics as fs
from .assembly import assemble
from .execution import TypedExecutor
from .generation import InitialDAGGenerator
from .test_assembly import plan
from . import test_typed_dag as fixtures

class SelectionTests(unittest.TestCase):
    def test_sentence_terminal_numbers(self):
        text='Last year cash: 6. This year cash: 17.';cs=fs.source_candidates(text)
        self.assertEqual([c['value'] for c in cs],[6,17])
        facts=fs.ground(fs.assemble_source_selection(dict(selected_source_ids=[c['source_id'] for c in cs],reason='cash operands'),text)['facts'],'t','e','ctx_table',text)
        self.assertEqual(fs.evaluate(fs.bind('v1-v0',facts),facts)['value'],11)
    def test_decimal_not_partially_scanned(self):self.assertEqual([c['value'] for c in fs.source_candidates('Value: 120.25.')],[120.25])
    def test_extraction_schema_requires_source(self):
        from .assembly import plan_schema
        variants=plan_schema({'extraction','reasoning'},6)['properties']['nodes']['items']['anyOf'];extract=next(v for v in variants if v['properties']['type']['enum']==['extraction'])
        self.assertIn('context_field',extract['required'])
    def test_schema_id_matches_assembler(self):
        import re
        from .assembly import plan_schema
        pattern=plan_schema({'extraction'},6)['properties']['nodes']['items']['anyOf'][0]['properties']['id']['pattern']
        self.assertIsNone(re.fullmatch(pattern,'1'));self.assertIsNotNone(re.fullmatch(pattern,'custom_17'))
    def test_unavailable_source_still_no_candidates(self):self.assertEqual(fs.source_candidates('Cash figures use the same unit.'),[])
    def test_candidates_include_every_occurrence(self):
        cs=fs.source_candidates('6 USD, 17 USD, 6 USD');self.assertEqual([c['value'] for c in cs],[6,17,6]);self.assertEqual(len({c['source_id'] for c in cs}),3)
    def test_order_preserved_without_changing_identity(self):
        text='6 USD and 17 USD';cs=fs.source_candidates(text);selection=dict(selected_source_ids=[c['source_id'] for c in reversed(cs)],reason='Both cash operands')
        facts=fs.ground(fs.assemble_source_selection(selection,text)['facts'],'t','e','ctx_table',text);self.assertEqual([f['value'] for f in facts],[17,6]);self.assertEqual(fs.evaluate(fs.bind('v0-v1',facts),facts)['value'],11)
    def test_unknown_never_guessed(self):
        with self.assertRaisesRegex(fs.DataError,'SOURCE_SELECTION_UNKNOWN'):fs.assemble_source_selection(dict(selected_source_ids=['s_missing'],reason='unknown'),'6')
    def test_duplicate_rejected(self):
        sid=fs.source_candidates('6')[0]['source_id']
        with self.assertRaisesRegex(fs.DataError,'SOURCE_SELECTION_DUPLICATE'):fs.assemble_source_selection(dict(selected_source_ids=[sid,sid],reason='duplicate'),'6')
    def test_stale_source_rejected(self):
        sid=fs.source_candidates('6')[0]['source_id']
        with self.assertRaisesRegex(fs.DataError,'SOURCE_SELECTION_UNKNOWN'):fs.assemble_source_selection(dict(selected_source_ids=[sid],reason='stale'),'17')
    def test_empty_is_abstention_not_filled(self):self.assertEqual(fs.assemble_source_selection(dict(selected_source_ids=[],reason='No relevant operands'),'6')['facts'],[])
    def test_reason_required(self):
        with self.assertRaisesRegex(fs.DataError,'SOURCE_SELECTION_FORMAT'):fs.assemble_source_selection(dict(selected_source_ids=[],reason=''),'6')
    def test_no_source_digits_schema(self):self.assertEqual(fs.source_selection_schema(fs.source_candidates('same unit'))['properties']['selected_source_ids']['maxItems'],0)

class SelectionLoopTests(fixtures.ExecutionTests):
    def respond(self,m,p):
        try:d=json.loads(p)
        except ValueError:d=json.loads(p.split('\n',1)[1])
        if d.get('operation') in ('plan_typed_dag','repair_semantic_plan'):return json.dumps(plan(4))
        if d.get('operation')=='review_coverage':return json.dumps(dict(covered=True,requirements={'answer':['check']},reason='computed output'))
        if d['contract']=='facts.v1':return json.dumps(dict(selected_source_ids=[c['source_id'] for c in d['source_candidates']],reason='Select both raw cash operands'))
        if d['contract']=='expression.v1':return json.dumps(dict(expression=d['available_fact_variables'][1]+'-'+d['available_fact_variables'][0]))
        return json.dumps(dict(value=d['inputs']['value']))
    def test_generated_pipeline_raw_selection_and_cost(self):
        context=dict(question='cash increase?',ctx_table='6 USD and 17 USD',ctx_text='same unit');ex=self.executor(self.respond)
        a,b=InitialDAGGenerator(ex,'medium').generate_and_execute('selection-task','financial_arithmetic',context,{'answer':'numeric cash increase'},lambda g:{n.node_id:'medium' for n in g.nodes},extraction_mode='source_selection')
        self.assertEqual(a.status,'GENERATED');self.assertEqual(b['status'],'COMPLETE');self.assertEqual(b['final_outputs']['answer'],11);self.assertEqual(b['pipeline_accounting']['new_requests'],5)
        read_id=a.graph.provenance['semantic_ref_map']['read']
        trajectory=[json.loads(l) for l in (ex.directory/'TRAJECTORY.jsonl').read_text().splitlines()];raw=[t for t in trajectory if f'typed:dag:v1:{read_id}:' in t['key']][0]['response']['answer'];self.assertIn('selected_source_ids',raw);self.assertNotIn('evidence_start',raw)
    def test_empty_selection_blocks_reasoning(self):
        ctx=dict(question='cash increase?',ctx_table='6 and 17',ctx_text='');g=assemble(plan(4),'t',ctx,{'answer':'number'});ex=self.executor(lambda m,p:'{"selected_source_ids":[],"reason":"Cannot identify relevant operands"}')
        result=TypedExecutor(g,{n.node_id:'medium' for n in g.nodes},ex,ctx,extraction_mode='source_selection').run();self.assertEqual(result['data_errors']['form']['error_code'],'FACT_MISSING');self.assertEqual(ex.budget.attempts,1)
for name in vars(fixtures.ExecutionTests):
    if name.startswith('test_'):setattr(SelectionLoopTests,name,None)
