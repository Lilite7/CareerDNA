import json
import sqlite3

import pytest

from ai import embeddings as emb
from ai import rag, retrieval
from ai.config import get_retrieval_settings
from ai.eval_fixture import SECRET_PROJECT
from ai.ollama_client import OllamaError
from ai.tools import ToolContext, call_tool
from tests.helpers import Recorder, concept_vec

TYPES = {"project", "experience", "certification", "profile"}


def hybrid_settings(**kw):
    from dataclasses import replace
    return replace(get_retrieval_settings(), mode="hybrid", min_similarity=0.3, calibrated=True, **kw)


def run(conn, uid, query, embed_fn, st=None, types=TYPES, k=4):
    ctx = ToolContext(conn, uid)
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    return retrieval.retrieve(conn, ctx.candidate_id, query, docs, k=k, types=types, settings=st or hybrid_settings(), embed_fn=embed_fn)


def refs(res):
    return [h["ref"] for h in res["hits"]]


# ------------------------------------------------------------------ settings / defaults
def test_defaults_preserve_previous_behaviour():
    s = get_retrieval_settings()
    assert (s.mode, s.wiring, s.embed_model) == ("bm25", "legacy", "nomic-embed-text") and s.calibrated is False and not s.warnings


def test_invalid_settings_never_crash_and_are_reported(monkeypatch):
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_MODE", "turbo")
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_WIRING", "x")
    monkeypatch.setenv("CAREERDNA_RRF_K", "sixty")
    s = get_retrieval_settings()
    assert s.mode == "bm25" and s.wiring == "legacy" and s.rrf_k == 60 and len(s.warnings) == 3


def test_tuning_file_is_per_model_and_env_overrides(monkeypatch, tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"models": {"all-minilm": {"min_similarity": 0.42, "w_sem": 2.0}}}))
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_TUNING", str(f))
    monkeypatch.setenv("CAREERDNA_EMBED_MODEL", "all-minilm:latest")
    s = get_retrieval_settings()
    assert s.embed_model == "all-minilm" and s.min_similarity == 0.42 and s.w_sem == 2.0 and s.calibrated
    monkeypatch.setenv("CAREERDNA_SEM_MIN_SIM", "0.7")
    assert get_retrieval_settings().min_similarity == 0.7
    monkeypatch.delenv("CAREERDNA_SEM_MIN_SIM")
    monkeypatch.setenv("CAREERDNA_EMBED_MODEL", "nomic-embed-text")
    assert get_retrieval_settings().calibrated is False        # tuning for another model does not apply


# ------------------------------------------------------------------ backward compatibility (bm25 default)
def test_default_mode_never_touches_embeddings(ctx):
    rec = Recorder()
    ctx.embed_fn = rec
    r = call_tool(ctx, "retrieve_context", {"query": "Python"})
    assert r["ok"] and rec.calls == []
    assert ctx.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'ai_embedding'").fetchone()[0] == 0   # default mode does not even create the table
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    assert [h["ref"] for h in r["data"]["hits"]] == [h["ref"] for h in rag.retrieve("Python", docs, k=4, types=TYPES)]
    d = r["data"]["retrieval"]
    assert d["requested_mode"] == "bm25" and d["effective_mode"] == "bm25" and d["fallback"] is False


def test_bm25_hits_keep_original_keys_and_lines(ctx):
    r = call_tool(ctx, "retrieve_context", {"query": "threat classification security logs"})
    assert r["lines"][0].startswith("[project:1] AI-SOC Platform: ") and r["refs"][0]["ref"] == "project:1"
    assert {"ref", "type", "title", "score"} <= set(r["data"]["hits"][0])


# ------------------------------------------------------------------ relevance
def test_hybrid_finds_paraphrases_that_bm25_misses(conn):
    rec = Recorder()
    q = "applications that forecast pay for job seekers"
    ctx = ToolContext(conn, 1)
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    assert rag.retrieve(q, docs, k=4, types=TYPES) == []                      # BM25 alone: nothing
    res = run(conn, 1, q, rec)
    assert "project:2" in refs(res) and res["diagnostics"]["effective_mode"] == "hybrid" and res["diagnostics"]["fallback"] is False
    h = next(x for x in res["hits"] if x["ref"] == "project:2")
    assert h["sources"] == ["semantic"] and h["semantic_rank"] == 1 and h["bm25_rank"] is None and h["similarity"] > 0.3
    assert "project:1" in refs(run(conn, 1, "network intrusion detection", rec))


def test_lexical_matches_still_win_and_report_both_sources(conn):
    res = run(conn, 1, "threat classification security logs", Recorder())
    assert refs(res)[0] == "project:1"
    assert set(res["hits"][0]["sources"]) == {"bm25", "semantic"} and res["hits"][0]["bm25_rank"] == 1


def test_rrf_arithmetic_and_weights():
    st = hybrid_settings()
    d = lambda r: {"ref": r, "type": "project", "title": r, "text": r}
    bm = [{**d("a"), "score": 9.0}, {**d("b"), "score": 5.0}]
    sem = [(0.9, d("b")), (0.8, d("c")), (0.7, d("a"))]
    out = retrieval.fuse(bm, sem, 10, st)
    k = st.rrf_k
    assert [h["ref"] for h in out] == ["b", "a", "c"]
    assert out[0]["score"] == pytest.approx(1 / (k + 2) + 1 / (k + 1), abs=1e-6)       # b: bm25 rank 2 + semantic rank 1
    assert out[1]["score"] == pytest.approx(1 / (k + 1) + 1 / (k + 3), abs=1e-6)       # a: bm25 rank 1 + semantic rank 3
    assert out[2]["sources"] == ["semantic"]
    from dataclasses import replace
    only_bm25 = retrieval.fuse(bm, sem, 10, replace(st, w_sem=0.0))
    assert [h["ref"] for h in only_bm25][:2] == ["a", "b"]                              # w_sem=0 reproduces the BM25 order


# ------------------------------------------------------------------ empty / no-answer
def test_no_answer_query_returns_nothing_in_hybrid(conn):
    res = run(conn, 1, "quantum gastronomy", Recorder())
    assert res["hits"] == [] and res["diagnostics"]["empty"] is True and res["diagnostics"]["effective_mode"] == "hybrid"
    res = run(conn, 1, "Have I played professional football?", Recorder())
    assert res["hits"] == []


@pytest.mark.parametrize("q", ["", "   ", None])
def test_blank_query_is_empty_and_never_embeds(conn, q):
    rec = Recorder()
    res = run(conn, 1, q, rec)
    assert res["hits"] == [] and rec.calls == [] and res["diagnostics"]["fallback"] is False


def test_user_with_no_free_text_documents(conn):
    conn.execute("DELETE FROM project WHERE candidate_id = 11")
    conn.commit()
    res = run(conn, 2, "payroll", Recorder())
    assert res["hits"] == [] and res["diagnostics"]["empty"]


def test_existing_nonsense_query_test_also_holds_in_hybrid_tool_path(ctx, hybrid_env):
    ctx.embed_fn = Recorder()
    assert call_tool(ctx, "retrieve_context", {"query": "quantum gastronomy"})["data"]["hits"] == []


# ------------------------------------------------------------------ failures -> visible BM25 fallback
FAILS = [("EMBED_UNREACHABLE", OllamaError("EMBED_UNREACHABLE", "Cannot reach Ollama")),
         ("EMBED_MODEL_MISSING", OllamaError("EMBED_MODEL_MISSING", "not installed", "ollama pull nomic-embed-text")),
         ("EMBED_TIMEOUT", OllamaError("EMBED_TIMEOUT", "too slow")),
         ("EMBED_BAD_RESPONSE", OllamaError("EMBED_BAD_RESPONSE", "malformed")),
         ("EMBED_UNEXPECTED_ERROR", RuntimeError("boom"))]


@pytest.mark.parametrize("code,exc", FAILS)
def test_embedding_failure_falls_back_visibly(conn, code, exc):
    def broken(texts):
        raise exc
    res = run(conn, 1, "threat classification security logs", broken)
    d = res["diagnostics"]
    assert d["requested_mode"] == "hybrid" and d["effective_mode"] == "bm25" and d["fallback"] is True
    assert d["fallback_reason"] == code and d["fallback_message"]
    assert refs(res) == ["project:1"] and all(h["sources"] == ["bm25"] for h in res["hits"])      # honest: nothing is labelled semantic


def test_failure_while_embedding_documents_writes_nothing(conn):
    def flaky(texts):
        if len(texts) == 1:
            return [concept_vec(texts[0])]
        raise OllamaError("EMBED_TIMEOUT", "slow")
    res = run(conn, 1, "security logs", flaky)
    assert res["diagnostics"]["fallback_reason"] == "EMBED_TIMEOUT"
    assert conn.execute("SELECT COUNT(*) FROM ai_embedding").fetchone()[0] == 0


def test_wrong_number_of_vectors_is_rejected(conn):
    res = run(conn, 1, "security", lambda texts: [concept_vec("security")] if len(texts) > 1 else [concept_vec(texts[0])])
    assert res["diagnostics"]["fallback_reason"] == "EMBED_BAD_RESPONSE"


def test_dimension_mismatch_heals_on_next_call(conn):
    run(conn, 1, "security", Recorder(dim=16))                                   # stores 16-d vectors
    res = run(conn, 1, "security", Recorder(dim=24))                             # same model name, new dimension
    assert res["diagnostics"]["fallback_reason"] == "EMBED_DIM_MISMATCH" and res["diagnostics"]["effective_mode"] == "bm25"
    res = run(conn, 1, "security", Recorder(dim=24))
    assert res["diagnostics"]["effective_mode"] == "hybrid" and res["diagnostics"]["fallback"] is False


# ------------------------------------------------------------------ stale embeddings
def test_cache_hit_embeds_only_the_query(conn):
    first, second = Recorder(), Recorder()
    run(conn, 1, "security logs", first)
    n_docs = len(first.calls[1])
    assert n_docs == 5 and len(first.calls[0]) == 1                               # query, then the 5 free-text docs (2 projects, experience, certification, goals)
    res = run(conn, 1, "security logs", second)
    assert second.calls == [["security logs"]] and res["diagnostics"]["cached"] == 5 and res["diagnostics"]["embedded_now"] == 0


def test_changed_text_is_reembedded_only_for_that_record(conn):
    run(conn, 1, "security", Recorder())
    conn.execute("UPDATE project SET description = 'Now a completely different description about gardening.' WHERE project_id = 2")
    conn.commit()
    rec = Recorder()
    res = run(conn, 1, "security", rec)
    assert res["diagnostics"]["embedded_now"] == 1 and any("gardening" in t for t in rec.texts) and len(rec.texts) == 2
    stored = conn.execute("SELECT text_hash FROM ai_embedding WHERE candidate_id = 10 AND ref = 'project:2'").fetchone()[0]
    assert stored == emb.text_hash(next(d for d in rag.build_documents(ToolContext(conn, 1).profile, [], ToolContext(conn, 1).catalog) if d["ref"] == "project:2"))


def test_deleted_record_vector_is_pruned(conn):
    run(conn, 1, "security", Recorder())
    conn.execute("DELETE FROM project_skill WHERE project_id = 1")
    conn.execute("DELETE FROM project WHERE project_id = 1")
    conn.commit()
    res = run(conn, 1, "security", Recorder())
    assert res["diagnostics"]["pruned"] == 1
    assert "project:1" not in {r[0] for r in conn.execute("SELECT ref FROM ai_embedding WHERE candidate_id = 10")}


def test_corrupt_blob_is_recomputed(conn):
    run(conn, 1, "security", Recorder())
    conn.execute("UPDATE ai_embedding SET vector = x'00' WHERE ref = 'project:1'")
    conn.commit()
    res = run(conn, 1, "security", Recorder())
    assert res["diagnostics"]["embedded_now"] == 1 and res["diagnostics"]["fallback"] is False


def test_changing_the_embedding_model_reembeds_everything_and_keeps_models_separate(conn):
    run(conn, 1, "security", Recorder(dim=16), st=hybrid_settings())
    from dataclasses import replace
    rec = Recorder(dim=24)
    res = run(conn, 1, "security", rec, st=replace(hybrid_settings(), embed_model="all-minilm"))
    assert res["diagnostics"]["embedded_now"] == 5 and res["diagnostics"]["embed_model"] == "all-minilm" and not res["diagnostics"]["fallback"]
    models = {r[0]: r[1] for r in conn.execute("SELECT model, COUNT(*) FROM ai_embedding GROUP BY model")}
    assert models == {"nomic-embed-text": 5, "all-minilm": 5}
    assert {r[0] for r in conn.execute("SELECT DISTINCT dim FROM ai_embedding WHERE model = 'all-minilm'")} == {24}
    assert emb.purge_other_models(conn, "all-minilm") == 5
    assert {r[0] for r in conn.execute("SELECT DISTINCT model FROM ai_embedding")} == {"all-minilm"}


# ------------------------------------------------------------------ candidate isolation
def test_embedding_inputs_and_rows_never_contain_another_candidates_data(conn):
    rec = Recorder()
    run(conn, 1, "confidential payroll processing", rec)
    doc_texts = [t for call in rec.calls[1:] for t in call]          # calls[0] is the asker's own query
    assert doc_texts and not any("payroll" in t.lower() or SECRET_PROJECT.lower() in t.lower() for t in doc_texts)
    owners = {(r[0], r[1]) for r in conn.execute("SELECT candidate_id, ref FROM ai_embedding")}
    assert owners and all(c == 10 for c, _ in owners) and "project:3" not in {r for _, r in owners}
    run(conn, 2, "confidential payroll processing", Recorder())
    assert {r[0] for r in conn.execute("SELECT ref FROM ai_embedding WHERE candidate_id = 11")} == {"project:3"}


def test_adversarial_embedder_cannot_pull_in_other_candidates_records(conn):
    same = lambda texts: [[1.0, 0.5, 0.25] for _ in texts]                        # every text identical -> cosine 1 everywhere
    from dataclasses import replace
    for q in ("confidential payroll processing", "anything at all"):
        res = run(conn, 1, q, same, st=replace(hybrid_settings(), min_similarity=0.0))
        assert res["hits"] and "project:3" not in refs(res) and "payroll" not in json.dumps(res).lower()
        assert set(refs(res)) <= {"project:1", "project:2", "experience:1", "certification:1", "profile:goals"}


def test_poisoned_cache_rows_are_ignored(conn):
    ctx = ToolContext(conn, 1)
    from ai.db import EMBEDDING_DDL
    conn.executescript(EMBEDDING_DDL)
    qvec = concept_vec("payroll spending money")
    for owner in (11, 10, 0):                         # Bob's row, a forged row under Ada, a forged SHARED row for a private ref
        conn.execute("INSERT OR REPLACE INTO ai_embedding VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                     (owner, "project:3", "nomic-embed-text", "x", len(qvec), emb.pack(qvec)))
    conn.commit()
    res = run(conn, 1, "payroll spending money", Recorder())
    assert "project:3" not in refs(res) and "payroll" not in json.dumps(res).lower()
    # Bob's legitimate lookup is unaffected by Ada's forged rows
    assert "project:3" in refs(run(conn, 2, "payroll", Recorder()))


def test_only_job_documents_use_the_shared_owner(conn):
    ctx = ToolContext(conn, 1)
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    retrieval.retrieve(conn, 10, "ml engineer", docs, k=4, types=None, settings=hybrid_settings(), embed_fn=Recorder())
    shared = {r[0] for r in conn.execute("SELECT ref FROM ai_embedding WHERE candidate_id = 0")}
    assert shared == {"job:1", "job:2", "job:3"}
    assert all(r[0] == 10 for r in conn.execute("SELECT candidate_id FROM ai_embedding WHERE candidate_id <> 0"))


def test_tool_arguments_cannot_select_another_candidate(ctx, hybrid_env):
    ctx.embed_fn = Recorder()
    for args in ({"query": "payroll", "candidate_id": 11}, {"query": "payroll", "user_id": 2}):
        r = call_tool(ctx, "retrieve_context", args)
        assert r["ok"] is False and "Unexpected argument" in r["error"]
    r = call_tool(ctx, "retrieve_context", {"query": "confidential payroll processing"})
    assert r["data"]["hits"] == [] or all(h["ref"] != "project:3" for h in r["data"]["hits"])


def test_shared_job_vectors_are_cache_hits_on_the_second_call(conn):
    ctx = ToolContext(conn, 1)
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    call = lambda rec: retrieval.retrieve(conn, 10, "ml engineer", docs, k=4, types=None, settings=hybrid_settings(), embed_fn=rec)
    call(Recorder())
    rec = Recorder()
    res = call(rec)
    assert rec.calls == [["ml engineer"]] and res["diagnostics"]["cached"] == 8 and res["diagnostics"]["embedded_now"] == 0


def test_same_ref_string_for_different_candidates_never_shares_a_vector(conn):
    """'profile:goals' is the same ref for every candidate; each must get (and use) its own vector."""
    conn.execute("INSERT INTO profile_version (candidate_id, version_number, profile_snapshot) VALUES (11, 1, ?)",
                 (json.dumps({"headline": "Payroll specialist", "goals": "I want to build confidential payroll and finance systems."}),))
    conn.commit()
    ada_rec, bob_rec = Recorder(), Recorder()
    ada = run(conn, 1, "career goals machine learning security", ada_rec)
    bob = run(conn, 2, "career goals payroll finance", bob_rec)
    rows = {r[0]: r[1] for r in conn.execute("SELECT candidate_id, text_hash FROM ai_embedding WHERE ref = 'profile:goals'")}
    assert set(rows) == {10, 11} and rows[10] != rows[11]
    assert any("payroll" in t.lower() for call in bob_rec.calls[1:] for t in call)
    assert not any("payroll" in t.lower() for call in ada_rec.calls[1:] for t in call)
    ada_goal = next((h for h in ada["hits"] if h["ref"] == "profile:goals"), None)
    bob_goal = next((h for h in bob["hits"] if h["ref"] == "profile:goals"), None)
    assert ada_goal and "payroll" not in ada_goal["text"].lower() and bob_goal and "payroll" in bob_goal["text"].lower()
