# Installs NOTHING silently. Asks before downloading an embedding model (needed only for CAREERDNA_RETRIEVAL_MODE=hybrid).
param([ValidateSet("nomic-embed-text","all-minilm")][string]$Model = "nomic-embed-text")
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Write-Host "Ollama is not installed. Run scripts\setup_ollama.ps1 first."; exit 1 }
$have = ollama list 2>$null | Select-String -SimpleMatch $Model
if ($have) { Write-Host "$Model is already installed."; exit 0 }
$size = if ($Model -eq "nomic-embed-text") { "roughly 270 MB (approximate, from memory)" } else { "roughly 45 MB (approximate, from memory)" }
$ans = Read-Host "Download $Model ($size)? (y/n)"
if ($ans -eq "y") { ollama pull $Model; Write-Host "Done. To use it: `$env:CAREERDNA_EMBED_MODEL = '$Model'" } else { Write-Host "Skipped. Nothing was downloaded." }
