"""Research evaluation harness.

Compares three systems on a FIXED set of questions (eval/cases.json) over a synthetic fixture database:
  A  existing CareerDNA outputs rendered as text, no LLM
  B  a local LLM given the profile as plain context, with no backend tools and no verification
  C  the full system: router -> validated backend tools -> grounded prompt -> local LLM -> deterministic verification
Every metric is computed from real runs. With --llm mock the harness only tests its own plumbing and the report is
stamped 'SELF-TEST ONLY'. Only --llm ollama produces measurements of a real model.

Run:  python -m ai.evaluation --llm ollama --out eval_results
"""
import argparse
import json
import os
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime

from . import ollama_client, router, scoring, verifier
from .agent import CareerAgent, build_facts
from .config import get_settings
from .db import BASE_DIR, connect
from .eval_fixture import build_fixture_db
from .ollama_client import OllamaError
from .tools import ToolContext, call_tool

EVAL_DIR = os.path.join(BASE_DIR, "eval")
NUM = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)")
HEDGE = verifier.HEDGE
SYSTEM_B = "You are a helpful career assistant. Answer the user's question about their career using the profile information provided."


# ------------------------------------------------------------------ verifier benchmark
def _bench_facts(ctx, kind):
    if kind == "scenario":
        calls = [("simulate_profile_change", {"add_skills": ["PyTorch"]})]
    else:
        calls = [("calculate_job_match", {}), ("get_skill_gaps", {"role": "ML Engineer"}), ("predict_salary", {}),
                 ("get_skill_evidence", {"skill": "Python"})]
    return build_facts(ctx, [call_tool(ctx, n, a) for n, a in calls], "")


def verifier_benchmark(path: str | None = None) -> dict:
    """Measures the deterministic verifier itself on hand-labelled answers (no LLM involved)."""
    data = json.load(open(path or os.path.join(EVAL_DIR, "verifier_benchmark.json"), encoding="utf-8"))["cases"]
    tmp = os.path.join(tempfile.mkdtemp(), "bench.db")
    build_fixture_db(tmp)
    old = os.environ.get("CAREERDNA_DB")
    os.environ["CAREERDNA_DB"] = tmp
    try:
        conn = connect()
        ctx = ToolContext(conn, 1)
        fcache = {k: _bench_facts(ctx, k) for k in ("base", "scenario")}
        tp = fn = fp = tn = exact = 0
        misses, false_pos = [], []
        for c in data:
            f = fcache[c["facts"]]
            f = type(f)(**{**f.__dict__, "user_numbers": c.get("user_numbers", [])})
            got = {i.code for i in verifier.verify(c["answer"], f)}
            exp = set(c["expect"])
            if exp:
                if got & exp:
                    tp += 1
                else:
                    fn += 1; misses.append({"id": c["id"], "expected": sorted(exp), "got": sorted(got), "known_limitation": bool(c.get("known_limitation"))})
            else:
                if got:
                    fp += 1; false_pos.append({"id": c["id"], "got": sorted(got)})
                else:
                    tn += 1
            exact += int(got == exp)
        conn.close()
    finally:
        if old is None:
            os.environ.pop("CAREERDNA_DB", None)
        else:
            os.environ["CAREERDNA_DB"] = old
    faulty, clean = tp + fn, fp + tn
    known = sum(1 for m in misses if m["known_limitation"])
    kl_total = sum(1 for c in data if c.get("known_limitation"))
    return {"cases": len(data), "faulty_answers": faulty, "clean_answers": clean, "true_positives": tp, "false_negatives": fn,
            "false_positives": fp, "true_negatives": tn, "recall": round(tp / faulty, 3) if faulty else None,
            "recall_excluding_documented_limitations": round(tp / (faulty - kl_total), 3) if faulty - kl_total else None,
            "documented_limitation_cases": kl_total,
            "false_positive_rate": round(fp / clean, 3) if clean else None, "exact_code_match": round(exact / len(data), 3),
            "missed": misses, "false_positive_cases": false_pos}


# ------------------------------------------------------------------ systems
def profile_dump(ctx) -> str:
    p = ctx.profile
    lines = [f"Candidate: {p['name']}. Goals: {p['goals']}", "Skills: " + "; ".join(f"{s['skill_name']} ({s['proficiency']}, {s['years']} years, evidence score {s['evidence_score']})" for s in p["skills"])]
    lines += [f"Project: {x['title']} - {x['description']} Skills: {', '.join(ctx.catalog['by_id'][i]['skill_name'] for i in x['skill_ids'])}" for x in p["projects"]]
    lines += [f"Certification: {c['name']} ({c['issuer']})" for c in p["certifications"]]
    for j in ctx.jobs:
        lines.append(f"Job: {j['role']} at {j['company']} requires " + ", ".join(f"{r['skill_name']} ({r['required_level']}, importance {r['importance']})" for r in j["requirements"]))
    return "\n".join(lines)


def system_a(ctx, question, plan):
    """Existing CareerDNA: only match, gap and salary outputs exist; nothing can explain evidence, compare, plan or simulate."""
    t = time.perf_counter()
    if plan["intent"] in ("match_explain", "skill_gaps", "overview"):
        have = ctx.have_ids()
        jobs = [j for j in ctx.jobs if not plan["roles"] or j["role"] in plan["roles"]]
        lines = []
        for j in jobs:
            m = scoring.compute_match(j["requirements"], have)
            lines.append(f"{j['role']}: {m['match_percent']}% match; missing: {', '.join(x['name'] for x in m['missing']) or 'none'}")
        return {"supported": True, "answer": "\n".join(lines), "latency_ms": int((time.perf_counter() - t) * 1000)}
    if plan["intent"] == "salary":
        s = scoring.estimate_salary(ctx.conn, ctx.candidate_id)
        return {"supported": True, "answer": f"Predicted salary: {s['predicted_salary_lpa']} LPA", "latency_ms": int((time.perf_counter() - t) * 1000)}
    return {"supported": False, "answer": "", "latency_ms": 0}


def system_b(ctx, question, llm_chat, settings):
    t = time.perf_counter()
    try:
        out = llm_chat([{"role": "system", "content": SYSTEM_B}, {"role": "user", "content": profile_dump(ctx) + "\n\nQuestion: " + question}], settings)
        return {"supported": True, "answer": out["content"], "latency_ms": int((time.perf_counter() - t) * 1000)}
    except OllamaError as e:
        return {"supported": True, "answer": "", "error": e.code, "latency_ms": int((time.perf_counter() - t) * 1000)}


# ------------------------------------------------------------------ per-answer checks
def analyse(case, answer, facts, extra_text=""):
    exp = case["expected"]
    text = answer or ""
    issues = verifier.verify(text, facts) if text else []
    nums = [float(x) for x in NUM.findall(text)]
    near = lambda e: any(abs(n - e) <= 0.051 for n in nums)
    r = {"empty": not text.strip(), "issue_codes": sorted({i.code for i in issues}), "n_issues": len(issues)}
    if "percents" in exp or "lpa" in exp:
        want = exp.get("percents", []) + exp.get("lpa", [])
        r["numbers_present"] = all(near(e) for e in want)
        r["numbers_correct"] = r["numbers_present"] and "unsupported_number" not in r["issue_codes"]
    if "mention_any" in exp:
        r["mentions_expected"] = any(m.lower() in text.lower() for m in exp["mention_any"])
    if "refs_any" in exp:
        r["cites_expected_ref"] = any(f"[{x}]" in text for x in exp["refs_any"])
    if "missing_evidence_skill" in exp:
        r["missing_evidence_ok"] = bool(text) and "missing_evidence_as_inability" not in r["issue_codes"] and "claimed_skill_not_in_profile" not in r["issue_codes"] and bool(HEDGE.search(text))
    if "not_documented" in exp:
        r["missing_evidence_ok"] = bool(text) and not re.search(r"\bdocumented\b(?! )|is documented|supported by (a )?project", text.lower()) and bool(re.search(r"no project|not linked|self-reported|no certification|only listed|listed in your profile", text.lower()))
    if "contradictory_skill" in exp:
        r["missing_evidence_ok"] = bool(text) and bool(re.search(r"disagree|contradict|12", text.lower()))
    if exp.get("hypothetical"):
        r["labelled_hypothetical"] = bool(verifier.HYP_WORDS.search(text))
    if exp.get("no_guarantee"):
        r["no_guarantee"] = not verifier.GUARANTEE.search(text)
    if exp.get("no_numeric_improvement"):
        r["no_numeric_improvement"] = not re.search(r"\b(increase|rise|improve|raise)[sd]?\b[^.]*\d", text.lower())
    if "forbidden_text" in exp:
        r["isolation_ok"] = not any(f.lower() in (text + extra_text).lower() for f in exp["forbidden_text"])
    return r


def _mock_llm(messages, settings=None, json_mode=False):
    """Plumbing-only stand-in. NOT a language model: it echoes the first backend FACTS lines (or a generic reply if there are none)."""
    user = messages[-1]["content"]
    if "FACTS" in user:
        facts = user.split("FACTS", 1)[1].split("\n", 1)[1].split("Answer the question")[0].strip().splitlines()
        body = " ".join(l.lstrip("- ").strip() for l in facts[:4])
        return {"content": body or "No facts.", "model": "mock", "eval_count": 0}
    return {"content": "Based on the profile you have a strong background and should keep learning.", "model": "mock", "eval_count": 0}


def _rate(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(1 for v in vals if v) / len(vals), 3) if vals else None


def _lat(xs):
    xs = sorted(x for x in xs if x)
    return {"median_ms": int(statistics.median(xs)), "p95_ms": xs[min(len(xs) - 1, int(0.95 * len(xs)))], "n": len(xs)} if xs else None


def summarise(per_case):
    allr = [x for x in per_case if x["supported"]]
    keys = ["numbers_correct", "mentions_expected", "cites_expected_ref", "missing_evidence_ok", "labelled_hypothetical", "no_guarantee", "no_numeric_improvement", "isolation_ok"]
    out = {"cases": len(per_case), "answered": len(allr), "coverage": round(len(allr) / len(per_case), 3) if per_case else None,
           "factual_consistency": _rate([x["checks"]["n_issues"] == 0 and not x["checks"]["empty"] for x in allr]),
           "answers_with_unsupported_claims": _rate([x["checks"]["n_issues"] > 0 for x in allr]),
           "unsupported_claims_per_answer": round(sum(x["checks"]["n_issues"] for x in allr) / len(allr), 3) if allr else None,
           "latency": _lat([x["latency_ms"] for x in allr])}
    for k in keys:
        out[k] = _rate([x["checks"].get(k) for x in allr])
    return out


# ------------------------------------------------------------------ main runner
def run_evaluation(llm: str = "mock", cases_path: str | None = None, repeat: int = 1, only: list[str] | None = None) -> dict:
    cases = json.load(open(cases_path or os.path.join(EVAL_DIR, "cases.json"), encoding="utf-8"))["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    tmp = os.path.join(tempfile.mkdtemp(), "eval.db")
    build_fixture_db(tmp)
    old = os.environ.get("CAREERDNA_DB")
    os.environ["CAREERDNA_DB"] = tmp
    report = {"generated_at": datetime.now().isoformat(timespec="seconds"), "llm_mode": llm, "fixture": "ai/eval_fixture.py (synthetic, 3 users)",
              "cases_file": "eval/cases.json", "n_cases": len(cases), "repeat": repeat}
    try:
        settings = get_settings()
        report["model"] = settings.model if llm == "ollama" else "mock (not a language model)"
        if llm == "ollama":
            st = ollama_client.get_status(settings)
            report["ollama_status"] = {k: st.get(k) for k in ("reachable", "model_installed", "ready", "model_size_bytes", "model_digest", "error")}
            if not st["ready"]:
                report["aborted"] = "Ollama/model not ready: " + json.dumps(st["error"])
                return report
            llm_chat = ollama_client.chat
        else:
            report["WARNING"] = "MOCK LLM - SELF-TEST ONLY. These numbers verify the harness, NOT the behaviour of any language model."
            llm_chat = _mock_llm
        conn = connect()
        per = {"A": [], "B": [], "C": []}
        for _ in range(repeat):
            for case in cases:
                ctx = ToolContext(conn, case.get("user", 1))
                plan = router.plan(case["question"], ctx.jobs, ctx.catalog)
                truth = [call_tool(ctx, c["name"], c["args"]) for c in plan["calls"]]
                truth_ok = [t for t in truth if t.get("ok")]
                facts = build_facts(ctx, truth_ok, case["question"]) if truth_ok else build_facts(ctx, [], case["question"])
                row_base = {"case": case["id"], "category": case["category"], "intent_ok": plan["intent"] == case["expected"].get("intent", plan["intent"])}
                a = system_a(ctx, case["question"], plan)
                per["A"].append({**row_base, **a, "checks": analyse(case, a["answer"], facts)})
                b = system_b(ctx, case["question"], llm_chat, settings)
                per["B"].append({**row_base, **b, "checks": analyse(case, b["answer"], facts)})
                c = CareerAgent(conn, case.get("user", 1), settings, llm_chat).run(case["question"], None, test_case_id=case["id"])
                ans = c.get("answer") or c.get("fallback_summary") or ""
                row = {**row_base, "supported": True, "answer": ans, "latency_ms": c.get("latency_ms"), "error": (c.get("error") or {}).get("code"),
                       "verification_status": c.get("verification", {}).get("status"), "regenerated": c.get("verification", {}).get("regenerated"),
                       "evidence_panel_refs": [e["ref"] for e in c.get("evidence", [])]}
                row["checks"] = analyse(case, ans if c.get("ok") else "", facts, extra_text=" ".join(" ".join(f["lines"]) for f in c.get("facts", [])))
                per["C"].append(row)
        conn.close()
        report["systems"] = {k: summarise(v) for k, v in per.items()}
        report["systems"]["C"]["intent_routing_accuracy"] = _rate([r["intent_ok"] for r in per["C"]])
        report["systems"]["C"]["verification_outcomes"] = {s: sum(1 for r in per["C"] if r.get("verification_status") == s) for s in {r.get("verification_status") for r in per["C"]}}
        report["system_descriptions"] = {"A": "existing CareerDNA outputs, no LLM", "B": "local LLM + profile text, no tools, no verification (verified offline for measurement only)",
                                         "C": "router + backend tools + grounded prompt + local LLM + deterministic verification"}
        report["verifier_benchmark"] = verifier_benchmark()
        report["resources"] = _resources(settings) if llm == "ollama" else {"note": "not measured in mock mode"}
        report["per_case"] = per
    finally:
        if old is None:
            os.environ.pop("CAREERDNA_DB", None)
        else:
            os.environ["CAREERDNA_DB"] = old
    return report


def _resources(settings) -> dict:
    out = {"configured_model": settings.model}
    try:
        _, tags = ollama_client.http_request("GET", f"{settings.base_url}/api/tags", timeout=5)
        for m in tags.get("models", []):
            if m.get("name") == settings.model:
                out["model_disk_bytes"] = m.get("size")
        _, ps = ollama_client.http_request("GET", f"{settings.base_url}/api/ps", timeout=5)
        for m in ps.get("models", []):
            if m.get("name") == settings.model:
                out["loaded_size_bytes"] = m.get("size"); out["loaded_vram_bytes"] = m.get("size_vram")
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


def to_markdown(r: dict) -> str:
    lines = [f"# CareerDNA evaluation - {r['llm_mode']} - {r['generated_at']}", ""]
    if r.get("WARNING"):
        lines += [f"> **{r['WARNING']}**", ""]
    if r.get("aborted"):
        return "\n".join(lines + [f"**Aborted:** {r['aborted']}"])
    lines += [f"Model: `{r['model']}`  |  cases: {r['n_cases']} x {r['repeat']}  |  fixture: {r['fixture']}", "",
              "| Metric | A existing | B raw LLM | C full system |", "|---|---|---|---|"]
    s = r["systems"]
    for k in ["coverage", "factual_consistency", "answers_with_unsupported_claims", "unsupported_claims_per_answer", "numbers_correct", "mentions_expected",
              "cites_expected_ref", "missing_evidence_ok", "labelled_hypothetical", "no_guarantee", "no_numeric_improvement", "isolation_ok"]:
        lines.append(f"| {k} | " + " | ".join(str(s[x].get(k)) for x in "ABC") + " |")
    lines.append("| latency median / p95 ms | " + " | ".join((f"{s[x]['latency']['median_ms']} / {s[x]['latency']['p95_ms']}" if s[x]["latency"] else "n/a") for x in "ABC") + " |")
    vb = r["verifier_benchmark"]
    lines += ["", f"Intent routing accuracy (C): {s['C'].get('intent_routing_accuracy')}   Verification outcomes (C): {s['C'].get('verification_outcomes')}", "",
              f"Verifier benchmark ({vb['cases']} hand-labelled answers): recall {vb['recall']} (excluding {vb['documented_limitation_cases']} documented-limitation cases: {vb['recall_excluding_documented_limitations']}), false-positive rate {vb['false_positive_rate']}, exact code match {vb['exact_code_match']}. "
              f"Missed: {[m['id'] for m in vb['missed']]}", "", f"Resources: {r.get('resources')}"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="CareerDNA AI evaluation")
    ap.add_argument("--llm", choices=["ollama", "mock"], default="ollama")
    ap.add_argument("--out", default=os.path.join(BASE_DIR, "eval_results"))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args(argv)
    rep = run_evaluation(a.llm, repeat=a.repeat, only=a.only)
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.join(a.out, f"{datetime.now():%Y%m%d_%H%M%S}_{a.llm}")
    json.dump(rep, open(stem + ".json", "w", encoding="utf-8"), indent=1)
    md = to_markdown(rep)
    open(stem + ".md", "w", encoding="utf-8").write(md)
    print(md)
    print("\nSaved:", stem + ".json /.md")
    return 0 if not rep.get("aborted") else 2


if __name__ == "__main__":
    sys.exit(main())
