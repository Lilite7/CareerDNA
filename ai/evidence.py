"""Evidence layer: links every skill to the records that support (or fail to support) it.

Statuses
  documented         - a project and/or certification record supports the skill
  self_reported_only - listed in the profile, but no project/certification record is linked
  contradictory      - the profile's own records disagree (e.g. 'Advanced' but a very low recorded evidence score)
  no_record          - nothing in the database; proficiency CANNOT BE ESTABLISHED (this is NOT evidence of inability)

The schema has no assessment table, so assessments are reported as unavailable instead of invented."""
import re

ADVANCED_MIN_SCORE = 40.0  # 'Advanced' with a recorded evidence score below this is flagged as contradictory


def _word_in(name: str, text: str) -> bool:
    return bool(text) and re.search(r"(?<![A-Za-z0-9])" + re.escape(name.lower()) + r"(?![A-Za-z0-9])", text.lower()) is not None


def cert_supports(cert: dict, skill_name: str) -> bool:
    explicit = [s.lower() for s in cert.get("skills", [])]  # only present on hypothetical certs
    return (skill_name.lower() in explicit) or _word_in(skill_name, cert.get("name") or "") or _word_in(skill_name, cert.get("domain") or "")


def skill_evidence(profile: dict, skill: dict) -> dict:
    sid, sname = skill["skill_id"], skill["skill_name"]
    own = next((s for s in profile["skills"] if s["skill_id"] == sid), None)
    projects = [{"ref": f"project:{p['project_id']}", "title": p["title"]} for p in profile["projects"] if sid in p.get("skill_ids", [])]
    certs = [{"ref": f"certification:{c['certification_id']}", "name": c["name"],
              "match_basis": "listed skills" if c.get("skills") else "skill name appears in certification name/domain",
              "verification_status": c.get("verification_status")}
             for c in profile["certifications"] if cert_supports(c, sname)]
    flags, contradictions = [], []
    self_rep = None
    if own:
        flags.append("self_reported")
        self_rep = {"ref": f"candidate_skill:{profile['candidate_id']}:{sid}", "proficiency": own.get("proficiency"),
                    "years": own.get("years"), "recorded_evidence_score": own.get("evidence_score")}
        score = own.get("evidence_score")
        if own.get("proficiency") == "Advanced" and score is not None and float(score) < ADVANCED_MIN_SCORE:
            contradictions.append(f"Profile says 'Advanced' but the recorded evidence score is {float(score):g}/100")
    if projects:
        flags.append("project_supported")
    if certs:
        flags.append("certification_supported")
    if contradictions:
        flags.append("contradictory_evidence")
    if not own and not projects and not certs:
        flags += ["missing_evidence", "insufficient_evidence"]
        status = "no_record"
        note = "No record in your profile. Proficiency cannot be established from the available data."
    elif contradictions:
        status = "contradictory"
        note = "The records disagree with each other; please review this skill."
    elif projects or certs:
        status = "documented"
        note = "Supported by " + ", ".join(
            [f"{len(projects)} project(s)"] * bool(projects) + [f"{len(certs)} certification(s)"] * bool(certs)) + "."
    else:
        flags += ["missing_evidence"]
        status = "self_reported_only"
        note = "Listed in the profile, but no project or certification record is linked to it."
    return {"skill_id": sid, "skill_name": sname, "in_profile": bool(own), "status": status, "flags": flags,
            "self_reported": self_rep, "projects": projects, "certifications": certs,
            "assessments": [], "assessment_data_available": False,
            "contradictions": contradictions, "note": note}


def evidence_for_skills(profile: dict, skills: list[dict]) -> dict:
    return {s["skill_id"]: skill_evidence(profile, s) for s in skills}


def documented_percent(requirements: list[dict], evidence: dict) -> dict:
    """SUPPLEMENTARY metric (not the official match): importance-weighted share of a role's required
    skills whose status is 'documented'."""
    total = sum(float(r["importance"] or 1) for r in requirements)
    doc = sum(float(r["importance"] or 1) for r in requirements if evidence.get(r["skill_id"], {}).get("status") == "documented")
    return {"documented_percent": round(doc / total * 100, 1) if total else 0.0,
            "documented_skills": [r["skill_name"] for r in requirements if evidence.get(r["skill_id"], {}).get("status") == "documented"]}
