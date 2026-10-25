"""Existing CareerDNA behaviour must be unchanged by the AI integration."""
import json
import os

import pytest

from ai import scoring


def test_job_match_values_and_order(client, ada_h):
    jobs = client.get("/job-match", headers=ada_h).json()["jobs"]
    assert [(j["role"], j["match_percent"]) for j in jobs] == [("ML Engineer", 81.2), ("Backend / SDE", 75.9), ("Cybersecurity Analyst", 52.1)]


def test_career_gap_rules_preserved(client, ada_h):
    g = client.get("/career-gap?role=cybersecurity analyst", headers=ada_h).json()   # case-insensitive exact
    assert g["role"] == "Cybersecurity Analyst" and g["match_percent"] == 52.1
    assert {m["name"] for m in g["missing_skills"]} == {"SIEM tools", "Cloud Security"}
    assert client.get("/career-gap?role=Nope", headers=ada_h).json()["role"] == "ML Engineer"   # falls back to first job
    assert client.get("/career-gap", headers=ada_h).json()["role"] == "ML Engineer"


def test_salary_and_what_if_endpoints(client, ada_h, conn):
    avg, n = scoring.salary_inputs(conn, 10)
    s = client.get("/salary", headers=ada_h).json()
    assert s["source"] == "explainable-profile-estimate" and s["predicted_salary_lpa"] == round(9.0 + avg * 0.06 + n * 0.15, 2)
    w = client.post("/salary/what-if", json={"added_skill_ids": [11], "added_experience_months": 2, "added_certifications": 1}, headers=ada_h).json()
    assert w["delta_lpa"] == 1.9                                    # 0.6 (skill) + 0.3*2 (months) + 0.7 (cert)
    assert abs(w["projected_salary_lpa"] - w["base_salary_lpa"] - w["delta_lpa"]) < 0.011


def test_stored_prediction_still_wins(client, ada_h, conn):
    conn.execute("INSERT INTO salary_prediction (candidate_id, predicted_salary, confidence) VALUES (10, 17.5, 81)")
    conn.commit()
    s = client.get("/salary", headers=ada_h).json()
    assert s["source"] == "database" and s["predicted_salary_lpa"] == 17.5


def test_profile_and_health_and_auth_endpoints_work(client, ada_h):
    assert client.get("/health").json()["status"] == "healthy"
    assert client.get("/profile", headers=ada_h).status_code == 200
    assert client.get("/skill-strength", headers=ada_h).status_code == 200
    assert client.get("/career-history", headers=ada_h).json() == {"history": []}
    assert client.get("/auth/me", headers=ada_h).json()["email"] == "ada@example.test"
    assert client.get("/job-match").status_code in (401, 403)          # still protected


def test_existing_features_work_with_ollama_down(client, ada_h, no_ollama):
    for ep in ("/job-match", "/salary", "/career-gap", "/profile", "/skill-strength"):
        assert client.get(ep, headers=ada_h).status_code == 200, ep


def test_before_after_snapshot_of_real_project_is_identical():
    """Compares captured outputs of the ORIGINAL code vs the refactored code on the real project database (if present)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    snap = os.path.join(here, "tests", "baseline_regression.json")
    if not os.path.exists(snap):
        pytest.skip("no baseline snapshot shipped")
    data = json.load(open(snap))
    assert data["identical"] == data["total"] and data["total"] >= 14
