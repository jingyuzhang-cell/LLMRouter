"""Fixed financial reference topology, expressed through explicit typed bindings."""
from .protocol import Graph,Node,Binding,Output

def fixed_financial_graph(task_id):
    task=lambda p,f:Binding(p,'task',f)
    src=lambda p,n,f:Binding(p,'node',f,n)
    nodes=[Node('e1','extraction','Extract supported table facts',[task('question','question'),task('context','ctx_table')],'facts.v1',[]),
           Node('e2','extraction','Extract supported text facts; empty is permitted',[task('question','question'),task('context','ctx_text')],'facts.v1',[]),
           Node('r','reasoning','Construct arithmetic expression',[task('question','question'),src('facts','e1','facts'),src('facts','e2','facts')],'expression.v1',['e1','e2']),
           # Facts are explicit dependencies; legacy executor passed these implicitly.
           Node('v','verification','Verify expression and return final value',[task('question','question'),src('facts','e1','facts'),src('facts','e2','facts'),src('expression','r','expression')],'verify_expression.v1',['e1','e2','r'])]
    return Graph('fixed-financial','typed-dag.v1',1,task_id,nodes,[Output('answer','v','value')],
                 {'origin':'fixed reference','dependency_note':'Legacy v receives facts implicitly; explicit data edges added. No claim of byte-identical prompts.'})
