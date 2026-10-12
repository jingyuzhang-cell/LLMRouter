"""Bounded generation+review only, sharing the production generator and ledger."""
import json,hashlib
from .http_diagnostic import build_request,decode_response
from .service_schema import full_validate
from collab_scheduler_v1.joint_search_smoke.proposal_v2.smoke_runner import StopRun,append

CONTEXT_LIMIT=8192
OUTPUT_LIMITS={'generate':768,'semantic_review':256}

def request_packet(served,prompt):
    body=json.loads(prompt);op=body['operation']
    if op=='review_coverage':phase='semantic_review';schema=body['review_json_schema']
    elif op in ('plan_typed_dag','plan_goal_ir'):phase='generate';schema=body['plan_json_schema']
    else:raise StopRun('Unapproved diagnostic phase: '+op)
    payload,audit=build_request(served,prompt,schema);payload['max_tokens']=4096 if phase=='generate' and body.get('wire_protocol')=='bounded-planning-wire.v1' else OUTPUT_LIMITS[phase]
    return phase,payload,audit

def count_input(tokenizer,payload):
    return len(tokenizer.apply_chat_template(payload['messages'],tokenize=True,add_generation_prompt=True))

class DiagnosticArm:
    """Preflight before original MeteredExecutor; each phase at most once."""
    def __init__(self,inner,tokenizer,served,expected_generation_tokens,expected_prompt_sha256=None):
        self.inner=inner;self.tokenizer=tokenizer;self.served=served;self.expected=expected_generation_tokens
        self.expected_prompt_sha256=expected_prompt_sha256
        self.counts={'generate':0,'semantic_review':0};self.requests=[]
    def __getattr__(self,name):return getattr(self.inner,name)
    def call(self,key,model,prompt):
        phase,payload,audit=request_packet(self.served,prompt);n=count_input(self.tokenizer,payload);out=payload['max_tokens']
        if self.counts[phase]>=1:raise StopRun('Phase request cap')
        if n+out>CONTEXT_LIMIT:raise StopRun('Context/input token boundary; no dispatch')
        if phase=='generate' and self.expected_prompt_sha256 and hashlib.sha256(prompt.encode()).hexdigest()!=self.expected_prompt_sha256:raise StopRun('Frozen generation Prompt hash changed')
        if phase=='generate' and n!=self.expected:raise StopRun('Frozen generation input changed')
        amount=n+out;future=CONTEXT_LIMIT if phase=='generate' else 0
        if self.budget.charged+amount+future>self.budget.caps['new_total_tokens']:raise StopRun('Future review reservation unavailable')
        if self.budget.attempts+1+(phase=='generate')>self.budget.caps['new_request_attempts']:raise StopRun('Future review request reservation unavailable')
        self.budget.caps['request_token_reservation']=amount
        self.budget.caps['max_output_tokens']=out
        self.counts[phase]+=1;record=dict(phase=phase,input_tokens=n,max_output_tokens=out,reservation=amount,review_future_reserve=future,schema_audit=audit,payload=payload)
        self.requests.append(record);append(self.directory/'REQUEST_PREFLIGHT.jsonl',record)
        return self.inner.call(key,model,prompt)
