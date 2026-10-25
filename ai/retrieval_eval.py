"""A/B/C retrieval evaluation. Same gold queries and same corpora for every arm.

  A  BM25, current ('legacy') wiring          - query = skill names, only for the evidence intent
  B  BM25, 'improved' wiring                  - query = the whole question, more intents retrieve
  C  Hybrid (BM25 + local embeddings + RRF)   - same wiring as B
  (diagnostic) B_direct / C_direct            - router bypassed: isolates the retriever itself

  A vs B isolates the effect of the wiring. B vs C isolates the semantic retriever.
Data are SYNTHETIC and the queries were written by the system's developer: treat results as indicative, not general.
Commands:
  python -m ai.retrieval_eval run  --embedder ollama [--llm ollama|mock|none] [--split test]
  python -m ai.retrieval_eval tune --embedder ollama            # picks threshold/weights on the DEV split only
"""
import argparse
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime

from . import evaluation, ollama_client, rag, retrieval, router
from .agent import CareerAgent, build_facts
from .config import get_retrieval_settings, tuning_path
from .db import BASE_DIR, connect
from .eval_fixture import build_fixture_db
from .eval_fixture_rich import build_rich_fixture_db
from .tools import ToolContext, call_tool

EVAL_DIR = os.path.join(BASE_DIR, "eval")
TYPES = {"project", "experience", "certification", "profile"}
ARMS = {"A": {"mode": "bm25", "wiring": "legacy", "direct": False, "label": "A: BM25, current wiring"},
        "B": {"mode": "bm25", "wiring": "improved", "direct": False, "label": "B: BM25, improved query + wiring"},
        "C": {"mode": "hybrid", "wiring": "improved", "direct": False, "label": "C: Hybrid, improved query + wiring"},
        "B_direct": {"mode": "bm25", "wiring": "improved", "direct": True, "label": "B_direct: BM25, router bypassed"},
        "C_direct": {"mode": "hybrid", "wiring": "improved", "direct": True, "label": "C_direct: Hybrid, router bypassed"}}


# ------------------------------------------------------------------ plumbing-only embedder
class HashingEmbedder:
    """NOT semantic. Hashes words and character trigrams into a fixed vector so the pipeline can be run without a model.
    Any report produced with it is stamped PLUMBING ONLY."""

    def __init__(self, dim=256):
        self.dim = dim

    def __call__(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            low = t.lower()
            grams = re.findall(r"[a-z0-9]+", low) + [low[i:i + 3] for i in range(len(low) - 2)]
            for g in grams:
                v[int(hashlib.md5(g.encode()).hexdigest(), 16) % self.dim] += 1.0
            out.append(v if any(v) else [1.0] + [0.0] * (self.dim - 1))
        return out


class Memo:
    """Caches single-query embeddings so tuning does not re-embed the same question for every grid point."""

    def __init__(self, fn):
        self.fn, self.cache = fn, {}

    def __call__(self, texts):
        if len(texts) == 1:
            if texts[0] not in self.cache:
                self.cache[texts[0]] = self.fn(texts)[0]
            return [self.cache[texts[0]]]
        return self.fn(texts)


# ------------------------------------------------------------------ corpora & gold
def load_gold(split="test"):
    q = json.load(open(os.path.join(EVAL_DIR, "retrieval_gold.json"), encoding="utf-8"))["queries"]
    return [x for x in q if split == "all" or x["split"] == split]


@contextmanager
def db_env(path):
    old = os.environ.get("CAREERDNA_DB")
    os.environ["CAREERDNA_DB"] = path
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("CAREERDNA_DB", None)
        else:
            os.environ["CAREERDNA_DB"] = old


def make_corpora():
    d = tempfile.mkdtemp()
    return {"small": build_fixture_db(os.path.join(d, "small.db")), "rich": build_rich_fixture_db(os.path.join(d, "rich.db"))}


def foreign_refs(conn, candidate_id):
    refs = set()
    for table, col, key in (("project", "project_id", "project"), ("experience", "experience_id", "experience")):
        refs |= {f"{key}:{r[0]}" for r in conn.execute(f"SELECT {col} FROM {table} WHERE candidate_id <> ?", (candidate_id,))}
    refs |= {f"certification:{r[0]}" for r in conn.execute("SELECT certification_id FROM candidate_certification WHERE candidate_id <> ?", (candidate_id,))}
    return refs - {f"project:{r[0]}" for r in conn.execute("SELECT project_id FROM project WHERE candidate_id = ?", (candidate_id,))} \
        - {f"certification:{r[0]}" for r in conn.execute("SELECT certification_id FROM candidate_certification WHERE candidate_id = ?", (candidate_id,))}


# ------------------------------------------------------------------ one arm over the gold set
def settings_for(arm, st):
    return replace(st, mode=arm["mode"], wiring=arm["wiring"])


def run_arm(arm_key, gold, dbs, embed_fn, base_settings, k=5, clear_cache=True):
    arm, rows = ARMS[arm_key], []
    for corpus in sorted({g["corpus"] for g in gold}):
        with db_env(dbs[corpus]):
            conn = connect()
            if clear_cache and conn.execute("SELECT 1 FROM sqlite_master WHERE name='ai_embedding'").fetchone():
                conn.execute("DELETE FROM ai_embedding")      # cold start, so the first query per user includes index-build time
                conn.commit()
            seen_users = set()
            for g in [x for x in gold if x["corpus"] == corpus]:
                ctx = ToolContext(conn, g["user"])
                docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
                own = {d["ref"]: d["text"] for d in docs}
                plan = router.plan(g["question"], ctx.jobs, ctx.catalog, wiring=arm["wiring"])
                query = g["question"] if arm["direct"] else plan["retrieval_query"]
                row = {"id": g["id"], "corpus": corpus, "category": g["category"], "split": g["split"], "relevant": g["relevant"], "intent": plan["intent"],
                       "query_used": query, "attempted": bool(query), "retrieved": [], "leak": False, "diag": None, "ms": None, "first_for_user": g["user"] not in seen_users}
                seen_users.add(g["user"])
                if query:
                    res = retrieval.retrieve(conn, ctx.candidate_id, query, docs, k=k, types=TYPES, settings=settings_for(arm, base_settings), embed_fn=embed_fn)
                    row["retrieved"] = [h["ref"] for h in res["hits"]]
                    row["sources"] = {h["ref"]: h["sources"] for h in res["hits"]}
                    d = res["diagnostics"]
                    row["diag"] = {x: d[x] for x in ("requested_mode", "effective_mode", "fallback", "fallback_reason", "embedded_now", "cached", "empty")}
                    row["ms"] = d["timings_ms"]["total"]
                    bad = foreign_refs(conn, ctx.candidate_id)
                    row["leak"] = any(h["ref"] in bad or (h["ref"] in own and h["text"] != own[h["ref"]]) or h["ref"] not in own for h in res["hits"])
                rows.append(row)
            conn.close()
    return rows


# ------------------------------------------------------------------ metrics
def recall_at(r, k):
    return len(set(r["retrieved"][:k]) & set(r["relevant"])) / len(r["relevant"])


def rr(r):
    for i, ref in enumerate(r["retrieved"], 1):
        if ref in r["relevant"]:
            return 1.0 / i
    return 0.0


def mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * len(xs)))], 2) if xs else None


def metrics(rows):
    ans = [r for r in rows if r["relevant"]]
    noa = [r for r in rows if not r["relevant"]]
    cold = [r["ms"] for r in rows if r["ms"] is not None and r["diag"] and r["diag"]["embedded_now"] > 0]
    warm = [r["ms"] for r in rows if r["ms"] is not None and not (r["diag"] and r["diag"]["embedded_now"] > 0)]
    return {"n": len(rows), "n_answerable": len(ans), "n_no_answer": len(noa), "attempted_rate": mean([1.0 if r["attempted"] else 0.0 for r in rows]),
            "recall@1": mean([recall_at(r, 1) for r in ans]), "recall@3": mean([recall_at(r, 3) for r in ans]), "recall@5": mean([recall_at(r, 5) for r in ans]),
            "mrr": mean([rr(r) for r in ans]), "no_answer_correct_empty": mean([1.0 if not r["retrieved"] else 0.0 for r in noa]),
            "avg_results_for_no_answer": mean([len(r["retrieved"]) for r in noa]), "leaks": sum(1 for r in rows if r["leak"]),
            "fallbacks": sum(1 for r in rows if r["diag"] and r["diag"]["fallback"]),
            "latency_ms_warm": {"median": pct(warm, 0.5), "p95": pct(warm, 0.95), "n": len(warm)},
            "latency_ms_with_index_build": {"median": pct(cold, 0.5), "p95": pct(cold, 0.95), "n": len(cold)}}


def by_category(rows):
    return {c: metrics([r for r in rows if r["category"] == c]) for c in sorted({r["category"] for r in rows})}


def paired_bootstrap(diffs, n=2000, seed=0):
    if not diffs:
        return None
    rng, m = random.Random(seed), len(diffs)
    means = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return {"mean_diff": round(sum(diffs) / m, 3), "ci95": [round(means[int(0.025 * n)], 3), round(means[int(0.975 * n) - 1], 3)], "n": m}


def compare(rows_x, rows_y):
    """y minus x on identical queries (paired)."""
    kx, ky = {r["id"]: r for r in rows_x}, {r["id"]: r for r in rows_y}
    ids = [i for i in kx if i in ky and kx[i]["relevant"]]
    noa = [i for i in kx if i in ky and not kx[i]["relevant"]]
    return {"recall@3": paired_bootstrap([recall_at(ky[i], 3) - recall_at(kx[i], 3) for i in ids]),
            "recall@1": paired_bootstrap([recall_at(ky[i], 1) - recall_at(kx[i], 1) for i in ids]),
            "mrr": paired_bootstrap([rr(ky[i]) - rr(kx[i]) for i in ids]),
            "no_answer": {"y_right_x_wrong": sum(1 for i in noa if not ky[i]["retrieved"] and kx[i]["retrieved"]),
                          "x_right_y_wrong": sum(1 for i in noa if ky[i]["retrieved"] and not kx[i]["retrieved"]), "n": len(noa)}}


def verdict(cmp_bc, m_b, m_c, calibrated, embedder):
    """Documented rule. 'Hybrid better' is only stated when ALL conditions hold on the held-out split."""
    reasons = []
    r3 = (cmp_bc["recall@3"] or {})
    if embedder != "ollama":
        reasons.append("embedder was not a real model (plumbing run)")
    if not calibrated:
        reasons.append("similarity threshold is an uncalibrated placeholder; run `tune` first")
    if not r3 or r3["ci95"][0] <= 0:
        reasons.append(f"recall@3 improvement not statistically clear (paired 95% CI {r3.get('ci95') if r3 else None})")
    if (cmp_bc["mrr"] or {}).get("mean_diff", 0) < 0:
        reasons.append("MRR is lower for hybrid")
    if (m_c["no_answer_correct_empty"] or 0) < (m_b["no_answer_correct_empty"] or 0):
        reasons.append("hybrid returns results for more no-answer queries than BM25")
    if m_c["leaks"] or m_b["leaks"]:
        reasons.append("candidate-isolation leaks detected")
    if m_c["fallbacks"]:
        reasons.append(f"{m_c['fallbacks']} hybrid queries fell back to BM25, so C is not a clean hybrid measurement")
    return {"hybrid_better_than_bm25_demonstrated": not reasons, "reasons_not_demonstrated": reasons,
            "rule": "all of: real embedder; calibrated threshold; paired-bootstrap 95% CI for recall@3 difference (C-B) above 0; MRR not lower; no-answer correct-empty rate not lower; zero leaks; zero fallbacks"}


# ------------------------------------------------------------------ answer level (identical cases for every arm)
def answer_level(arm_key, dbs, llm, embed_fn):
    arm = ARMS[arm_key]
    cases = [("small", c) for c in json.load(open(os.path.join(EVAL_DIR, "cases.json")))["cases"]] + \
            [("rich", c) for c in json.load(open(os.path.join(EVAL_DIR, "cases_rich.json")))["cases"]]
    saved = {k: os.environ.get(k) for k in ("CAREERDNA_RETRIEVAL_MODE", "CAREERDNA_RETRIEVAL_WIRING")}
    os.environ["CAREERDNA_RETRIEVAL_MODE"], os.environ["CAREERDNA_RETRIEVAL_WIRING"] = arm["mode"], arm["wiring"]
    rows = []
    try:
        for corpus, case in cases:
            with db_env(dbs[corpus]):
                conn = connect()
                ctx = ToolContext(conn, case.get("user", 1))
                plan = router.plan(case["question"], ctx.jobs, ctx.catalog, wiring=arm["wiring"])
                truth = [t for t in (call_tool(ctx, c["name"], c["args"]) for c in plan["calls"] if c["name"] != "retrieve_context") if t.get("ok")]
                facts = build_facts(ctx, truth, case["question"])
                t0 = time.perf_counter()
                out = CareerAgent(conn, case.get("user", 1), llm_chat=llm, embed_fn=embed_fn).run(case["question"], None, test_case_id=f"{arm_key}:{case['id']}")
                ans = out.get("answer") or ""
                v = out.get("verification", {})
                checks = evaluation.analyse(case, ans if out.get("ok") else "", facts)
                rd = (out.get("retrieval") or [None])[0]
                rows.append({"case": case["id"], "corpus": corpus, "supported": True, "latency_ms": out.get("latency_ms") or int((time.perf_counter() - t0) * 1000), "checks": checks,
                             "first_draft_issues": len(v.get("first_draft_issue_codes", [])), "regenerated": bool(v.get("regenerated")), "status": v.get("status"),
                             "retrieval_attempted": rd is not None, "retrieval_fallback": bool(rd and rd["fallback"]), "ok": out.get("ok")})
                conn.close()
    finally:
        for k, val in saved.items():
            os.environ.pop(k, None) if val is None else os.environ.__setitem__(k, val)
    s = evaluation.summarise(rows)
    s.update({"first_draft_unsupported_claims_per_answer": mean([r["first_draft_issues"] for r in rows]),
              "answers_with_first_draft_issues": mean([1.0 if r["first_draft_issues"] else 0.0 for r in rows]),
              "regeneration_rate": mean([1.0 if r["regenerated"] else 0.0 for r in rows]),
              "retrieval_attempted_rate": mean([1.0 if r["retrieval_attempted"] else 0.0 for r in rows]),
              "retrieval_fallbacks": sum(1 for r in rows if r["retrieval_fallback"]),
              "llm_errors": sum(1 for r in rows if not r["ok"])})
    return s, rows


# ------------------------------------------------------------------ tuning (DEV split only)
def tune(embed_fn, embedder_name, write=True):
    gold = load_gold("dev")
    assert all(g["split"] == "dev" for g in gold)            # the test split is never touched while tuning
    dbs, memo = make_corpora(), Memo(embed_fn)
    base = get_retrieval_settings()
    best = None
    for w_sem in (0.5, 1.0, 2.0):
        for sim in [round(0.20 + 0.05 * i, 2) for i in range(0, 14)]:
            st = replace(base, min_similarity=sim, w_sem=w_sem, w_bm25=1.0, calibrated=True)
            m = metrics(run_arm("C_direct", gold, dbs, memo, st, clear_cache=False))
            obj = round(0.5 * (m["recall@3"] or 0) + 0.25 * (m["mrr"] or 0) + 0.25 * (m["no_answer_correct_empty"] or 0), 4)
            cand = {"min_similarity": sim, "w_bm25": 1.0, "w_sem": w_sem, "dev_objective": obj, "dev_recall@3": m["recall@3"], "dev_mrr": m["mrr"], "dev_no_answer_correct_empty": m["no_answer_correct_empty"], "dev_fallbacks": m["fallbacks"]}
            if m["fallbacks"] == 0 and (best is None or obj > best["dev_objective"] or (obj == best["dev_objective"] and sim > best["min_similarity"])):
                best = cand
    result = {**(best or {}), "n_dev_queries": len(gold), "objective": "0.5*recall@3 + 0.25*MRR + 0.25*no-answer-correct-empty on the DEV split (direct retriever)",
              "embedder": embedder_name, "tuned_at": datetime.now().isoformat(timespec="seconds")}
    if write and embedder_name == "ollama" and best:
        path = tuning_path()
        data = json.load(open(path)) if os.path.exists(path) else {"models": {}}
        data["models"][base.embed_model] = result
        json.dump(data, open(path, "w"), indent=1)
        result["written_to"] = path
    return result


# ------------------------------------------------------------------ driver
def run(embedder="fake", llm="none", split="test", min_sim=None):
    embed_fn = (lambda texts: ollama_client.embed(texts)) if embedder == "ollama" else HashingEmbedder()
    base = get_retrieval_settings()
    if min_sim is not None:
        base = replace(base, min_similarity=min_sim, calibrated=True)
    rep = {"generated_at": datetime.now().isoformat(timespec="seconds"), "data": "SYNTHETIC (ai/eval_fixture.py + ai/eval_fixture_rich.py)", "split": split,
           "embedder": embedder, "embed_model": base.embed_model if embedder == "ollama" else "hashing (NOT semantic)", "calibrated": base.calibrated,
           "min_similarity": base.min_similarity, "rrf": {"k": base.rrf_k, "w_bm25": base.w_bm25, "w_sem": base.w_sem}}
    if embedder != "ollama":
        rep["WARNING"] = "PLUMBING ONLY - the embedder is a hashing stand-in, not a language model. These numbers say nothing about nomic-embed-text."
    if embedder == "ollama":
        st = ollama_client.get_status()
        es = ollama_client.embed_model_status(st, base.embed_model)
        if not es["ready"]:
            rep["aborted"] = f"Embedding model not ready: {es['error']['message']} {es['error']['instructions']}"
            return rep
        try:
            ollama_client.embed(["probe"])
        except Exception as e:  # noqa: BLE001
            rep["aborted"] = f"Embedding probe failed: {e}"
            return rep
    gold, dbs = load_gold(split), make_corpora()
    rep["n_queries"] = len(gold)
    rows = {a: run_arm(a, gold, dbs, embed_fn, base) for a in ARMS}
    rep["retrieval"] = {a: {"label": ARMS[a]["label"], "overall": metrics(r), "by_category": by_category(r)} for a, r in rows.items()}
    rep["paired_differences"] = {"B_minus_A (wiring effect)": compare(rows["A"], rows["B"]), "C_minus_B (semantic retriever effect)": compare(rows["B"], rows["C"]),
                                 "C_direct_minus_B_direct (retriever only)": compare(rows["B_direct"], rows["C_direct"])}
    rep["verdict_C_vs_B"] = verdict(compare(rows["B"], rows["C"]), rep["retrieval"]["B"]["overall"], rep["retrieval"]["C"]["overall"], base.calibrated, embedder)
    rep["per_query"] = rows
    if llm != "none":
        llm_chat = ollama_client.chat if llm == "ollama" else evaluation._mock_llm
        rep["answer_level"] = {"llm": llm if llm == "ollama" else "mock (NOT a language model)", "arms": {}}
        if llm == "mock":
            rep["answer_level"]["WARNING"] = "MOCK LLM - harness self-test only."
        rep["answer_level_rows"] = {}
        for a in ("A", "B", "C"):
            s, r = answer_level(a, dbs, llm_chat, embed_fn)
            rep["answer_level"]["arms"][a] = s
            rep["answer_level_rows"][a] = r
    return rep


def to_markdown(r):
    L = [f"# Retrieval evaluation - {r['generated_at']}", f"Data: {r['data']}  |  split: {r['split']}  |  embedder: {r['embedder']} ({r['embed_model']})  |  calibrated threshold: {r['calibrated']} (min_similarity {r['min_similarity']})"]
    if r.get("WARNING"):
        L += ["", f"> **{r['WARNING']}**"]
    if r.get("aborted"):
        return "\n".join(L + ["", f"**Aborted:** {r['aborted']}"])
    n_ans = r["retrieval"]["C"]["overall"]["n_answerable"]
    L += ["", f"{r['n_queries']} gold queries, of which {n_ans} answerable. With samples this small a paired 95% CI is typically about +/-0.2 wide on recall@3, so only large differences can be established: read the intervals, not just the means.", "", "## Retrieval quality (identical queries for every arm)", "",
          "| Arm | retrieval attempted | answerable n | Recall@1 | Recall@3 | Recall@5 | MRR | no-answer correct-empty | leaks | fallbacks | warm latency median / p95 ms |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a, x in r["retrieval"].items():
        o = x["overall"]
        L.append(f"| {x['label']} | {o['attempted_rate']} | {o['n_answerable']} | {o['recall@1']} | {o['recall@3']} | {o['recall@5']} | {o['mrr']} | {o['no_answer_correct_empty']} (n={o['n_no_answer']}) | {o['leaks']} | {o['fallbacks']} | {o['latency_ms_warm']['median']} / {o['latency_ms_warm']['p95']} |")
    L += ["", "Note: an arm that rarely retrieves (see 'retrieval attempted') gets a vacuously perfect no-answer score; compare that column only between arms with similar attempted rates."]
    cold = r["retrieval"]["C"]["overall"]["latency_ms_with_index_build"]
    L += ["", f"Hybrid first-query cost including embedding the user's records (arm C): median {cold['median']} ms, p95 {cold['p95']} ms (n={cold['n']}).", "", "## Paired differences (second minus first; 95% bootstrap CI)", ""]
    for name, c in r["paired_differences"].items():
        L.append(f"- **{name}**: recall@3 {c['recall@3']}; MRR {c['mrr']}; no-answer {c['no_answer']}")
    v = r["verdict_C_vs_B"]
    L += ["", "## Verdict (C vs B)", "", f"**Hybrid better than BM25 demonstrated: {v['hybrid_better_than_bm25_demonstrated']}**"]
    L += [f"- not demonstrated because: {x}" for x in v["reasons_not_demonstrated"]] + [f"- rule: {v['rule']}"]
    if "answer_level" in r:
        al = r["answer_level"]
        L += ["", f"## Answer level (llm: {al['llm']})", ""] + ([f"> **{al['WARNING']}**", ""] if al.get("WARNING") else [])
        keys = ["numbers_correct", "mentions_expected", "cites_expected_ref", "first_draft_unsupported_claims_per_answer", "answers_with_first_draft_issues", "unsupported_claims_per_answer", "regeneration_rate",
                "retrieval_attempted_rate", "retrieval_fallbacks", "llm_errors"]
        L += ["| Metric | A | B | C |", "|---|---|---|---|"] + [f"| {k} | " + " | ".join(str(al["arms"][a].get(k)) for a in "ABC") + " |" for k in keys]
        L.append("| latency median / p95 ms | " + " | ".join(f"{(al['arms'][a]['latency'] or {}).get('median_ms')} / {(al['arms'][a]['latency'] or {}).get('p95_ms')}" for a in "ABC") + " |")
        L += ["", "`first_draft_*` = problems the verifier found in the model's first draft (before regeneration or sentence removal); `unsupported_claims_per_answer` = what is left in the final answer."]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ai.retrieval_eval")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "tune"):
        p = sub.add_parser(name)
        p.add_argument("--embedder", choices=["ollama", "fake"], default="ollama")
    sub.choices["run"].add_argument("--llm", choices=["ollama", "mock", "none"], default="none")
    sub.choices["run"].add_argument("--split", choices=["test", "dev", "all"], default="test")
    sub.choices["run"].add_argument("--min-sim", type=float, default=None)
    sub.choices["run"].add_argument("--out", default=os.path.join(BASE_DIR, "eval_results"))
    a = ap.parse_args(argv)
    if a.cmd == "tune":
        res = tune((lambda t: ollama_client.embed(t)) if a.embedder == "ollama" else HashingEmbedder(), a.embedder)
        print(json.dumps(res, indent=1))
        if a.embedder != "ollama":
            print("\n(PLUMBING ONLY: nothing was written because the embedder is not a real model.)")
        return 0
    rep = run(a.embedder, a.llm, a.split, a.min_sim)
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.join(a.out, f"retrieval_{datetime.now():%Y%m%d_%H%M%S}_{a.embedder}_{a.llm}_{a.split}")
    json.dump(rep, open(stem + ".json", "w", encoding="utf-8"), indent=1)
    md = to_markdown(rep)
    open(stem + ".md", "w", encoding="utf-8").write(md)
    print(md, "\n\nSaved:", stem + ".json /.md")
    return 2 if rep.get("aborted") else 0


if __name__ == "__main__":
    sys.exit(main())
