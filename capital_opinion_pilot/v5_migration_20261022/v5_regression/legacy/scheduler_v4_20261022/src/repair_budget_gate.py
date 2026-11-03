"""Pure strict pre-dispatch gate, does not transmit or estimate unknown input."""
def check(actual,pending,attempts,input_upper,output_upper,token_cap=4000,call_cap=2):
 if attempts>=call_cap:raise ValueError('REQUEST_CAP')
 if input_upper is None:raise ValueError('INPUT_BOUND_UNKNOWN')
 if any(type(x)!=int or x<0 for x in (actual,pending,attempts,input_upper,output_upper)):raise ValueError('BUDGET_FORMAT')
 reservation=input_upper+output_upper
 if actual+pending+reservation>token_cap:raise ValueError('TOKEN_CAP')
 return reservation
