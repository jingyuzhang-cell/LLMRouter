"""Offline freeze validation. No model dispatch/start on import or CLI."""
import hashlib,json
from pathlib import Path

def validate_package(directory):
 directory=Path(directory);manifest=json.loads((directory/'MANIFEST.json').read_text())
 for file,digest in manifest['files'].items():
  path=directory/file
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('FREEZE_HASH:'+file)
 protocol=json.loads((directory/'PROTOCOL.json').read_text())
 if protocol['model_request_cap']!=0 or protocol['generation_paths_allowed']!=[]:raise ValueError('GENERATION_FORBIDDEN')
 if protocol['wall_seconds']!=300 or protocol['load_seconds']+protocol['cleanup_seconds']+protocol['margin_seconds']!=300:raise ValueError('WALL_ENVELOPE')
 if protocol['metadata_http_paths']!=['/health','/v1/models']:raise ValueError('HTTP_ALLOWLIST')
 return protocol

def metadata_request(method,path):
 if method!='GET' or path not in ['/health','/v1/models']:raise ValueError('PREFLIGHT_HTTP_FORBIDDEN')
 return {'method':method,'path':path}
