"""REAL integration test against a locally running Ollama + the configured model.
Skipped automatically unless you opt in:   $env:CAREERDNA_RUN_OLLAMA_TESTS = "1"   (PowerShell)
Nothing here is mocked: it calls the real model and checks grounding/verification on real output."""
import os

import pytest

from ai import ollama_client

pytestmark = pytest.mark.ollama
RUN = os.getenv("CAREERDNA_RUN_OLLAMA_TESTS") == "1"


def _ready():
    try:
        return ollama_client.get_status()["ready"]
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not RUN, reason="set CAREERDNA_RUN_OLLAMA_TESTS=1 to run against a real local Ollama")
def test_real_model_end_to_end(conn):
    if not _ready():
        pytest.fail("CAREERDNA_RUN_OLLAMA_TESTS=1 but Ollama/model is not ready: " + str(ollama_client.get_status()["error"]))
    from ai.agent import CareerAgent
    out = CareerAgent(conn, 1).run("Why am I a 68% match for ML Engineer?")
    assert out["ok"], out.get("error")
    assert out["answer"] and out["verification"]["status"] in ("passed", "regenerated", "qualified", "fallback")
    assert "81.2" in out["answer"]                       # the official number must be in the final answer (model or deterministic correction)
    assert any(e["ref"] == "job:1" for e in out["evidence"])
    print("\nmodel:", out["model"], "latency_ms:", out["latency_ms"], "verification:", out["verification"]["status"])
    print(out["answer"])


@pytest.mark.skipif(not RUN, reason="set CAREERDNA_RUN_OLLAMA_TESTS=1 to run against a real local Ollama")
def test_real_model_whatif_is_labelled(conn):
    if not _ready():
        pytest.fail("Ollama/model not ready")
    from ai.agent import CareerAgent
    out = CareerAgent(conn, 1).run("What if I learn PyTorch and complete a machine learning project?")
    assert out["ok"] and out["hypothetical"] and "hypothetical" in out["answer"].lower()


@pytest.mark.skipif(not RUN, reason="set CAREERDNA_RUN_OLLAMA_TESTS=1 to run against a real local Ollama")
def test_real_embedding_model_hybrid_retrieval(conn, monkeypatch):
    """Needs the embedding model:  ollama pull nomic-embed-text   (nothing is mocked)."""
    from ai import rag, retrieval
    from ai.config import get_retrieval_settings
    from ai.tools import ToolContext
    from dataclasses import replace
    st = ollama_client.get_status()
    es = ollama_client.embed_model_status(st)
    if not es["ready"]:
        pytest.fail("embedding model not ready: " + str(es["error"]))
    ctx = ToolContext(conn, 1)
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    settings = replace(get_retrieval_settings(), mode="hybrid", min_similarity=0.0)      # threshold is calibrated separately by `tune`
    res = retrieval.retrieve(conn, ctx.candidate_id, "Have I built something to predict salaries?", docs, k=4, types={"project", "experience", "certification", "profile"}, settings=settings)
    d = res["diagnostics"]
    assert d["effective_mode"] == "hybrid" and d["fallback"] is False, d
    assert res["hits"] and all(h["ref"] in {x["ref"] for x in docs} for h in res["hits"])
    print("\nhits:", [(h["ref"], h["sources"], h["similarity"]) for h in res["hits"]], "timings:", d["timings_ms"])
