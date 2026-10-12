"""JSON Schema describing the existing Graph; not a separate graph format."""
def graph_schema(contracts,types,task_id,max_nodes):
    def obj(properties,required=None):return dict(type='object',properties=properties,required=list(properties) if required is None else required,additionalProperties=False)
    text={'type':'string','minLength':1}
    binding=obj(dict(port=text,source={'enum':['task','node']},field=text,node_id={'type':['string','null']}))
    node=obj(dict(node_id=text,node_type={'enum':sorted(types)},subtask=text,inputs={'type':'array','items':binding,'minItems':1},output_contract={'enum':sorted(contracts)},dependencies={'type':'array','items':text,'uniqueItems':True},success_contract={'const':'schema.v1'}))
    output=obj(dict(name=text,node_id=text,port=text))
    return obj(dict(graph_id=text,schema_version={'const':'typed-dag.v1'},graph_version={'const':1},task_id={'const':task_id},nodes={'type':'array','items':node,'minItems':1,'maxItems':max_nodes},final_outputs={'type':'array','items':output,'minItems':1},provenance={'type':'object'}))

OUTPUT_GUIDANCE={
 'facts.v1':'Return an object with facts array. Each item has value (finite number), kind=source_fact, and evidence (exact supporting input quote containing that exact numerical value). Optional unit must be explicitly supported adjacent to the number; do not infer or convert units. Omit evidence_start and number_start unless the quote or value repeats. If needed, copy absolute zero-based offsets from source_numeric_locations; NEVER guess offsets. Extract each relevant raw number separately. Never compute a total or invent a number. If no relevant numerical facts appear in selected context, return an empty array.',
 'expression.v1':'Return an object with expression string. Prefer the supplied stable fact_id variables. Position aliases v0, v1 are accepted only through the explicit position_to_fact_id mapping in this request. Do the operation requested in the question. Never refer to an index beyond the supplied facts length. Only arithmetic +,-,*,/ and numeric constants, no code.',
 'calculate.v1':'Return an object with value containing the computed finite number, not an example.',
 'verify_expression.v1':'Return an object with value containing the computed finite answer. Evaluate the input expression with the supplied facts, never copy format examples.',
 'verify_value.v1':'Return an object with value containing the checked input numeric value. Do not substitute a demonstration number.'}
