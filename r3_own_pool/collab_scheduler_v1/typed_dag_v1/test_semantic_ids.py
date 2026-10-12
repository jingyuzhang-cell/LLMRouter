import copy
import json
import unittest
from pathlib import Path
from .semantic_ids import assemble_semantic, normalize_plan, guard_semantic_repair, semantic_schema
from .assembly import ConstraintError
from .protocol import validate, digest
from .generation import InitialDAGGenerator
from . import test_typed_dag as fixtures

CTX = dict(question='sum?', ctx_table='2', ctx_text='3')

def plan(size=3):
    rows = [dict(ref='raw', name='Read operands', type='extraction', subtask='Read table operands', context_field='ctx_table', dependencies=[]),
            dict(ref='math', name='Calculate sum', type='reasoning', subtask='Form sum of extracted operands', dependencies=['raw']),
            dict(ref='compute', name='Evaluate sum', type='transformation', subtask='Evaluate expression', dependencies=['raw','math'])]
    if size == 5:
        rows.insert(1, dict(ref='text', name='Read operands', type='extraction', subtask='Read text operands', context_field='ctx_text', dependencies=[]))
        rows[2]['dependencies'].append('text'); rows[3]['dependencies'].append('text')
        rows.append(dict(ref='audit', name='Check result', type='verification', subtask='Check computed result', dependencies=['compute']))
    return dict(nodes=rows, final_outputs=[dict(name='answer', node_ref=rows[-1]['ref'])])

class IdentityTests(unittest.TestCase):
    def make(self, p): return assemble_semantic(p, 'fresh-id-unit-task', CTX, {'answer':'number'})
    def error(self, p, code):
        before = copy.deepcopy(p)
        with self.assertRaises(ConstraintError) as exc: self.make(p)
        self.assertEqual(exc.exception.feedback['error_code'], code)
        self.assertEqual(p, before)
    def test_duplicate_decorative_ids_distinct_refs(self):
        p=plan(5)
        for row in p['nodes']: row['id']='1'
        g=self.make(p); self.assertEqual(len({n.node_id for n in g.nodes}),5)
    def test_duplicate_handle_rejected(self):
        p=plan();p['nodes'][1]['ref']='raw';self.error(p,'AMBIGUOUS_SEMANTIC_REFERENCE')
    def test_duplicate_legacy_id_not_guessed(self):
        p=plan()
        for row in p['nodes']:row['id']='1';del row['ref']
        self.error(p,'AMBIGUOUS_SEMANTIC_REFERENCE')
    def test_nonexistent_node(self):
        p=plan();p['nodes'][1]['dependencies']=['unknown'];self.error(p,'DEPENDENCY_REFERENCE')
    def test_forward_reference_and_order_stability(self):
        p=plan(5);q=copy.deepcopy(p);q['nodes'].reverse()
        a=self.make(p);b=self.make(q)
        self.assertEqual(a.nodes,b.nodes);self.assertEqual(a.final_outputs,b.final_outputs)
        self.assertEqual(a.provenance['semantic_ref_map'],b.provenance['semantic_ref_map'])
    def test_multiple_roots(self):
        g=self.make(plan(5));layers=validate(g).layers;self.assertEqual(len(layers[0]),2)
    def test_three_nodes(self):self.assertEqual(len(self.make(plan()).nodes),3)
    def test_five_nodes(self):self.assertEqual(len(self.make(plan(5)).nodes),5)
    def test_same_name_semantic_nodes(self):
        p=plan(5)
        for row in p['nodes']:row['name']='Same name'
        g=self.make(p);self.assertEqual(len(g.nodes),5)
    def test_wrong_output_port_rejected(self):
        p=plan();p['final_outputs'][0]['port']='facts';self.error(p,'FINAL_OUTPUT_FORMAT')
    def test_descriptive_dependency_not_guessed(self):
        p=plan();p['nodes'][1]['dependencies']=['Read operands'];self.error(p,'DEPENDENCY_REFERENCE')
    def test_numeric_legacy_handles_allocated(self):
        p=plan();mapping={n['ref']:str(i) for i,n in enumerate(p['nodes'])}
        for n in p['nodes']:
            n['id']=mapping[n['ref']]
            n['dependencies']=[mapping[d] for d in n['dependencies']];del n['ref']
        p['final_outputs']=[dict(name='answer',node_id='2')]
        g=self.make(p);self.assertTrue(all(n.node_id.startswith('node_') for n in g.nodes))
    def test_cycle_not_removed(self):
        p=plan();p['nodes'][0]['dependencies']=['compute'];self.error(p,'CYCLE')
    def test_incompatible_edge_not_removed(self):
        p=plan();p['nodes'][2]['dependencies']=['math'];self.error(p,'CONTRACT_UNBINDABLE')
    def test_id_stable_subtask_repair(self):
        p=plan();q=copy.deepcopy(p);q['nodes'][0]['subtask']='Read relevant numeric operands from table'
        self.assertEqual(self.make(p).provenance['semantic_ref_map'],self.make(q).provenance['semantic_ref_map'])
    def test_repair_cannot_delete_node_or_valid_edge(self):
        p=plan();q=copy.deepcopy(p);q['nodes'][2]['dependencies']=['math']
        with self.assertRaisesRegex(ConstraintError,'REPAIR_REMOVED_VALID_EDGE'):guard_semantic_repair(p,q,'u')
        q['nodes'].pop()
        with self.assertRaisesRegex(ConstraintError,'REPAIR_REMOVED_NODE'):guard_semantic_repair(p,q,'u')
    def test_ambiguous_repair_fails_closed(self):
        p=plan();p['nodes'][1]['ref']='raw'
        with self.assertRaisesRegex(ConstraintError,'REPAIR_AMBIGUOUS_IDENTITY'):guard_semantic_repair(p,plan(),'u')
    def test_real_invalid_replay_not_laundered(self):
        path=Path(__file__).parent/'stage3_source_selection_real_04/TRAJECTORY.jsonl'
        saved=[json.loads(l) for l in path.read_text().splitlines()]
        candidates=[json.loads(r['response']['answer']) for r in saved if 'generate' in r.get('key','')]
        self.assertGreaterEqual(len(candidates),2)
        for p in candidates:
            normalized,mapping,_=normalize_plan(p,'replay')
            self.assertEqual(len(mapping),len(p['nodes']))
            self.assertTrue(all(n['id'].startswith('node_') for n in normalized['nodes']))
            # Fixing IDs does NOT fix the missing facts+expression dependencies.
            self.error(p,'CONTRACT_UNBINDABLE')
    def test_schema_owns_no_execution_ids(self):
        s=semantic_schema({'extraction','reasoning'},8)
        for v in s['properties']['nodes']['items']['anyOf']:
            self.assertIn('ref',v['required']);self.assertNotIn('id',v['properties'])
        self.assertIn('node_ref',s['properties']['final_outputs']['items']['required'])

class LoopTests(fixtures.ExecutionTests):
    def dispatch(self,m,p):
        try:d=json.loads(p)
        except ValueError:d=json.loads(p.split('\n',1)[1])
        op=d.get('operation')
        if op in ('plan_typed_dag','repair_semantic_plan'):
            self.assertIn('node_ref',json.dumps(d['plan_json_schema']))
            return json.dumps(next(self.candidates))
        if op=='review_coverage':return json.dumps(dict(covered=True,requirements={'answer':[d['graph']['final_outputs'][0]['node_id']]},reason='Proposed sum is covered; heuristic only'))
        if d['contract']=='facts.v1':return json.dumps(dict(facts=[dict(value=2 if d['inputs']['context']=='2' else 3,evidence=d['inputs']['context'])]))
        if d['contract']=='expression.v1':return json.dumps(dict(expression='+'.join(d['available_fact_variables'])))
        return json.dumps(dict(value=d['inputs']['value']))
    def test_fresh_three_and_five_node_mock_complete(self):
        for size in (3,5):
            with self.subTest(size=size):
                self.candidates=iter([plan(size)]);ex=self.executor(self.dispatch)
                generated,result=InitialDAGGenerator(ex,'medium').generate_and_execute('mock-fresh-'+str(size),'financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
                self.assertEqual(generated.status,'GENERATED');self.assertEqual(len(generated.graph.nodes),size)
                self.assertEqual(result['status'],'COMPLETE');self.assertEqual(result['final_outputs']['answer'],2 if size==3 else 5)
                self.assertEqual(result['pipeline_accounting']['new_requests'],4 if size==3 else 6)
    def test_dangling_reference_repair_complete(self):
        broken=plan();broken['nodes'][1]['dependencies']=['missing']
        self.candidates=iter([broken,plan()]);ex=self.executor(self.dispatch)
        generated,result=InitialDAGGenerator(ex,'medium',max_repairs=1).generate_and_execute('mock-repair','financial_arithmetic',CTX,{'answer':'sum'},lambda g:{n.node_id:'medium' for n in g.nodes})
        self.assertEqual(generated.status,'REPAIRED');self.assertEqual(result['status'],'COMPLETE')
        self.assertEqual(generated.graph.graph_version,2);self.assertIsNotNone(generated.graph.provenance['parent_graph'])
    def test_unresolved_reference_bounded_fallback(self):
        p=plan();p['nodes'][1]['dependencies']=['missing'];self.candidates=iter([p,p]);ex=self.executor(self.dispatch)
        result=InitialDAGGenerator(ex,'medium',max_repairs=1).generate('mock-fallback','financial_arithmetic',CTX,{'answer':'sum'})
        self.assertEqual(result.status,'FALLBACK');validate(result.graph);self.assertEqual(ex.budget.attempts,2)
for name in vars(fixtures.ExecutionTests):
    if name.startswith('test_'):setattr(LoopTests,name,None)
