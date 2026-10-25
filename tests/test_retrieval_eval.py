import json
import os

import pytest

from ai import rag, retrieval_eval as re_
from ai.config import get_retrieval_settings
from ai.db import connect
from ai.tools import ToolContext


@pytest.fixture(scope="module")
def corpora():
    return re_.make_corpora()


def test_gold_labels_refer_to_real_records_of_the_right_user(corpora):
    """Catches typos in the hand-written gold set: every relevant ref must exist in THAT user's own documents."""
    gold = re_.load_gold("all")
    for g in gold:
        with re_.db_env(corpora[g["corpus"]]):
            c = connect()
            ctx = ToolContext(c, g["user"])
            refs = {d["ref"] for d in rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog) if d["type"] != "job"}
            c.close()
        assert set(g["relevant"]) <= refs, g["id"]


def test_gold_set_shape_and_split():
    gold = re_.load_gold("all")
    ids = [g["id"] for g in gold]
    assert len(ids) == len(set(ids)) == 41
    dev, test = re_.load_gold("dev"), re_.load_gold("test")
    assert not ({g["id"] for g in dev} & {g["id"] for g in test}) and len(dev) + len(test) == 41
    for cat in ("paraphrase", "lexical", "no_answer"):
        assert any(g["category"] == cat for g in dev) and any(g["category"] == cat for g in test)
    assert all(g["relevant"] == [] for g in gold if g["category"] == "no_answer")


def test_rich_fixture_is_clearly_synthetic_and_separate_from_the_small_one(corpora):
    assert corpora["small"] != corpora["rich"]
    with re_.db_env(corpora["rich"]):
        c = connect()
        names = [r[0] for r in c.execute("SELECT name FROM candidate")]
        assert all("SYNTHETIC" in n for n in names if "Rhea" in n) and not c.execute("SELECT 1 FROM candidate WHERE name = 'Ada Test'").fetchone()
        c.close()
    assert "SYNTHETIC" in open(os.path.join(os.path.dirname(re_.__file__), "eval_fixture_rich.py")).read()[:200]


def test_metrics_on_hand_computed_rows():
    rows = [{"relevant": ["a", "b"], "retrieved": ["x", "a", "c"], "ms": None, "diag": None, "attempted": True, "leak": False, "id": "1", "category": "c"},
            {"relevant": ["a"], "retrieved": ["a"], "ms": 1.0, "diag": None, "attempted": True, "leak": False, "id": "2", "category": "c"},
            {"relevant": [], "retrieved": [], "ms": None, "diag": None, "attempted": False, "leak": False, "id": "3", "category": "c"},
            {"relevant": [], "retrieved": ["z"], "ms": None, "diag": None, "attempted": True, "leak": True, "id": "4", "category": "c"}]
    m = re_.metrics(rows)
    assert m["recall@1"] == 0.5 and m["recall@3"] == 0.75 and m["mrr"] == 0.75           # (1/2 + 1)/2 ; recall (1/2 + 1)/2 at k=3
    assert m["no_answer_correct_empty"] == 0.5 and m["leaks"] == 1 and m["attempted_rate"] == 0.75


def test_paired_bootstrap_is_deterministic_and_sane():
    d = [0.5, 0.25, 0.0, 0.75, 0.5, 0.25]
    a, b = re_.paired_bootstrap(d), re_.paired_bootstrap(d)
    assert a == b and a["ci95"][0] <= a["mean_diff"] <= a["ci95"][1] and re_.paired_bootstrap([0.0] * 5)["ci95"] == [0.0, 0.0]


def _cmp(lo, mrr=0.1):
    return {"recall@3": {"mean_diff": lo + 0.1, "ci95": [lo, lo + 0.2], "n": 15}, "mrr": {"mean_diff": mrr, "ci95": [0, 0], "n": 15}}


def test_verdict_requires_every_condition():
    ok_b = {"no_answer_correct_empty": 0.8, "leaks": 0, "fallbacks": 0}
    ok_c = dict(ok_b)
    assert re_.verdict(_cmp(0.05), ok_b, ok_c, True, "ollama")["hybrid_better_than_bm25_demonstrated"] is True
    cases = [(_cmp(0.05), ok_b, ok_c, False, "ollama"), (_cmp(0.05), ok_b, ok_c, True, "fake"), (_cmp(-0.05), ok_b, ok_c, True, "ollama"),
             (_cmp(0.05, mrr=-0.1), ok_b, ok_c, True, "ollama"), (_cmp(0.05), ok_b, {**ok_c, "no_answer_correct_empty": 0.6}, True, "ollama"),
             (_cmp(0.05), ok_b, {**ok_c, "leaks": 1}, True, "ollama"), (_cmp(0.05), ok_b, {**ok_c, "fallbacks": 2}, True, "ollama")]
    for c in cases:
        v = re_.verdict(*c)
        assert v["hybrid_better_than_bm25_demonstrated"] is False and v["reasons_not_demonstrated"], c


def test_plumbing_run_is_stamped_and_cannot_claim_improvement():
    rep = re_.run("fake", "none", "test")
    assert "PLUMBING ONLY" in rep["WARNING"] and rep["verdict_C_vs_B"]["hybrid_better_than_bm25_demonstrated"] is False
    assert set(rep["retrieval"]) == {"A", "B", "C", "B_direct", "C_direct"} and rep["n_queries"] == 20
    assert all(rep["retrieval"][a]["overall"]["leaks"] == 0 for a in rep["retrieval"])
    md = re_.to_markdown(rep)
    assert "PLUMBING ONLY" in md and "demonstrated: False" in md


def test_arms_share_identical_queries_and_arm_a_matches_current_behaviour(corpora):
    gold = re_.load_gold("all")
    base = get_retrieval_settings()
    a, b = re_.run_arm("A", gold, corpora, re_.HashingEmbedder(), base), re_.run_arm("B", gold, corpora, re_.HashingEmbedder(), base)
    assert [r["id"] for r in a] == [r["id"] for r in b] and sorted(r["id"] for r in a) == sorted(g["id"] for g in gold)
    assert sum(r["attempted"] for r in a) < sum(r["attempted"] for r in b)              # legacy wiring retrieves far less often
    for r in a:
        assert r["query_used"] in (None,) or r["intent"] == "skill_evidence"           # legacy: only the evidence intent retrieves


def test_evaluation_aborts_instead_of_silently_falling_back_when_embeddings_are_unavailable(no_ollama):
    rep = re_.run("ollama", "none", "test")
    assert "aborted" in rep and "per_query" not in rep and "retrieval" not in rep


def test_model_missing_aborts_with_install_command(fake_ollama):
    rep = re_.run("ollama", "none", "test")
    assert "ollama pull nomic-embed-text" in rep["aborted"]


# ---- tuning uses DEV only; the measuring machinery is sensitive (uses the fake Ollama server = plumbing/test double, NOT evidence)
def test_tune_touches_only_dev_and_writes_per_model_file(fake_ollama, tmp_path, monkeypatch):
    fake_ollama.models.append({"name": "nomic-embed-text"})
    f = tmp_path / "tuning.json"
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_TUNING", str(f))
    seen = []
    orig = re_.run_arm
    monkeypatch.setattr(re_, "run_arm", lambda arm, gold, *a, **k: (seen.extend(g["split"] for g in gold), orig(arm, gold, *a, **k))[1])
    from ai import ollama_client
    res = re_.tune(lambda t: ollama_client.embed(t), "ollama")
    assert set(seen) == {"dev"} and res["n_dev_queries"] == 21 and 0.2 <= res["min_similarity"] <= 0.85
    saved = json.load(open(f))["models"]["nomic-embed-text"]
    assert saved["min_similarity"] == res["min_similarity"] and "test" not in json.dumps(saved).lower().replace("tested", "")
    s = get_retrieval_settings()
    assert s.calibrated is True and s.min_similarity == res["min_similarity"]


def test_tune_with_fake_embedder_never_writes(tmp_path, monkeypatch):
    f = tmp_path / "t.json"
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_TUNING", str(f))
    re_.tune(re_.HashingEmbedder(), "fake")
    assert not f.exists()


def test_measurement_registers_direction_but_is_strict_about_claiming_improvement(fake_ollama):
    """Sensitivity check of the MACHINERY using the concept-lexicon test double through the real HTTP client.
    Not evidence about nomic-embed-text. It shows two things: a gain in the right direction is registered, AND with only
    ~15 answerable held-out queries the paired 95% CI still spans zero, so the verdict rule refuses to claim hybrid is better.
    (That strictness is intended; it also means the gold set is underpowered for modest gains.)"""
    fake_ollama.models.append({"name": "nomic-embed-text"})
    rep = re_.run("ollama", "none", "test", min_sim=0.3)
    c = rep["paired_differences"]["C_minus_B (semantic retriever effect)"]
    assert rep["retrieval"]["C"]["overall"]["fallbacks"] == 0 and rep["retrieval"]["C"]["overall"]["leaks"] == 0
    assert c["recall@3"]["mean_diff"] > 0 and c["recall@3"]["n"] == 15
    assert rep["retrieval"]["C"]["overall"]["latency_ms_with_index_build"]["n"] >= 1
    v = rep["verdict_C_vs_B"]
    if c["recall@3"]["ci95"][0] <= 0:
        assert v["hybrid_better_than_bm25_demonstrated"] is False and any("not statistically clear" in r for r in v["reasons_not_demonstrated"])
