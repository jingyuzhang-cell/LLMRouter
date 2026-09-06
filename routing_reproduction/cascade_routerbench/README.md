# Independent Cascade Routing / RouterBench reproduction

Scope: R1 only. No new model API calls. No edits to frozen E4/C9/E2/E3 experiments.

Protocol: REPRO_PROTOCOL.json. Environment: REPRO_ENVIRONMENT.json.
Upstream code revisions are recorded in the protocol; upstream checkouts remain unchanged.

Verified source: data/SOURCE.json. Hugging Face zero-shot pickle converted to CSV without reordering or imputation. The authors archive download was stopped after the smaller verified official RouterBench file became available; official-data.tar.gz is incomplete and must not be used.

Setup: `.venv/bin/pip install -r requirements-cpu.txt --index-url https://pypi.org/simple`

Run: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python run_reproduction.py --dataset gsm8k --models 9,4,5 --output-dir runs/gsm8k_3 > logs/smoke.log 2>&1`

The wrapper preserves upstream optimizer settings, seed, and 5%/95% split after dataset filtering. It disables network connection attempts during execution. GSM8K is published as grade-school-math (7450 rows, 372 train, 7078 test).

Do not run scripts/main.sh: it includes unrelated experiments. Do not run inference or generation scripts.

Smoke PASS requires both upstream AUC comparisons to favor Cascade Routing. A failure must be reported, without adjusting algorithms, thresholds, or splits. Broader 3/5/11-model experiments are gated on smoke PASS. No innovation is authorized in this project.

Resume the gated matrix (completed PASS and FAIL results are both preserved):

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 .venv/bin/python run_matrix.py >> logs/matrix.log 2>&1
.venv/bin/python aggregate_results.py
.venv/bin/python validate_results.py
```

AUC is the upstream trapezoidal integral between the cheapest and most expensive single-model mean costs, divided by that cost interval. Endpoint handling and duplicate-point processing follow `selection.utils.area_under_curve` unchanged. AUC comparisons apply within each setting; they are not significance tests.
