from ai import evidence as ev
from ai.tools import call_tool


def _e(ctx, name):
    return call_tool(ctx, "get_skill_evidence", {"skill": name})["data"]


def test_documented_by_projects(ctx):
    e = _e(ctx, "Python")
    assert e["status"] == "documented" and {"self_reported", "project_supported"} <= set(e["flags"])
    assert [p["ref"] for p in e["projects"]] == ["project:1", "project:2"]


def test_documented_by_certification_text_match(ctx):
    e = _e(ctx, "AWS")
    assert e["status"] == "documented" and "certification_supported" in e["flags"]
    assert e["certifications"][0]["match_basis"].startswith("skill name appears")


def test_self_reported_only(ctx):
    e = _e(ctx, "Docker")
    assert e["status"] == "self_reported_only" and "missing_evidence" in e["flags"] and not e["projects"] and not e["certifications"]


def test_contradictory_evidence(ctx):
    e = _e(ctx, "Deep Learning")
    assert e["status"] == "contradictory" and "contradictory_evidence" in e["flags"]
    assert "Advanced" in e["contradictions"][0] and "12" in e["contradictions"][0]


def test_no_record_is_not_treated_as_inability(ctx):
    e = _e(ctx, "PyTorch")
    assert e["status"] == "no_record" and {"missing_evidence", "insufficient_evidence"} <= set(e["flags"])
    assert "cannot be established" in e["note"] and "incompeten" not in e["note"].lower()


def test_assessments_reported_unavailable_not_invented(ctx):
    e = _e(ctx, "Python")
    assert e["assessment_data_available"] is False and e["assessments"] == []
    assert "assessment_supported" not in e["flags"]


def test_documented_percent_is_separate_from_official_match(ctx):
    job = next(j for j in ctx.jobs if j["role"] == "ML Engineer")
    d = ev.documented_percent(job["requirements"], ctx.evidence())
    assert d["documented_percent"] == 46.9 and set(d["documented_skills"]) == {"Python", "Machine Learning"}


def test_sources_use_real_record_refs(ctx):
    e = _e(ctx, "Python")
    assert e["self_reported"]["ref"] == "candidate_skill:10:1"


def test_unknown_skill_is_a_validation_error_not_a_guess(ctx):
    r = call_tool(ctx, "get_skill_evidence", {"skill": "Underwater Basket Weaving"})
    assert r["ok"] is False and "Unknown skill" in r["error"]
