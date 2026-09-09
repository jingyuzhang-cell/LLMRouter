from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2 import watch_judge

class WatchJudgeTests(unittest.TestCase):
    def test_stop_states_without_retrying_external_calls(self):
        cases=[({'phase':'CIRCUIT_OPEN'},'BLOCKED_CONSECUTIVE_JUDGE_ERRORS'),
               ({'phase':'LABEL_COVERAGE_COMPLETE'},'TRAIN_JUDGE_COVERAGE_COMPLETE'),
               ({'phase':'PARTIAL','missing_raw':0,'exhausted_unscored':1},'BLOCKED_EXHAUSTED_ATTEMPTS')]
        for result,expected in cases:
            with self.subTest(expected=expected),tempfile.TemporaryDirectory() as tmp:
                with patch('sys.argv',['judge','--output',tmp]),patch('openai.OpenAI'),patch('dotenv.dotenv_values',return_value={'QWEN_API_KEY':'test'}),patch.object(watch_judge,'run',return_value=result) as run:
                    watch_judge.main()
                    self.assertEqual(run.call_count,1)
                self.assertEqual(json.loads((Path(tmp)/'WATCHER_STATUS.json').read_text())['phase'],expected)

if __name__=='__main__':unittest.main()
