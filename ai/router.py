"""Validated intent routing: decides which explicit backend tools to call for a question.

Why a router instead of letting the model pick tools? Small local models (1.5B-3B) call tools unreliably, and a wrong
tool call would silently produce wrong numbers. The router is deterministic and unit-tested; every planned call is
still passed through the same argument validation as any other tool call. The LLM only writes the final explanation."""
import re

from .entities import find_roles_in_text, find_skills_in_text

REFERENTIAL = re.compile(r"\b(what about|how about|and for|that role|this role|same role|for it|there)\b")
PATTERNS = [  # order = priority
    ("what_if", re.compile(r"\bwhat if\b|\bsuppose\b|\bassum(e|ing)\b|\bhypothetic|\bif i (learn|add|get|complete|finish|build|earn|take|gain|had|pick|do)\b|\bsimulat")),
    ("compare", re.compile(r"\bcompare\b|\bversus\b|\bvs\.?\b|\bdifference between\b|\bwhich (role|career|path)\b")),
    ("missing_info", re.compile(r"missing (information|info|data)|what (information|data|info)\b|before you can|insufficient|\breadiness\b|how complete|incomplete")),
    ("skill_evidence", re.compile(r"\bevidence\b|\bproof\b|\bsupports?\b|\bproficien|\bback(s|ed)? up\b|\bdocumented\b|\bverified\b|\bhow (good|strong)\b")),
    ("roadmap", re.compile(r"learn next|what should i learn|\broadmap\b|study plan|\bplan\b|next steps|\bprepare\b|\bpath to\b|how (do|can) i (get|become)")),
    ("skill_gaps", re.compile(r"holding me back|\bgaps?\b|\bmissing\b|\bweak|\black\b|\bimprove\b|what.*(stop|block)")),
    ("match_explain", re.compile(r"\bmatch\b|\bscore\b|\bfit\b|\bsuitab|\bqualified\b|\bready for\b")),
    ("salary", re.compile(r"\bsalary\b|\bpay\b|\bearn|\blpa\b|\bctc\b|compensation")),
]
CERT_WORDS = re.compile(r"certif|\bexam\b")
# 'improved' wiring: retrieve with the user's whole question, and for these intents (documented in AI_README.md)
IMPROVED_RETRIEVAL_INTENTS = {"skill_evidence", "skill_gaps", "match_explain", "missing_info", "overview", "roadmap"}


def _clip(q: str, limit: int = 200) -> str:
    q = " ".join((q or "").split())
    return q if len(q) <= limit else q[:limit].rsplit(" ", 1)[0]


def _time(q):
    hpw = wk = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\s*(?:/|per|a|each)\s*week", q)
    if m:
        hpw = float(m.group(1))
    m = re.search(r"(\d+)\s*weeks?\b", q)
    if m:
        wk = int(m.group(1))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*months?\b", q)
        if m and not re.search(r"experience|internship|work", q[max(0, m.start() - 30):m.end() + 30]):
            wk = max(1, round(float(m.group(1)) * 4.345))
    return hpw, wk


def _whatif_args(ctx_cat, q, roles):
    skills_p, projects, certs, add_skills = [], [], [], []
    months = 0
    for clause in re.split(r"\band\b|,|;|\bthen\b|\bplus\b", q):
        sk = find_skills_in_text(ctx_cat, clause)
        if re.search(r"\bproject\b", clause):
            projects.append({"title": "hypothetical " + (" / ".join(sk) if sk else "new") + " project", "skills": sk})
        elif CERT_WORDS.search(clause):
            mm = re.search(r"((?:[A-Za-z0-9+#.\-]+\s+){0,5})(?:certification|certificate|exam)", clause)
            name = ((mm.group(1).strip() if mm else "") + " certification").strip()
            name = re.sub(r"^(?:if i |i |get |earn |take |complete |finish |pass |the |a |an )+", "", name, flags=re.I) or "hypothetical certification"
            certs.append({"name": name[:80], "skills": sk})
        else:
            add_skills += [s for s in sk if s not in add_skills]
        mm = re.search(r"(\d+)\s*(months?|years?)\b", clause)
        if mm and re.search(r"experience|internship|work|job", clause):
            n = int(mm.group(1)) * (12 if mm.group(2).startswith("year") else 1)
            months += n
    args = {}
    if add_skills: args["add_skills"] = add_skills
    if projects: args["add_projects"] = projects
    if certs: args["add_certifications"] = certs
    if months: args["add_experience_months"] = min(months, 120)
    if roles: args["roles"] = roles[:4]
    return args


def plan(question: str, jobs: list[dict], catalog: dict, context: dict | None = None, wiring: str = "legacy") -> dict:
    q = " ".join((question or "").lower().split())
    roles, masked = find_roles_in_text(jobs, q)
    skills = find_skills_in_text(catalog, masked)
    notes = []
    ctx_roles = (context or {}).get("roles") or []
    carried = False
    if not roles and ctx_roles and REFERENTIAL.search(q):
        roles, carried = [ctx_roles[-1]], True
        notes.append(f"Interpreting your follow-up as being about {roles[0]}.")
    intent = "overview"
    for name, pat in PATTERNS:
        if pat.search(q):
            if name == "skill_evidence" and not skills:
                continue  # 'evidence' without a named skill is handled by gaps/profile
            intent = name
            break
    else:
        if re.search(r"\bevidence\b|\bproof\b", q):
            intent = "skill_gaps"
    premise = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", q)]
    role = roles[0] if roles else None
    hpw, wk = _time(q)
    calls, clarification = [], None

    if intent == "what_if":
        args = _whatif_args(catalog, masked, roles)
        if set(args) - {"roles"}:
            calls = [("simulate_profile_change", args)]
        else:
            clarification = "I could not tell which change to simulate. Name a skill, project, certification, or months of experience."
            calls = [("get_career_profile", {})]
    elif intent == "compare":
        pick = roles if len(roles) >= 2 else [j["role"] for j in jobs][:4]
        if len(roles) < 2:
            notes.append("You did not name two roles, so all available roles are compared.")
        calls = [("compare_career_paths", {"roles": pick[:4]})]
    elif intent == "missing_info":
        calls = [("get_career_profile", {}), ("get_skill_gaps", {"role": role} if role else {})]
    elif intent == "skill_evidence":
        calls = [("get_skill_evidence", {"skill": s}) for s in skills[:2]]
        if wiring != "improved":
            calls.append(("retrieve_context", {"query": " ".join(skills[:2])}))
    elif intent == "roadmap":
        a = {"role": role} if role else {}
        if hpw is not None: a["hours_per_week"] = hpw
        if wk is not None: a["weeks"] = wk
        if hpw is None or wk is None:
            notes.append(f"Time budget assumed ({hpw if hpw else 5:g} h/week for {wk if wk else 12} weeks) because you did not specify it; change it in the Roadmap tab.")
        calls = [("get_learning_roadmap", a), ("calculate_job_match", {"role": role} if role else {})]
    elif intent == "skill_gaps":
        calls = [("get_skill_gaps", {"role": role} if role else {}), ("calculate_job_match", {"role": role} if role else {})]
    elif intent == "match_explain":
        calls = [("calculate_job_match", {"role": role} if role else {})]
        if role:
            calls.append(("get_skill_gaps", {"role": role}))
    elif intent == "salary":
        calls = [("predict_salary", {})] + ([("get_job_requirements", {"role": role})] if role else [])
    else:
        calls = [("get_career_profile", {}), ("calculate_job_match", {})]
    if intent == "skill_evidence" and not skills:  # defensive; normally unreachable
        calls = [("get_career_profile", {})]
    retrieval_query = None
    if wiring == "improved":
        if intent in IMPROVED_RETRIEVAL_INTENTS and (question or "").strip() and not (intent == "skill_evidence" and not skills):
            retrieval_query = _clip(question)
            calls.append(("retrieve_context", {"query": retrieval_query}))
    elif intent == "skill_evidence" and skills:
        retrieval_query = " ".join(skills[:2])
    return {"intent": intent, "calls": [{"name": n, "args": a} for n, a in calls], "retrieval_query": retrieval_query, "roles": roles, "skills": skills,
            "premise_percents": premise, "notes": notes, "clarification": clarification, "carried_context": carried}
