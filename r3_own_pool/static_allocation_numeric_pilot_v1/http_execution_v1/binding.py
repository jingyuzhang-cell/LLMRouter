"""Frozen-plan checks and explicit authorization; no network or key reads on import."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path

HERE=Path(__file__).resolve().parent

class Halt(RuntimeError):pass

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_plan():
    freeze=json.loads((HERE/'FREEZE.json').read_text())
    for path,identity in freeze['files'].items():
        if sha(path)!=identity:raise Halt('FROZEN_HASH_MISMATCH:'+path)
    return json.loads((HERE/'PLAN.json').read_text())

def verify_authorization(path,plan,now=None):
    if not path or not Path(path).is_file():raise Halt('INDEPENDENT_EXECUTION_AUTHORIZATION_REQUIRED')
    a=json.loads(Path(path).read_text())
    required={'batch_id':plan['batch_id'],'freeze_sha256':sha(HERE/'FREEZE.json'),
              'execution_authorized':True,'accept_estimated_envelope_not_hard_cash_limit':True,
              'allow_public_task_material_to_bound_official_endpoints':True,
              'max_requests':8,'max_output_tokens_total':36864,
              'input_reservation_tokens_per_request':65536,
              'estimate_caps_native':plan['estimate_caps_native'],
              'request_deadline_s':180,'arm_deadline_s':240,'batch_deadline_s':3600,
              'automatic_retries':0}
    for k,v in required.items():
        if a.get(k)!=v:raise Halt('AUTHORIZATION_MISMATCH:'+k)
    if a.get('evidence_class')=='SYNTHETIC_TEST_ONLY':raise Halt('TEST_RECEIPT_CANNOT_AUTHORIZE_REAL_HTTP')
    if not isinstance(a.get('operator_statement'),str) or not a['operator_statement'].strip():
        raise Halt('MISSING_OPERATOR_STATEMENT')
    try:expiry=dt.datetime.fromisoformat(a['not_after_utc'].replace('Z','+00:00'))
    except (KeyError,ValueError,TypeError):raise Halt('AUTHORIZATION_EXPIRY_REQUIRED')
    now=now or dt.datetime.now(dt.timezone.utc)
    if expiry.tzinfo is None or expiry<=now:raise Halt('AUTHORIZATION_EXPIRED')
    if expiry>now+dt.timedelta(hours=48):raise Halt('AUTHORIZATION_WINDOW_TOO_LONG')
    # Public prices must be checked again if this prepared snapshot ages.
    checked=dt.date.fromisoformat(plan['public_price_snapshot_date_Asia_Shanghai'])
    today=now.astimezone(dt.timezone(dt.timedelta(hours=8))).date()
    if not 0 <= (today-checked).days <= 1:raise Halt('PUBLIC_PRICE_SNAPSHOT_STALE_REFRESH_BEFORE_EXECUTION')
    return a

def load_keys_after_authorization(plan):
    """Called only after the independent execution receipt has passed."""
    needed=set(plan['credential_env'].values())
    keys={k:os.environ[k] for k in needed if os.environ.get(k)}
    for path in [Path('/root/.env.modelpool'),Path('/root/.env')]:
        if needed<=keys.keys():break
        if not path.is_file():continue
        for line in path.read_text().splitlines():
            line=line.strip()
            if line.startswith('export '):line=line[7:].lstrip()
            if not line or line.startswith('#') or '=' not in line:continue
            name,value=line.split('=',1);name=name.strip()
            if name in needed and name not in keys:
                value=value.strip().strip('"').strip("'")
                if value:keys[name]=value
    if needed-keys.keys():raise Halt('REQUIRED_CREDENTIAL_NOT_AVAILABLE')
    return {model:keys[name] for model,name in plan['credential_env'].items()}
