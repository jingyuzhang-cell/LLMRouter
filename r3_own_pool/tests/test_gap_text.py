import sys
from pathlib import Path
import unittest
import numpy as np
from sklearn.linear_model import Ridge
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.improve_gap_text import text_kernels,predict


class TextGapTests(unittest.TestCase):
    def test_held_text_cannot_change_training_kernel(self):
        train=['algebra numbers repeated','geometry shapes repeated','algebra shapes repeated','geometry numbers repeated']
        xt=np.ones((4,2));xv=np.ones((1,2))
        a,_=text_kernels(train,['numbers'],xt,xv,0.)
        b,_=text_kernels(train,['novelword novelword othernewword'],xt,xv,0.)
        np.testing.assert_array_equal(a,b)

    def test_kernel_prediction_matches_ridge(self):
        rng=np.random.default_rng(7);xt=rng.normal(size=(10,4));xv=rng.normal(size=(3,4));y=rng.integers(0,2,size=(10,4))
        actual=predict(xt@xt.T,xv@xt.T,y,1.)
        expected=Ridge(alpha=1.).fit(xt,y).predict(xv).clip(0,1)
        np.testing.assert_allclose(actual,expected,atol=1e-10)

if __name__=='__main__':unittest.main()
