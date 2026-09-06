import numpy as np
from phase_e5_unified.common import components,delivery,whole_prompt

def test_reference_excluded_from_prompt():
 t={'question':'q','context':'ctx','table':[],'reference_answer':'SECRET_GOLD'}
 assert 'SECRET_GOLD' not in whole_prompt(t)
 assert 'citations' in whole_prompt(t)

def test_final_delivery_shared_strict_gate():
 raw='{"answer":"1","citations":["table"],"confidence":0.5}'
 assert delivery(raw)[0]
 assert not delivery(raw,provider_success=False)[0]
 assert not delivery(raw,binding=True)[0]
 assert not delivery('{"answer":"1"}')[0]

def test_metrics_use_workflow_units():
 np.testing.assert_allclose(components(.75,.01,5000,True),[.75,.5,.5,1])
 np.testing.assert_allclose(components(0,.2,100000,False),[0,0,0,0])

def test_budget_rejects_before_provider_call(tmp_path,monkeypatch):
 import asyncio
 from types import SimpleNamespace
 import phase_e5_unified.execute as ex
 monkeypatch.setattr(ex,'OUT',tmp_path)
 engine=ex.Engine()
 engine.cfg=SimpleNamespace(llms={'fake':SimpleNamespace(provider='fake',input_price=1.,output_price=1.,context_limit=1000000)})
 engine.budget={'cap_usd':10.,'reservations':{'old':{'bound_usd':9.5}}}
 class Backend:
  async def call(self,*a,**kw):raise AssertionError('must not call provider')
 engine.backend=Backend()
 try:asyncio.run(engine.call('new','fake','q',1200,120))
 except ex.BudgetExceeded:pass
 else:raise AssertionError('budget should reject')
 assert 'new' not in engine.budget['reservations']

def test_unknown_billing_retains_reservation(tmp_path,monkeypatch):
 import asyncio
 from types import SimpleNamespace
 import phase_e5_unified.execute as ex
 monkeypatch.setattr(ex,'OUT',tmp_path)
 engine=ex.Engine()
 engine.cfg=SimpleNamespace(llms={'fake':SimpleNamespace(provider='fake',model_id='fake',input_price=1.,output_price=1.,context_limit=1000)})
 class Backend:
  async def call(self,*a,**kw):raise TimeoutError()
 engine.backend=Backend()
 r=asyncio.run(engine.call('new','fake','q',100,120))
 assert not r['billing_known']
 assert abs(engine.charged()-.0011)<1e-10
 assert engine.budget['reservations']['new']['status']=='UNKNOWN_BILLING_BOUND_RETAINED'
 # Resume uses saved event, never sends again or charges twice.
 asyncio.run(engine.call('new','fake','q',100,120))
 assert abs(engine.charged()-.0011)<1e-10
