"""Synthetic acceptance/boundary cases, not experimental model outcomes."""
import copy
import json
import socket
import unittest
from unittest.mock import patch

with patch.object(socket.socket,'connect',side_effect=AssertionError('network prohibited')):
    from evaluate_terminal import CONTRACT,evaluate

def fixture():
    binding=json.load(open('..'+'/BINDING.json'))
    ids=list(binding['task']['evidence_catalog'])
    ref={i['item_id']:i for i in CONTRACT['reference']['items']}
    return {node:{'items':[{'item_id':key,'fields':{'amount':copy.deepcopy(ref[key]['fields']['amount']['expected'])},'evidence_ids':ids[:]} for key in keys]} for node,keys in CONTRACT['assigned_slots'].items()}

class ContractTests(unittest.TestCase):
    def test_correct_terminal(self):
        r=evaluate(fixture());self.assertEqual(r['content_Q'],1)
        self.assertEqual(r['legal_correct_targets'],6)
        self.assertTrue(r['all_branches_numeric_lane_legal'])
        self.assertIsNone(r['full_opinion_Q'])

    def test_wrong_value(self):
        f=fixture();f['extract_purchase']['items'][0]['fields']['amount']['number']='-1'
        r=evaluate(f);self.assertLess(r['content_Q'],1);self.assertEqual(r['legal_correct_targets'],5)

    def test_null_not_filled(self):
        f=fixture();f['extract_purchase']['items'][0]['fields']['amount']['number']=None
        before=copy.deepcopy(f);r=evaluate(f)
        self.assertEqual(f,before);self.assertEqual(r['legal_correct_targets'],5)
        self.assertNotEqual(r['content_Q'],5/6)  # F1 is not accuracy.

    def test_missing_branch_keeps_content_unknown(self):
        f=fixture();del f['extract_payables'];r=evaluate(f)
        self.assertIsNone(r['content_Q']);self.assertEqual(r['legal_correct_targets'],3)

    def test_native_array_not_repaired(self):
        f=fixture();f['extract_purchase']=f['extract_purchase']['items'];r=evaluate(f)
        self.assertEqual(r['content_Q'],1);self.assertFalse(r['all_branches_numeric_lane_legal'])
        self.assertEqual(r['legal_correct_targets'],3)

    def test_duplicate_slot_blocks_delivery(self):
        f=fixture();f['extract_purchase']['items'].append(copy.deepcopy(f['extract_purchase']['items'][0]))
        r=evaluate(f);self.assertFalse(r['all_branches_numeric_lane_legal']);self.assertEqual(r['legal_correct_targets'],3)

    def test_foreign_slot_not_discarded(self):
        f=fixture();f['extract_purchase']['items'][0]['item_id']='unexpected'
        r=evaluate(f);self.assertIsNone(r['content_Q']);self.assertFalse(r['all_branches_numeric_lane_legal'])

    def test_unknown_evidence_not_accepted(self):
        f=fixture();f['extract_purchase']['items'][0]['evidence_ids']=['NONEXISTENT']
        r=evaluate(f);self.assertEqual(r['content_Q'],1);self.assertEqual(r['legal_correct_targets'],3)

    def test_wrong_unit_not_credited(self):
        f=fixture();f['extract_purchase']['items'][0]['fields']['amount']['unit']='元'
        r=evaluate(f);self.assertLess(r['content_Q'],1)

    def test_duplicate_json_key_not_silent_overwrite(self):
        f=fixture();f['extract_purchase']='{"items":[],"items":[]}'
        r=evaluate(f);self.assertIsNone(r['content_Q']);self.assertEqual(r['legal_correct_targets'],3)

    def test_extra_branch_not_silent_drop(self):
        f=fixture();f['other']={'items':[]};r=evaluate(f)
        self.assertIsNone(r['content_Q']);self.assertEqual(r['content_status'],'UNRESOLVED_EXTRA_BRANCH')

    def test_extra_container_assertion_not_discarded(self):
        f=fixture();f['extract_purchase']['unsupported_conclusion']='全部合规'
        r=evaluate(f);self.assertIsNone(r['content_Q']);self.assertEqual(r['content_status'],'UNRESOLVED_CONTAINER_ASSERTIONS')

    def test_determinism_and_no_input_mutation(self):
        f=fixture();old=copy.deepcopy(f);self.assertEqual(evaluate(f),evaluate(f));self.assertEqual(f,old)

if __name__=='__main__':unittest.main(verbosity=2)
