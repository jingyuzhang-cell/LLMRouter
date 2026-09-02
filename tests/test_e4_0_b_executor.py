from run_e4_0_b_exploration import parse,state_from
def test_parse_and_state_boundary():
 obj,valid=parse('{"evidence_items":[{"quote":"x"}],"confidence":0.8}'); assert valid and obj['confidence']==.8
 previous=[{'post_action_outcome':{'provider_success':True,'format_valid':True,'total_latency_ms':10,'cost_usd':.01,'attempt':1},'parsed_output':obj,'raw_output':'abc'}]
 s=state_from(previous,.01,1); assert s['evidence_count']==1 and s['upstream_output_length']==3 and 'provider_error' not in s
