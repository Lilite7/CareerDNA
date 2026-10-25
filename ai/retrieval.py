"""Hybrid retrieval = existing BM25 (ai/rag.py, unchanged) + optional local semantic search, fused with Reciprocal Rank Fusion.

RRF: score(d) = sum over the rankings that contain d of  weight / (k + rank)      (rank starts at 1, default k = 60).
BM25 scores and cosine similarities are not comparable, so only RANKS are fused. A semantic candidate must also clear a
minimum cosine similarity, which is what lets a query with no relevant record return nothing.

Honesty rule: if anything in the semantic path fails, the function returns the BM25 result and says so in
`diagnostics` (effective_mode='bm25', fallback=True, fallback_reason=<code>). It never labels such a result 'hybrid'."""
import logging
import time
from dataclasses import replace

from . import embeddings as emb
from . import ollama_client, rag
from .config import RetrievalSettings, get_retrieval_settings
from .embeddings import EmbeddingError
from .ollama_client import OllamaError

log = logging.getLogger("careerdna.retrieval")


def _bm25_hit(h, rank):
    return {**h, "sources": ["bm25"], "bm25_rank": rank, "semantic_rank": None, "similarity": None, "bm25_score": h["score"]}


def _diag(requested, effective, st, **kw):
    d = {"requested_mode": requested, "effective_mode": effective, "fallback": False, "fallback_reason": None, "fallback_message": None,
         "embed_model": st.embed_model if requested == "hybrid" else None, "calibrated": st.calibrated if requested == "hybrid" else None,
         "min_similarity": st.min_similarity if requested == "hybrid" else None, "bm25_candidates": 0, "semantic_candidates": 0,
         "embedded_now": 0, "cached": 0, "pruned": 0, "empty": False, "warnings": list(st.warnings), "timings_ms": {}}
    d.update(kw)
    return d


def fuse(bm25_ranked: list[dict], semantic_ranked: list[tuple], k: int, st: RetrievalSettings) -> list[dict]:
    """bm25_ranked: hits best-first; semantic_ranked: [(similarity, doc)] best-first. Returns fused hits best-first."""
    table = {}
    for rank, h in enumerate(bm25_ranked, 1):
        table[h["ref"]] = {**h, "sources": ["bm25"], "bm25_rank": rank, "semantic_rank": None, "similarity": None, "bm25_score": h["score"],
                           "score": st.w_bm25 / (st.rrf_k + rank)}
    for rank, (sim, d) in enumerate(semantic_ranked, 1):
        inc = st.w_sem / (st.rrf_k + rank)
        if d["ref"] in table:
            e = table[d["ref"]]
            e["sources"].append("semantic"); e["semantic_rank"] = rank; e["similarity"] = round(sim, 4); e["score"] += inc
        else:
            table[d["ref"]] = {**{x: d[x] for x in ("ref", "type", "title", "text")}, "sources": ["semantic"], "bm25_rank": None,
                               "semantic_rank": rank, "similarity": round(sim, 4), "bm25_score": None, "score": inc}
    out = sorted(table.values(), key=lambda e: (-e["score"], min(r for r in (e["bm25_rank"], e["semantic_rank"]) if r), e["ref"]))
    for e in out:
        e["score"] = round(e["score"], 6)
    return out[:k]


def retrieve(conn, candidate_id: int, query: str, docs: list[dict], k: int = 4, types: set | None = None,
             settings: RetrievalSettings | None = None, embed_fn=None) -> dict:
    """`docs` MUST already be built from the authenticated candidate's own records (plus the shared job catalogue)."""
    st = settings or get_retrieval_settings()
    t0 = time.perf_counter()
    pool_docs = [d for d in docs if not types or d["type"] in types]
    q = (query or "").strip()
    t = time.perf_counter()
    bm = rag.retrieve(q, pool_docs, k=max(len(pool_docs), 1), types=None) if q else []
    t_bm = (time.perf_counter() - t) * 1000

    def done(hits, diag):
        diag["empty"] = not hits
        diag["timings_ms"]["bm25"] = round(t_bm, 2)
        diag["timings_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 2)
        return {"hits": hits, "diagnostics": diag}

    bm_hits = [_bm25_hit(h, i) for i, h in enumerate(bm, 1)][:k]
    if st.mode != "hybrid" or not q or not pool_docs:
        return done(bm_hits, _diag(st.mode, "bm25", st, bm25_candidates=len(bm)))
    embed_fn = embed_fn or (lambda texts: ollama_client.embed(texts, model=st.embed_model, timeout=st.embed_timeout))
    try:
        t = time.perf_counter()
        qv = embed_fn([q])[0]
        t_q = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        vecs, stats = emb.ensure_vectors(conn, candidate_id, pool_docs, st.embed_model, embed_fn, prune_refs={d["ref"] for d in docs})
        t_idx = (time.perf_counter() - t) * 1000
        bad = [r for r, v in vecs.items() if len(v) != len(qv)]
        if bad:   # e.g. the same model name now produces a different dimension: heal by dropping, fall back this once
            emb.drop_vectors(conn, candidate_id, bad, st.embed_model)
            raise EmbeddingError("EMBED_DIM_MISMATCH", "Stored vectors do not match the current embedding dimension; they were discarded and will be recomputed.")
        t = time.perf_counter()
        scored = sorted(((emb.cosine(qv, vecs[d["ref"]]), d) for d in pool_docs), key=lambda x: (-x[0], x[1]["ref"]))
        semantic = [(s, d) for s, d in scored if s >= st.min_similarity][:st.pool]
        t_sem = (time.perf_counter() - t) * 1000
        fused = fuse(bm[:st.pool], semantic, k, st)
        diag = _diag("hybrid", "hybrid", st, bm25_candidates=len(bm), semantic_candidates=len(semantic),
                     embedded_now=stats["embedded_now"], cached=stats["cached"], pruned=stats["pruned"])
        diag["timings_ms"].update({"embed_query": round(t_q, 2), "index": round(t_idx, 2), "semantic": round(t_sem, 2)})
        return done(fused, diag)
    except (EmbeddingError, OllamaError) as e:
        code, msg = e.code, e.message
    except Exception as e:  # noqa: BLE001 - chat must survive any retrieval bug; the failure is still reported
        code, msg = "EMBED_UNEXPECTED_ERROR", f"{type(e).__name__}: {e}"
    log.warning("hybrid retrieval unavailable (%s): %s - using BM25", code, msg)
    return done(bm_hits, _diag("hybrid", "bm25", st, fallback=True, fallback_reason=code, fallback_message=msg, bm25_candidates=len(bm)))
