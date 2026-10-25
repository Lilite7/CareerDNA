# Real A/B/C evaluation. Needs: Ollama running, the chat model, and the embedding model (scripts\setup_embeddings.ps1).
# Step 1 tunes the similarity threshold on the DEV split only. Step 2 reports on the held-out TEST split.
python -m ai.retrieval_eval tune --embedder ollama
python -m ai.retrieval_eval run --embedder ollama --llm none   --split test      # retrieval quality only (minutes)
python -m ai.retrieval_eval run --embedder ollama --llm ollama --split test      # + answer-level metrics with the real chat model (slower)
Write-Host "Reports are in eval_results\ (retrieval_*.md / .json). Read the 'Verdict (C vs B)' section first."
