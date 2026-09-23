# 从仓库根目录启动 AI Runtime（:9000）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$aiDir = Join-Path $root "ai_runtime"
Set-Location $aiDir
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "已复制 .env.example -> .env，请填写 DEEPSEEK_API_KEY 后重跑。"
}
Write-Host "Starting ai_runtime on :9000 ..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 9000
