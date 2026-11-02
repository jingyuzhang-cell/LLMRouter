from pathlib import Path
import hashlib,json
p=Path(__file__).resolve().parent
old=Path('/root/research_outputs/RONBAY_DYNAMIC_PI_20261102/transport.py')
s=old.read_text()
s=s.replace("else:raise ValueError('UNBOUND_MODEL')", "elif model in ('glm-5.3','glm-5.3-flash'):\n   if body.get('thinking')!={'type':'enabled'} or body.get('reasoning_effort')!='low':raise ValueError('GLM_MODE_MISMATCH')\n  else:raise ValueError('UNBOUND_MODEL')")
s=s.replace("envname='DYNAMIC_PI_QWEN_KEY' if model.startswith('qwen') else 'DYNAMIC_PI_DEEPSEEK_KEY'", "envname={'glm-5.3':'RQ1_GLM_KEY','glm-5.3-flash':'RQ1_GLM_KEY','deepseek-flash':'DYNAMIC_PI_DEEPSEEK_KEY','qwen-plus-2025-12-01':'DYNAMIC_PI_QWEN_KEY'}[model]")
s=s.replace("'reported_model=reply.get('model')", "'reported_model=reply.get('model')") # no response rewriting
with (p/'transport.py').open('x') as f:f.write(s)
base=Path('/root/research_outputs/RONBAY_FINAL_ADMISSION_20261102')
ms=json.loads((base/'MODEL_BINDINGS.json').read_text())['models']
a={'authorized':False,'max_requests':60,'max_calls_per_model':15,'CNY_equivalent_estimate_stop':None,'USD_to_CNY':8,'accept_non_absolute_bill_cap':False,'accept_input_reservation_error':False,'models':{m['key']:{'model_id':m['model_id'],'endpoint':m['endpoint'],'currency':m['price']['currency'],'input_per_million':m['price']['input_per_M'],'output_per_million':m['price']['output_per_M'],'public_tariff_only':True,'account_confirmed':False,'account_evidence':None,'completion_usage_includes_all_billed_thinking':None,'usage_basis_evidence':None,'returned_aliases':[m['model_id']]} for m in ms},'stage2_authorized':False}
with (p/'AUTHORIZATION_TEMPLATE.json').open('x') as f:json.dump(a,f,ensure_ascii=False,indent=2)
print('new transport only; old SHA256',hashlib.sha256(old.read_bytes()).hexdigest())
