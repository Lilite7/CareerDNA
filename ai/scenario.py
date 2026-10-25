"""Career What-If simulator.

Works on an in-memory COPY of the profile; the real profile and database are never modified.
All numbers come from the same official functions the dashboard uses (ai.scoring), recomputed on the copy."""
import copy

from . import evidence as ev
from . import scoring
from .knowledge import SKILL_ALIASES

LABEL = "HYPOTHETICAL SCENARIO - these changes are NOT part of your real profile"


def resolve_skill(catalog: dict, name: str):
    key = (name or "").strip().lower()
    key = SKILL_ALIASES.get(key, key).lower()
    return catalog["by_name"].get(key)


def _snapshot_metrics(profile, jobs, salary_in, n_added, months, certs, role_names=None):
    have = {s["skill_id"] for s in profile["skills"]}
    skills_by_id = {}
    for j in jobs:
        for r in j["requirements"]:
            skills_by_id[r["skill_id"]] = {"skill_id": r["skill_id"], "skill_name": r["skill_name"]}
    evid = ev.evidence_for_skills(profile, list(skills_by_id.values()))
    roles = {}
    for j in jobs:
        if role_names and j["role"] not in role_names:
            continue
        m = scoring.compute_match(j["requirements"], have)
        d = ev.documented_percent(j["requirements"], evid)
        roles[j["role"]] = {"job_id": j["job_id"], "match_percent": m["match_percent"], "missing": [x["name"] for x in m["missing"]],
                            "matched": m["matched"], "total_weight": m["total_weight"],
                            "documented_percent": d["documented_percent"]}
    sal = scoring.salary_what_if_values(salary_in[0], salary_in[1], n_added, months, certs)
    return {"roles": roles, "salary": sal, "evidence": evid}


def run_scenario(profile: dict, catalog: dict, jobs: list[dict], salary_in: tuple, changes: dict,
                 role_names: list[str] | None = None) -> dict:
    sc = copy.deepcopy(profile)
    base_ids = {s["skill_id"] for s in profile["skills"]}
    applied, unresolved, assumptions, notes = [], [], [], []
    h_proj = h_cert = 0

    def add_hyp_skill(sk, via):
        if sk["skill_id"] in {s["skill_id"] for s in sc["skills"]}:
            return False
        sc["skills"].append({"skill_id": sk["skill_id"], "skill_name": sk["skill_name"], "category": sk.get("category"),
                             "proficiency": None, "years": 0, "evidence_score": None, "last_used": None, "hypothetical": True})
        applied.append({"type": "skill", "skill": sk["skill_name"], "via": via})
        return True

    for name in changes.get("add_skills", []):
        sk = resolve_skill(catalog, name)
        if not sk:
            unresolved.append({"input": name, "reason": "not in the CareerDNA skill catalog, so no role requirement or salary rule can use it"})
        elif sk["skill_id"] in {s["skill_id"] for s in sc["skills"]}:
            notes.append(f"{sk['skill_name']} is already in your profile; no change.")
        else:
            add_hyp_skill(sk, "claimed skill (self-reported)")

    for p in changes.get("add_projects", []):
        h_proj += 1
        ids = []
        for name in p.get("skills", []):
            sk = resolve_skill(catalog, name)
            if not sk:
                unresolved.append({"input": name, "reason": "project skill not in the CareerDNA skill catalog"})
                continue
            ids.append(sk["skill_id"])
            add_hyp_skill(sk, f"hypothetical project '{p.get('title') or 'new project'}'")
        sc["projects"].append({"project_id": f"hypothetical-{h_proj}", "title": p.get("title") or "hypothetical project",
                               "description": "", "skill_ids": ids, "hypothetical": True})
        applied.append({"type": "project", "title": p.get("title") or "hypothetical project", "skills": [catalog["by_id"][i]["skill_name"] for i in ids]})

    for c in changes.get("add_certifications", []):
        h_cert += 1
        names = []
        for name in c.get("skills", []):
            sk = resolve_skill(catalog, name)
            if sk:
                names.append(sk["skill_name"])
            else:
                unresolved.append({"input": name, "reason": "certification skill not in the CareerDNA skill catalog"})
        for sk in catalog["by_id"].values():  # catalogued skills named in the certification title
            if ev._word_in(sk["skill_name"], c.get("name", "")) and sk["skill_name"] not in names:
                names.append(sk["skill_name"])
                assumptions.append(f"The certification name mentions '{sk['skill_name']}', so it is treated as evidence for that skill.")
        sc["certifications"].append({"certification_id": f"hypothetical-{h_cert}", "name": c.get("name") or "hypothetical certification",
                                     "domain": "", "skills": names, "verification_status": "hypothetical"})
        for nm in names:
            sk = catalog["by_name"].get(nm.lower())
            if sk and add_hyp_skill(sk, f"hypothetical certification '{c.get('name')}'"):
                assumptions.append(f"Assuming you would also list '{nm}' among your skills after earning the certification.")
        applied.append({"type": "certification", "name": c.get("name") or "hypothetical certification", "skills": names})

    months = int(changes.get("add_experience_months", 0) or 0)
    if months:
        applied.append({"type": "experience", "months": months})
    new_ids = {s["skill_id"] for s in sc["skills"]} - base_ids

    base = _snapshot_metrics(profile, jobs, salary_in, 0, 0, 0, role_names)
    scen = _snapshot_metrics(sc, jobs, salary_in, len(new_ids), months, h_cert, role_names)

    role_changes = {}
    for role, b in base["roles"].items():
        s = scen["roles"][role]
        total = b["total_weight"] or 0
        newly = []
        for m in s["matched"]:
            if m["skill_id"] not in {x["skill_id"] for x in b["matched"]}:
                newly.append({"skill": m["name"], "importance": m["importance"],
                              "contribution_pp": round(m["importance"] / total * 100, 1) if total else 0.0})
        status_changes = []
        for sid, after in scen["evidence"].items():
            before = base["evidence"].get(sid)
            if before and before["status"] != after["status"] and sid in {r["skill_id"] for j in jobs if j["role"] == role for r in j["requirements"]}:
                status_changes.append({"skill": after["skill_name"], "before": before["status"], "after": after["status"],
                                       "via": [x["ref"] for x in after["projects"] + after["certifications"]]})
        role_changes[role] = {"match_delta_pp": round(s["match_percent"] - b["match_percent"], 1),
                              "documented_delta_pp": round(s["documented_percent"] - b["documented_percent"], 1),
                              "newly_matched": newly, "evidence_status_changes": status_changes}

    limitations = [
        "The official match score only counts WHICH required skills appear in your profile. It does not weigh proficiency or "
        "documentation, so documenting a skill you already list does not change the official match (it changes the separate "
        "'documented %' evidence metric).",
        "CareerDNA's salary rules add a fixed amount per new skill, certification and month of experience and have no project term; "
        "a project only moves the salary figure if it introduces a skill that is new to your profile.",
        "This is a simulation using CareerDNA's current scoring rules. It does not predict or guarantee interviews, job offers, or real salary.",
    ]
    if unresolved:
        limitations.append("Some inputs could not be scored because they are not in the CareerDNA skill catalog (see 'unresolved').")

    out = {
        "hypothetical": True, "label": LABEL, "applied": applied, "unresolved": unresolved,
        "assumptions": sorted(set(assumptions)), "notes": notes, "limitations": limitations,
        "baseline": {"salary": base["salary"], "roles": {r: {k: v for k, v in d.items() if k in ("match_percent", "documented_percent", "missing")} for r, d in base["roles"].items()}},
        "scenario": {"salary": scen["salary"], "roles": {r: {k: v for k, v in d.items() if k in ("match_percent", "documented_percent", "missing")} for r, d in scen["roles"].items()}},
        "changes": {"roles": role_changes,
                    "salary_delta_lpa": round(scen["salary"]["projected_salary_lpa"] - base["salary"]["base_salary_lpa"], 2)},
        "inputs": {"new_skill_count": len(new_ids), "added_experience_months": months, "added_certifications": h_cert},
    }
    return out
