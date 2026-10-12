"""Full strict protocol -> audited vLLM transport schema, never acceptance weakening."""
import ast,copy,json,hashlib,typing
from pathlib import Path
from importlib.metadata import distribution,version
from .protocol import canonical
from .semantic_validation import SemanticErrors,issue

def full_validate(candidate,schema):
    from jsonschema import Draft202012Validator
    errors=sorted(Draft202012Validator(schema).iter_errors(candidate),key=lambda e:str(list(e.path)))
    if errors:raise SemanticErrors([issue('PLANNING_SCHEMA',field='.'.join(map(str,e.path)) or 'root',expected='full frozen planning schema',actual=e.message) for e in errors])

def unsupported(schema):
    rows=[]
    def walk(obj,path):
        if isinstance(obj,dict):
            typ=obj.get('type')
            keys=('uniqueItems','contains','minContains','maxContains') if typ=='array' else ('format',) if typ=='string' else ('minProperties','maxProperties','propertyNames','patternProperties') if typ=='object' else ('multipleOf',) if typ in ('integer','number') else ()
            rows.extend(dict(path=path+'/'+key,keyword=key,value=obj[key]) for key in keys if key in obj)
            for key,value in obj.items():walk(value,path+'/'+str(key))
        elif isinstance(obj,list):
            for i,value in enumerate(obj):walk(value,path+'/'+str(i))
    walk(schema,'');return rows

def to_service_schema(schema):
    service=copy.deepcopy(schema);diffs=unsupported(schema)
    if any(d['keyword']!='uniqueItems' for d in diffs):raise ValueError('Unsupported service Schema feature without audited conversion: '+json.dumps(diffs))
    def strip(obj):
        if isinstance(obj,dict):
            if obj.get('type')=='array':obj.pop('uniqueItems',None)
            for value in obj.values():strip(value)
        elif isinstance(obj,list):
            for value in obj:strip(value)
    strip(service)
    return service,dict(full_sha256=hashlib.sha256(canonical(schema).encode()).hexdigest(),service_sha256=hashlib.sha256(canonical(service).encode()).hexdigest(),differences=diffs,conversion='omit uniqueItems from transport ONLY; full validation remains mandatory',full_schema=schema,service_schema=service)

def backend_precheck(schema):
    """Actual installed vLLM pure precheck + xgrammar compile; no engine/HTTP."""
    path=Path(distribution('vllm').locate_file('vllm/v1/structured_output/backend_xgrammar.py'))
    source=path.read_text();tree=ast.parse(source);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='has_xgrammar_unsupported_json_features')
    scope={'Any':typing.Any};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),'exec'),scope)
    if scope[fn.name](schema):raise ValueError('Installed vLLM HTTP backend refuses schema')
    import xgrammar
    xgrammar.Grammar.from_json_schema(schema)
    return dict(status='PASS',vllm=version('vllm'),xgrammar=version('xgrammar'),backend='xgrammar',backend_path=str(path),backend_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),http_requests=0)

def classify_http(status,body):
    return 'SERVICE_SCHEMA_UNSUPPORTED' if status==400 and 'schema' in body.lower() and ('not supported' in body.lower() or 'unsupported' in body.lower()) else 'HTTP_SERVICE_ERROR'
