import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.assemble_development import snapshot,merge_labels

class MatrixTests(unittest.TestCase):
    def test_unfinished_tail_is_recorded_not_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cache.jsonl';path.write_bytes(b'{"a":1}\n{"a":')
            rows,info=snapshot(path)
            self.assertEqual(rows,[{'a':1}]);self.assertGreater(info['ignored_unfinished_tail_bytes'],0)

    def test_binding_and_first_judge_value(self):
        base=dict(query_id='x',slot='small',source_sha256='s',response_sha256='r')
        code=dict(**base,quality=None)
        supplement=dict(**base,quality=0)
        judge=dict(**base,response='unused',quality=.4,event='grade')
        later=dict(judge,quality=.9)
        labels=merge_labels([],[],[],[judge,later])
        self.assertEqual(next(iter(labels.values()))[1]['quality'],.4)
        labels=merge_labels([],[code],[supplement],[])
        self.assertEqual(next(iter(labels.values()))[0],'code_numpy')
        changed=dict(supplement,response_sha256='different')
        labels=merge_labels([],[code],[changed],[])
        self.assertEqual(len(labels),2)

if __name__=='__main__':unittest.main()
