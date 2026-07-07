# Example startup script for LLMRouter with multiple providers.
# Copy this file to start-multi-provider.local.ps1 and fill in your real keys.
# Do not commit or share the .local.ps1 file.

$env:PYTHONIOENCODING = "utf-8"

$env:DEEPSEEK_API_KEY = "YOUR_DEEPSEEK_KEY"
$env:QWEN_API_KEY = "YOUR_QWEN_KEY"
$env:DOUBAO_API_KEY = "YOUR_DOUBAO_ARK_KEY"
$env:GEMINI_API_KEY = "YOUR_GEMINI_KEY"

$env:API_KEYS = @{
  DeepSeek = $env:DEEPSEEK_API_KEY
  Qwen = $env:QWEN_API_KEY
  Doubao = $env:DOUBAO_API_KEY
  Gemini = $env:GEMINI_API_KEY
} | ConvertTo-Json -Compress

# API service:
# python -m llmrouter.cli.router_main serve --config configs/openclaw_multi_provider.yaml --host 127.0.0.1 --port 8000

# Gradio chat demo:
# python -m llmrouter.cli.router_main chat --router smallest_llm --config configs/model_config_test/multi_provider_smallest_llm.yaml --host 127.0.0.1 --port 8001
