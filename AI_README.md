# CareerDNA Local AI Assistant (Ollama + Qwen2.5)

All AI runs on YOUR computer through Ollama. No API key, no cloud LLM, no per-request cost.
Profile data is only sent to `http://localhost:11434`; other hosts are refused unless you set `CAREERDNA_ALLOW_REMOTE_OLLAMA=1`.

## Quick start (Windows PowerShell, from the folder containing main.py)
```powershell
.\scripts\check_hardware.ps1          # shows RAM and recommends qwen2.5:1.5b or qwen2.5:3b (downloads nothing)
winget install Ollama.Ollama          # install Ollama (or https://ollama.com/download), then reopen PowerShell
.\scripts\setup_ollama.ps1            # asks before downloading the model (3b is about 1.9 GB)
# manual equivalent:  ollama pull qwen2.5:3b     then check with:  ollama list
.\scripts\run_backend.ps1             # terminal 1: http://127.0.0.1:8000
.\scripts\run_frontend.ps1            # terminal 2: http://localhost:5173
```
Sign in, open the **AI Assistant** tab. The dot at the top shows whether Ollama is running and the model is installed.
To change model: `$env:CAREERDNA_LLM_MODEL = "qwen2.5:1.5b"` before starting the backend.

Settings (environment variables): `CAREERDNA_OLLAMA_URL`, `CAREERDNA_LLM_MODEL` (default qwen2.5:3b), `CAREERDNA_LLM_TIMEOUT` (180 s),
`CAREERDNA_LLM_TEMPERATURE` (0.2), `CAREERDNA_LLM_NUM_CTX` (4096), `CAREERDNA_LLM_NUM_PREDICT` (500), `CAREERDNA_LLM_MAX_REGEN` (1).

## How it works
1. `POST /ai/chat` -> `ai/router.py` picks an intent and the backend functions to call (deterministic, tested).
   Native model tool-calling is NOT used: 1.5B-3B models call tools unreliably.
2. `ai/tools.py` runs those functions after validating every argument. Tools are read-only, take no candidate id
   (the user comes from the login token), and the model never sees SQL, shell or code execution.
3. Numbers come from `ai/scoring.py`, the same code the dashboard endpoints now use (outputs verified identical).
4. The model receives only the computed FACTS and writes an explanation.
5. `ai/verifier.py` checks the answer with plain rules: every % / LPA figure must match a backend number, cited `[record:id]` must exist,
   skills/certifications/projects claimed must exist in your records, "no record" must not be phrased as inability,
   no guarantees, hypotheticals labelled. On failure the model is asked once to correct itself; otherwise offending sentences are removed
   or the backend results are shown instead. Wrong user numbers (e.g. "68% match") are corrected deterministically.
6. Evidence (`ai/evidence.py`): documented / self-reported only / contradictory / no record. CareerDNA has no assessment table, so assessments are reported unavailable, never invented.
7. What-If (`ai/scenario.py`) works on a copy of the profile and reuses the official scoring. Roadmap (`ai/roadmap.py`) is rule-based; the model only explains it.
8. Retrieval is local BM25 over your project/experience text. No embeddings, no pgvector (this project uses SQLite).

## Tests
```powershell
.\scripts\run_tests.ps1                                   # backend (mocked/fake Ollama) + frontend
$env:CAREERDNA_RUN_OLLAMA_TESTS='1'; python -m pytest tests/test_integration_ollama.py -s     # REAL model
python -m ai.evaluation --llm ollama --out eval_results   # REAL measurements: systems A/B/C on eval/cases.json
```
`eval_results/*_mock.*` was produced with a mock and is only a harness self-test. Real model results do not exist until you run the command above.
The `ai_eval_log` table (created automatically, additive) records model, refs, backend numbers, verification outcome, flags, latency, errors; it stores the question LENGTH only and a salted hash instead of the candidate id.

## Known limitations
- Verifier is rule-based: on 42 hand-labelled answers it caught 23/28 faulty ones (5 documented limits: implicit wording, skills outside the catalog, ranking claims). The benchmark was written alongside the rules, so treat it as optimistic.
- Official match counts which required skills are listed; it ignores proficiency/documentation. Documenting a skill changes the separate "documented %" metric, not the official score.
- Salary rules are CareerDNA's existing formula (no XGBoost is in this project) and have no project term.
- Roadmap hours and prerequisites are a curated table in `ai/knowledge.py`, labelled as estimates.
- Not tested here against a real Qwen model (sandbox had no access to Ollama's registry).

## Existing issues found (left unchanged)
- `GET /candidates/{id}/profile` has no authentication.
- `/skill-strength` `project_count` counts other candidates' projects (join missing a candidate filter).


---
# Hybrid RAG (optional) - BM25 + local embeddings

**Status: OFF by default.** `CAREERDNA_RETRIEVAL_MODE=bm25` and `CAREERDNA_RETRIEVAL_WIRING=legacy` reproduce the previous behaviour exactly.
No measurement yet shows hybrid is better; the evaluation below is how you find out on your machine.

## Settings (environment variables)
| Variable | Default | Meaning |
|---|---|---|
| `CAREERDNA_RETRIEVAL_MODE` | `bm25` | `bm25` or `hybrid`. Invalid values fall back to `bm25` and are listed in `/ai/status`. |
| `CAREERDNA_RETRIEVAL_WIRING` | `legacy` | `legacy` = retrieve only for the evidence intent, query = skill names. `improved` = query is your whole question, and skill_evidence, skill_gaps, match_explain, missing_info, overview and roadmap retrieve. |
| `CAREERDNA_EMBED_MODEL` | `nomic-embed-text` | or `all-minilm`. Vectors of different models are stored separately and never mixed. |
| `CAREERDNA_EMBED_TIMEOUT` | `20` s | bounds the extra latency when embeddings are slow. |
| `CAREERDNA_RRF_K`, `_W_BM25`, `_W_SEM` | `60`, `1`, `1` | fusion constants. |
| `CAREERDNA_SEM_MIN_SIM` | placeholder `0.55` | minimum cosine similarity for a semantic candidate. **This default is an uncalibrated guess**; run `tune` (writes `eval/retrieval_tuning.json`, per model). `/ai/status` shows `calibrated`. |

## How it works
`ai/rag.py` (BM25) is unchanged. `ai/retrieval.py` runs BM25 and, in hybrid mode, embeds the question (Ollama `/api/embed`) and ranks the user's own records by cosine similarity (plain Python, no new dependency, no vector database: a user has a few dozen records).
The two rankings are fused with Reciprocal Rank Fusion: `score = sum(weight / (60 + rank))` over the lists containing the record. Only ranks are fused because BM25 scores and cosines are not comparable.
Records need `similarity >= min_similarity` to enter the semantic list, which is what lets a question with no relevant record return nothing.
Each hit reports `sources` (`bm25`/`semantic`), both ranks and the similarity.

## Storage and isolation
One additive table, `ai_embedding(candidate_id, ref, model, text_hash, dim, vector)`, created automatically. `candidate_id = 0` is used for the shared job catalogue only.
Documents are always built from the signed-in user's own profile (the candidate comes from the login token; tools accept no candidate id). Cached vectors are keyed by (owner, ref, model) and validated by text hash,
so edited records are re-embedded, deleted records are pruned, and changing the model re-embeds everything. Owner-scoping is defence in depth: a cache hit also needs an identical text hash.
`python -c "from ai.db import connect; from ai.embeddings import purge_other_models as p; print(p(connect(), 'nomic-embed-text'))"` removes vectors of other models.

## Failures are visible, never silent
If embedding fails for any reason (Ollama down, model missing, timeout, malformed or wrong-size vectors, bug), the answer uses BM25 and `/ai/chat` returns
`retrieval: [{requested_mode: "hybrid", effective_mode: "bm25", fallback: true, fallback_reason: "EMBED_MODEL_MISSING", ...}]`; the UI shows "Hybrid unavailable - keyword search used (reason)", and the model is told semantic search was unavailable.
It is never labelled hybrid. Codes: `EMBED_UNREACHABLE, EMBED_TIMEOUT, EMBED_MODEL_MISSING, EMBED_UNSUPPORTED, EMBED_ERROR, EMBED_BAD_RESPONSE, EMBED_DIM_MISMATCH, EMBED_UNEXPECTED_ERROR`.

## Install the embedding model (asks before downloading)
```powershell
.\scripts\setup_embeddings.ps1                 # nomic-embed-text, or:  .\scripts\setup_embeddings.ps1 -Model all-minilm
# manual:  ollama pull nomic-embed-text
$env:CAREERDNA_RETRIEVAL_MODE   = "hybrid"       # opt in (default stays bm25)
$env:CAREERDNA_RETRIEVAL_WIRING = "improved"     # optional; evaluated separately in arm B
```

## A/B/C evaluation
```powershell
.\scripts\run_retrieval_eval.ps1      # or run the three commands inside by hand
python -m ai.retrieval_eval tune --embedder ollama                       # DEV split only
python -m ai.retrieval_eval run  --embedder ollama --llm none --split test
python -m ai.retrieval_eval run  --embedder ollama --llm ollama --split test   # adds answer-level metrics
```
Arms: **A** BM25 + current wiring, **B** BM25 + improved wiring, **C** hybrid + improved wiring. A vs B isolates the wiring; B vs C isolates the semantic retriever (`*_direct` rows bypass the router).
Same 41 gold queries (21 dev / 20 test, split fixed before any run) and the same 17 + 10 answer-level cases for every arm, on SYNTHETIC corpora (`ai/eval_fixture.py`, `ai/eval_fixture_rich.py`).
Metrics: Recall@1/3/5, MRR, correct-empty rate on no-answer queries, isolation leaks, fallbacks, latency (warm and including index build); answer level: correctness, evidence support, first-draft and residual unsupported claims, regeneration rate, end-to-end latency.
The report ends with a verdict that says "hybrid better" only if: real embedder; calibrated threshold; paired-bootstrap 95% CI of the recall@3 difference (C-B) above 0; MRR not lower; no-answer correct-empty not lower; zero leaks; zero fallbacks.

## Limitations of this evaluation (read before trusting any number)
- **Underpowered.** About 15 answerable held-out queries: a paired 95% CI is roughly +/-0.2 wide on recall@3, so only large differences can be established. Add queries to `eval/retrieval_gold.json` to tighten it.
- **Synthetic and self-authored.** Corpora, queries and labels were written by the developer of the system; paraphrases may be easier or harder than real users' wording. Per-user corpora are tiny (5 to 21 records).
- Experience records have no description column, so their searchable text is only role, company and domain. Job postings have no description text.
- `verifier.py` is unchanged: it does not check free-text details that are not catalogued skills, numbers or citations (e.g. "deployed on a private cluster"). `first_draft_*` metrics measure this exposure; a test documents the limitation.
- The embedding model sizes quoted (~270 MB / ~45 MB) are from memory.
- Nothing here was run against a real embedding model in development (no access to Ollama's registry): retrieval-quality results do not exist until you run the commands above.
