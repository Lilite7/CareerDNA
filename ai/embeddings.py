"""Embedding cache for Hybrid RAG.

* Vectors live in the additive `ai_embedding` table, keyed by (owner, ref, model) with a text hash.
* Owner = the authenticated candidate, or 0 for shared JOB-catalogue documents only. A private record can never be
  stored under, or read from, the shared owner, and rows belonging to other candidates are never read.
* A changed text hash, a corrupt blob, or a different model means the vector is stale and is recomputed.
* No third-party dependency: cosine similarity is plain Python (a user has at most a few dozen documents)."""
import hashlib
import math
import struct

from .db import EMBEDDING_DDL

SHARED_OWNER = 0


class EmbeddingError(Exception):
    def __init__(self, code: str, message: str, instructions: str = ""):
        super().__init__(message)
        self.code, self.message, self.instructions = code, message, instructions


def text_hash(doc: dict) -> str:
    return hashlib.sha256(f"{doc['title']}\n{doc['text']}".encode("utf-8")).hexdigest()[:32]


def pack(vec) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def unpack(blob: bytes, dim: int):
    return list(struct.unpack(f"<{dim}f", blob))


def cosine(a, b) -> float:
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    return dot / math.sqrt(na * nb) if na and nb else 0.0


def owner_of(doc: dict, candidate_id: int) -> int:
    return SHARED_OWNER if doc["type"] == "job" else candidate_id


def ensure_vectors(conn, candidate_id: int, docs: list[dict], model: str, embed_fn, prune_refs: set | None = None, batch: int = 32):
    """Returns ({ref: vector}, stats). Embeds only documents whose cached vector is missing or stale.
    Nothing is written unless every needed embedding succeeded (all-or-nothing)."""
    conn.executescript(EMBEDDING_DDL)   # idempotent: the additive table is created on first use even if startup has not run yet
    rows = conn.execute("SELECT candidate_id, ref, text_hash, dim, vector FROM ai_embedding WHERE model = ? AND candidate_id IN (?, ?)",
                        (model, candidate_id, SHARED_OWNER)).fetchall()
    cache = {(r["candidate_id"], r["ref"]): (r["text_hash"], r["dim"], r["vector"]) for r in rows}
    vectors, needed = {}, []
    for d in docs:
        key, h = (owner_of(d, candidate_id), d["ref"]), text_hash(d)
        row = cache.get(key)      # only the doc's OWN owner scope is consulted
        if row and row[0] == h and row[1] > 0 and len(row[2]) == row[1] * 4:
            vectors[d["ref"]] = unpack(row[2], row[1])
        else:
            needed.append((d, h))
    stats = {"cached": len(vectors), "embedded_now": 0, "pruned": 0}
    fresh = []
    for i in range(0, len(needed), batch):
        chunk = needed[i:i + batch]
        vecs = embed_fn([f"{d['title']}. {d['text']}" for d, _ in chunk])
        if not isinstance(vecs, list) or len(vecs) != len(chunk):
            raise EmbeddingError("EMBED_BAD_RESPONSE", "The embedding service returned the wrong number of vectors.")
        fresh += [(d, h, v) for (d, h), v in zip(chunk, vecs)]
    for d, h, v in fresh:
        conn.execute("INSERT OR REPLACE INTO ai_embedding (candidate_id, ref, model, text_hash, dim, vector) VALUES (?,?,?,?,?,?)",
                     (owner_of(d, candidate_id), d["ref"], model, h, len(v), pack(v)))
        vectors[d["ref"]] = [float(x) for x in v]
    stats["embedded_now"] = len(fresh)
    if prune_refs is not None:   # remove this candidate's vectors for records that no longer exist (never shared rows)
        stale = [r["ref"] for r in conn.execute("SELECT ref FROM ai_embedding WHERE candidate_id = ? AND model = ?", (candidate_id, model))
                 if r["ref"] not in prune_refs]
        for ref in stale:
            conn.execute("DELETE FROM ai_embedding WHERE candidate_id = ? AND ref = ? AND model = ?", (candidate_id, ref, model))
        stats["pruned"] = len(stale)
    conn.commit()
    return vectors, stats


def drop_vectors(conn, candidate_id: int, refs, model: str) -> None:
    for ref in refs:
        conn.execute("DELETE FROM ai_embedding WHERE candidate_id IN (?, ?) AND ref = ? AND model = ?", (candidate_id, SHARED_OWNER, ref, model))
    conn.commit()


def purge_other_models(conn, keep_model: str) -> int:
    """Housekeeping after changing CAREERDNA_EMBED_MODEL: removes vectors of every other model."""
    n = conn.execute("DELETE FROM ai_embedding WHERE model <> ?", (keep_model,)).rowcount
    conn.commit()
    return n
