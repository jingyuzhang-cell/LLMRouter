"""Human-authored pre-generation requirements, public evidence only; no gold."""
from .source_coverage import manifest,validate_requirements
from .protocol import digest

def freeze_requirements(context,decisions,reviewer,version):
 sources=manifest(context);fields={s['field'] for s in sources['sources']}
 if not reviewer or not version or set(decisions)!=fields:raise ValueError('Every public source must be independently reviewed')
 required=[];uncertain=[]
 for field,d in decisions.items():
  if set(d)!={'status','kind','evidence','rationale'} or d['status'] not in ('REQUIRED','IRRELEVANT','UNCERTAIN') or d['kind'] not in ('DATA','RULE','MIXED') or not d['rationale'] or d['evidence'] not in context[field] or not d['evidence']:raise ValueError('Exact public evidence and rationale required')
  if d['status']=='REQUIRED':required.append(dict(data_id=field+'-requirement',source_id=field,evidence=d['evidence']))
  if d['status']=='UNCERTAIN':uncertain.append(field)
 validate_requirements(required or None,sources)
 return dict(version=version,reviewer=reviewer,context_sha=digest(context),decisions=decisions,required_source_data=required or None,uncertain_sources=uncertain,semantic_status='REQUIRES_SEMANTIC_REVIEW' if uncertain else 'REVIEWER_DECLARATION_NOT_PROOF',scope='Source-path requirement; RULE linkage currently shares extraction-path rule, not a general instruction-dependency proof')
