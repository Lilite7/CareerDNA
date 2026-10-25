import pytest

from ai import scoring
from ai.tools import call_tool

TABLES = ("candidate_skill", "project", "project_skill", "candidate_certification", "certification", "skill", "experience", "profile_version")


def counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}


def sim(ctx, **kw):
    r = call_tool(ctx, "simulate_profile_change", kw)
    assert r["ok"], r.get("error")
    return r


def test_original_profile_and_database_are_untouched(ctx):
    before, prof = counts(ctx.conn), repr(ctx.profile)
    sim(ctx, add_skills=["PyTorch"], add_projects=[{"title": "p", "skills": ["PyTorch"]}], add_certifications=[{"name": "AWS Cloud Practitioner"}], add_experience_months=6)
    assert counts(ctx.conn) == before and repr(ctx.profile) == prof


def test_claimed_skill_changes_match_exactly_as_the_formula_says(ctx):
    r = sim(ctx, add_skills=["PyTorch"], roles=["ML Engineer"])
    d = r["data"]
    assert d["hypothetical"] is True and d["label"].startswith("HYPOTHETICAL")
    assert d["baseline"]["roles"]["ML Engineer"]["match_percent"] == 81.2
    assert d["scenario"]["roles"]["ML Engineer"]["match_percent"] == 100.0
    assert d["changes"]["roles"]["ML Engineer"]["match_delta_pp"] == 18.8
    assert [n["skill"] for n in d["changes"]["roles"]["ML Engineer"]["newly_matched"]] == ["PyTorch"]
    # cross-check against the official function recomputed independently
    job = next(j for j in ctx.jobs if j["role"] == "ML Engineer")
    independent = scoring.compute_match(job["requirements"], ctx.have_ids() | {11})["match_percent"]
    assert independent == d["scenario"]["roles"]["ML Engineer"]["match_percent"]


def test_no_hardcoded_improvement_for_skills_no_role_requires(ctx):
    """Months of experience only: the official match must not move; only the existing salary rule applies."""
    d = sim(ctx, add_experience_months=6)["data"]
    for role, c in d["changes"]["roles"].items():
        assert c["match_delta_pp"] == 0 and c["documented_delta_pp"] == 0
    assert d["changes"]["salary_delta_lpa"] == pytest.approx(0.3 * 6, abs=0.011)


def test_documenting_an_already_listed_skill_changes_evidence_not_official_match(ctx):
    d = sim(ctx, add_projects=[{"title": "Containerised deployment", "skills": ["Docker"]}], roles=["ML Engineer"])["data"]
    c = d["changes"]["roles"]["ML Engineer"]
    assert c["match_delta_pp"] == 0                                  # official score counts presence only
    assert c["documented_delta_pp"] == 15.6                          # Docker weight 1.0 / 6.4 -> 15.6 pp more documented coverage
    assert c["evidence_status_changes"][0]["skill"] == "Docker" and c["evidence_status_changes"][0]["after"] == "documented"
    assert d["changes"]["salary_delta_lpa"] == 0                     # no project term and no new skill -> no salary change
    assert any("does not weigh proficiency" in x for x in d["limitations"])


def test_salary_matches_the_existing_what_if_endpoint(ctx, client, ada_h):
    d = sim(ctx, add_skills=["PyTorch", "System Design"], add_experience_months=3, add_certifications=[{"name": "Some certificate"}])["data"]
    api = client.post("/salary/what-if", json={"added_skill_ids": [11, 9], "added_experience_months": 3, "added_certifications": 1}, headers=ada_h).json()
    assert d["scenario"]["salary"]["projected_salary_lpa"] == api["projected_salary_lpa"]
    assert d["baseline"]["salary"]["base_salary_lpa"] == api["base_salary_lpa"]
    assert d["changes"]["salary_delta_lpa"] == pytest.approx(api["delta_lpa"], abs=0.011)


def test_unknown_skill_is_reported_not_invented(ctx):
    d = sim(ctx, add_skills=["Kubernetes"])["data"]
    assert d["unresolved"][0]["input"] == "Kubernetes" and not d["applied"]
    assert all(c["match_delta_pp"] == 0 for c in d["changes"]["roles"].values())
    assert d["changes"]["salary_delta_lpa"] == 0
    assert any("could not be scored" in x for x in d["limitations"])


def test_already_listed_skill_is_a_noop(ctx):
    d = sim(ctx, add_skills=["Python"])["data"]
    assert not d["applied"] and any("already in your profile" in n for n in d["notes"])


def test_certification_assumption_is_labelled(ctx):
    d = sim(ctx, add_certifications=[{"name": "Google Cloud Security Specialist", "skills": ["Cloud Security"]}], roles=["Cybersecurity Analyst"])["data"]
    c = d["changes"]["roles"]["Cybersecurity Analyst"]
    assert [n["skill"] for n in c["newly_matched"]] == ["Cloud Security"]
    assert any("Assuming you would also list" in a for a in d["assumptions"])
    assert c["evidence_status_changes"][0]["after"] == "documented"
    assert d["inputs"]["added_certifications"] == 1


def test_compare_baseline_and_scenario_are_both_present_and_distinct(ctx):
    d = sim(ctx, add_skills=["SIEM tools", "Cloud Security"])["data"]
    assert d["baseline"]["roles"]["Cybersecurity Analyst"]["match_percent"] == 52.1
    assert d["scenario"]["roles"]["Cybersecurity Analyst"]["match_percent"] == 100.0


def test_result_lines_never_promise_outcomes(ctx):
    r = sim(ctx, add_skills=["PyTorch"])
    text = " ".join(r["lines"]).lower()
    assert "hypothetical" in text and "does not predict or guarantee" in text
