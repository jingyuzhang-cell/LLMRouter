import unittest
import torch
from router_v2.soft_pair_replay import soft_loss

class SoftPairTests(unittest.TestCase):
 def test_ties_have_no_artificial_direction(self):
  p=torch.zeros((3,4),requires_grad=True)
  soft_loss(p,torch.zeros(3)).backward()
  torch.testing.assert_close(p.grad,torch.zeros_like(p))
 def test_pair_swap_preserves_loss(self):
  p=torch.tensor([[0.,0.,.2,.8],[0.,0.,.7,.3]])
  m=torch.tensor([.4,-.2])
  torch.testing.assert_close(soft_loss(p,m),soft_loss(p[:,[0,1,3,2]],-m))
 def test_common_quality_offset_does_not_change_pair_loss(self):
  p=torch.tensor([[0.,0.,.2,.5]])
  torch.testing.assert_close(soft_loss(p,torch.tensor([.2])),soft_loss(p+.1,torch.tensor([.2])))

if __name__=='__main__':unittest.main()
