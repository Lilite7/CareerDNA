# Installs nothing silently. Checks Ollama, then asks before downloading the model.
param([string]$Model = "qwen2.5:3b")
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Write-Host "Ollama is not installed. Install it with:  winget install Ollama.Ollama"
  Write-Host "(or download from https://ollama.com/download), then re-open PowerShell and run this script again."
  exit 1
}
Write-Host "Ollama found: $(ollama --version)"
$installed = ollama list 2>$null | Select-String -SimpleMatch $Model
if ($installed) { Write-Host "Model $Model is already installed."; exit 0 }
$size = switch ($Model) { "qwen2.5:1.5b" {"about 1 GB"} "qwen2.5:3b" {"about 1.9 GB"} "qwen2.5:7b" {"about 4.7 GB"} default {"size unknown"} }
$ans = Read-Host "Download $Model ($size)? Needs that much free disk. (y/n)"
if ($ans -eq "y") { ollama pull $Model } else { Write-Host "Skipped. Nothing was downloaded." }
