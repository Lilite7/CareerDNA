# Checks RAM / disk and recommends a Qwen2.5 size. Does NOT download anything.
$ramGB  = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$disk   = Get-PSDrive -Name ($PWD.Drive.Name) -ErrorAction SilentlyContinue
$freeGB = if ($disk) { [math]::Round($disk.Free / 1GB, 1) } else { "unknown" }
$gpu    = (Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join ", "
Write-Host "RAM: $ramGB GB   Free disk: $freeGB GB   GPU: $gpu"
if ($ramGB -lt 8)      { $m = "qwen2.5:1.5b"; $why = "under 8 GB RAM: the 1.5B model (about 1 GB download) is the safe choice" }
elseif ($ramGB -lt 16) { $m = "qwen2.5:3b";   $why = "8-16 GB RAM: the 3B model (about 2 GB download) should run, answers take longer without a GPU" }
else                   { $m = "qwen2.5:3b";   $why = "16+ GB RAM: 3B is fine (you could try qwen2.5:7b, about 4.7 GB, for better quality)" }
Write-Host "Recommended model: $m  ($why)"
Write-Host "To use it:  `$env:CAREERDNA_LLM_MODEL = `"$m`"   then   ollama pull $m"
