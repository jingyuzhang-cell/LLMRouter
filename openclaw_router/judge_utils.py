"""Robust judge response extraction, JSON parsing, and optional score calibration."""
from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

def message_text_candidates(result: Dict[str, Any]) -> list[str]:
    values=[]
    try:
        choice=(result.get('choices') or [{}])[0]; message=choice.get('message') or {}
        for key in ('content','reasoning_content','reasoning','analysis'):
            value=message.get(key)
            if isinstance(value,str) and value.strip():values.append(value.strip())
        text=choice.get('text')
        if isinstance(text,str) and text.strip():values.append(text.strip())
    except Exception:pass
    return values

def extract_message_text(result: Dict[str, Any]) -> str:
    values=message_text_candidates(result)
    return '\n'.join(dict.fromkeys(values))

def _json_objects(text: str) -> Iterable[Dict[str, Any]]:
    decoder=json.JSONDecoder(); cleaned=re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$','',text or '',flags=re.I|re.S)
    for index,char in enumerate(cleaned):
        if char!='{':continue
        try:
            value,_=decoder.raw_decode(cleaned[index:])
            if isinstance(value,dict):yield value
        except Exception:continue

def parse_judge_payload(text: str) -> Optional[Dict[str, Any]]:
    data=None
    for item in _json_objects(text):
        if any(key in item for key in ('score','overall_score','评分','总分')):
            data=item;break
    if data is None:return None
    raw_score=next((data.get(k) for k in ('score','overall_score','评分','总分') if data.get(k) is not None),None)
    try:score=float(str(raw_score).strip().rstrip('%'))
    except Exception:return None
    if isinstance(raw_score,str) and raw_score.strip().endswith('%'):score/=100
    elif score>1:score/=100
    dimensions=data.get('dimensions') or data.get('维度') or {};clean={}
    aliases={'accuracy':('accuracy','准确性'),'completeness':('completeness','完整性'),'reasoning':('reasoning','推理'),'clarity':('clarity','清晰度'),'safety':('safety','安全性')}
    if isinstance(dimensions,dict):
        for target,keys in aliases.items():
            raw=next((dimensions.get(k) for k in keys if dimensions.get(k) is not None),None)
            if raw is None:continue
            try:value=float(str(raw).strip().rstrip('%'));value=value/100 if (isinstance(raw,str) and raw.strip().endswith('%')) or value>1 else value;clean[target]=round(max(0,min(1,value)),3)
            except Exception:continue
    return {'score':round(max(0,min(1,score)),3),'reason':str(data.get('reason') or data.get('理由') or '').strip()[:500],'dimensions':clean}

def load_calibration(path: Path) -> Dict[str, Any]:
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except Exception:return {}

def calibrate_score(model: str, score: float, config: Dict[str, Any]) -> float:
    if not config.get('enabled'):return round(max(0,min(1,float(score))),3)
    item=(config.get('models') or {}).get(model) or {}
    if not item.get('enabled',True):return round(max(0,min(1,float(score))),3)
    return round(max(0,min(1,float(item.get('intercept',0))+float(item.get('slope',1))*float(score))),3)
