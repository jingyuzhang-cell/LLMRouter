import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.prepare_judge_review import select_groups
from router_v2.core import SLOTS

class ReviewTests(unittest.TestCase):
    def group(self,primary,components):
        return {s:dict(quality=p,rubric=dict(correctness=c,completeness=0,clarity=0))
                for s,p,c in zip(SLOTS,primary,components)}
    def test_strata_and_determinism(self):
        groups={'a':self.group([.9,.6,.4,.2],[1,6,4,2]),
                'b':self.group([.9,.6,.4,.2],[6,5,4,2]),
                'c':self.group([.6,.5,.4,.2],[6,5,4,2])}
        selected,pools=select_groups(groups,1)
        self.assertEqual(dict(selected),dict(a='best_set_changed',b='score_changed_best_stable',c='consistent_control'))
        self.assertEqual(select_groups(dict(reversed(list(groups.items()))),1),(selected,pools))
    def test_missing_or_invalid_cannot_be_controls(self):
        group=self.group([.6,.5,.4,.2],[6,5,4,2]); group.pop(SLOTS[0])
        invalid=self.group([.6,.5,.4,.2],[True,5,4,2])
        self.assertEqual(select_groups({'a':group,'b':invalid})[0],[])

if __name__ == '__main__': unittest.main()
