import copy
import json
import unittest
from .recovery_matrix_v2_snapshot import Sources,build_snapshot,assert_runtime,BASE,OUT,digest
from .recovery_matrix_v2_pilot import execute_action,parse_retrieval

class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=Sources();cls.node=json.loads((BASE/'recovery_matrix_v2_pilot20.json').read_text())[0]
    def test_missing_actual_fails_closed(self):
        src=copy.copy(self.sources);src.responses={}
        s=build_snapshot(self.node,src)
        self.assertFalse(s['valid']);self.assertEqual(s['invalid_reason'],'missing_actual_extraction_output')
    def test_gold_mutation_cannot_change_runtime(self):
        before=build_snapshot(self.node,self.sources);src=copy.deepcopy(self.sources)
        for t in src.tasks.values():t.update(answer=987654321,derivation='SENTINEL_GOLD',program='SENTINEL_GOLD')
        for n in src.nodes.values():n.update(gold_facts={'facts':[{'value':987654321}]},program='SENTINEL_GOLD')
        self.assertEqual(before,build_snapshot(self.node,src));assert_runtime(before)
    def test_present_unparseable_is_not_missing(self):
        node=json.loads((BASE/'recovery_matrix_v2_pilot20.json').read_text())[1]
        s=build_snapshot(node,self.sources)
        self.assertTrue(s['valid']);self.assertEqual(s['facts_before'],{'facts':[]})
        self.assertTrue(s['actual_parent_outputs'][0]['output'])
    def test_retrieval_contract(self):
        f=parse_retrieval('row text\n{"facts":[{"value":2,"source":"row"}]}')
        self.assertEqual(f['facts'][0]['value'],2)
    def test_decompose_failure_does_not_reuse_old_response(self):
        s=build_snapshot(self.node,self.sources)
        def call(*args):return dict(answer='invalid json',usage={'total_tokens':17},latency_s=1.25)
        r=execute_action(s,'local_decompose',call)
        self.assertEqual(r['tokens'],17);self.assertEqual(r['dt_s'],1.25)
        self.assertEqual(len(r['calls']),1);self.assertEqual(r['snapshot_hash'],digest(s))
    def test_offline_keys_rejected(self):
        s=build_snapshot(self.node,self.sources);s['required_operands']=[1]
        with self.assertRaises(AssertionError):execute_action(s,'retry_same',None)

if __name__=='__main__':unittest.main()
