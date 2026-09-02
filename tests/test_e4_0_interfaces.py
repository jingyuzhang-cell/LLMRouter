import pytest
from phase_e4_0.interfaces import DAGNode,RuntimeState,StateAwareRouteRequest

def test_state_contract_accepts_only_pre_route_state():
 n=DAGNode('N2','structured_extraction',('N1',),'extract')
 r=StateAwareRouteRequest('t',n,{'context_token_count':10},RuntimeState(upstream_provider_success=True,upstream_output_length=20),('m1',))
 assert r.state.upstream_output_length==20

def test_state_contract_rejects_gold_and_post_route_leakage():
 n=DAGNode('N1','evidence_localization',(),'locate')
 with pytest.raises(ValueError,match='forbidden'):
  StateAwareRouteRequest('t',n,{'reference_answer':'leak'},RuntimeState(),('m1',))
 with pytest.raises(ValueError): RuntimeState(upstream_confidence=1.1)
