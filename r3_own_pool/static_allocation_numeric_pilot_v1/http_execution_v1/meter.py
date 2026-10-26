"""Exploratory estimates with inflight reservations. Never claims certification."""
from decimal import Decimal,InvalidOperation
from threading import RLock
from binding import Halt

def decimal(x):
    try:d=Decimal(str(x))
    except InvalidOperation:raise Halt('INVALID_MONEY')
    if not d.is_finite() or d<0:raise Halt('INVALID_MONEY')
    return d

def price(rate,tin,tout):
    effective=rate
    if rate.get('input_tiers'):
        effective=next((t for t in rate['input_tiers'] if tin<=t['up_to']),rate['input_tiers'][-1])
    return (decimal(tin)*decimal(effective['input'])+decimal(tout)*decimal(effective['output']))/Decimal(1000000)

class EstimatedMeter:
    def __init__(self,plan,caps=None,max_requests=8,max_output=36864):
        self.caps={k:decimal(v) for k,v in (caps or plan['estimate_caps_native']).items()}
        self.spent={k:Decimal(0) for k in self.caps};self.held={k:Decimal(0) for k in self.caps}
        self.claims={};self.outputs=0;self.max_requests=max_requests;self.max_output=max_output
        self.stopped=False;self.lock=RLock()

    def reserve(self,r,rate):
        cur=rate['currency'];amount=price(rate,65536,r['body']['max_tokens'])
        with self.lock:
            if self.stopped:raise Halt('ESTIMATE_METER_STOPPED')
            if r['request_id'] in self.claims:raise Halt('DUPLICATE_NO_RETRY')
            if len(self.claims)>=self.max_requests:raise Halt('REQUEST_LIMIT')
            if self.outputs+r['body']['max_tokens']>self.max_output:raise Halt('OUTPUT_RESERVATION_LIMIT')
            if self.spent[cur]+self.held[cur]+amount>self.caps[cur]:raise Halt('ESTIMATE_RESERVATION_LIMIT')
            self.claims[r['request_id']]={'currency':cur,'amount':amount,'settled':False}
            self.held[cur]+=amount;self.outputs+=r['body']['max_tokens']

    def settle(self,r,rate,usage):
        amount=price(rate,usage['prompt_tokens'],usage['completion_tokens'])
        with self.lock:
            c=self.claims[r['request_id']]
            if c['settled']:raise Halt('DOUBLE_SETTLEMENT')
            self.held[c['currency']]-=c['amount'];self.spent[c['currency']]+=amount;c['settled']=True
            # Persist the observed estimate even if the input assumption failed.
            # No code can undo already incurred external charges.
            if amount>c['amount'] or self.spent[c['currency']]+self.held[c['currency']]>self.caps[c['currency']]:
                self.stopped=True;raise Halt('ESTIMATE_EXCEEDED_AFTER_RESPONSE_NOT_CASH_HARD_LIMIT')
        return str(amount)

    def fail(self):
        with self.lock:self.stopped=True

    def snapshot(self):
        with self.lock:
            return {'estimate_spent_native':{k:str(v) for k,v in self.spent.items()},
                    'estimate_reservations_retained_native':{k:str(v) for k,v in self.held.items()},
                    'reserved_requests':len(self.claims),'output_tokens_reserved':self.outputs,
                    'input_bound_certified':False,'cash_hard_cap_certified':False,
                    'actual_cash':None,'bill_status':'PENDING_ACCOUNT_BILL_VERIFICATION'}
