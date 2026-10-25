"""Read-only, parameterised loading of one candidate's records into an in-memory snapshot.
The snapshot can be copied and modified for what-if scenarios WITHOUT touching the database."""
import json
from typing import Optional


def candidate_id_for_user(conn, user_id: int) -> Optional[int]:
    row = conn.execute("SELECT candidate_id FROM candidate WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
    return int(row["candidate_id"]) if row else None


def skill_catalog(conn) -> dict:
    rows = conn.execute("SELECT skill_id, skill_name, category FROM skill ORDER BY skill_id").fetchall()
    by_id = {r["skill_id"]: {"skill_id": r["skill_id"], "skill_name": r["skill_name"], "category": r["category"]} for r in rows}
    by_name = {v["skill_name"].lower(): v for v in by_id.values()}
    return {"by_id": by_id, "by_name": by_name}


def _latest_snapshot(conn, candidate_id: int) -> dict:
    row = conn.execute("SELECT profile_snapshot FROM profile_version WHERE candidate_id = ? ORDER BY version_id DESC LIMIT 1",
                       (candidate_id,)).fetchone()
    if not row or not row["profile_snapshot"]:
        return {}
    try:
        data = json.loads(row["profile_snapshot"])
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def load_profile(conn, candidate_id: int) -> dict:
    cand = conn.execute("SELECT candidate_id, name, location FROM candidate WHERE candidate_id = ?", (candidate_id,)).fetchone()
    if not cand:
        raise LookupError("candidate not found")
    snap = _latest_snapshot(conn, candidate_id)
    skills = [dict(r) for r in conn.execute(
        """SELECT cs.skill_id, s.skill_name, s.category, cs.proficiency, cs.years, cs.evidence_score, cs.last_used
           FROM candidate_skill cs JOIN skill s ON s.skill_id = cs.skill_id
           WHERE cs.candidate_id = ? ORDER BY cs.evidence_score DESC, s.skill_name""", (candidate_id,))]
    projects = []
    for p in conn.execute("SELECT project_id, title, description, complexity, impact, solo, github_url FROM project WHERE candidate_id = ? ORDER BY project_id", (candidate_id,)):
        d = dict(p)
        d["skill_ids"] = [r["skill_id"] for r in conn.execute("SELECT skill_id FROM project_skill WHERE project_id = ?", (d["project_id"],))]
        projects.append(d)
    certs = [dict(r) for r in conn.execute(
        """SELECT c.certification_id, c.name, c.issuer, c.domain, c.level, cc.issue_date, cc.verification_status
           FROM candidate_certification cc JOIN certification c ON c.certification_id = cc.certification_id
           WHERE cc.candidate_id = ?""", (candidate_id,))]
    experience = [dict(r) for r in conn.execute(
        "SELECT experience_id, company, role, domain, start_date, end_date FROM experience WHERE candidate_id = ? ORDER BY experience_id", (candidate_id,))]
    education = [dict(r) for r in conn.execute(
        "SELECT education_id, degree, institution, field, cgpa, start_date, end_date FROM education WHERE candidate_id = ?", (candidate_id,))]
    return {"candidate_id": candidate_id, "name": cand["name"], "location": cand["location"],
            "headline": snap.get("headline") or "", "goals": snap.get("goals") or "",
            "skills": skills, "projects": projects, "certifications": certs,
            "experience": experience, "education": education}
