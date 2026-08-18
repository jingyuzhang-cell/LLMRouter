param(
  [switch]$RealCall,
  [int]$Limit = 4,
  [string[]]$Models = @("deepseek-chat", "qwen-plus", "gemini-2.5-flash", "glm-5.2")
)

$ErrorActionPreference = "Stop"

Set-Location "D:\Claude Code\LLMRouter-main\LLMRouter-main"
$env:PYTHONIOENCODING = "utf-8"
$env:LLMROUTER_OFFLINE_EMBEDDINGS = "1"

$Models = @(
  foreach ($model in $Models) {
    foreach ($name in $model -split ",") {
      $trimmed = $name.Trim()
      if ($trimmed) {
        $trimmed
      }
    }
  }
)

function Invoke-PipelineStep {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments
  )

  Write-Host ""
  Write-Host $Label
  & python @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Label failed with exit code $LASTEXITCODE"
  }
}

Invoke-PipelineStep `
  -Label "Step 1/3: prepare standardized finance tasks" `
  -Arguments @(
    "scripts\prepare_finance_router_data.py",
    "--source", "seed"
  )

$evalArgs = @(
  "scripts\run_finance_model_evaluation.py",
  "--input", "data\finance_router\standardized\finance_router_tasks.jsonl",
  "--output", "data\finance_router\standardized\finance_router_tasks.with_results.jsonl",
  "--limit", "$Limit",
  "--force",
  "--models"
)

foreach ($model in $Models) {
  $evalArgs += $model
}

if (-not $RealCall) {
  $evalArgs += "--dry-run"
}

if ($RealCall) {
  Invoke-PipelineStep -Label "Step 2/3: run finance model evaluation" -Arguments $evalArgs
} else {
  Invoke-PipelineStep -Label "Step 2/3: run finance model evaluation (dry-run)" -Arguments $evalArgs
}

$labelArgs = @(
  "scripts\build_finance_router_training.py",
  "--input", "data\finance_router\standardized\finance_router_tasks.with_results.jsonl",
  "--output-jsonl", "data\finance_router\routing\finance_router_train.jsonl",
  "--output-csv", "data\finance_router\routing\finance_router_train.csv",
  "--models"
)

foreach ($model in $Models) {
  $labelArgs += $model
}

Invoke-PipelineStep -Label "Step 3/3: build router training labels" -Arguments $labelArgs

Write-Host ""
Write-Host "Done."
Write-Host "Training JSONL: data\finance_router\routing\finance_router_train.jsonl"
Write-Host "Training CSV:   data\finance_router\routing\finance_router_train.csv"
