import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.probe_gap_information import draft_features,nested_subset,shuffled_indices,kernels


class InformationTests(unittest.TestCase):
    def test_draft_features_ignore_quality_and_gold(self):
        row=dict(answer='The answer is 12.',status='ok',quality=1,ground_truth='12')
        first=draft_features(row)
        row.update(quality=0,ground_truth='99',other_model_answer='unavailable')
        self.assertEqual(first,draft_features(row))

    def test_learning_subsets_are_nested(self):
        ids=np.arange(40);ds=np.array(['a']*20+['b']*20)
        small=set(nested_subset(ids,ds,42,.25));medium=set(nested_subset(ids,ds,42,.5));full=set(nested_subset(ids,ds,42,1.))
        self.assertTrue(small<medium<full)
        self.assertEqual(full,set(ids))

    def test_shuffle_stays_in_partition_and_dataset(self):
        ds=np.array(['a','b']*20);ids=np.arange(20)
        shuffled=shuffled_indices(ids,ds,42)
        self.assertEqual(set(ids),set(shuffled))
        np.testing.assert_array_equal(ds[ids],ds[shuffled])

    def test_held_drafts_cannot_change_training_kernel(self):
        x=np.ones((8,3));ds=np.array(['a']*8)
        text=np.array(['draft numbers repeat','draft code repeat']*4);num=np.ones((8,6))
        tr=np.arange(6);va=np.arange(6,8)
        a=kernels(x,text,num,ds,tr,va,'draft',42)
        text[va]='unseen tokens';num[va]=999
        b=kernels(x,text,num,ds,tr,va,'draft',42)
        np.testing.assert_array_equal(a[2],b[2])

if __name__=='__main__':unittest.main()
