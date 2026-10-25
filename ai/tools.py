"""Controlled, read-only AI tools.

Safety properties
  * The model never receives database access, SQL, shell or code execution - only these named functions.
  * No tool takes a candidate_id: the candidate is derived from the authenticated user, so a prompt
    cannot ask for another person's data.
  * Every argument is validated (type, range, length, unknown keys, role/skill must exist in the catalog).
  * Numbers returned here come from ai.scoring (the same code as the dashboard), never from the LLM."""
from dataclasses import dataclass
from typing import Any, Callable

from . import evidence as ev
from . import rag, retrieval, scoring
from .entities import find_roles_in_text, resolve_role
from .profile_data import candidate_id_for_user, load_profile, skill_catalog
from .roadmap import build_roadmap
from .scenario import resolve_skill, run_scenario

MAX_TEXT = 200


class ToolArgError(ValueError):
    pass


class NoProfileError(LookupError):
    pass


class ToolContext:
    """Per-request, per-user view of the data. Everything is cached and read-only."""

    def __init__(self, conn, user_id: int):
        self.conn, self.user_id = conn, user_id
        self.candidate_id = candidate_id_for_user(conn, user_id)
        if self.candidate_id is None:
            raise NoProfileError("No CareerDNA profile is linked to this account yet.")
        self._profile = self._catalog = self._jobs = None
        self.embed_fn = None   # optional override of the embedding function (tests / evaluation); default = local Ollama

    @property
    def profile(self):
        if self._profile is None:
            self._profile = load_profile(self.conn, self.candidate_id)
        return self._profile

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = skill_catalog(self.conn)
        return self._catalog

    @property
    def jobs(self):
        if self._jobs is None:
            self._jobs = [{**j, "requirements": scoring.load_requirements(self.conn, j["job_id"])} for j in scoring.load_jobs(self.conn)]
        return self._jobs

    def job(self, role_text):
        j = resolve_role(self.jobs, role_text)
        if not j:
            raise ToolArgError(f"Unknown role '{role_text}'. Available roles: {', '.join(x['role'] for x in self.jobs)}.")
        return j

    def evidence(self):
        skills = {}
        for j in self.jobs:
            for r in j["requirements"]:
                skills[r["skill_id"]] = {"skill_id": r["skill_id"], "skill_name": r["skill_name"]}
        for s in self.profile["skills"]:
            skills[s["skill_id"]] = {"skill_id": s["skill_id"], "skill_name": s["skill_name"]}
        for p in self.profile["projects"]:
            for sid in p.get("skill_ids", []):
                if sid in self.catalog["by_id"]:
                    skills[sid] = self.catalog["by_id"][sid]
        return ev.evidence_for_skills(self.profile, list(skills.values()))

    def have_ids(self):
        return {s["skill_id"] for s in self.profile["skills"]}

    def default_role(self):
        """Target role = a role named in the user's own goals/headline; otherwise the best official match (stated as an assumption)."""
        text = f"{self.profile.get('headline', '')} {self.profile.get('goals', '')}"
        named, _ = find_roles_in_text(self.jobs, text)
        have = self.have_ids()
        scored = {j["role"]: scoring.compute_match(j["requirements"], have)["match_percent"] for j in self.jobs}
        if named:
            best = max(named, key=lambda r: scored[r])
            others = [r for r in named if r != best]
            note = f"Target role taken from your profile goals ('{best}')" + (f"; your goals also mention {', '.join(others)}." if others else ".")
            return next(j for j in self.jobs if j["role"] == best), note
        best = max(self.jobs, key=lambda j: scored[j["role"]])
        return best, f"Your profile does not name a target role, so '{best['role']}' (your highest official match) is used as an assumption."


# ------------------------------------------------------------------ result helpers
def _ref(ref, typ, label):
    return {"ref": ref, "type": typ, "label": label}


def _num(value, kind, label):
    return {"value": value, "kind": kind, "label": label}


def _result(data, lines, refs=None, numbers=None, assumptions=None, hypothetical=False):
    return {"data": data, "lines": lines, "refs": refs or [], "numbers": numbers or [],
            "assumptions": assumptions or [], "hypothetical": hypothetical}


def _role_arg(ctx, args):
    if args.get("role"):
        return ctx.job(args["role"]), []
    job, note = ctx.default_role()
    return job, [note]


# ------------------------------------------------------------------ tools
def get_career_profile(ctx, **_):
    p = ctx.profile
    missing = [n for n, v in [("skills", p["skills"]), ("projects", p["projects"]), ("certifications", p["certifications"]),
                              ("work experience", p["experience"]), ("education", p["education"]),
                              ("career goals", p["goals"]), ("headline", p["headline"])] if not v]
    refs = ([_ref(f"project:{x['project_id']}", "project", x["title"]) for x in p["projects"]] +
            [_ref(f"certification:{x['certification_id']}", "certification", x["name"]) for x in p["certifications"]] +
            [_ref(f"experience:{x['experience_id']}", "experience", f"{x['role']} at {x['company']}") for x in p["experience"]] +
            [_ref(f"education:{x['education_id']}", "education", f"{x['degree']}, {x['institution']}") for x in p["education"]])
    lines = [f"Profile of {p['name']}" + (f" ({p['location']})" if p["location"] else "") + ".",
             f"Listed skills ({len(p['skills'])}): " + (", ".join(f"{s['skill_name']} ({s['proficiency'] or 'level n/a'})" for s in p["skills"]) or "none"),
             f"Projects ({len(p['projects'])}): " + ("; ".join(f"[project:{x['project_id']}] {x['title']}" for x in p["projects"]) or "none"),
             f"Certifications ({len(p['certifications'])}): " + ("; ".join(f"[certification:{x['certification_id']}] {x['name']}" for x in p["certifications"]) or "none recorded"),
             f"Experience: " + ("; ".join(f"[experience:{x['experience_id']}] {x['role']} at {x['company']}" for x in p["experience"]) or "none recorded"),
             "Sections with no data: " + (", ".join(missing) if missing else "none") + ". Missing data means the system cannot assess that area, not that the ability is absent."]
    data = {"name": p["name"], "location": p["location"], "headline": p["headline"], "goals": p["goals"], "missing_sections": missing,
            "counts": {"skills": len(p["skills"]), "projects": len(p["projects"]), "certifications": len(p["certifications"]),
                       "experience": len(p["experience"]), "education": len(p["education"])},
            "skills": [{"name": s["skill_name"], "proficiency": s["proficiency"], "years": s["years"], "evidence_score": s["evidence_score"]} for s in p["skills"]]}
    return _result(data, lines, refs, [_num(len(p["skills"]), "count", "skills listed"), _num(len(p["projects"]), "count", "projects"),
                                       _num(len(p["certifications"]), "count", "certifications")])


def get_job_requirements(ctx, role=None, **_):
    job, notes = _role_arg(ctx, {"role": role})
    reqs = sorted(job["requirements"], key=lambda r: (-float(r["importance"] or 1), r["skill_name"]))
    lines = [f"{job['role']} at {job['company']} ({job['location']}) [job:{job['job_id']}] requires: " +
             "; ".join(f"{r['skill_name']} ({r['required_level']}, weight {float(r['importance'] or 1):g})" for r in reqs) + ".",
             f"Listed salary range in the database: {job['min_salary']:g}-{job['max_salary']:g} LPA (a posting range, not your prediction)."]
    nums = [_num(float(r["importance"] or 1), "weight", f"weight of {r['skill_name']}") for r in reqs]
    nums += [_num(float(job["min_salary"]), "lpa", "listed min salary"), _num(float(job["max_salary"]), "lpa", "listed max salary")]
    return _result({"role": job["role"], "company": job["company"], "requirements": reqs}, lines,
                   [_ref(f"job:{job['job_id']}", "job", f"{job['role']} ({job['company']})")], nums, notes)


def calculate_job_match(ctx, role=None, **_):
    have, evid = ctx.have_ids(), ctx.evidence()
    targets = [ctx.job(role)] if role else ctx.jobs
    rows, lines, refs, nums = [], [], [], []
    for j in targets:
        m = scoring.compute_match(j["requirements"], have)
        d = ev.documented_percent(j["requirements"], evid)
        rows.append({"role": j["role"], "company": j["company"], "match_percent": m["match_percent"],
                     "matched": [{"name": x["name"], "importance": x["importance"]} for x in m["matched"]],
                     "missing": [{"name": x["name"], "required_level": x["required_level"], "importance": x["importance"]} for x in m["missing"]],
                     "documented_percent": d["documented_percent"], "documented_skills": d["documented_skills"]})
        matched_txt = ", ".join("%s (weight %g)" % (x["name"], x["importance"]) for x in m["matched"]) or "none"
        missing_txt = ", ".join("%s (%s, weight %g)" % (x["name"], x["required_level"], x["importance"]) for x in m["missing"]) or "none"
        lines.append(f"OFFICIAL MATCH for {j['role']} [job:{j['job_id']}]: {m['match_percent']}% (importance-weighted share of required skills found in your profile). "
                     f"Matched: {matched_txt}. Not in profile: {missing_txt}. "
                     f"Documented-evidence coverage (supplementary, not the official score): {d['documented_percent']}%.")
        refs.append(_ref(f"job:{j['job_id']}", "job", f"{j['role']} ({j['company']})"))
        nums += [_num(m["match_percent"], "percent", f"official match {j['role']}"), _num(d["documented_percent"], "percent", f"documented coverage {j['role']}")]
    return _result({"roles": rows}, lines, refs, nums)


def get_skill_gaps(ctx, role=None, **_):
    job, notes = _role_arg(ctx, {"role": role})
    have, evid = ctx.have_ids(), ctx.evidence()
    m = scoring.compute_match(job["requirements"], have)
    missing = sorted(m["missing"], key=lambda x: -x["importance"])
    gaps = [{"skill": x["name"], "required_level": x["required_level"], "importance": x["importance"],
             "would_add_pp": round(scoring.compute_match(job["requirements"], have | {x["skill_id"]})["match_percent"] - m["match_percent"], 1),
             "status": "no_record",
             "meaning": "Not in your profile - proficiency cannot be established from available data (not proof you lack it)."} for x in missing]
    ev_gaps = []
    for r in job["requirements"]:
        e = evid.get(r["skill_id"])
        if e and e["status"] in ("self_reported_only", "contradictory"):
            ev_gaps.append({"skill": r["skill_name"], "status": e["status"], "detail": e["contradictions"] or [e["note"]],
                            "refs": [e["self_reported"]["ref"]] if e["self_reported"] else []})
    lines = [f"Skill gaps for {job['role']} [job:{job['job_id']}] (official match {m['match_percent']}%):"]
    lines += [f"- {g['skill']} ({g['required_level']}, weight {g['importance']:g}): not in your profile; listing it would add {g['would_add_pp']} percentage points to the official match. {g['meaning']}" for g in gaps]
    lines += [f"- {g['skill']}: {g['status'].replace('_', ' ')} - {'; '.join(g['detail'])} [{', '.join(g['refs'])}]" for g in ev_gaps]
    if not gaps and not ev_gaps:
        lines.append("- No gaps found in the required skills for this role.")
    nums = [_num(m["match_percent"], "percent", "official match")] + [_num(g["would_add_pp"], "percent", f"gain {g['skill']}") for g in gaps]
    refs = [_ref(f"job:{job['job_id']}", "job", job["role"])] + [_ref(r, "skill_record", r) for g in ev_gaps for r in g["refs"]]
    return _result({"role": job["role"], "match_percent": m["match_percent"], "missing_skills": gaps, "evidence_gaps": ev_gaps}, lines, refs, nums, notes)


def get_skill_evidence(ctx, skill=None, **_):
    sk = resolve_skill(ctx.catalog, skill)
    if not sk:
        raise ToolArgError(f"Unknown skill '{skill}'. Known skills: {', '.join(v['skill_name'] for v in ctx.catalog['by_id'].values())}.")
    e = ev.skill_evidence(ctx.profile, sk)
    sr = e["self_reported"]
    parts = [f"Evidence for {sk['skill_name']}: status = {e['status'].replace('_', ' ')}. {e['note']}"]
    refs, nums = [], []
    if sr:
        sc = sr["recorded_evidence_score"]
        parts.append(f"Self-reported [{sr['ref']}]: {sr['proficiency']}, {sr['years']} years, recorded evidence score {sc:g}/100." if sc is not None else
                     f"Self-reported [{sr['ref']}]: {sr['proficiency']}, {sr['years']} years.")
        refs.append(_ref(sr["ref"], "skill_record", f"{sk['skill_name']} (self-reported)"))
        if sc is not None:
            nums.append(_num(float(sc), "score", "recorded evidence score"))
        nums.append(_num(float(sr["years"] or 0), "years", "years"))
    parts.append("Projects: " + ("; ".join(f"[{x['ref']}] {x['title']}" for x in e["projects"]) or "none linked"))
    parts.append("Certifications: " + ("; ".join(f"[{x['ref']}] {x['name']}" for x in e["certifications"]) or "none linked"))
    parts.append("Assessments: CareerDNA has no assessment data, so this cannot be checked.")
    if e["contradictions"]:
        parts.append("Contradictions: " + "; ".join(e["contradictions"]))
    refs += [_ref(x["ref"], "project", x["title"]) for x in e["projects"]] + [_ref(x["ref"], "certification", x["name"]) for x in e["certifications"]]
    return _result(e, parts, refs, nums)


def predict_salary(ctx, **_):
    s = scoring.estimate_salary(ctx.conn, ctx.candidate_id)
    lines = [f"CareerDNA's existing salary estimate: {s['predicted_salary_lpa']} LPA (source: {s['source']}, confidence {s['confidence']}). "
             "This is an estimate from CareerDNA's current rules, not a guaranteed salary."]
    return _result({k: v for k, v in s.items() if k != "prediction"}, lines, [], [_num(float(s["predicted_salary_lpa"]), "lpa", "predicted salary")])


def compare_career_paths(ctx, roles=None, **_):
    jobs = [ctx.job(r) for r in roles]
    seen, uniq = set(), []
    for j in jobs:
        if j["job_id"] not in seen:
            seen.add(j["job_id"]); uniq.append(j)
    if len(uniq) < 2:
        raise ToolArgError("Please name two different roles to compare.")
    have, evid = ctx.have_ids(), ctx.evidence()
    rows, lines, refs, nums = [], [], [], []
    for j in uniq:
        m = scoring.compute_match(j["requirements"], have)
        d = ev.documented_percent(j["requirements"], evid)
        rows.append({"role": j["role"], "company": j["company"], "match_percent": m["match_percent"], "documented_percent": d["documented_percent"],
                     "missing": [x["name"] for x in m["missing"]], "listed_salary_lpa": [j["min_salary"], j["max_salary"]]})
        lines.append(f"{j['role']} [job:{j['job_id']}]: official match {m['match_percent']}%; documented coverage {d['documented_percent']}%; "
                     f"not in profile: {', '.join(x['name'] for x in m['missing']) or 'none'}; listed salary range {j['min_salary']:g}-{j['max_salary']:g} LPA (posting range).")
        refs.append(_ref(f"job:{j['job_id']}", "job", j["role"]))
        nums += [_num(m["match_percent"], "percent", f"match {j['role']}"), _num(d["documented_percent"], "percent", f"documented {j['role']}"),
                 _num(float(j["min_salary"]), "lpa", "min"), _num(float(j["max_salary"]), "lpa", "max")]
    top = max(rows, key=lambda r: r["match_percent"])
    tied = [r["role"] for r in rows if r["match_percent"] == top["match_percent"]]
    lines.append("Higher official match: " + (" and ".join(tied) + " (tie)" if len(tied) > 1 else top["role"]) + ". This compares skill coverage only; it does not say which career is better for you.")
    return _result({"comparison": rows}, lines, refs, nums)


def simulate_profile_change(ctx, add_skills=None, add_projects=None, add_certifications=None, add_experience_months=0, roles=None, **_):
    changes = {"add_skills": add_skills or [], "add_projects": add_projects or [], "add_certifications": add_certifications or [],
               "add_experience_months": add_experience_months or 0}
    if not (changes["add_skills"] or changes["add_projects"] or changes["add_certifications"] or changes["add_experience_months"]):
        raise ToolArgError("Describe at least one hypothetical change (a skill, project, certification or months of experience).")
    role_names = [ctx.job(r)["role"] for r in roles] if roles else None
    out = run_scenario(ctx.profile, ctx.catalog, ctx.jobs, scoring.salary_inputs(ctx.conn, ctx.candidate_id), changes, role_names)
    lines = ["HYPOTHETICAL SCENARIO (not your real profile). Changes simulated: " +
             ("; ".join(_describe(a) for a in out["applied"]) or "none could be applied") + "."]
    nums = []
    for role, b in out["baseline"]["roles"].items():
        s, c = out["scenario"]["roles"][role], out["changes"]["roles"][role]
        lines.append(f"{role}: official match {b['match_percent']}% -> {s['match_percent']}% (change {c['match_delta_pp']:+g} percentage points); documented coverage {b['documented_percent']}% -> {s['documented_percent']}% ({c['documented_delta_pp']:+g}).")
        if c["newly_matched"]:
            lines.append("  Cause: newly satisfied requirement(s) " + ", ".join(f"{n['skill']} (weight {n['importance']:g})" for n in c["newly_matched"]) + ".")
        for sc in c["evidence_status_changes"]:
            lines.append(f"  Evidence: {sc['skill']} {sc['before'].replace('_', ' ')} -> {sc['after'].replace('_', ' ')} via {', '.join(sc['via']) or 'hypothetical records'}.")
        nums += [_num(b["match_percent"], "percent", "baseline"), _num(s["match_percent"], "percent", "scenario"), _num(abs(c["match_delta_pp"]), "percent", "delta"),
                 _num(b["documented_percent"], "percent", "baseline doc"), _num(s["documented_percent"], "percent", "scenario doc"), _num(abs(c["documented_delta_pp"]), "percent", "delta doc")]
    bs, ss = out["baseline"]["salary"], out["scenario"]["salary"]
    lines.append(f"Salary (CareerDNA what-if rules): {bs['base_salary_lpa']} LPA -> {ss['projected_salary_lpa']} LPA (change {out['changes']['salary_delta_lpa']:+g} LPA).")
    nums += [_num(bs["base_salary_lpa"], "lpa", "base"), _num(ss["projected_salary_lpa"], "lpa", "projected"), _num(abs(out["changes"]["salary_delta_lpa"]), "lpa", "delta")]
    for u in out["unresolved"]:
        lines.append(f"Could not score '{u['input']}': {u['reason']}.")
    lines += [f"Limitation: {x}" for x in out["limitations"]]
    return _result(out, lines, [], nums, out["assumptions"] + out["notes"], hypothetical=True)


def _describe(a):
    if a["type"] == "skill":
        return f"add skill {a['skill']} ({a['via']})"
    if a["type"] == "project":
        return f"add project '{a['title']}' using {', '.join(a['skills']) or 'no catalogued skills'}"
    if a["type"] == "certification":
        return f"add certification '{a['name']}'"
    return f"add {a['months']} months of experience"


def get_learning_roadmap(ctx, role=None, hours_per_week=5, weeks=12, **_):
    job, notes = _role_arg(ctx, {"role": role})
    r = build_roadmap(ctx.profile, job, ctx.evidence(), float(hours_per_week), int(weeks))
    lines = [f"Roadmap toward {job['role']} [job:{job['job_id']}] assuming {r['hours_per_week']:g} h/week for {r['weeks']} weeks (budget {r['budget_hours']} h)."]
    if r["nothing_to_do"]:
        lines.append("No missing or undocumented required skills were found for this role in your records.")
    for it in r["items"]:
        lines.append(f"{it['step']}. {it['action'].upper()} {it['skill']} - {it['reason']}; estimate {it['hours_low']}-{it['hours_high']} h; "
                     f"cumulative {it['cumulative_hours'][0]}-{it['cumulative_hours'][1]} h; fits your window: {it['fits_window']}; source: {it['source']}.")
    lines.append("Estimates are rough planning ranges, not promises.")
    nums = [_num(float(r["budget_hours"]), "hours", "budget")] + [_num(float(h), "hours", "est") for it in r["items"] for h in (it["hours_low"], it["hours_high"], *it["cumulative_hours"])]
    nums += [_num(float(w), "weeks", "est weeks") for it in r["items"] for w in it["estimated_weeks"]]
    return _result(r, lines, [_ref(f"job:{job['job_id']}", "job", job["role"])], nums, notes)


def retrieve_context(ctx, query=None, **_):
    """Searches ONLY the signed-in user's own free-text records (plus the shared job catalogue, which is excluded here).
    Mode comes from CAREERDNA_RETRIEVAL_MODE: 'bm25' (default, unchanged) or 'hybrid' (BM25 + local embeddings, RRF fusion)."""
    docs = rag.build_documents(ctx.profile, ctx.jobs, ctx.catalog)
    res = retrieval.retrieve(ctx.conn, ctx.candidate_id, query, docs, k=4, types={"project", "experience", "certification", "profile"}, embed_fn=ctx.embed_fn)
    hits, diag = res["hits"], res["diagnostics"]
    lines = [f"[{h['ref']}] {h['title']}: {h['text'][:260]}" for h in hits] or ["No relevant free-text records were found."]
    notes = []
    if diag["fallback"]:
        notes.append(f"Semantic retrieval was unavailable ({diag['fallback_reason']}), so keyword search was used for the related records.")
    return _result({"hits": [{k: v for k, v in h.items() if k != "text"} for h in hits], "retrieval": diag}, lines,
                   [_ref(h["ref"], h["type"], h["title"]) for h in hits], assumptions=notes)


# ------------------------------------------------------------------ registry & validation
@dataclass
class Tool:
    name: str
    fn: Callable
    description: str
    params: dict  # name -> {"type":..., "required":bool, ...}


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("get_career_profile", get_career_profile, "Summary of the signed-in user's profile and which sections have no data.", {}),
    Tool("get_job_requirements", get_job_requirements, "Required skills and weights for a role.", {"role": {"type": "role"}}),
    Tool("calculate_job_match", calculate_job_match, "Official match percentage(s) from CareerDNA's scoring code.", {"role": {"type": "role"}}),
    Tool("get_skill_gaps", get_skill_gaps, "Missing and weakly-evidenced skills for a role.", {"role": {"type": "role"}}),
    Tool("get_skill_evidence", get_skill_evidence, "Evidence records behind one skill.", {"skill": {"type": "skill", "required": True}}),
    Tool("predict_salary", predict_salary, "CareerDNA's existing salary estimate for the user.", {}),
    Tool("compare_career_paths", compare_career_paths, "Compare two to four roles.", {"roles": {"type": "role_list", "required": True, "min": 2, "max": 4}}),
    Tool("simulate_profile_change", simulate_profile_change, "Hypothetical what-if; never changes real data.", {
        "add_skills": {"type": "skill_list", "max": 8}, "add_projects": {"type": "project_list", "max": 4},
        "add_certifications": {"type": "cert_list", "max": 4}, "add_experience_months": {"type": "int", "min": 0, "max": 120},
        "roles": {"type": "role_list", "max": 4}}),
    Tool("get_learning_roadmap", get_learning_roadmap, "Ordered plan toward a role within a time budget.", {
        "role": {"type": "role"}, "hours_per_week": {"type": "float", "min": 1, "max": 80}, "weeks": {"type": "int", "min": 1, "max": 104}}),
    Tool("retrieve_context", retrieve_context, "Search the user's own free-text records.", {"query": {"type": "text", "required": True}}),
]}


def _text(v, name):
    if not isinstance(v, str) or not v.strip():
        raise ToolArgError(f"'{name}' must be a non-empty string.")
    if len(v) > MAX_TEXT:
        raise ToolArgError(f"'{name}' is too long (max {MAX_TEXT} characters).")
    return v.strip()


def _num_in(v, name, spec, cast):
    try:
        x = cast(v)
    except (TypeError, ValueError):
        raise ToolArgError(f"'{name}' must be a number.")
    if isinstance(v, bool) or x < spec.get("min", float("-inf")) or x > spec.get("max", float("inf")):
        raise ToolArgError(f"'{name}' must be between {spec.get('min')} and {spec.get('max')}.")
    return x


def validate_args(ctx, tool: Tool, args: dict) -> dict:
    if not isinstance(args, dict):
        raise ToolArgError("Arguments must be an object.")
    unknown = set(args) - set(tool.params)
    if unknown:
        raise ToolArgError(f"Unexpected argument(s): {', '.join(sorted(unknown))}.")
    clean = {}
    for name, spec in tool.params.items():
        if name not in args or args[name] is None:
            if spec.get("required"):
                raise ToolArgError(f"Missing required argument '{name}'.")
            continue
        v, t = args[name], spec["type"]
        if t == "role":
            clean[name] = ctx.job(_text(v, name))["role"]
        elif t == "skill":
            s = resolve_skill(ctx.catalog, _text(v, name))
            if not s:
                raise ToolArgError(f"Unknown skill '{v}'.")
            clean[name] = s["skill_name"]
        elif t == "text":
            clean[name] = _text(v, name)
        elif t == "int":
            clean[name] = _num_in(v, name, spec, int)
        elif t == "float":
            clean[name] = _num_in(v, name, spec, float)
        elif t in ("role_list", "skill_list"):
            if not isinstance(v, list) or len(v) > spec.get("max", 8) or len(v) < spec.get("min", 0):
                raise ToolArgError(f"'{name}' must be a list of {spec.get('min', 0)}-{spec.get('max', 8)} items.")
            clean[name] = [ctx.job(_text(x, name))["role"] for x in v] if t == "role_list" else [_text(x, name) for x in v]
        elif t == "project_list":
            if not isinstance(v, list) or len(v) > spec["max"]:
                raise ToolArgError(f"'{name}' must be a list of at most {spec['max']} projects.")
            clean[name] = [{"title": _text(p.get("title") or "hypothetical project", "title"),
                            "skills": [_text(x, "skills") for x in (p.get("skills") or [])][:8]} for p in v if isinstance(p, dict)]
        elif t == "cert_list":
            if not isinstance(v, list) or len(v) > spec["max"]:
                raise ToolArgError(f"'{name}' must be a list of at most {spec['max']} certifications.")
            clean[name] = [{"name": _text(c.get("name") or "hypothetical certification", "name"),
                            "skills": [_text(x, "skills") for x in (c.get("skills") or [])][:8]} for c in v if isinstance(c, dict)]
    return clean


def call_tool(ctx: ToolContext, name: str, args: dict) -> dict:
    """Validates arguments, runs a tool, and wraps any failure as a structured error (never raises to the caller)."""
    tool = TOOLS.get(name)
    if not tool:
        return {"tool": name, "args": args, "ok": False, "error": f"Unknown tool '{name}'."}
    try:
        clean = validate_args(ctx, tool, args or {})
        res = tool.fn(ctx, **clean)
        return {"tool": name, "args": clean, "ok": True, **res}
    except ToolArgError as e:
        return {"tool": name, "args": args, "ok": False, "error": str(e)}


def tool_specs() -> list[dict]:
    """JSON-schema style description of the tools (documentation / future native tool-calling)."""
    return [{"name": t.name, "description": t.description, "parameters": t.params} for t in TOOLS.values()]
