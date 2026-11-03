"""Separate cooperative protocol. No model start or HTTP implementation."""
import time
from pathlib import Path
from kdx_service_preflight import validate_package

def offline_validate(package):
 p=validate_package(package)
 if p.get('protocol_kind')!='TRUSTED_SHARED_PREFLIGHT' or p.get('isolation_enforced') is not False:raise ValueError('PROTOCOL_SCOPE')
 expected=['same_permission_gpu_access_possible','lock_is_cooperative','driver_release_deadline_not_guaranteed','development_preflight_only']
 if p.get('limitations')!=expected:raise ValueError('LIMITATIONS_MISSING')
 if p.get('inference_token_cap')!=0 or p.get('business_extraction_allowed') is not False:raise ValueError('INFERENCE_FORBIDDEN')
 return p

def start_admission(protocol,attestation,gpu_processes,run_dir,history_records=(),now=None):
 # Attestations are human coordination evidence, not permission isolation or real-call authorization.
 now=time.time() if now is None else now
 if not attestation.get('operators_agreed') or not attestation.get('coordination_evidence'):raise ValueError('OPERATOR_COORDINATION_REQUIRED')
 if not attestation.get('window_start',float('inf'))<=now or now+protocol['wall_seconds']>attestation.get('window_end',0):raise ValueError('EXCLUSIVE_WINDOW_INSUFFICIENT')
 if Path(protocol['quarantine_path']).exists():raise ValueError('RESOURCE_QUARANTINED')
 if gpu_processes:raise ValueError('GPU_IN_USE')
 if Path(run_dir).exists() or any(r.get('protocol_id')==protocol['protocol_id'] for r in history_records):raise ValueError('DUPLICATE_PREFLIGHT')
 if not attestation.get('collaborative_lock_available'):raise ValueError('COOPERATIVE_LOCK_UNAVAILABLE')
 return {'status':'ADMISSIBLE_AFTER_SEPARATE_REAL_AUTHORIZATION','actual_lock_required':'atomic nonblocking flock must be acquired again at actual start','generation_requests':0}
