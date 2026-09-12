"""Offline extraction audit; immutable raw answers, no generation or answer repair."""
import ast,json,random,re
from pathlib import Path
from . import score_code,score_available
from .data import load_cohort,sha
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/pool4_glm_rescore_v1'

def extract_option(text):
    boxed=re.findall(r'\\boxed\s*\{\s*([A-J])\s*\}',text or '',re.I)
    if boxed:return boxed[-1].upper()
    # Explicit answer marker accepts markdown, math delimiters and multiline answers.
    clean=re.sub(r'[*`$]','',text)
    clean=re.sub(r'\\boxed\{([A-J])\}',r'\1',clean)
    matches=re.findall(r'(?:\b(?:final\s+|correct\s+)?answer\s*(?:is\b)?\s*[:：]?|答案\s*[:：]?)\s*[\[(]?([A-J])\b',clean,re.I)
    if matches:return matches[-1].upper()
    # Isolated choice paragraph, never a list of alternatives or arbitrary last letter.
    paras=[p.strip() for p in re.split(r'\n\s*\n',clean) if p.strip()]
    if len(paras)>=2:
        for i in range(max(1,len(paras)-2),len(paras)):
            prev=paras[i-1]
            if re.search(r'(?:answer|(?:next\s+step|option|choice)\s+is)\s*[:：]\s*$',prev,re.I):
                m=re.match(r'^\(?([A-J])[.)]\s+[^\n]+$',paras[i])
                if m:return m.group(1)
    return score_available.metrics.extract_option(text)

def extract_code(text):
    blocks=re.findall(r'```[ \t]*(?:(?:python|py|python3)[ \t]*)?\n(.*?)```',text,re.S|re.I)
    code='\n\n'.join(blocks) if blocks else text
    lines=code.splitlines();has_function=False
    for i,line in enumerate(lines):
        if re.match(r'^(?:async )?def (?!check\b)\w+\(',line):has_function=True
        if has_function and (re.match(r'^(?:assert\b|def check\(|METADATA\s*=|check\(|print\(|if __name__\s*==)',line) or re.match(r'^#\s*(?:test(?:\s+cases?|s)?|example(?:\s+usage)?|usage)\b',line,re.I)):
            return '\n'.join(lines[:i]).rstrip()+'\n'
    return code

def self_test():
    for s in ['The answer is C because it follows.','Answer: $C','答案：C','**Answer:** (C)','The correct answer is:\n\nC. text','The most appropriate next step is:\n\nC. text\n\nThis follows.','Thus, the answer is \\[ \\boxed{C} \\]','C. concise answer text']:
        assert extract_option(s)=='C',s
    for s in ['A. one\nB. two\nC. three','Answer cannot be determined.','Calculate area A.','The numeric result is \\boxed{3}.']:
        assert extract_option(s) is None,s
    text='Explanation\n```python\ndef f(x):\n    return x\n\n# Test cases\nassert f(1)) == 1\n```\nEnd'
    assert extract_code(text)=='def f(x):\n    return x\n'
    assert 'return x))' in extract_code('```python\ndef f(x):\n    return x))\n```')
    ast.parse(extract_code(text))

def main():
    self_test();OUT.mkdir(exist_ok=False)
    raw=ROOT/'data/pool4_glm_pilot_120/glm.jsonl';panel=ROOT/'router_v2/pool4_pilot_120/PANEL.jsonl';rows=list(map(json.loads,raw.read_text().splitlines()));cohort,split=load_cohort(ROOT/'data/cohort_full_v2')
    original_hash=sha(raw);assert len(rows)==len({r['query_id'] for r in rows})==120
    runtime=score_code.verify_runtime();probe=json.loads((ROOT/'router_v2/CODE_SANDBOX_PROBE_V3.json').read_text());assert probe['status']=='PASS' and probe['runtime_manifest_sha256']==runtime
    protocol={'raw_sha256':original_hash,'panel_sha256':sha(panel),'scorer_sha256':sha(Path(__file__)),'runtime_sha256':runtime,'new_generations':0,'policy':'Extract code fence and implementation before top-level self-tests; no function-body repair. Explicit choice format expansion, no answer-key-assisted extraction. GSM8K unchanged. All 120 retained.'}
    (OUT/'PROTOCOL.json').write_text(json.dumps(protocol,indent=2)+'\n')
    audits=[];results=[];code_rows=[]
    for row in rows:
        q=row['query_id'];assert q in split['train'];source=cohort[q];ds=source['dataset'];detail={'query_id':q,'dataset':ds,'old_quality':row['quality']}
        if ds in ('humaneval','mbpp'):
            old_code=score_available.metrics.extract_code(row['answer']);code=extract_code(row['answer']);detail.update(extraction_changed=code.strip()!=old_code.strip(),raw_answer=row['answer'],extracted_code=code)
            for key,c in [('old_syntax',old_code),('new_syntax',code)]:
                try:ast.parse(c);detail[key]={'valid':True}
                except SyntaxError as e:detail[key]={'valid':False,'message':e.msg,'line':e.lineno,'text':e.text}
            result=score_code.score(source,{'answer':'```python\n'+code+'\n```','status':row['status']});code_rows.append(detail)
        elif ds=='mmlupro':
            option=extract_option(row['answer']);detail.update(old_option=score_available.metrics.extract_option(row['answer']),new_option=option,raw_answer=row['answer'])
            result={'quality':float(option==str(source['ground_truth']).strip().upper()[-1]) if option else 0.,'evaluation_status':'scored' if option else 'answer_parse_failed','parse_succeeded':option is not None}
        else:result=score_available.score(source,row)
        assert result['quality'] in (0,1),result
        detail.update(new_quality=result['quality'],evaluation=result);audits.append(detail);results.append({**row,**result,'rescore_raw_sha256':original_hash,'old_quality':row['quality']})
    assert sha(raw)==original_hash
    (OUT/'glm.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in results))
    (OUT/'AUDIT.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in audits))
    sample=random.Random(20260911).sample(code_rows,5)
    (OUT/'RANDOM_5_CODE.json').write_text(json.dumps(sample,ensure_ascii=False,indent=2)+'\n')
    (OUT/'STATUS.json').write_text(json.dumps({'phase':'COLLECTION_FINISHED','records':120,'new_generations':0})+'\n')
    print(json.dumps({'old_correct':sum(r['quality'] for r in rows),'new_correct':sum(r['quality'] for r in results),'changed':[d['query_id'] for d in audits if d['old_quality']!=d['new_quality']]},indent=2))
if __name__=='__main__':main()
