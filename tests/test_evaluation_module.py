import json

from ai import evaluation


def test_mock_run_is_clearly_labelled_and_complete():
    r = evaluation.run_evaluation("mock", only=["match_ml_wrong_premise", "whatif_pytorch_project", "evidence_python", "isolation_other_user", "compare_roles"])
    assert "SELF-TEST ONLY" in r["WARNING"] and r["llm_mode"] == "mock" and "not a language model" in r["model"]
    assert set(r["systems"]) == {"A", "B", "C"} and r["systems"]["A"]["coverage"] < 1       # existing CareerDNA cannot answer all question types
    assert r["systems"]["C"]["coverage"] == 1 and r["systems"]["C"]["intent_routing_accuracy"] == 1.0
    assert r["verifier_benchmark"]["cases"] >= 40 and r["resources"]["note"]
    md = evaluation.to_markdown(r)
    assert "SELF-TEST ONLY" in md and "| factual_consistency |" in md


def test_dataset_is_fixed_and_well_formed():
    d = json.load(open(evaluation.EVAL_DIR + "/cases.json"))["cases"]
    ids = [c["id"] for c in d]
    assert len(ids) == len(set(ids)) >= 15 and all("question" in c and "expected" in c for c in d)


def test_expected_numbers_in_dataset_match_official_scoring(conn):
    """The dataset's hand-verified constants must equal what the official scoring code returns for the fixture."""
    from ai.tools import ToolContext, call_tool
    ctx = ToolContext(conn, 1)
    rows = {r["role"]: r["match_percent"] for r in call_tool(ctx, "calculate_job_match", {})["data"]["roles"]}
    assert rows == {"ML Engineer": 81.2, "Cybersecurity Analyst": 52.1, "Backend / SDE": 75.9}
    assert call_tool(ctx, "predict_salary", {})["data"]["predicted_salary_lpa"] == 13.9
    d = call_tool(ctx, "simulate_profile_change", {"add_skills": ["Cloud Security"], "roles": ["Cybersecurity Analyst"]})["data"]
    assert d["scenario"]["roles"]["Cybersecurity Analyst"]["match_percent"] == 72.9


def test_aborts_cleanly_when_ollama_not_ready(no_ollama):
    r = evaluation.run_evaluation("ollama", only=["salary"])
    assert "aborted" in r and "not ready" in r["aborted"]
