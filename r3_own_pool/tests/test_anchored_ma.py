import unittest
import numpy as np
import torch
from router_v2.anchored_ma import AnchoredMA, fit_outer, guarded


class AnchoredMATests(unittest.TestCase):
    def test_initial_policy_is_exact_ridge_and_corrections_are_bounded(self):
        model=AnchoredMA(8,42)
        x=torch.randn(10,8);base=torch.rand(10,4)
        torch.testing.assert_close(model(x,base),base,rtol=0,atol=0)
        with torch.no_grad(): model.query[-1].weight.fill_(10.)
        self.assertLessEqual(float((model(x,base)-base).detach().abs().max()),.100001)

    def test_outer_labels_cannot_change_selection_or_choices(self):
        torch.set_num_threads(2);rng=np.random.default_rng(1)
        x=rng.normal(size=(90,12)).astype('float32');y=rng.integers(0,2,size=(90,4)).astype('float32')
        ds=np.array(['synthetic']*90);groups=np.arange(90)//2;tr=np.arange(60);va=np.arange(60,90)
        before,details=fit_outer(x,y,ds,groups,tr,va,42)
        y[va]=1-y[va]
        after,changed=fit_outer(x,y,ds,groups,tr,va,42)
        self.assertEqual(details['configurations'],changed['configurations'])
        for key in before:np.testing.assert_array_equal(before[key],after[key])

    def test_guard_respects_fallback_and_margin(self):
        pred=np.array([[.5,.51,.1,.2],[.5,.8,.1,.2]])
        np.testing.assert_array_equal(guarded(pred,np.array([0,0]),.02),[0,1])

if __name__=='__main__':unittest.main()
