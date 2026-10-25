import json
import os

import pytest

from ai import router
from ai.agent import CareerAgent
from ai.eval_fixture import SECRET_PROJECT
from ai.tools import ToolContext, call_tool
from tests.helpers import Recorder

ANSWER = "Your AI Hiring Assistant project [project:2] covers salary prediction and candidate shortlisting."
Q_PARAPHRASE = "Have I built something to predict salaries?"


def chat(client, h, msg):
    r = client.post("/ai/chat", json={"message": msg}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def embed_requests(fake):
    return [x[2] for x in fake.requests if x[1] == "/api/embed"]


@pytest.fixture
def fake_chat(fake_ollama):
    fake_ollama.chat_handler = lambda p: (200, {"model": p["model"], "message": {"role": "assistant", "content": ANSWER}})
    return fake_ollama


@pytest.fixture
def improved_hybrid(monkeypatch, hybrid_env):
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_WIRING", "improved")


# ------------------------------------------------------------------ default = unchanged
def test_default_mode_makes_no_embedding_requests(client, ada_h, fake_chat):
    out = chat(client, ada_h, Q_PARAPHRASE)
    assert embed_requests(fake_chat) == [] and out["retrieval"] == []                 # legacy wiring: overview intent does not retrieve
    out = chat(client, ada_h, "What evidence supports my Python proficiency?")
    assert embed_requests(fake_chat) == []
    d = out["retrieval"][0]
    assert d["requested_mode"] == "bm25" and d["effective_mode"] == "bm25" and d["fallback"] is False


# ------------------------------------------------------------------ hybrid end to end
def test_hybrid_chat_retrieves_paraphrase_and_exposes_diagnostics(client, ada_h, fake_chat, improved_hybrid):
    out = chat(client, ada_h, Q_PARAPHRASE)
    d = out["retrieval"][0]
    assert d["requested_mode"] == "hybrid" and d["effective_mode"] == "hybrid" and d["fallback"] is False and d["embed_model"] == "nomic-embed-text"
    assert "project:2" in {e["ref"] for e in out["evidence"]}                           # evidence reference exposed to the UI
    sent = [x[2] for x in fake_chat.requests if x[1] == "/api/chat"][0]["messages"][1]["content"]
    assert "[project:2] AI Hiring Assistant" in sent                                     # retrieved record reached the model, tagged with its ref
    assert out["verification"]["status"] == "passed" and out["cited_refs"] == ["project:2"]
    assert set(d["timings_ms"]) >= {"bm25", "embed_query", "index", "semantic", "total"}


def test_hybrid_chat_only_embeds_the_signed_in_users_records(client, ada_h, bob_h, fake_chat, improved_hybrid):
    ada = chat(client, ada_h, "Which of my projects is about confidential payroll processing?")
    texts = " ".join(t for req in embed_requests(fake_chat) for t in req["input"][1:])      # [0] is the asker's own query
    assert "payroll" not in texts.lower() and SECRET_PROJECT.lower() not in json.dumps(ada).lower()
    n_before = len(embed_requests(fake_chat))
    bob = chat(client, bob_h, "Which of my projects is about confidential payroll processing?")
    assert "project:3" in {e["ref"] for e in bob["evidence"]}
    bob_texts = " ".join(t for req in embed_requests(fake_chat)[n_before:] for t in req["input"][1:])
    assert "ai-soc" not in bob_texts.lower() and "hiring assistant" not in bob_texts.lower()      # and never Ada's


def test_embedding_model_missing_does_not_break_chat_and_is_reported(client, ada_h, fake_chat, improved_hybrid):
    fake_chat.embed_handler = lambda p: (404, {"error": "model \"nomic-embed-text\" not found, try pulling it first"})
    out = chat(client, ada_h, Q_PARAPHRASE)
    d = out["retrieval"][0]
    assert out["ok"] is True and out["answer"]                                           # chat continues
    assert d["requested_mode"] == "hybrid" and d["effective_mode"] == "bm25" and d["fallback"] is True and d["fallback_reason"] == "EMBED_MODEL_MISSING"
    assert any("Semantic retrieval was unavailable" in a for f in out["facts"] for a in f["assumptions"])    # the model is told too


@pytest.mark.parametrize("handler,code", [
    (lambda p: (200, {"embeddings": [[0.1, 0.2]]}), "EMBED_BAD_RESPONSE"),                       # wrong number of vectors
    (lambda p: (200, {"embeddings": [[0.0, 0.0] for _ in p["input"]]}), "EMBED_BAD_RESPONSE"),   # zero vectors
    (lambda p: (200, {"embeddings": [["x"] for _ in p["input"]]}), "EMBED_BAD_RESPONSE"),
    (lambda p: (500, {"error": "out of memory"}), "EMBED_ERROR"),
    (lambda p: (404, {"error": "page not found"}), "EMBED_UNSUPPORTED"),
])
def test_malformed_or_failing_embedding_responses_fall_back_visibly(client, ada_h, fake_chat, improved_hybrid, handler, code):
    fake_chat.embed_handler = handler
    out = chat(client, ada_h, Q_PARAPHRASE)
    d = out["retrieval"][0]
    assert out["ok"] and d["effective_mode"] == "bm25" and d["fallback"] and d["fallback_reason"] == code


def test_embedding_timeout_is_bounded_and_reported(client, ada_h, fake_chat, improved_hybrid, monkeypatch):
    monkeypatch.setenv("CAREERDNA_EMBED_TIMEOUT", "1")
    import time
    fake_chat.embed_handler = lambda p: (time.sleep(2.5), (200, {"embeddings": []}))[1]
    out = chat(client, ada_h, Q_PARAPHRASE)
    assert out["ok"] and out["retrieval"][0]["fallback_reason"] == "EMBED_TIMEOUT"


def test_ollama_fully_down_still_returns_facts_and_reports_both_failures(client, ada_h, no_ollama, improved_hybrid):
    out = chat(client, ada_h, Q_PARAPHRASE)
    assert out["ok"] is False and out["error"]["code"] == "OLLAMA_UNREACHABLE" and out["fallback_summary"]
    assert out["retrieval"][0]["fallback"] is True and out["retrieval"][0]["fallback_reason"] == "EMBED_UNREACHABLE"


def test_existing_endpoints_unaffected_by_hybrid_failures(client, ada_h, no_ollama, improved_hybrid):
    for ep in ("/job-match", "/salary", "/career-gap", "/profile"):
        assert client.get(ep, headers=ada_h).status_code == 200


# ------------------------------------------------------------------ status endpoint
def test_status_reports_retrieval_and_embedding_readiness(client, ada_h, fake_ollama, monkeypatch):
    s = client.get("/ai/status", headers=ada_h).json()
    assert s["retrieval"]["mode"] == "bm25" and s["retrieval"]["calibrated"] is False and s["embedding"]["ready"] is False
    assert "ollama pull nomic-embed-text" in s["embedding"]["error"]["instructions"] and s["ready"] is True       # chat model unaffected
    fake_ollama.models.append({"name": "nomic-embed-text:latest"})
    assert client.get("/ai/status", headers=ada_h).json()["embedding"]["ready"] is True
    monkeypatch.setenv("CAREERDNA_EMBED_MODEL", "all-minilm")
    assert client.get("/ai/status", headers=ada_h).json()["embedding"]["model"] == "all-minilm"


def test_status_when_ollama_down_marks_embeddings_unavailable(client, ada_h, no_ollama):
    s = client.get("/ai/status", headers=ada_h).json()
    assert s["embedding"]["ready"] is False and s["embedding"]["error"]["code"] == "EMBED_UNREACHABLE"


# ------------------------------------------------------------------ evidence references & unsupported claims
def agent(conn, *answers):
    from tests.conftest import ScriptedLLM
    return CareerAgent(conn, 1, llm_chat=ScriptedLLM(*answers), embed_fn=Recorder())


def test_citing_another_candidates_record_is_flagged_and_removed(conn, improved_hybrid):
    out = agent(conn, "Your payroll work is described in [project:3]. Your AI Hiring Assistant [project:2] predicts salaries.").run(Q_PARAPHRASE)
    v = out["verification"]
    assert "invalid_citation" in v["first_draft_issue_codes"] and "[project:3]" not in out["answer"]
    assert "payroll" not in out["answer"].lower()


def test_retrieved_record_citations_are_accepted(conn, improved_hybrid):
    out = agent(conn, ANSWER).run(Q_PARAPHRASE)
    assert out["verification"]["status"] == "passed" and out["verification"]["first_draft_issue_codes"] == [] and out["cited_refs"] == ["project:2"]


def test_skill_claim_not_in_records_is_still_caught_with_retrieved_text(conn, improved_hybrid):
    out = agent(conn, "You used PyTorch in your AI Hiring Assistant [project:2].").run(Q_PARAPHRASE)
    assert "claimed_skill_not_in_profile" in out["verification"]["first_draft_issue_codes"]
    assert "PyTorch" not in out["answer"] or out["verification"]["status"] == "fallback"


def test_known_limitation_free_text_detail_not_verified(conn, improved_hybrid):
    """DOCUMENTS current behaviour (verifier.py is intentionally unchanged in this phase): a made-up detail that is not a
    catalogued skill, number or citation is NOT detected. The evaluation reports first-draft unsupported claims so this
    exposure is measured rather than hidden."""
    out = agent(conn, "Your AI-SOC Platform [project:1] was deployed on a private cluster serving thousands of analysts.").run(Q_PARAPHRASE)
    assert out["verification"]["first_draft_issue_codes"] == []


# ------------------------------------------------------------------ router wiring
LEGACY_EXPECT = {
    "What evidence supports my Python proficiency?": ["get_skill_evidence", "retrieve_context"],
    "How well do I match ML Engineer?": ["calculate_job_match", "get_skill_gaps"],
    "Which skills are holding me back?": ["get_skill_gaps", "calculate_job_match"],
    "hello there": ["get_career_profile", "calculate_job_match"],
    "What salary can I expect?": ["predict_salary"],
}


def test_legacy_wiring_reproduces_previous_tool_plans(ctx):
    for q, names in LEGACY_EXPECT.items():
        p = router.plan(q, ctx.jobs, ctx.catalog)
        assert [c["name"] for c in p["calls"]] == names, q
    p = router.plan("What evidence supports my Python proficiency?", ctx.jobs, ctx.catalog)
    assert p["calls"][-1]["args"] == {"query": "Python"} and p["retrieval_query"] == "Python"
    assert router.plan("hello there", ctx.jobs, ctx.catalog)["retrieval_query"] is None


def test_improved_wiring_uses_full_question_and_limited_intents(ctx):
    q = "What evidence supports my Python proficiency?"
    p = router.plan(q, ctx.jobs, ctx.catalog, wiring="improved")
    assert p["calls"][-1] == {"name": "retrieve_context", "args": {"query": q}} and sum(c["name"] == "retrieve_context" for c in p["calls"]) == 1
    for q in ("Which skills are holding me back?", "How well do I match ML Engineer?", "hello there", "What should I learn next?"):
        assert router.plan(q, ctx.jobs, ctx.catalog, wiring="improved")["calls"][-1]["name"] == "retrieve_context", q
    for q in ("What if I learn PyTorch?", "What salary can I expect?", "Compare ML Engineer and Cybersecurity Analyst"):
        p = router.plan(q, ctx.jobs, ctx.catalog, wiring="improved")
        assert all(c["name"] != "retrieve_context" for c in p["calls"]) and p["retrieval_query"] is None, q


def test_improved_query_is_clipped_to_the_tool_limit(ctx):
    long_q = "Which skills are holding me back? " + "very " * 100
    p = router.plan(long_q, ctx.jobs, ctx.catalog, wiring="improved")
    q = p["calls"][-1]["args"]["query"]
    assert len(q) <= 200 and call_tool(ctx, "retrieve_context", {"query": q})["ok"]


# ------------------------------------------------------------------ official scoring is unchanged
TOOL_CALLS = [("calculate_job_match", {}), ("get_skill_gaps", {"role": "ML Engineer"}), ("predict_salary", {}), ("get_learning_roadmap", {"role": "ML Engineer"}),
              ("simulate_profile_change", {"add_skills": ["PyTorch"], "add_projects": [{"title": "p", "skills": ["Docker"]}], "add_experience_months": 3}),
              ("get_skill_evidence", {"skill": "Docker"}), ("compare_career_paths", {"roles": ["ML Engineer", "Backend / SDE"]})]


def snapshot(conn):
    ctx = ToolContext(conn, 1)
    ctx.embed_fn = Recorder()
    out = {}
    for n, a in TOOL_CALLS:
        r = call_tool(ctx, n, a)
        out[n + json.dumps(a)] = {"data": r["data"], "lines": r["lines"], "numbers": r["numbers"], "refs": r["refs"]}
    return json.loads(json.dumps(out, sort_keys=True, default=str))


@pytest.mark.parametrize("mode,wiring", [("bm25", "legacy"), ("bm25", "improved"), ("hybrid", "legacy"), ("hybrid", "improved")])
def test_scoring_tools_identical_to_pre_change_snapshot_in_every_mode(conn, monkeypatch, mode, wiring):
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_MODE", mode)
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_WIRING", wiring)
    monkeypatch.setenv("CAREERDNA_SEM_MIN_SIM", "0.3")
    before = json.load(open(os.path.join(os.path.dirname(__file__), "tools_before_hybrid.json")))     # captured BEFORE any hybrid edit
    assert snapshot(conn) == before


@pytest.mark.parametrize("mode", ["bm25", "hybrid"])
def test_existing_endpoints_identical_in_both_modes(client, ada_h, monkeypatch, mode):
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_MODE", mode)
    jobs = client.get("/job-match", headers=ada_h).json()["jobs"]
    assert [(j["role"], j["match_percent"]) for j in jobs] == [("ML Engineer", 81.2), ("Backend / SDE", 75.9), ("Cybersecurity Analyst", 52.1)]
    w = client.post("/salary/what-if", json={"added_skill_ids": [11], "added_experience_months": 2, "added_certifications": 1}, headers=ada_h).json()
    assert w["delta_lpa"] == 1.9
