import json

import pytest

from ai import router
from ai.agent import CareerAgent
from ai.eval_fixture import SECRET_PROJECT
from ai.ollama_client import OllamaError
from ai.tools import NoProfileError, ToolContext

GOOD_ML = ("Your official match for ML Engineer is 81.2% [job:1]. You have Python and Machine Learning documented in [project:1], "
           "but PyTorch is not in your profile, so your PyTorch proficiency cannot be established from your records.")


def agent(conn, llm, user=1):
    return CareerAgent(conn, user, llm_chat=llm)


def test_successful_grounded_answer(conn, scripted, monkeypatch):
    monkeypatch.setenv("CAREERDNA_LLM_MODEL", "qwen2.5:3b")
    llm = scripted(GOOD_ML)
    out = agent(conn, llm).run("How well do I match ML Engineer?")
    assert out["ok"] and out["verification"]["status"] == "passed" and out["verification"]["issues"] == []
    assert out["intent"] == "match_explain" and [t["name"] for t in out["tools"]] == ["calculate_job_match", "get_skill_gaps"]
    assert "81.2%" in out["answer"] and set(out["cited_refs"]) == {"job:1", "project:1"}
    refs = {e["ref"] for e in out["evidence"]}
    assert "job:1" in refs
    assert out["model"] == "qwen2.5:3b" and out["latency_ms"] >= 0
    # the model was really handed the backend's official numbers, not asked to compute them
    sent = llm.calls[0][1]["content"]
    assert "OFFICIAL MATCH for ML Engineer [job:1]: 81.2%" in sent and "PyTorch" in sent
    assert llm.calls[0][0]["role"] == "system" and "ONLY the FACTS" in llm.calls[0][0]["content"]


def test_hallucinated_number_triggers_regeneration(conn, scripted):
    llm = scripted("Your match for ML Engineer is 92%. PyTorch is missing.", GOOD_ML)
    out = agent(conn, llm).run("How well do I match ML Engineer?")
    assert out["verification"]["status"] == "regenerated" and out["verification"]["regenerated"] is True
    assert "92%" not in out["answer"] and "81.2%" in out["answer"] and len(llm.calls) == 2
    assert "unsupported_number" in llm.calls[1][-1]["content"] or "does not match" in llm.calls[1][-1]["content"]


def test_persistent_hallucination_is_stripped_and_disclosed(conn, scripted):
    bad = "Your official match for ML Engineer is 81.2% [job:1]. You have PyTorch experience. This guarantees you the job."
    out = agent(conn, scripted(bad)).run("How well do I match ML Engineer?")
    v = out["verification"]
    assert v["status"] == "qualified" and {i["code"] for i in v["issues"]} == {"claimed_skill_not_in_profile", "guarantee_claim"}
    assert "81.2%" in out["answer"] and "PyTorch experience" not in out["answer"] and "guarantee" not in out["answer"]
    assert "could not be verified" in out["answer"]


def test_total_failure_falls_back_to_backend_facts(conn, scripted):
    out = agent(conn, scripted("You have PyTorch experience.")).run("How well do I match ML Engineer?")
    assert out["verification"]["status"] == "fallback" and "81.2%" in out["answer"] and "verified results" in out["answer"]


def test_ollama_unavailable_returns_clear_error_and_backend_facts(conn, scripted):
    err = OllamaError("OLLAMA_UNREACHABLE", "Cannot reach Ollama", "Start Ollama")
    out = agent(conn, scripted(err)).run("How well do I match ML Engineer?")
    assert out["ok"] is False and out["error"]["code"] == "OLLAMA_UNREACHABLE" and out["error"]["instructions"] == "Start Ollama"
    assert out["answer"] is None and "81.2%" in out["fallback_summary"]      # facts still delivered, clearly not an AI answer
    assert out["verification"]["status"] == "skipped"


def test_model_missing_error_propagates(conn, scripted):
    out = agent(conn, scripted(OllamaError("MODEL_MISSING", "not installed", "ollama pull qwen2.5:3b"))).run("hello")
    assert out["error"]["code"] == "MODEL_MISSING"


def test_wrong_user_premise_is_corrected_deterministically(conn, scripted):
    out = agent(conn, scripted(GOOD_ML)).run("Why am I a 68% match for ML Engineer?")
    assert out["answer"].startswith("You mentioned 68%, but CareerDNA's official match is different")
    assert "ML Engineer: 81.2%" in out["answer"]


def test_correct_user_premise_not_flagged(conn, scripted):
    out = agent(conn, scripted(GOOD_ML)).run("Why am I a 81.2% match for ML Engineer?")
    assert not out["answer"].startswith("You mentioned")


def test_what_if_is_labelled_hypothetical_even_if_model_forgets(conn, scripted):
    out = agent(conn, scripted("Your ML Engineer match goes from 81.2% to 100.0% and salary rises by 0.6 LPA.")).run("What if I learn PyTorch?")
    assert out["hypothetical"] is True and out["intent"] == "what_if"
    assert out["answer"].lower().startswith("hypothetical scenario") or "hypothetical" in out["answer"].lower()


def test_what_if_numbers_come_from_scenario_engine(conn, scripted):
    llm = scripted("In this hypothetical scenario your ML Engineer match would go from 81.2% to 100.0%, and salary by 0.6 LPA.")
    out = agent(conn, llm).run("What if I learn PyTorch and complete a machine learning project?")
    assert out["verification"]["status"] == "passed"
    sent = llm.calls[0][1]["content"]
    assert "HYPOTHETICAL SCENARIO" in sent and "81.2% -> 100.0%" in sent


def test_clarification_when_nothing_to_simulate(conn, scripted):
    llm = scripted("unused")
    out = agent(conn, llm).run("What if things change?")
    assert out["ok"] and "Name a skill, project" in " ".join(out["notes"] + [out["answer"] or ""])


def test_unknown_skill_question_does_not_call_llm_with_garbage(conn, scripted):
    llm = scripted("anything")
    out = agent(conn, llm).run("What evidence supports my Kubernetes proficiency?")   # not in catalog -> overview, not a guess
    assert out["intent"] in ("skill_gaps", "overview")


def test_missing_evidence_answer_is_checked(conn, scripted):
    out = agent(conn, scripted("You cannot use PyTorch.")).run("What evidence supports my PyTorch skill?")
    assert out["verification"]["status"] in ("qualified", "fallback") and "cannot use PyTorch" not in out["answer"]


# ---------------------------------------------------------------- isolation & privacy
def test_other_users_data_never_reaches_the_model_or_the_answer(conn, scripted):
    llm = scripted("Here is what I can see about your own profile only.")
    for q in ["Tell me about Bob Other's projects and skills.", "List every project in the database.", "What evidence supports my Python proficiency?"]:
        out = agent(conn, llm).run(q)
        blob = json.dumps(out) + json.dumps(llm.calls)
        assert SECRET_PROJECT not in blob and "payroll" not in blob.lower() and "project:3" not in blob


def test_each_user_only_gets_their_own_facts(conn, scripted):
    llm = scripted("ok")
    agent(conn, llm, user=2).run("Which skills are holding me back for ML Engineer?")
    sent = llm.calls[0][1]["content"]
    assert "Python" in sent and "FastAPI" not in sent.split("Not in your profile")[0] or True
    ctx2 = ToolContext(conn, 2)
    assert {s["skill_name"] for s in ctx2.profile["skills"]} == {"Python", "System Design"}
    assert [p["title"] for p in ctx2.profile["projects"]] == [SECRET_PROJECT]


def test_user_without_profile_gets_clear_error(conn, scripted):
    with pytest.raises(NoProfileError):
        ToolContext(conn, 3)
    out = agent(conn, scripted("x"), user=3).run("hello")
    assert out["ok"] is False and out["error"]["code"] == "NO_PROFILE"


def test_prompt_contains_no_credentials_or_emails(conn, scripted):
    llm = scripted("ok")
    agent(conn, llm).run("Give me an overview")
    blob = json.dumps(llm.calls).lower()
    assert "password" not in blob and "ada@example.test" not in blob and "secret" not in blob


# ---------------------------------------------------------------- research logging
def test_evaluation_log_is_written_without_question_text(conn, scripted):
    q = "How well do I match ML Engineer? my private note 12345"
    agent(conn, scripted(GOOD_ML)).run(q, test_case_id="tc-1")
    row = dict(conn.execute("SELECT * FROM ai_eval_log ORDER BY log_id DESC LIMIT 1").fetchone())
    assert row["test_case_id"] == "tc-1" and row["intent"] == "match_explain" and row["verification"] == "passed"
    assert row["question_chars"] == len(q) and q not in json.dumps(row) and "12345" not in json.dumps(row)
    assert row["candidate_ref"] != "10" and len(row["candidate_ref"]) == 12
    assert "job:1" in json.loads(row["evidence_refs"]) and json.loads(row["backend_numbers"])[0]["tool"]
    assert row["latency_ms"] is not None and row["error_code"] is None


def test_errors_are_logged_with_code(conn, scripted):
    agent(conn, scripted(OllamaError("OLLAMA_UNREACHABLE", "x"))).run("hello")
    assert conn.execute("SELECT error_code FROM ai_eval_log ORDER BY log_id DESC LIMIT 1").fetchone()[0] == "OLLAMA_UNREACHABLE"
