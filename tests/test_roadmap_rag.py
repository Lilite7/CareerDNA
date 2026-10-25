import pytest

from ai import rag
from ai.tools import ToolContext, call_tool


def road(ctx, **kw):
    r = call_tool(ctx, "get_learning_roadmap", kw)
    assert r["ok"], r.get("error")
    return r["data"]


def test_priorities_follow_job_requirements(ctx):
    d = road(ctx, role="Cybersecurity Analyst", hours_per_week=10, weeks=12)
    assert [(i["action"], i["skill"]) for i in d["items"]] == [("learn", "SIEM tools"), ("learn", "Cloud Security")]  # Critical before Required
    assert all(i["source"] == "job requirement (database)" for i in d["items"])


def test_self_reported_and_contradictory_become_document_and_review_steps(ctx):
    d = road(ctx, role="ML Engineer")
    acts = {(i["action"], i["skill"]) for i in d["items"]}
    assert ("learn", "PyTorch") in acts and ("document", "Docker") in acts and ("review", "Deep Learning") in acts


def test_prerequisites_inserted_before_dependent_skill(conn):
    ctx = ToolContext(conn, 2)       # Bob: has Python + System Design only
    d = road(ctx, role="ML Engineer", hours_per_week=10, weeks=20)
    order = [i["skill"] for i in d["items"]]
    assert order.index("Machine Learning") < order.index("Deep Learning") < order.index("PyTorch")


def test_time_window_flags_are_honest(ctx):
    tight = road(ctx, role="ML Engineer", hours_per_week=1, weeks=1)
    assert tight["budget_hours"] == 1 and all(i["fits_window"] in ("no", "maybe") for i in tight["items"])
    roomy = road(ctx, role="ML Engineer", hours_per_week=40, weeks=52)
    assert all(i["fits_window"] == "yes" for i in roomy["items"])
    assert "not promises" in roomy["disclaimer"]
    for i in roomy["items"]:
        assert i["estimated_weeks"][0] <= i["estimated_weeks"][1]


def test_default_role_comes_from_profile_goals_and_is_stated(ctx):
    r = call_tool(ctx, "get_learning_roadmap", {})
    assert r["data"]["role"] == "ML Engineer"
    assert any("taken from your profile goals" in a for a in r["assumptions"])


def test_default_role_falls_back_to_best_match_with_assumption_note(conn):
    conn.execute("DELETE FROM profile_version")
    conn.commit()
    r = call_tool(ToolContext(conn, 1), "get_learning_roadmap", {})
    assert any("does not name a target role" in a for a in r["assumptions"])


# -------------------------------------------------------------- retrieval
def test_retrieval_finds_relevant_project(ctx):
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    hits = rag.retrieve("threat classification security logs", docs)
    assert hits and hits[0]["ref"] == "project:1"
    hits = rag.retrieve("salary prediction web app", docs, types={"project"})
    assert hits[0]["ref"] == "project:2"


def test_retrieval_returns_nothing_for_unrelated_query(ctx):
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    assert rag.retrieve("quantum gastronomy", docs) == []


def test_retrieval_is_scoped_to_the_users_own_records(ctx):
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    assert not any("Bob" in d["title"] or "payroll" in d["text"].lower() for d in docs)
    r = call_tool(ctx, "retrieve_context", {"query": "confidential payroll engine"})
    assert r["ok"] and r["data"]["hits"] == []
