"""Orchestrates: plan -> validated tool calls -> grounded prompt -> local LLM -> deterministic verification."""
import hashlib
import json
import re
import time

from . import ollama_client, router, verifier
from .config import AISettings, ConfigError, get_retrieval_settings, get_settings
from .db import ensure_ai_tables
from .ollama_client import OllamaError
from .prompts import REGEN_TEMPLATE, SYSTEM_PROMPT, USER_TEMPLATE
from .tools import NoProfileError, ToolContext, call_tool

MAX_FACT_CHARS = 4500
_SALT = "careerdna-eval-log"


def _ref_set(ctx: ToolContext, results: list[dict]) -> set:
    refs = {r["ref"] for res in results if res.get("ok") for r in res["refs"]}
    p = ctx.profile
    refs |= {f"project:{x['project_id']}" for x in p["projects"]} | {f"certification:{x['certification_id']}" for x in p["certifications"]}
    refs |= {f"experience:{x['experience_id']}" for x in p["experience"]} | {f"education:{x['education_id']}" for x in p["education"]}
    refs |= {f"candidate_skill:{p['candidate_id']}:{s['skill_id']}" for s in p["skills"]} | {f"job:{j['job_id']}" for j in ctx.jobs}
    return refs


def build_facts(ctx: ToolContext, results: list[dict], question: str) -> verifier.Facts:
    p, ev = ctx.profile, ctx.evidence()
    hyp = any(r.get("hypothetical") for r in results if r.get("ok"))
    hyp_skills = set()
    for r in results:
        if r.get("ok") and r.get("hypothetical"):
            for a in r["data"]["applied"]:
                if a["type"] == "skill":
                    hyp_skills.add(a["skill"].lower())
                else:
                    hyp_skills |= {x.lower() for x in a.get("skills", [])}
    user_nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", question)]
    return verifier.Facts(
        profile_skills={s["skill_name"].lower(): s["proficiency"] for s in p["skills"]},
        documented_skills={e["skill_name"].lower() for e in ev.values() if e["status"] == "documented"},
        known_skills=[v["skill_name"] for v in ctx.catalog["by_id"].values()],
        project_titles=[x["title"] for x in p["projects"]], certification_count=len(p["certifications"]),
        refs=_ref_set(ctx, results), numbers=verifier.numbers_from_tools(results), hypothetical=hyp,
        hypothetical_skills=hyp_skills, user_numbers=user_nums,
        cert_supported_skills={e["skill_name"].lower() for e in ev.values() if e["certifications"]})


def _premise_note(question_nums, results):
    if not question_nums:
        return None
    official = {}
    for r in results:
        if r.get("ok") and r["tool"] == "calculate_job_match":
            for row in r["data"]["roles"]:
                official[row["role"]] = row["match_percent"]
    if not official:
        return None
    for q in question_nums:
        if not any(abs(q - v) <= 0.5 for v in official.values()):
            vals = "; ".join(f"{k}: {v}%" for k, v in official.items())
            return f"You mentioned {q:g}%, but CareerDNA's official match is different ({vals})."
    return None


def _fact_text(results):
    lines = []
    for r in results:
        if r.get("ok"):
            lines += [f"- {l}" if not l.startswith(("-", " ")) else l for l in r["lines"]]
            lines += [f"- Note: {a}" for a in r.get("assumptions", [])]
        else:
            lines.append(f"- (A lookup failed: {r['error']})")
    text = "\n".join(lines)
    return text if len(text) <= MAX_FACT_CHARS else text[:MAX_FACT_CHARS] + "\n- (further facts omitted for length)"


def _fallback(results, premise):
    out = ["Here are the verified results straight from CareerDNA's calculations:"]
    if premise:
        out.append(premise)
    for r in results:
        out += [l for l in (r["lines"] if r.get("ok") else [r["error"]])]
    return "\n".join(out)


def _hash(candidate_id):
    return hashlib.sha256(f"{_SALT}:{candidate_id}".encode()).hexdigest()[:12]


class CareerAgent:
    def __init__(self, conn, user_id: int, settings: AISettings | None = None, llm_chat=None, embed_fn=None):
        self.conn, self.user_id = conn, user_id
        self.embed_fn = embed_fn
        self._settings = settings
        self.llm_chat = llm_chat or ollama_client.chat

    @property
    def settings(self):
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    # -------------------------------------------------------------------------------------------
    def run(self, question: str, context: dict | None = None, test_case_id: str | None = None) -> dict:
        try:
            ctx = ToolContext(self.conn, self.user_id)
        except NoProfileError as e:
            return {"ok": False, "error": {"code": "NO_PROFILE", "message": str(e), "instructions": "Complete your CareerDNA profile first."}}
        ctx.embed_fn = self.embed_fn
        plan = router.plan(question, ctx.jobs, ctx.catalog, context, wiring=get_retrieval_settings().wiring)
        return self.run_plan(ctx, question, plan, test_case_id)

    def run_plan(self, ctx: ToolContext, question: str, plan: dict, test_case_id: str | None = None) -> dict:
        t0 = time.perf_counter()
        ctx.embed_fn = self.embed_fn or ctx.embed_fn
        results = [call_tool(ctx, c["name"], c["args"]) for c in plan["calls"]]
        ok_results = [r for r in results if r.get("ok")]
        premise = _premise_note(plan.get("premise_percents", []), ok_results)
        numbers = [{"tool": r["tool"], "kind": n["kind"], "value": n["value"]} for r in ok_results for n in r.get("numbers", []) if n["kind"] in ("percent", "lpa")]
        qlen = len(question or "")
        refs, seen = [], set()
        for r in ok_results:
            for x in r["refs"]:
                if x["ref"] not in seen:
                    seen.add(x["ref"]); refs.append(x)
        base = {"intent": plan["intent"], "entities": {"roles": plan["roles"], "skills": plan["skills"]},
                "tools": [{"name": r["tool"], "args": r["args"], "ok": r["ok"], **({"error": r["error"]} if not r["ok"] else {})} for r in results],
                "facts": [{"tool": r["tool"], "lines": r["lines"], "assumptions": r.get("assumptions", [])} for r in ok_results],
                "evidence": refs, "hypothetical": any(r.get("hypothetical") for r in ok_results),
                "notes": plan["notes"] + ([premise] if premise else []), "model": self._model_name(),
                "retrieval": [r["data"]["retrieval"] for r in ok_results if r["tool"] == "retrieve_context"]}
        if not ok_results:
            msg = " ".join(r["error"] for r in results) or "I could not find the information needed to answer that."
            if plan.get("clarification"):
                msg = plan["clarification"]
            return self._finish(ctx, base, {"ok": True, "answer": msg, "verification": {"status": "no_llm_needed", "issues": []}}, plan, test_case_id, t0, [], "skipped", numbers, qlen)
        if plan.get("clarification"):
            base["notes"].append(plan["clarification"])
        facts_text = _fact_text(results)
        notes = "".join(f"\nNOTE: {n}" for n in base["notes"])
        prompt = USER_TEMPLATE.format(question=question.strip(), facts=facts_text, related="", notes=notes)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        try:
            raw = self.llm_chat(messages, self.settings)
        except (OllamaError, ConfigError) as e:
            err = e.to_dict() if isinstance(e, OllamaError) else {"code": "CONFIG_ERROR", "message": str(e), "instructions": ""}
            out = {"ok": False, "error": err, "answer": None, "fallback_summary": _fallback(ok_results, premise),
                   "verification": {"status": "skipped", "issues": []}}
            return self._finish(ctx, base, out, plan, test_case_id, t0, [], err["code"], numbers, qlen)
        facts = build_facts(ctx, ok_results, question)
        answer, issues = raw["content"], []
        issues = verifier.verify(answer, facts)
        first_draft_codes = [i.code for i in issues]     # measured before any regeneration/removal (evaluation uses this)
        status, regenerated = "passed", False
        attempts = 0
        while issues and attempts < self.settings.max_regenerations:
            attempts += 1
            problems = "\n".join(f"- {i.detail}: \"{i.sentence[:120]}\"" for i in issues[:6])
            try:
                again = self.llm_chat(messages + [{"role": "assistant", "content": answer},
                                                  {"role": "user", "content": REGEN_TEMPLATE.format(problems=problems)}], self.settings)
            except (OllamaError, ConfigError):
                break
            regenerated = True
            answer = again["content"]
            issues = verifier.verify(answer, facts)
            status = "regenerated"
        flagged = [i.to_dict() for i in issues]
        if issues:
            answer, kept_chars = verifier.qualify(answer, issues)
            status = "qualified"
            if kept_chars < 40:      # almost nothing verified survived: show the backend's own results instead
                answer, status = _fallback(ok_results, premise), "fallback"
        if premise and premise not in answer:
            answer = premise + "\n\n" + answer
        out = {"ok": True, "answer": answer,
               "verification": {"status": status, "issues": flagged, "regenerated": regenerated, "first_draft_issue_codes": first_draft_codes,
                                "note": "Numbers, cited records and skill claims in this answer were checked against your CareerDNA data."}}
        cited = [r for r in verifier.REF_RE.findall(answer)]
        out["cited_refs"] = [c for c in cited if c in facts.refs]
        return self._finish(ctx, base, out, plan, test_case_id, t0, flagged, status, numbers, qlen)

    # -------------------------------------------------------------------------------------------
    def _model_name(self):
        try:
            return self.settings.model
        except ConfigError:
            return None

    def _finish(self, ctx, base, out, plan, case_id, t0, flagged, status, numbers=None, qlen=0):
        latency = int((time.perf_counter() - t0) * 1000)
        res = {**base, **out, "latency_ms": latency, "context": {"roles": plan["roles"]}}
        try:
            ensure_ai_tables()
            self.conn.execute(
                """INSERT INTO ai_eval_log (test_case_id, candidate_ref, intent, question_chars, model_name, evidence_refs, backend_numbers,
                   verification, unsupported_flags, regenerated, latency_ms, error_code) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (case_id, _hash(ctx.candidate_id), plan["intent"], qlen, res.get("model"),
                 json.dumps([e["ref"] for e in base["evidence"]]), json.dumps((numbers or [])[:60]),
                 status, json.dumps([f["code"] for f in flagged]), int(bool(out.get("verification", {}).get("regenerated"))), latency,
                 None if out.get("ok") else (out.get("error") or {}).get("code")))
            self.conn.commit()
        except Exception:  # logging must never break an answer
            pass
        return res
