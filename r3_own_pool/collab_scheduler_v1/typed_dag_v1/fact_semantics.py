"""Deterministic lexical source grounding and stable reference snapshots.

A numeric token in a quote is evidence location, NOT proof of semantic relevance.
"""
import ast,copy,hashlib,json,math,re
from fractions import Fraction
from .protocol import canonical,digest
NUMBER=re.compile(r'(?<![\w.])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?!\w|\.\d)')
class DataError(ValueError):
    def __init__(self,code,detail,node_id=None):
        self.feedback=dict(error_code=code,node_id=node_id,detail=detail,cause_certainty='OBSERVED_CONTRACT_VIOLATION')
        super().__init__(code+': '+detail)

def ground(facts,task_id,node_id,source_field,text):
    result=[]
    for f in facts:
        if f.get('kind','source_fact')!='source_fact':raise DataError('DERIVED_AS_SOURCE','Extraction cannot register a derived result',node_id)
        quote=f['evidence'];positions=[m.start() for m in re.finditer(re.escape(quote),text)]
        if not positions:raise DataError('SOURCE_MISMATCH','Evidence quote not found in selected input',node_id)
        pos=f.get('evidence_start')
        if pos is None:
            if len(positions)!=1:raise DataError('AMBIGUOUS_SOURCE','Provide evidence_start for repeated quote',node_id)
            pos=positions[0]
        if type(pos)!=int or pos not in positions:raise DataError('SOURCE_MISMATCH','Evidence offset mismatch',node_id)
        matches=[m for m in NUMBER.finditer(quote) if Fraction(m.group().replace(',',''))==Fraction(str(f['value']))]
        offset=f.get('number_start')
        if offset is not None:matches=[m for m in matches if type(offset)==int and pos+m.start()==offset]
        if not matches:raise DataError('SOURCE_VALUE_UNSUPPORTED','No exact numeric token supports value; cause (calculation/hallucination/conversion) undetermined',node_id)
        if len(matches)!=1:raise DataError('AMBIGUOUS_SOURCE','Provide absolute number_start for repeated numeric value',node_id)
        m=matches[0];start=pos+m.start();end=pos+m.end()
        suffix=text[end:];prefix=text[:start]
        unit='unknown'
        if suffix.startswith('%'):unit='percent'
        elif prefix.endswith('$'):unit='USD'
        else:
            um=re.match(r'\s*(USD|EUR|kg|万元|元)(?![A-Za-z])',suffix)
            if um:unit=um.group(1)
        claimed=f.get('unit')
        if claimed is not None and claimed!=unit:raise DataError('UNIT_SOURCE_MISMATCH','Claimed unit lacks adjacent source support',node_id)
        identity=dict(task_id=task_id,source_field=source_field,source_sha=hashlib.sha256(text.encode()).hexdigest(),number_start=start,number_end=end,value=str(Fraction(str(f['value']))),unit=unit)
        fid='f_'+digest(identity)[:24]
        result.append(dict(fact_id=fid,kind='source_fact',value=f['value'],unit=unit,data_type='number',evidence=quote,source={**identity,'evidence_start':pos,'evidence_end':pos+len(quote)},producing_nodes=[node_id],support_status='LEXICAL_NUMERIC_LOCATION_ONLY'))
    return merge(result)

def merge(facts):
    rows={}
    for f in facts:
        fid=f.get('fact_id')
        if not fid:raise DataError('FACT_ID_MISSING','Unregistered fact input')
        if f.get('kind')!='source_fact' or f.get('data_type')!='number' or type(f.get('value')) not in (int,float) or not math.isfinite(f['value']):raise DataError('FACT_TYPE','Expected finite registered source_fact number')
        if fid in rows:
            a={k:v for k,v in rows[fid].items() if k!='producing_nodes'};b={k:v for k,v in f.items() if k!='producing_nodes'}
            if a!=b:raise DataError('FACT_ID_COLLISION','Same ID has different content')
            rows[fid]['producing_nodes']=sorted(set(rows[fid]['producing_nodes']+f['producing_nodes']))
        else:rows[fid]=copy.deepcopy(f)
    return list(rows.values())

def fingerprint(fact):
    return digest({k:v for k,v in fact.items() if k!='producing_nodes'})

def bind(expression,facts):
    facts=merge(facts)
    if not facts:raise DataError('FACT_MISSING','Reasoning requires registered input facts')
    registry={f['fact_id']:f for f in facts};aliases={'v'+str(i):f['fact_id'] for i,f in enumerate(facts)}
    try:tree=ast.parse(expression,mode='eval')
    except SyntaxError as exc:raise DataError('EXPRESSION_ILLEGAL','Malformed arithmetic expression') from exc
    permitted=(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Name,ast.Load,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.USub,ast.UAdd)
    class Resolve(ast.NodeTransformer):
        def visit_Name(self,n):
            if n.id in aliases:n.id=aliases[n.id]
            elif re.fullmatch('v[0-9]+',n.id):raise DataError('REFERENCE_NOT_FOUND','Expression references unavailable fact index '+n.id)
            elif n.id not in registry:raise DataError('REFERENCE_NOT_FOUND','Unknown fact ID '+n.id)
            return n
    for n in ast.walk(tree):
        if not isinstance(n,permitted):raise DataError('EXPRESSION_ILLEGAL','Only restricted arithmetic allowed')
        if isinstance(n,ast.Constant) and (type(n.value) not in (int,float) or not math.isfinite(n.value)):raise DataError('EXPRESSION_ILLEGAL','Finite numeric constants only')
    tree=Resolve().visit(tree);canonical_expression=ast.unparse(tree)
    refs=sorted({n.id for n in ast.walk(tree) if isinstance(n,ast.Name)})
    if not refs:raise DataError('REFERENCE_MISSING','Expression must reference a registered fact')
    snapshot={u:fingerprint(registry[u]) for u in refs}
    binding=dict(expression=canonical_expression,references=refs,snapshot=snapshot,position_map=aliases,policy='typed-facts.v1')
    evaluate(binding,facts)
    return binding

def evaluate(binding,facts):
    registry={f['fact_id']:f for f in merge(facts)}
    for fid,h in binding['snapshot'].items():
        if fid not in registry:raise DataError('REFERENCE_NOT_FOUND','Required fact absent '+fid)
        if fingerprint(registry[fid])!=h:raise DataError('REFERENCE_CHANGED','Fact content/provenance changed '+fid)
    def visit(n):
        if isinstance(n,ast.Name):
            f=registry[n.id];return Fraction(str(f['value'])),{f['unit']:1}
        if isinstance(n,ast.Constant):return Fraction(str(n.value)),{}
        if isinstance(n,ast.UnaryOp):
            value,units=visit(n.operand);return (-value if isinstance(n.op,ast.USub) else value),units
        a,ua=visit(n.left);b,ub=visit(n.right)
        if isinstance(n.op,(ast.Add,ast.Sub)):
            if ua!=ub:raise DataError('UNIT_MISMATCH','Addition/subtraction require equal unit dimensions')
            return (a+b if isinstance(n.op,ast.Add) else a-b),ua
        units=dict(ua)
        for u,power in ub.items():units[u]=units.get(u,0)+(power if isinstance(n.op,ast.Mult) else -power)
        units={u:p for u,p in units.items() if p}
        return (a*b if isinstance(n.op,ast.Mult) else a/b),units
    try:value,units=visit(ast.parse(binding['expression'],mode='eval').body)
    except (KeyError,ZeroDivisionError,TypeError) as exc:raise DataError('EXPRESSION_ILLEGAL',str(exc)) from exc
    return dict(unit_check='UNDETERMINED' if any(registry[f]['unit']=='unknown' for f in binding['references']) else 'DIMENSIONS_CHECKED',kind='derived_value',value=float(value),unit_dimensions=units,data_type='number',source_fact_ids=binding['references'],expression=binding['expression'],binding_snapshot=binding['snapshot'],support_status='COMPUTED_FROM_REGISTERED_INPUTS_NOT_TASK_CORRECTNESS')


def lower_expression(binding,facts):
    evaluate(binding,facts)
    positions={f['fact_id']:'v'+str(i) for i,f in enumerate(facts)}
    class Lower(ast.NodeTransformer):
        def visit_Name(self,n):
            if n.id not in positions:raise DataError('REFERENCE_NOT_FOUND','Missing stable ID during tool adaptation')
            return ast.copy_location(ast.Name(id=positions[n.id],ctx=ast.Load()),n)
    return ast.unparse(Lower().visit(ast.parse(binding['expression'],mode='eval')))


def source_fact_output_schema(text):
    """Constrained extraction decoding: all numeric occurrences, no gold filtering.

    The LLM selects a subset; exact positions/values come from the public source.
    This controls source support, not task relevance or semantic completeness.
    """
    variants=[]
    for m in NUMBER.finditer(text):
        value=float(Fraction(m.group().replace(',','')))
        if not math.isfinite(value):continue
        properties={'value':{'type':'number','enum':[value]},'evidence':{'type':'string','enum':[text]},'evidence_start':{'type':'integer','enum':[0]},'number_start':{'type':'integer','enum':[m.start()]}}
        variants.append(dict(type='object',properties=properties,required=list(properties),additionalProperties=False))
    items={'anyOf':variants} if variants else {'type':'object'}
    facts=dict(type='array',items=items,maxItems=min(32,len(variants)))
    return dict(type='object',properties={'facts':facts},required=['facts'],additionalProperties=False)


def source_candidates(text):
    """All public numeric occurrences, with exact source-derived identities."""
    source_sha=hashlib.sha256(text.encode()).hexdigest()
    rows=[]
    for m in NUMBER.finditer(text):
        value=float(Fraction(m.group().replace(',','')))
        if not math.isfinite(value):continue
        rows.append(dict(source_id='s_'+source_sha[:12]+'_'+str(m.start()),value=value,literal=m.group(),source_sha=source_sha,number_start=m.start(),number_end=m.end(),context_window=text[max(0,m.start()-48):min(len(text),m.end()+48)]))
    return rows


def source_selection_schema(candidates):
    ids=[c['source_id'] for c in candidates]
    choices=dict(type='array',items={'type':'string','enum':ids} if ids else {'type':'string'},maxItems=len(ids))
    return dict(type='object',properties={'selected_source_ids':choices,'reason':{'type':'string','minLength':1}},required=['selected_source_ids','reason'],additionalProperties=False)


def assemble_source_selection(selection,text):
    """Resolve model choices only; never fill in missing or guessed selections."""
    if not isinstance(selection,dict) or set(selection)!={'selected_source_ids','reason'} or not isinstance(selection['reason'],str) or not selection['reason'].strip():raise DataError('SOURCE_SELECTION_FORMAT','Expected selected_source_ids and nonempty reason')
    ids=selection['selected_source_ids']
    if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):raise DataError('SOURCE_SELECTION_FORMAT','Source IDs must be strings')
    if len(set(ids))!=len(ids):raise DataError('SOURCE_SELECTION_DUPLICATE','Repeated source ID')
    candidates={c['source_id']:c for c in source_candidates(text)}
    result=[]
    for sid in ids:
        if sid not in candidates:raise DataError('SOURCE_SELECTION_UNKNOWN','Source ID absent from this public input '+sid)
        c=candidates[sid]
        result.append(dict(value=c['value'],kind='source_fact',evidence=text,evidence_start=0,number_start=c['number_start']))
    return {'facts':result}
