# Backend tests (no Ollama needed), then frontend tests
pip install -r requirements-dev.txt
python -m pytest -q
cd frontend; npm install; npm test; cd ..
Write-Host "To ALSO run the real-model tests:  `$env:CAREERDNA_RUN_OLLAMA_TESTS='1'; python -m pytest tests/test_integration_ollama.py -s"
