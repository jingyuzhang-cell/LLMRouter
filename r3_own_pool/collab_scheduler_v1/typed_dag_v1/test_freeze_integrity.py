import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from .freeze_integrity import check,sha
class IntegrityTests(unittest.TestCase):
 def setup_packet(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);root=Path(t.name);model=root/'model';model.mkdir()
  for n in ('config.json','tokenizer.json','weight.bin'):(model/n).write_text('{}')
  snap={'medium':dict(path=str(model),served='medium-real',weights_verified=True,config_sha256={'config.json':sha(model/'config.json')},tokenizer_sha256={'tokenizer.json':sha(model/'tokenizer.json')},weight_sha256={'weight.bin':sha(model/'weight.bin')})}
  (root/'MODEL_POOL_OFFLINE.json').write_text(json.dumps(snap));(root/'PROMPT.json').write_text('{}')
  p=dict(required_files=['MODEL_POOL_OFFLINE.json','PROMPT.json'],file_sha256={n:sha(root/n) for n in ('MODEL_POOL_OFFLINE.json','PROMPT.json')},requests=2,total_tokens=100,cells=[dict(requests_upper=2,tokens_upper=100)])
  return root,p,{'medium':dict(path=str(model),served='medium-real')}
 def test_normal_no_http(self):
  r,p,c=self.setup_packet()
  with patch('urllib.request.urlopen',side_effect=AssertionError('HTTP')):self.assertEqual(check(r,p,c)['status'],'OFFLINE_GO')
 def test_missing_snapshot(self):
  r,p,c=self.setup_packet();(r/'MODEL_POOL_OFFLINE.json').unlink()
  with self.assertRaisesRegex(ValueError,'missing required'):check(r,p,c)
 def test_wrong_path(self):
  r,p,c=self.setup_packet();c['medium']['path']='/nonexistent'
  with self.assertRaisesRegex(ValueError,'model binding'):check(r,p,c)
 def test_tokenizer_changed(self):
  r,p,c=self.setup_packet();(Path(c['medium']['path'])/'tokenizer.json').write_text('{"changed":1}')
  with self.assertRaisesRegex(ValueError,'tokenizer_sha256'):check(r,p,c)
 def test_snapshot_hash(self):
  r,p,c=self.setup_packet();(r/'MODEL_POOL_OFFLINE.json').write_text('{}')
  with self.assertRaisesRegex(ValueError,'file hash'):check(r,p,c)
 def test_required_prompt_missing(self):
  r,p,c=self.setup_packet();(r/'PROMPT.json').unlink()
  with self.assertRaisesRegex(ValueError,'missing required'):check(r,p,c)
 def test_changed_prompt(self):
  r,p,c=self.setup_packet();(r/'PROMPT.json').write_text('{"changed":true}')
  with self.assertRaisesRegex(ValueError,'file hash'):check(r,p,c)
 def test_budget_sum(self):
  r,p,c=self.setup_packet();p['total_tokens']=99
  with self.assertRaisesRegex(ValueError,'budget sum'):check(r,p,c)
 def test_provider_mismatch(self):
  r,p,c=self.setup_packet();c['medium']['served']='other'
  with self.assertRaisesRegex(ValueError,'model binding'):check(r,p,c)
