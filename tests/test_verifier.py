import pytest

from ai import verifier as v


def facts(**kw):
    base = dict(profile_skills={"python": "Advanced", "docker": "Intermediate"}, documented_skills={"python"},
                known_skills=["Python", "Docker", "PyTorch", "SQL", "Machine Learning"], project_titles=["AI-SOC Platform"],
                certification_count=0, refs={"project:1", "job:1", "candidate_skill:10:1"},
                numbers={"percent": [81.2, 18.8, 100.0], "lpa": [13.9, 14.5, 0.6]}, hypothetical=False)
    base.update(kw)
    return v.Facts(**base)


def codes(answer, **kw):
    return {i.code for i in v.verify(answer, facts(**kw))}


def test_correct_numbers_pass():
    assert codes("Your official match is 81.2%. Adding it gives +18.8 percentage points. Estimated 13.9 LPA.") == set()


def test_rounding_of_a_real_number_is_tolerated_but_other_numbers_are_not():
    assert codes("Your match is about 81%.") == set()
    assert codes("Your match is 85%.") == {"unsupported_number"}
    assert codes("The salary will be 25 LPA.") == {"unsupported_number"}


def test_percent_and_lpa_are_checked_separately():
    assert codes("You earn 81.2 LPA.") == {"unsupported_number"}      # 81.2 is a percent value, not a salary


def test_user_number_echo_allowed_only_when_clearly_a_quote():
    f = facts(user_numbers=[68.0])
    assert not v.verify("You mentioned 68%, but the official match is 81.2%.", f)
    assert {i.code for i in v.verify("Yes, 68% is correct.", f)} == {"unsupported_number"}


def test_claiming_a_skill_not_in_profile():
    assert codes("You have PyTorch experience from your projects.") == {"claimed_skill_not_in_profile"}
    assert codes("You are proficient in Machine Learning.") == {"claimed_skill_not_in_profile"}


def test_gap_language_about_missing_skills_is_fine():
    assert codes("PyTorch is missing from your profile, so you should learn it.") == set()
    assert codes("If you add PyTorch, your match would rise.") == set()
    assert codes("You have Python and Docker listed.") == set()


def test_documented_skill_via_project_counts_as_possessed():
    assert codes("You are proficient in Machine Learning.", documented_skills={"python", "machine learning"}) == set()


def test_proficiency_mismatch():
    assert codes("Your Docker level is Advanced.") == {"proficiency_mismatch"}
    assert codes("Your Docker level is Intermediate.") == set()


def test_certification_claim_without_records():
    assert codes("You have a certification in cloud computing.") == {"claimed_certification_not_in_records"}
    assert codes("You have a certification in cloud computing.", certification_count=1) == set()
    assert codes("You do not have any certification recorded.") == set()


def test_unknown_project_reference():
    assert codes('You built the "Quantum Trading Bot" project.') == {"unknown_project_reference"}
    assert codes('You built the "AI-SOC Platform" project [project:1].') == set()


def test_invalid_citation():
    assert codes("Supported by [project:99].") == {"invalid_citation"}
    assert codes("Supported by [project:1].") == set()


def test_missing_evidence_not_stated_as_inability():
    assert codes("You cannot do PyTorch.") == {"missing_evidence_as_inability"}
    assert codes("You are not proficient in PyTorch.") == {"missing_evidence_as_inability"}
    assert codes("PyTorch proficiency cannot be established from your records; you are not proficient on paper only.") == set()


def test_guarantees_are_flagged_but_disclaimers_are_not():
    assert codes("This guarantees you a job.") == {"guarantee_claim"}
    assert codes("You will definitely get the offer.") == {"guarantee_claim"}
    assert codes("This does not guarantee an offer.") == set()


def test_hypothetical_results_must_be_labelled():
    assert codes("Your match will be 100.0%.", hypothetical=True) == {"unlabelled_hypothetical"}
    assert codes("In this hypothetical scenario your match would be 100.0%.", hypothetical=True) == set()


def test_qualify_removes_bad_sentences_and_adds_notice():
    ans = "Your match is 81.2%. You have PyTorch experience. This guarantees you a job."
    issues = v.verify(ans, facts())
    out, kept = v.qualify(ans, issues)
    assert kept > 0 and "81.2%" in out and "PyTorch" not in out and "guarantee" not in out and "2 statement(s)" in out


def test_qualify_prefixes_hypothetical_label():
    ans = "Your match will be 100.0%."
    out, _ = v.qualify(ans, v.verify(ans, facts(hypothetical=True)))
    assert out.startswith("Hypothetical scenario")


def test_benchmark_file_scores():
    from ai.evaluation import verifier_benchmark
    r = verifier_benchmark()
    assert r["cases"] >= 40 and r["recall"] >= 0.8 and r["false_positive_rate"] <= 0.05   # measured: recall 0.821, FPR 0.0
