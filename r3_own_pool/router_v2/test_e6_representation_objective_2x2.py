import unittest
import numpy as np
from sklearn.linear_model import Ridge
from .run_e6_representation_objective_2x2 import objective_weights,fit_delta_kernel,predict_delta,fit_four


class E6Tests(unittest.TestCase):
    def test_identity_is_existing_queryonly(self):
        rng=np.random.default_rng(4);x=rng.normal(size=(20,7));xt=rng.normal(size=(6,7));y=rng.random((20,4))
        delta=y[:,:3]-y[:,[3]]
        model=fit_delta_kernel(x,delta,np.eye(3),np.ones_like(delta))
        reference=Ridge(alpha=1.).fit(x,y).predict(xt)
        np.testing.assert_allclose(predict_delta(model,xt),reference[:,:3]-reference[:,[3]],atol=1e-10)

    def test_weighted_identity_is_weighted_ridge(self):
        rng=np.random.default_rng(5);x=rng.normal(size=(20,7));xt=rng.normal(size=(6,7));y=rng.random((20,3))
        w=rng.uniform(.1,2,y.shape);w/=w.mean(0)
        fitted=fit_delta_kernel(x,y,np.eye(3),w)
        expected=np.column_stack([Ridge(alpha=1.).fit(x,y[:,m],sample_weight=w[:,m]).predict(xt) for m in range(3)])
        np.testing.assert_allclose(predict_delta(fitted,xt),expected,atol=1e-10)

    def test_ties_retained_and_noise_downweighted(self):
        v=np.zeros((3,4,5))
        v[0,0,0]=1
        v[1,0,:3]=1;v[1,3,:2]=1
        delta,w,stability,raw=objective_weights(v)
        np.testing.assert_allclose(delta[0,0],delta[1,0])
        self.assertGreater(stability[0,0],stability[1,0]);self.assertGreater(raw[0,0],raw[1,0])
        self.assertTrue((w>0).all());np.testing.assert_allclose(raw[delta==0],.05)
        np.testing.assert_allclose(w.mean(0),1)

    def test_no_assumed_repeat_pairing(self):
        rng=np.random.default_rng(6);v=rng.integers(0,2,(14,4,5));original=objective_weights(v)
        altered=v.copy()
        for q in range(14):
            for m in range(4):altered[q,m]=rng.permutation(altered[q,m])
        for a,b in zip(original,objective_weights(altered)):np.testing.assert_allclose(a,b)

    def test_fit_does_not_use_outer_features_or_labels(self):
        rng=np.random.default_rng(7);x=rng.normal(size=(24,6));v=rng.integers(0,2,(24,4,5))
        d=np.arange(16);t=np.arange(16,24)
        _,f1,a1=fit_four(x[d],v[d],x[t])
        changed=x.copy();changed[t]*=100
        labels=v.copy();labels[t]=1-labels[t]
        _,f2,a2=fit_four(changed[d],labels[d],changed[t])
        self.assertEqual(a1['profiles'],a2['profiles'])
        np.testing.assert_array_equal(a1['weights'],a2['weights'])
        for arm in f1:
            np.testing.assert_array_equal(f1[arm]['dual'],f2[arm]['dual'])
            np.testing.assert_array_equal(f1[arm]['bias'],f2[arm]['bias'])


if __name__=='__main__':unittest.main()
