"""Read-only formal search admission report. Never imports model engine."""
import hashlib
import json
from pathlib import Path


def main():
    root=Path(__file__).resolve().parent
    a=json.loads((root/'ADMISSION_V1.json').read_text())
    mismatches=[name for name,digest in a['bindings'].items()
                if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest]
    protocol=json.loads((root/'SEARCH_BUDGET_V1.json').read_text())
    for name,digest in protocol['code_sha256'].items():
        path=Path('/root/r3_own_pool')/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:mismatches.append(str(path))
    print(json.dumps(dict(status='NOT_READY' if a['blockers'] or mismatches else a['status'],
          code_binding_mismatches=mismatches,blockers=a['blockers'],
          runtime_tests_pass=a['runtime_tests_pass'],per_session_caps=protocol['per_session_caps'],
          campaign_caps=protocol['campaign_caps'],execution_authorized=False,model_calls=0),
          ensure_ascii=False,indent=2))
    return 2 if mismatches else 0


if __name__=='__main__':raise SystemExit(main())
