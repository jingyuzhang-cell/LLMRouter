import sys
from pathlib import Path
import unittest
import numpy as np
from sklearn.linear_model import Ridge
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.improve_gap import predict_kernel, guarded, select_config


class GapTests(unittest.TestCase):
    def test_linear_kernel_matches_ridge_with_intercept(self):
        rng=np.random.default_rng(42);x=rng.normal(size=(20,8));y=rng.integers(0,2,size=(20,4)).astype(float)
        tr=np.arange(12);va=np.arange(12,20);ds=np.array(['a']*20)
        actual=predict_kernel(x@x.T,y,ds,tr,va,1.,False)
        expected=Ridge(alpha=1.).fit(x[tr],y[tr]).predict(x[va]).clip(0,1)
        np.testing.assert_allclose(actual,expected,atol=1e-10)

    def test_residual_and_ordinary_predictions_ignore_held_labels(self):
        rng=np.random.default_rng(7);x=rng.normal(size=(20,8));y=rng.integers(0,2,size=(20,4)).astype(float)
        tr=np.arange(12);va=np.arange(12,20);ds=np.array(['a','b']*10)
        changed=y.copy();changed[va]=1-changed[va]
        for residual in (False,True):
            a=predict_kernel(x@x.T,y,ds,tr,va,1.,residual)
            b=predict_kernel(x@x.T,changed,ds,tr,va,1.,residual)
            np.testing.assert_array_equal(a,b)

    def test_guard_retains_anchor_on_ties_and_small_gains(self):
        pred=np.array([[.5,.5,.1,.1],[.5,.53,.1,.1],[.5,.7,.1,.1]])
        np.testing.assert_array_equal(guarded(pred,np.zeros(3,dtype=int),.05),[0,0,1])

    def test_inner_ties_prefer_regularization_and_guard(self):
        candidates=[dict(quality=.8,alpha=1.,threshold=0.,gamma=1.),dict(quality=.8,alpha=20.,threshold=.05,gamma=1.)]
        self.assertEqual(select_config(candidates),candidates[1])

if __name__=='__main__':unittest.main()
