import pytest

from ai import router
from ai.tools import TOOLS, call_tool

SAMPLES = {
    "Why am I a 68% match for ML Engineer?": ("match_explain", "calculate_job_match"),
    "Which skills are holding me back?": ("skill_gaps", "get_skill_gaps"),
    "What evidence supports my Python proficiency?": ("skill_evidence", "get_skill_evidence"),
    "Compare ML Engineer and Cybersecurity Analyst for my profile.": ("compare", "compare_career_paths"),
    "What should I learn next for my target career?": ("roadmap", "get_learning_roadmap"),
    "What if I learn PyTorch and complete a machine learning project?": ("what_if", "simulate_profile_change"),
    "What information is missing before you can assess my readiness?": ("missing_info", "get_career_profile"),
    "What salary can I expect?": ("salary", "predict_salary"),
    "hello there": ("overview", "get_career_profile"),
}


@pytest.mark.parametrize("q,expected", SAMPLES.items())
def test_intent_and_first_tool(ctx, q, expected):
    p = router.plan(q, ctx.jobs, ctx.catalog)
    assert p["intent"] == expected[0]
    assert p["calls"][0]["name"] == expected[1]


def test_role_phrase_does_not_leak_into_skills(ctx):
    p = router.plan("Why am I a 68% match for ML Engineer?", ctx.jobs, ctx.catalog)
    assert p["roles"] == ["ML Engineer"] and p["skills"] == [] and p["premise_percents"] == [68.0]


def test_whatif_extraction(ctx):
    p = router.plan("What if I learn PyTorch and complete a machine learning project?", ctx.jobs, ctx.catalog)
    a = p["calls"][0]["args"]
    assert a["add_skills"] == ["PyTorch"] and a["add_projects"][0]["skills"] == ["Machine Learning"]
    p = router.plan("What if I earn the AWS Cloud Practitioner certification and get 6 months of internship experience?", ctx.jobs, ctx.catalog)
    a = p["calls"][0]["args"]
    assert a["add_certifications"][0]["skills"] == ["AWS"] and a["add_experience_months"] == 6


def test_whatif_without_details_asks_for_clarification(ctx):
    p = router.plan("What if things change?", ctx.jobs, ctx.catalog)
    assert p["intent"] == "what_if" and p["clarification"] and p["calls"][0]["name"] == "get_career_profile"


def test_roadmap_time_constraints_parsed(ctx):
    p = router.plan("Give me a roadmap for ML Engineer, 8 hours per week for 6 weeks", ctx.jobs, ctx.catalog)
    a = p["calls"][0]["args"]
    assert a == {"role": "ML Engineer", "hours_per_week": 8.0, "weeks": 6}
    p = router.plan("What should I learn in 3 months?", ctx.jobs, ctx.catalog)
    assert p["calls"][0]["args"]["weeks"] == 13 and any("assumed" in n for n in p["notes"])


def test_follow_up_uses_previous_role_only_with_referential_cue(ctx):
    p = router.plan("What about the skill gaps there?", ctx.jobs, ctx.catalog, {"roles": ["Backend / SDE"]})
    assert p["roles"] == ["Backend / SDE"] and p["carried_context"]
    p = router.plan("Which skills are holding me back?", ctx.jobs, ctx.catalog, {"roles": ["Backend / SDE"]})
    assert p["roles"] == []


# -------------------------------------------------------------- argument validation
def test_unknown_argument_rejected(ctx):
    r = call_tool(ctx, "calculate_job_match", {"role": "ML Engineer", "candidate_id": 11})
    assert r["ok"] is False and "Unexpected argument" in r["error"]


def test_no_tool_accepts_a_candidate_or_user_id():
    for t in TOOLS.values():
        assert not {"candidate_id", "user_id", "sql", "query_sql", "command", "code"} & set(t.params), t.name


@pytest.mark.parametrize("name,args", [
    ("calculate_job_match", {"role": "Astronaut"}),
    ("get_skill_evidence", {}),
    ("get_learning_roadmap", {"hours_per_week": 500}),
    ("get_learning_roadmap", {"weeks": 0}),
    ("get_learning_roadmap", {"weeks": "lots"}),
    ("compare_career_paths", {"roles": ["ML Engineer"]}),
    ("compare_career_paths", {"roles": ["ML Engineer", "ML Engineer"]}),
    ("simulate_profile_change", {}),
    ("simulate_profile_change", {"add_experience_months": 9999}),
    ("simulate_profile_change", {"add_skills": ["x"] * 20}),
    ("retrieve_context", {"query": "a" * 5000}),
    ("get_career_profile", {"role": "ML Engineer"}),
    ("not_a_tool", {}),
])
def test_invalid_arguments_return_errors_not_exceptions(ctx, name, args):
    r = call_tool(ctx, name, args)
    assert r["ok"] is False and r["error"]


def test_sql_injection_text_is_inert(ctx):
    r = call_tool(ctx, "get_skill_evidence", {"skill": "Python'; DROP TABLE candidate; --"})
    assert r["ok"] is False
    assert ctx.conn.execute("SELECT COUNT(*) FROM candidate").fetchone()[0] == 2


def test_tools_are_read_only(ctx):
    before = {t: ctx.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("candidate_skill", "project", "candidate_certification", "candidate")}
    for name, args in [("simulate_profile_change", {"add_skills": ["PyTorch"], "add_projects": [{"title": "p", "skills": ["PyTorch"]}], "add_certifications": [{"name": "c"}]}),
                       ("get_learning_roadmap", {}), ("calculate_job_match", {}), ("get_skill_gaps", {}), ("predict_salary", {})]:
        assert call_tool(ctx, name, args)["ok"]
    after = {t: ctx.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert before == after
