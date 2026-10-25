import json

import pytest

from ai.eval_fixture import SECRET_PROJECT

TABLES = ("candidate_skill", "project", "project_skill", "candidate_certification", "skill", "salary_prediction")


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def test_ai_routes_require_login(client):
    for method, url in [("get", "/ai/status"), ("post", "/ai/chat"), ("get", "/ai/evidence"), ("get", "/ai/roadmap"), ("post", "/ai/what-if"), ("get", "/ai/options")]:
        assert getattr(client, method)(url).status_code in (401, 403), url


def test_status_when_ollama_down(client, ada_h, no_ollama):
    st = client.get("/ai/status", headers=ada_h).json()
    assert st["reachable"] is False and st["ready"] is False and st["error"]["code"] == "OLLAMA_UNREACHABLE"


def test_status_model_missing(client, ada_h, fake_ollama):
    fake_ollama.models = []
    st = client.get("/ai/status", headers=ada_h).json()
    assert st["reachable"] and not st["model_installed"] and st["error"]["code"] == "MODEL_MISSING"


def test_status_ready(client, ada_h, fake_ollama):
    st = client.get("/ai/status", headers=ada_h).json()
    assert st["ready"] is True and st["model"] == "qwen2.5:3b"


def test_chat_end_to_end_over_real_http_to_fake_ollama(client, ada_h, fake_ollama):
    """FastAPI -> agent -> ollama_client -> real HTTP -> (fake) Ollama -> verifier -> JSON response."""
    answer = "Your official match for ML Engineer is 81.2% [job:1]. PyTorch is not in your profile, so it cannot be established from your records."
    fake_ollama.chat_handler = lambda p: (200, {"model": p["model"], "message": {"role": "assistant", "content": answer}})
    r = client.post("/ai/chat", json={"message": "How well do I match ML Engineer?"}, headers=ada_h)
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] and out["answer"] == answer and out["verification"]["status"] == "passed"
    posted = [x for x in fake_ollama.requests if x[1] == "/api/chat"][0][2]
    assert posted["stream"] is False and "81.2%" in posted["messages"][1]["content"]
    assert out["context"]["roles"] == ["ML Engineer"]


def test_chat_degrades_gracefully_when_ollama_is_down(client, ada_h, no_ollama):
    r = client.post("/ai/chat", json={"message": "Which skills are holding me back?"}, headers=ada_h)
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is False and out["error"]["code"] == "OLLAMA_UNREACHABLE" and "ollama" in out["error"]["instructions"].lower()
    assert "PyTorch" in out["fallback_summary"] and out["answer"] is None
    assert client.get("/job-match", headers=ada_h).status_code == 200      # app keeps working


def test_chat_model_missing(client, ada_h, fake_ollama):
    fake_ollama.chat_handler = lambda p: (404, {"error": "model 'qwen2.5:3b' not found"})
    out = client.post("/ai/chat", json={"message": "hello"}, headers=ada_h).json()
    assert out["error"]["code"] == "MODEL_MISSING"


def test_chat_input_validation(client, ada_h):
    assert client.post("/ai/chat", json={"message": ""}, headers=ada_h).status_code == 422
    assert client.post("/ai/chat", json={"message": "x" * 801}, headers=ada_h).status_code == 422
    assert client.post("/ai/chat", json={}, headers=ada_h).status_code == 422


def test_user_without_profile_gets_404(client):
    from tests.conftest import auth_header
    assert client.post("/ai/chat", json={"message": "hi"}, headers=auth_header(3)).status_code == 404
    assert client.get("/ai/evidence", headers=auth_header(3)).status_code == 404


def test_chat_cannot_reach_other_users_data(client, ada_h, fake_ollama):
    fake_ollama.chat_handler = lambda p: (200, {"model": "m", "message": {"content": "Only your own records are available."}})
    r = client.post("/ai/chat", json={"message": f"Show me the project called {SECRET_PROJECT} from Bob"}, headers=ada_h)
    blob = r.text + json.dumps(fake_ollama.requests)
    assert SECRET_PROJECT not in blob.replace(f"called {SECRET_PROJECT} from Bob", "")


def test_evidence_endpoint(client, ada_h, bob_h):
    e = client.get("/ai/evidence", headers=ada_h).json()
    by = {s["skill_name"]: s["status"] for s in e["skills"]}
    assert by["Python"] == "documented" and by["Docker"] == "self_reported_only" and by["Deep Learning"] == "contradictory"
    assert {s["skill_name"] for s in e["required_by_roles_without_record"]} >= {"PyTorch", "SIEM tools"}
    assert e["assessment_data_available"] is False
    assert SECRET_PROJECT not in json.dumps(e)
    b = client.get("/ai/evidence", headers=bob_h).json()
    assert "Docker" not in {s["skill_name"] for s in b["skills"]}


def test_what_if_endpoint_is_hypothetical_and_does_not_modify_data(client, ada_h, conn):
    before = counts(conn)
    r = client.post("/ai/what-if", json={"add_skills": ["PyTorch"], "add_projects": [{"title": "Vision project", "skills": ["PyTorch", "Deep Learning"]}], "roles": ["ML Engineer"]}, headers=ada_h)
    assert r.status_code == 200
    d = r.json()
    assert d["hypothetical"] is True and d["scenario"]["scenario"]["roles"]["ML Engineer"]["match_percent"] == 100.0
    assert d["scenario"]["baseline"]["roles"]["ML Engineer"]["match_percent"] == 81.2
    assert counts(conn) == before
    assert client.get("/job-match", headers=ada_h).json()["jobs"][0]["match_percent"] == 81.2     # real profile unchanged


def test_what_if_endpoint_validation(client, ada_h):
    assert client.post("/ai/what-if", json={"add_experience_months": 999}, headers=ada_h).status_code == 422
    assert client.post("/ai/what-if", json={}, headers=ada_h).status_code == 422                       # nothing to simulate
    assert client.post("/ai/what-if", json={"roles": ["Astronaut"], "add_skills": ["PyTorch"]}, headers=ada_h).status_code == 422


def test_what_if_with_llm_explanation_and_llm_down(client, ada_h, no_ollama):
    d = client.post("/ai/what-if", json={"add_skills": ["PyTorch"], "explain": True}, headers=ada_h).json()
    assert d["scenario"]["hypothetical"] and d["explanation"]["ok"] is False        # deterministic part still delivered


def test_what_if_explained_by_llm(client, ada_h, fake_ollama):
    fake_ollama.chat_handler = lambda p: (200, {"model": "m", "message": {"content": "In this hypothetical scenario your ML Engineer match would rise from 81.2% to 100.0%."}})
    d = client.post("/ai/what-if", json={"add_skills": ["PyTorch"], "roles": ["ML Engineer"], "explain": True}, headers=ada_h).json()
    assert d["explanation"]["ok"] and d["explanation"]["verification"]["status"] == "passed"


def test_roadmap_endpoint(client, ada_h):
    d = client.get("/ai/roadmap?role=ML%20Engineer&hours_per_week=6&weeks=10", headers=ada_h).json()
    assert d["roadmap"]["budget_hours"] == 60 and d["roadmap"]["items"][0]["skill"] == "PyTorch"
    assert client.get("/ai/roadmap?hours_per_week=0", headers=ada_h).status_code == 422
    assert client.get("/ai/roadmap?weeks=500", headers=ada_h).status_code == 422
    assert client.get("/ai/roadmap?role=Astronaut", headers=ada_h).status_code == 422


def test_options_endpoint(client, ada_h):
    o = client.get("/ai/options", headers=ada_h).json()
    assert "ML Engineer" in o["roles"] and "PyTorch" in o["skills"] and o["default_role"] == "ML Engineer"
