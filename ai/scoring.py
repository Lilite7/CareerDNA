"""Official CareerDNA scoring logic.

This code was EXTRACTED unchanged from the inline logic in main.py's /career-gap, /job-match, /salary and
/salary/what-if endpoints so that the endpoints and the AI assistant share one implementation.
The LLM never computes these numbers; it only receives them."""
from typing import Iterable, Optional


# ---------------------------------------------------------------- job requirements & match
def load_jobs(conn) -> list[dict]:
    rows = conn.execute("SELECT job_id, role, company, location, min_salary, max_salary FROM job ORDER BY job_id").fetchall()
    return [dict(r) for r in rows]


def load_requirements(conn, job_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT s.skill_id, s.skill_name, js.required_level, js.importance
           FROM job_skill js JOIN skill s ON s.skill_id = js.skill_id
           WHERE js.job_id = ?""", (job_id,)).fetchall()
    return [dict(r) for r in rows]


def candidate_skill_ids(conn, candidate_id: int) -> set[int]:
    return {r["skill_id"] for r in conn.execute(
        "SELECT skill_id FROM candidate_skill WHERE candidate_id = ?", (candidate_id,)).fetchall()}


def compute_match(requirements: Iterable[dict], have_skill_ids: set[int]) -> dict:
    """Importance-weighted share of required skills present in the profile (existing formula)."""
    total_weight = 0.0
    matched_weight = 0.0
    matched, missing = [], []
    for row in requirements:
        importance = float(row["importance"] or 1)
        total_weight += importance
        if row["skill_id"] in have_skill_ids:
            matched_weight += importance
            matched.append({"skill_id": row["skill_id"], "name": row["skill_name"],
                            "required_level": row["required_level"], "importance": importance})
        else:
            missing.append({"skill_id": row["skill_id"], "name": row["skill_name"],
                            "required_level": row["required_level"], "importance": importance})
    match_percent = round((matched_weight / total_weight * 100) if total_weight else 0, 1)
    return {"match_percent": match_percent, "matched": matched, "missing": missing,
            "total_weight": total_weight, "matched_weight": matched_weight}


def select_job_for_gap(jobs: list[dict], role: Optional[str]) -> Optional[dict]:
    """Existing /career-gap selection rule: exact case-insensitive role, otherwise the first job."""
    if not jobs:
        return None
    if role:
        for job in jobs:
            if job["role"].lower() == role.lower():
                return job
    return jobs[0]


def career_gap(conn, candidate_id: int, role: Optional[str]) -> dict:
    jobs = load_jobs(conn)
    if not jobs:
        return {"role": role or "No target role", "match_percent": 0, "missing_skills": []}
    job = select_job_for_gap(jobs, role)
    m = compute_match(load_requirements(conn, job["job_id"]), candidate_skill_ids(conn, candidate_id))
    return {"role": job["role"], "company": job["company"], "match_percent": m["match_percent"],
            "missing_skills": [{"name": x["name"], "required_level": x["required_level"],
                                "importance": x["importance"]} for x in m["missing"]]}


def job_match_all(conn, candidate_id: int) -> list[dict]:
    have = candidate_skill_ids(conn, candidate_id)
    results = []
    for job in load_jobs(conn):
        m = compute_match(load_requirements(conn, job["job_id"]), have)
        results.append({"job_id": job["job_id"], "role": job["role"], "company": job["company"],
                        "match_percent": m["match_percent"]})
    results.sort(key=lambda item: item["match_percent"], reverse=True)
    return results


# ---------------------------------------------------------------- salary
def salary_inputs(conn, candidate_id: int) -> tuple[float, int]:
    row = conn.execute(
        "SELECT AVG(evidence_score) AS avg_evidence, COUNT(*) AS skill_count FROM candidate_skill WHERE candidate_id = ?",
        (candidate_id,)).fetchone()
    return float(row["avg_evidence"] or 0), int(row["skill_count"] or 0)


def formula_base_salary(avg_evidence: float, skill_count: int) -> float:
    return 9.0 + avg_evidence * 0.06 + skill_count * 0.15


def what_if_delta(n_added_skills: int, added_experience_months: int, added_certifications: int) -> float:
    return 0.6 * n_added_skills + 0.3 * added_experience_months + 0.7 * added_certifications


def estimate_salary(conn, candidate_id: int) -> dict:
    """Existing /salary behaviour: latest stored prediction, else the explainable profile estimate."""
    result = conn.execute(
        "SELECT * FROM salary_prediction WHERE candidate_id = ? ORDER BY timestamp DESC LIMIT 1",
        (candidate_id,)).fetchone()
    if result:
        data = dict(result)
        value = data.get("predicted_salary") or data.get("salary") or data.get("predicted_salary_lpa")
        if value is not None:
            return {"predicted_salary_lpa": float(value), "confidence": data.get("confidence", 78),
                    "source": "database", "prediction": data}
    avg_evidence, skill_count = salary_inputs(conn, candidate_id)
    predicted = formula_base_salary(avg_evidence, skill_count)
    return {"predicted_salary_lpa": round(predicted, 2), "confidence": 72,
            "source": "explainable-profile-estimate",
            "average_evidence": round(avg_evidence, 2), "skill_count": skill_count}


def salary_what_if_values(avg_evidence: float, skill_count: int, n_added_skills: int,
                          months: int, certs: int) -> dict:
    base = formula_base_salary(avg_evidence, skill_count)
    delta = what_if_delta(n_added_skills, months, certs)
    projected = base + delta
    return {"base_salary_lpa": round(base, 2), "projected_salary_lpa": round(projected, 2),
            "delta_lpa": round(delta, 2)}


def salary_what_if(conn, candidate_id: int, added_skill_ids, months: int, certs: int) -> dict:
    avg_evidence, skill_count = salary_inputs(conn, candidate_id)
    return salary_what_if_values(avg_evidence, skill_count, len(added_skill_ids), months, certs)
