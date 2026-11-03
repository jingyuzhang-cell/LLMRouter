import unittest
from kdx_token_accounting import build_request,compare,MODEL
class Accounting(unittest.TestCase):
 def response(self):return {'model':MODEL,'choices':[{'prompt_token_ids':[1,2],'token_ids':[3],'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':1,'total_tokens':3}}
 def test_match(self):self.assertEqual(compare(build_request([1,2]),self.response())['status'],'TOKEN_IDS_AND_USAGE_MATCH')
 def test_count_only(self):r=self.response();del r['choices'][0]['prompt_token_ids'];self.assertEqual(compare(build_request([1,2]),r)['status'],'COUNT_ONLY')
 def test_ids_mismatch(self):r=self.response();r['choices'][0]['prompt_token_ids']=[2,1];self.assertRaises(ValueError,compare,build_request([1,2]),r)
 def test_usage_missing(self):r=self.response();r['usage']={};self.assertRaises(ValueError,compare,build_request([1,2]),r)
 def test_usage_wrong(self):r=self.response();r['usage']['prompt_tokens']=3;self.assertRaises(ValueError,compare,build_request([1,2]),r)
 def test_output_limit(self):r=self.response();r['choices'][0]['token_ids']=[3]*9;self.assertRaises(ValueError,compare,build_request([1,2]),r)
 def test_no_wrapping(self):r=build_request([1,2]);self.assertFalse(r['add_special_tokens']);self.assertFalse(r['stream']);self.assertEqual(r['n'],1)
 def test_invalid_input(self):self.assertRaises(ValueError,build_request,['1'])
 def test_output_ids_missing(self):r=self.response();del r['choices'][0]['token_ids'];self.assertRaises(ValueError,compare,build_request([1,2]),r)
 def test_model_wrong(self):r=self.response();r['model']='other';self.assertRaises(ValueError,compare,build_request([1,2]),r)
