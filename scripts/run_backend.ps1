# Run from the project root (the folder that contains main.py)
python -m venv .venv 2>$null
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not $env:CAREERDNA_LLM_MODEL) { $env:CAREERDNA_LLM_MODEL = "qwen2.5:3b" }
uvicorn main:app --reload
