#!/usr/bin/env python3
"""Dry-run-first immutable snapshot builder for validated KQAPro routing data."""
import argparse,hashlib,json,os,shutil
from datetime import datetime,timezone
from pathlib import Path
from kqa_routing_utils import MODEL_SPECS, validate_file
ROOT=Path(__file__).resolve().parents[1];DEFAULT=ROOT/"data/kqapro/router_data"
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,default=DEFAULT);p.add_argument('--models',nargs='+',required=True,choices=MODEL_SPECS);p.add_argument('--target',type=Path,required=True);p.add_argument('--include',nargs='*',type=Path,default=[]);p.add_argument('--apply',action='store_true');a=p.parse_args()
 sources=[];validation={}
 for m in a.models:
  src=a.data_dir/MODEL_SPECS[m]['file'];validation[m]=validate_file(src)
  if not validation[m]['passed']:raise SystemExit(f'validation failed: {m}')
  sources.append((Path('per_model')/src.name,src))
 for src in a.include:
  if src.is_file():
   sources.append((Path('artifacts')/src.name,src))
  elif src.is_dir():
   for child in sorted(x for x in src.rglob('*') if x.is_file()):
    sources.append((Path('artifacts')/src.name/child.relative_to(src),child))
  else:
   raise SystemExit(f'missing include: {src}')
 plan={'schema':'kqapro-freeze-plan-v1','dry_run':not a.apply,'target':str(a.target),'models':a.models,'source_files':[str(x[1]) for x in sources],'validated':True,'would_create_sha256sums':True,'would_mark_read_only':True}
 if not a.apply:print(json.dumps(plan,ensure_ascii=False,indent=2));return
 if a.target.exists():raise SystemExit(f'refusing to overwrite existing target: {a.target}')
 for rel,src in sources:
  dst=a.target/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 records={}
 for path in sorted(x for x in a.target.rglob('*') if x.is_file()):
  rel=str(path.relative_to(a.target));records[rel]={'bytes':path.stat().st_size,'sha256':digest(path)}
 manifest={'schema':'kqapro-frozen-snapshot-v1','created_utc':datetime.now(timezone.utc).isoformat(),'immutable_intent':True,'models':a.models,'files':records}
 (a.target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 all_files=sorted(x for x in a.target.rglob('*') if x.is_file() and x.name!='SHA256SUMS')
 (a.target/'SHA256SUMS').write_text(''.join(f"{digest(x)}  {x.relative_to(a.target)}\n" for x in all_files))
 for path in a.target.rglob('*'):
  os.chmod(path,0o555 if path.is_dir() else 0o444)
 os.chmod(a.target,0o555);print(json.dumps({'target':str(a.target),'files':len(all_files)+1,'frozen':True},indent=2))
if __name__=='__main__':main()
