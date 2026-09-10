import sys
from pathlib import Path
import unittest
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from router_v2.diagnose_mechanism import diagnostic_fit, make_model
from router_v2.experiment import Router


class MechanismTests(unittest.TestCase):
    def test_normalization_keeps_parameter_count_and_initial_weights(self):
        a=make_model('original',8,42);b=make_model('normalized_model',8,42)
        self.assertEqual(sum(p.numel() for p in a.parameters()),sum(p.numel() for p in b.parameters()))
        for pa,pb in zip(a.parameters(),b.parameters()):
            torch.testing.assert_close(pa,pb)

    def test_curve_instrumentation_preserves_original_and_ignores_held_labels(self):
        torch.set_num_threads(1)
        rng=np.random.default_rng(42)
        x=rng.normal(size=(20,8)).astype('float32');y=rng.integers(0,2,size=(20,4)).astype('float32')
        original=Router(q_dim=8,seed=42,alpha=0.)
        original.fit(x[:12],y[:12],epochs=2,seed=42)
        pred,history,_=diagnostic_fit('original',x[:12],y[:12],x[12:],y[12:],42,epochs=2)
        np.testing.assert_array_equal(pred,original.predict_all(x[12:]))
        changed,_,_=diagnostic_fit('original',x[:12],y[:12],x[12:],1-y[12:],42,epochs=2)
        np.testing.assert_array_equal(pred,changed)
        self.assertEqual([r['epoch'] for r in history],[1,2])

if __name__=='__main__':unittest.main()
